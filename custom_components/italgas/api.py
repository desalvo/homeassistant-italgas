from __future__ import annotations

import html
import logging
import re
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse, parse_qs

import aiohttp
from aiohttp import ClientResponse, ClientSession

from .const import BASE_URL, DEFAULT_LOOKBACK_DAYS
from .models import GasPortalData, GasReading, GasSupply

_LOGGER = logging.getLogger(__name__)


class GasPortalError(Exception):
    """Base API error."""


class GasPortalAuthError(GasPortalError):
    """Authentication/session error."""


class GasPortalProtocolError(GasPortalError):
    """Unexpected MyItalgas response."""


class _PortalHTMLParser(HTMLParser):
    """Small HTML parser for the stable pieces used by MyItalgas."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.inputs: dict[str, str] = {}
        self.links: list[tuple[str, str]] = []
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell_parts: list[str] | None = None
        self._link_href: str | None = None
        self._link_parts: list[str] | None = None
        self.title_parts: list[str] = []
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        data = {k.lower(): (v or "") for k, v in attrs}
        if tag == "input" and data.get("name"):
            self.inputs[data["name"]] = data.get("value", "")
        elif tag == "a" and data.get("href"):
            self._link_href = data["href"]
            self._link_parts = []
        elif tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell_parts = []
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._link_href is not None:
            self.links.append((self._link_href, " ".join(self._link_parts or []).strip()))
            self._link_href = None
            self._link_parts = None
        elif tag in ("td", "th") and self._row is not None and self._cell_parts is not None:
            self._row.append(" ".join(self._cell_parts).strip())
            self._cell_parts = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None
            self._cell_parts = None
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if not text:
            return
        if self._link_parts is not None:
            self._link_parts.append(text)
        if self._cell_parts is not None:
            self._cell_parts.append(text)
        if self._in_title:
            self.title_parts.append(text)

    @property
    def title(self) -> str:
        return " ".join(self.title_parts).strip()


def _parse_html(text: str) -> _PortalHTMLParser:
    parser = _PortalHTMLParser()
    parser.feed(text)
    return parser


def _parse_decimal(value: str) -> Decimal:
    cleaned = value.strip().replace(".", "").replace(",", ".")
    try:
        return Decimal(cleaned)
    except InvalidOperation as err:
        raise GasPortalProtocolError(f"Invalid meter reading value: {value!r}") from err


def _parse_italian_date(value: str) -> datetime:
    try:
        return datetime.strptime(value.strip(), "%d/%m/%Y").replace(tzinfo=timezone.utc)
    except ValueError as err:
        raise GasPortalProtocolError(f"Invalid reading date: {value!r}") from err


def parse_readings_html(text: str, pdr: str) -> GasPortalData:
    """Parse the HTML table returned by ricercaLetture.action."""
    parser = _parse_html(text)
    readings: list[GasReading] = []

    for row in parser.rows:
        if len(row) < 4:
            continue
        # HAR-confirmed columns: Matricola contatore, Data Lettura, Lettura, Tipologia lettura.
        if not re.fullmatch(r"\d{2}/\d{2}/\d{4}", row[1].strip()):
            continue
        try:
            value = _parse_decimal(row[2])
            timestamp = _parse_italian_date(row[1])
        except GasPortalProtocolError:
            continue
        readings.append(
            GasReading(
                timestamp=timestamp,
                value_m3=value,
                source=row[3].strip() or None,
                meter_serial=row[0].strip() or None,
            )
        )

    readings.sort(key=lambda item: item.timestamp)
    if not readings:
        # An empty result set is valid only when the page still looks like the readings page.
        title = parser.title.lower()
        body_lower = text.lower()
        if "lettur" not in title and "matricola contatore" not in body_lower:
            raise GasPortalProtocolError("MyItalgas did not return the expected readings page")

    return GasPortalData(pdr=pdr, readings=tuple(readings))


def _extract_struts_token(text: str) -> tuple[str, str]:
    """Extract the Struts token pair used by MyItalgas forms.

    Standard Struts renders two hidden fields::

        struts.token.name = token
        token = <random value>

    Some portal responses omit the first helper field while still rendering the
    actual token input.  Accept that shape too, since the HAR confirms that the
    submitted field name is currently simply ``token``.
    """
    parser = _parse_html(text)

    token_field_name = parser.inputs.get("struts.token.name", "").strip()
    if token_field_name:
        token_value = parser.inputs.get(token_field_name, "").strip()
        if token_value:
            return token_field_name, token_value

    # MyItalgas currently submits a field named exactly ``token``.  Be tolerant
    # of pages where Struts does not emit the companion struts.token.name field.
    direct_token = parser.inputs.get("token", "").strip()
    if direct_token:
        return "token", direct_token

    # Defensive compatibility with a future custom Struts token field name.
    for field_name, value in parser.inputs.items():
        if field_name == "struts.token.name":
            continue
        if "token" in field_name.lower() and value.strip():
            return field_name, value.strip()

    # DisplayTag links on MyItalgas also carry the Struts token in their query
    # string.  This fallback handles pages where the hidden inputs are omitted
    # but a paging/export link still contains a valid token pair.
    decoded = html.unescape(text)
    name_match = re.search(r"(?:[?&]|\b)struts\.token\.name=([^&\"'<> ]+)", decoded, re.I)
    if name_match:
        field_name = name_match.group(1).strip()
        value_match = re.search(
            rf"(?:[?&]|\b){re.escape(field_name)}=([^&\"'<> ]+)",
            decoded,
            re.I,
        )
        if value_match and value_match.group(1).strip():
            return field_name, value_match.group(1).strip()

    safe_names = sorted(
        name for name in parser.inputs
        if not any(secret in name.lower() for secret in ("password", "username"))
    )
    title = parser.title or "<no title>"
    raise GasPortalProtocolError(
        "Struts token not found in MyItalgas page "
        f"(title={title!r}, inputs={safe_names[:20]!r})"
    )


def _extract_supply_ids(text: str) -> list[str]:
    parser = _parse_html(text)
    ids: list[str] = []
    for href, _label in parser.links:
        absolute = urljoin(BASE_URL + "/", href)
        parsed = urlparse(absolute)
        if not parsed.path.endswith("/elencoLetture.action"):
            continue
        opaque_id = parse_qs(parsed.query).get("id", [""])[0].strip()
        if opaque_id and opaque_id not in ids:
            ids.append(opaque_id)
    return ids


def _extract_pdr(text: str) -> str | None:
    parser = _parse_html(text)
    value = parser.inputs.get("pdr", "").strip()
    if value:
        return value
    # Defensive fallback for PDRs rendered as text instead of a hidden input.
    match = re.search(r"\bPDR\b[^0-9]{0,40}(\d{14})\b", text, flags=re.IGNORECASE)
    return match.group(1) if match else None


def _multipart(fields: dict[str, str]) -> aiohttp.FormData:
    form = aiohttp.FormData(default_to_multipart=True)
    for name, value in fields.items():
        form.add_field(name, value)
    return form




def _one_calendar_month_ago(value: date) -> date:
    """Return the same day in the previous month, clipping at month end."""
    if value.month == 1:
        year, month = value.year - 1, 12
    else:
        year, month = value.year, value.month - 1
    # Avoid an extra dependency for a simple calendar-month subtraction.
    from calendar import monthrange

    day = min(value.day, monthrange(year, month)[1])
    return date(year, month, day)

class MyItalgasClient:
    """Authenticated client reconstructed from the MyItalgas web flow."""

    def __init__(
        self,
        session: ClientSession,
        *,
        username: str,
        password: str,
        pdr: str | None = None,
        verify_ssl: bool = True,
    ) -> None:
        self._session = session
        self._username = username.strip()
        self._password = password
        self.pdr = pdr.strip() if pdr else None
        self._verify_ssl = verify_ssl
        self._cookies: dict[str, str] = {}
        self._authenticated = False
        self._supply: GasSupply | None = None

    @property
    def name(self) -> str:
        return "MyItalgas"

    async def async_close(self) -> None:
        """Close this client's dedicated HTTP session."""
        if not self._session.closed:
            await self._session.close()

    def _headers(self, *, referer: str | None = None) -> dict[str, str]:
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
            "Cache-Control": "no-cache",
        }
        if self._cookies:
            headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in self._cookies.items())
        if referer:
            headers["Referer"] = referer
        return headers

    def _capture_cookies(self, response: ClientResponse) -> None:
        # The authentication cookie can be set on an intermediate 302. The shared
        # Home Assistant session may use a non-persistent cookie jar, so retain it
        # explicitly from both redirect history and the final response.
        for item in (*response.history, response):
            for name, morsel in item.cookies.items():
                self._cookies[name] = morsel.value

    @staticmethod
    def _looks_like_login(response: ClientResponse, text: str) -> bool:
        path = response.url.path.lower()
        if path.endswith("/login.action"):
            return True
        lowered = text.lower()
        return 'name="username"' in lowered and 'name="password"' in lowered

    async def _request_text(self, method: str, path: str, **kwargs: Any) -> tuple[ClientResponse, str]:
        url = path if path.startswith("http") else f"{BASE_URL}/{path.lstrip('/')}"
        headers = self._headers(referer=kwargs.pop("referer", None))
        headers.update(kwargs.pop("headers", {}))
        try:
            async with self._session.request(
                method,
                url,
                headers=headers,
                ssl=self._verify_ssl,
                timeout=aiohttp.ClientTimeout(total=30),
                **kwargs,
            ) as response:
                self._capture_cookies(response)
                text = await response.text(errors="replace")
                if response.status >= 500:
                    raise GasPortalError(f"MyItalgas HTTP {response.status}")
                return response, text
        except GasPortalError:
            raise
        except (aiohttp.ClientError, TimeoutError) as err:
            raise GasPortalError(f"MyItalgas request failed: {err}") from err

    async def async_login(self) -> None:
        # First load the real login form.  A browser-like request matters here:
        # the portal sits behind an ADC and may vary the generated page by client.
        response, login_html = await self._request_text(
            "GET",
            "login.action",
            allow_redirects=True,
            headers={
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
            },
        )
        if response.status >= 400:
            raise GasPortalError(f"Unable to load MyItalgas login page: HTTP {response.status}")

        try:
            token_name, token_value = _extract_struts_token(login_html)
        except GasPortalProtocolError:
            # Retry once with a cache-busting query.  This avoids stale/cached
            # login shells that do not contain the per-request Struts token.
            response, login_html = await self._request_text(
                "GET",
                f"login.action?_={int(time.time() * 1000)}",
                allow_redirects=True,
                referer=f"{BASE_URL}/login.action",
                headers={
                    "Pragma": "no-cache",
                    "Upgrade-Insecure-Requests": "1",
                    "Sec-Fetch-Dest": "document",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Site": "same-origin",
                },
            )
            token_name, token_value = _extract_struts_token(login_html)

        fields = {
            "privacy": "",
            "consensoSms": "",
            "username": self._username,
            "password": self._password,
            "ricordami": "true",
            "__checkbox_ricordami": "true",
            "blogin": "login",
            "struts.token.name": token_name,
            token_name: token_value,
        }
        response, body = await self._request_text(
            "POST",
            "login.action",
            data=_multipart(fields),
            allow_redirects=True,
            referer=f"{BASE_URL}/login.action",
            headers={
                "Origin": "https://clienti.italgas.it",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "same-origin",
            },
        )
        if response.status in (401, 403) or self._looks_like_login(response, body):
            self._authenticated = False
            raise GasPortalAuthError("Invalid MyItalgas credentials or login rejected")
        if not response.url.path.endswith("/home.action") and "logout.action" not in body:
            # Some deployments may redirect to another authenticated landing page;
            # require an authenticated-only marker before accepting it.
            raise GasPortalAuthError("MyItalgas login did not reach an authenticated page")
        self._authenticated = True
        self._supply = None

    async def _ensure_login(self) -> None:
        if not self._authenticated:
            await self.async_login()

    async def _get_protected(self, path: str, *, referer: str | None = None) -> str:
        await self._ensure_login()
        response, text = await self._request_text("GET", path, allow_redirects=True, referer=referer)
        if self._looks_like_login(response, text):
            self._authenticated = False
            await self.async_login()
            response, text = await self._request_text("GET", path, allow_redirects=True, referer=referer)
            if self._looks_like_login(response, text):
                raise GasPortalAuthError("MyItalgas session could not be restored")
        if response.status in (401, 403):
            raise GasPortalAuthError("MyItalgas session is unauthorized")
        if response.status >= 400:
            raise GasPortalError(f"MyItalgas HTTP {response.status}")
        return text

    async def async_list_supplies(self) -> list[GasSupply]:
        """Return PDRs visible in MyItalgas.

        The HAR shows elencoLettForn.action links to elencoLetture.action?id=<opaque>.
        We follow each opaque id because the detail page contains the real PDR in
        the hidden search form, avoiding assumptions about how the list table is rendered.
        """
        await self._ensure_login()
        await self._get_protected(
            "elencoForniture.action", referer=f"{BASE_URL}/home.action"
        )
        list_html = await self._get_protected(
            "elencoLettForn.action", referer=f"{BASE_URL}/elencoForniture.action"
        )
        ids = _extract_supply_ids(list_html)
        if not ids:
            raise GasPortalProtocolError("No supply links found in MyItalgas")

        supplies: list[GasSupply] = []
        for opaque_id in ids:
            detail_path = f"elencoLetture.action?id={opaque_id}"
            detail_html = await self._get_protected(
                detail_path, referer=f"{BASE_URL}/elencoLettForn.action"
            )
            pdr = _extract_pdr(detail_html)
            if not pdr:
                _LOGGER.debug("Skipping MyItalgas supply %s because no PDR was found", opaque_id)
                continue
            supplies.append(GasSupply(opaque_id=opaque_id, pdr=pdr))

        if not supplies:
            raise GasPortalProtocolError("MyItalgas supply pages did not expose a PDR")
        return supplies

    async def async_select_supply(self, pdr: str | None = None) -> GasSupply:
        wanted = (pdr or self.pdr or "").strip()
        supplies = await self.async_list_supplies()
        if wanted:
            for supply in supplies:
                if supply.pdr == wanted:
                    self.pdr = supply.pdr
                    self._supply = supply
                    return supply
            raise GasPortalProtocolError("Configured PDR is not present in this MyItalgas account")
        if len(supplies) != 1:
            raise GasPortalProtocolError("Multiple PDRs are available; one must be selected")
        self.pdr = supplies[0].pdr
        self._supply = supplies[0]
        return supplies[0]

    async def async_fetch(
        self,
        *,
        lookback_days: int = DEFAULT_LOOKBACK_DAYS,
        full_history: bool = False,
    ) -> GasPortalData:
        """Fetch readings using month-sized searches.

        MyItalgas' own UI issues searches for calendar-month ranges.  A single
        very large range can return the readings page with no table rows, which
        leaves Home Assistant with an entity but no state.  Querying calendar
        months mirrors the portal behaviour and is also kinder to the backend.

        We always inspect at least the current and previous calendar month so
        daily readings, when exposed by MyItalgas, can be detected across a
        month boundary. If fewer than two readings exist, the search continues
        backwards up to ``lookback_days``.
        """
        await self._ensure_login()
        if self._supply is None or (self.pdr and self._supply.pdr != self.pdr):
            await self.async_select_supply(self.pdr)
        assert self._supply is not None
        assert self.pdr is not None

        detail_path = f"elencoLetture.action?id={self._supply.opaque_id}"
        detail_url = f"{BASE_URL}/{detail_path}"
        detail_html = await self._get_protected(
            detail_path, referer=f"{BASE_URL}/elencoLettForn.action"
        )
        token_name, token_value = _extract_struts_token(detail_html)

        today = date.today()
        earliest = today - timedelta(days=lookback_days)
        period_end = today
        readings_by_key: dict[tuple[datetime, Decimal], GasReading] = {}
        months_queried = 0

        while period_end >= earliest:
            period_start = period_end.replace(day=1)
            if period_start < earliest:
                period_start = earliest

            fields = {
                "pdr": self.pdr,
                "dataDa": period_start.strftime("%d/%m/%Y"),
                "dataA": period_end.strftime("%d/%m/%Y"),
                "struts.token.name": token_name,
                token_name: token_value,
            }
            response, html = await self._request_text(
                "POST",
                "ricercaLetture.action",
                data=_multipart(fields),
                allow_redirects=True,
                referer=detail_url,
            )
            if self._looks_like_login(response, html):
                self._authenticated = False
                await self.async_login()
                self._supply = None
                return await self.async_fetch(
                    lookback_days=lookback_days, full_history=full_history
                )
            if response.status in (401, 403):
                raise GasPortalAuthError("MyItalgas session is unauthorized")
            if response.status >= 400:
                raise GasPortalError(f"MyItalgas HTTP {response.status}")

            page_data = parse_readings_html(html, self.pdr)
            months_queried += 1
            for reading in page_data.readings:
                readings_by_key[(reading.timestamp, reading.value_m3)] = reading

            # The response contains the token to use for the next search.  If
            # its shape changes, reload the detail page to obtain a fresh token.
            try:
                token_name, token_value = _extract_struts_token(html)
            except GasPortalProtocolError:
                detail_html = await self._get_protected(
                    detail_path, referer=f"{BASE_URL}/elencoLettForn.action"
                )
                token_name, token_value = _extract_struts_token(detail_html)

            # Two months are enough to detect recent daily measurements and
            # handle a day pair that straddles the month boundary.  If there
            # are still fewer than two readings, continue backwards to retain
            # the existing fallback for sparse/monthly accounts.
            if (
                not full_history
                and months_queried >= 2
                and len(readings_by_key) >= 2
            ):
                break
            if period_start <= earliest:
                break
            period_end = period_start - timedelta(days=1)

        readings = tuple(
            sorted(readings_by_key.values(), key=lambda item: item.timestamp)
        )
        if not readings:
            raise GasPortalProtocolError(
                "MyItalgas returned no meter readings in the configured lookback period"
            )
        return GasPortalData(pdr=self.pdr, readings=readings)

    async def async_fetch_history(
        self, *, lookback_days: int = DEFAULT_LOOKBACK_DAYS
    ) -> GasPortalData:
        """Fetch all real readings available in the configured lookback window."""
        return await self.async_fetch(
            lookback_days=lookback_days, full_history=True
        )

    async def async_fetch_initial_history(self) -> GasPortalData:
        """Fetch portal history from one calendar month ago through today."""
        today = date.today()
        start = _one_calendar_month_ago(today)
        return await self.async_fetch(
            lookback_days=(today - start).days,
            full_history=True,
        )

    async def async_validate(self) -> GasPortalData:
        await self.async_login()
        return await self.async_fetch()
