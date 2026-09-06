from __future__ import annotations

import html as html_lib
import logging
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser

import aiohttp

_LOGGER = logging.getLogger(__name__)

ARERA_CMEM_URL = (
    "https://www.arera.it/area-operatori/prezzi-e-tariffe/"
    "valore-cmemm-vulnerabili"
)

_MONTHS = {
    "gennaio",
    "febbraio",
    "marzo",
    "aprile",
    "maggio",
    "giugno",
    "luglio",
    "agosto",
    "settembre",
    "ottobre",
    "novembre",
    "dicembre",
}


@dataclass(frozen=True, slots=True)
class AreraGasPrice:
    value_eur_smc: Decimal
    period: str
    source_url: str = ARERA_CMEM_URL


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"td", "th"} and self._cell is not None and self._row is not None:
            value = " ".join("".join(self._cell).split())
            self._row.append(value)
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None
            self._cell = None


def parse_arera_cmem_html(text: str) -> AreraGasPrice:
    """Return the newest CMEM row published by ARERA.

    The official table is ordered newest year first and newest month first.
    The last numeric column is Euro/Smc. We deliberately expose it as EUR/m³
    in Home Assistant because 1 Smc is the standard cubic-metre billing unit
    represented by the portal price; the sensor attributes make the provenance
    explicit.
    """
    parser = _TableParser()
    parser.feed(text)

    current_year: str | None = None
    for row in parser.rows:
        if row and re.fullmatch(r"20\d{2}", row[0].strip()):
            current_year = row[0].strip()
            continue
        if len(row) < 4:
            continue
        month = row[0].strip().lower()
        if month not in _MONTHS:
            continue
        raw = html_lib.unescape(row[-1]).replace("\xa0", " ").strip()
        raw = re.sub(r"[^0-9,.-]", "", raw).replace(",", ".")
        try:
            value = Decimal(raw)
        except (InvalidOperation, ValueError):
            continue
        if value <= 0:
            continue
        period = f"{month} {current_year}" if current_year else month
        return AreraGasPrice(value_eur_smc=value, period=period)

    # Defensive fallback for markup changes: search rendered text-like content.
    plain = re.sub(r"<[^>]+>", " ", text)
    plain = " ".join(html_lib.unescape(plain).replace("\xa0", " ").split())
    match = re.search(
        r"(gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|"
        r"settembre|ottobre|novembre|dicembre)\s+\|?\s*"
        r"[0-9]+[,.][0-9]+\s+\|?\s*[0-9]+[,.][0-9]+\s+\|?\s*"
        r"([0-9]+[,.][0-9]+)",
        plain,
        re.IGNORECASE,
    )
    if match:
        return AreraGasPrice(
            value_eur_smc=Decimal(match.group(2).replace(",", ".")),
            period=match.group(1).lower(),
        )

    raise ValueError("Unable to parse ARERA CMEM price table")


async def async_fetch_arera_gas_price(session: aiohttp.ClientSession) -> AreraGasPrice:
    headers = {
        "Accept": "text/html,application/xhtml+xml",
        "User-Agent": "HomeAssistant Italgas integration",
    }
    try:
        async with session.get(
            ARERA_CMEM_URL,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as response:
            response.raise_for_status()
            text = await response.text(errors="replace")
    except (aiohttp.ClientError, TimeoutError) as err:
        raise ValueError(f"Unable to fetch ARERA gas price: {err}") from err
    return parse_arera_cmem_html(text)
