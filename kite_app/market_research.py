"""Public NSE, BSE, news, and SEBI text for the final call.

A source that does not answer is omitted. Nothing is invented in its place.
"""

from __future__ import annotations

import html
import http.cookiejar
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, timedelta

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
_OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
_ANCHOR = re.compile(r"<a\b([^>]*)>(.*?)</a>", re.IGNORECASE | re.DOTALL)
_ATTR = re.compile(r"""([:\w-]+)\s*=\s*["']([^"']*)["']""")
_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")


def lookup_text(source: str, symbol: str, company: str, get=None) -> str:
    """Return the text for one research tool. An empty string means nothing was read."""
    reader = get or http_get
    names = _names(symbol, company)
    if source == "read_filings":
        return _filings(symbol, names, reader)
    if source == "read_news":
        return _news(names, reader)
    if source == "read_lawsuits":
        return _lawsuits(names, reader)
    return ""


def http_get(url: str) -> bytes:
    request = urllib.request.Request(url, headers=_headers(url))
    with _OPENER.open(request, timeout=12) as response:
        return response.read(200_000)


def _filings(symbol: str, names: list[str], get) -> str:
    lines = []
    lines.extend(_prefix("NSE", _nse_announcements(symbol, get)))
    lines.extend(_prefix("BSE", _bse_announcements(symbol, names, get)))
    lines.extend(_prefix("SEBI filing", _sebi_links(names, "/filings/", get)))
    return _join(lines)


def _news(names: list[str], get) -> str:
    if not names:
        return ""
    query = urllib.parse.quote(f"{names[0]} NSE")
    url = f"https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"
    text = _text(get, url)
    if not text:
        return ""
    lines = []
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return ""
    for item in root.iter("item"):
        title = _clean(item.findtext("title") or "")
        when = _clean(item.findtext("pubDate") or "")
        if title:
            lines.append(f"{when} {title}".strip())
        if len(lines) == 8:
            break
    return _join(_prefix("News", lines))


def _lawsuits(names: list[str], get) -> str:
    return _join(_prefix("SEBI order", _sebi_links(names, "/enforcement/", get)))


def _nse_announcements(symbol: str, get) -> list[str]:
    if not symbol:
        return []
    _text(get, "https://www.nseindia.com/")
    quoted = urllib.parse.quote(symbol)
    text = _text(get, f"https://www.nseindia.com/api/corporate-announcements?index=equities&symbol={quoted}")
    payload = _json(text)
    rows = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return []
    lines = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        headline = _clean(str(row.get("desc") or row.get("attchmntText") or row.get("subject") or ""))
        when = _clean(str(row.get("an_dt") or ""))
        if headline:
            lines.append(f"{when} {headline}".strip())
        if len(lines) == 8:
            break
    return lines


def _bse_announcements(symbol: str, names: list[str], get) -> list[str]:
    code = _scrip_code(symbol, names, get)
    if not code:
        return []
    end = date.today()
    start = end - timedelta(days=90)
    url = (
        "https://api.bseindia.com/BseIndiaAPI/api/AnnGetData/w"
        f"?pageno=1&strCat=-1&strPrevDate={start:%Y%m%d}&strScrip={code}"
        f"&strSearch=P&strToDate={end:%Y%m%d}&strType=C"
    )
    payload = _json(_text(get, url))
    rows = payload.get("Table") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    lines = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        headline = _clean(str(row.get("NEWSSUB") or row.get("HEADLINE") or ""))
        when = _clean(str(row.get("News_submission_dt") or ""))
        if headline:
            lines.append(f"{when} {headline}".strip())
        if len(lines) == 8:
            break
    return lines


def _scrip_code(symbol: str, names: list[str], get) -> str:
    query = urllib.parse.quote(symbol or (names[0] if names else ""))
    if not query:
        return ""
    payload = _json(_text(get, f"https://api.bseindia.com/BseIndiaAPI/api/PeerSmartSearch/w?Type=SS&text={query}"))
    rows = payload if isinstance(payload, list) else []
    if isinstance(payload, dict):
        rows = payload.get("Table") or payload.get("data") or []
    if not isinstance(rows, list):
        return ""
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = str(row.get("scrip_cd") or row.get("scripcode") or row.get("SCRIP_CD") or row.get("Security_Code") or "").strip()
        label = str(row.get("symbol") or row.get("Scrip_Id") or row.get("scrip_id") or "").upper()
        blob = " ".join(str(row.get(key) or "") for key in ("scrip_name", "Scrip_Name", "name", "LONG_NAME", "SHORT_NAME"))
        if code.isdigit() and (label == symbol.upper() or _mentions(blob, names)):
            return code
    return ""


def _sebi_links(names: list[str], path: str, get) -> list[str]:
    if not names:
        return []
    query = urllib.parse.quote(names[0])
    text = _text(get, f"https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListingAll=yes&search={query}")
    if not text:
        return []
    lines = []
    for href, title in _anchors(text):
        if path not in href or not _mentions(title, names):
            continue
        lines.append(f"{title} {href}".strip())
        if len(lines) == 8:
            break
    return lines


def _anchors(page: str) -> list[tuple[str, str]]:
    found = []
    for attrs, inner in _ANCHOR.findall(page):
        values = {key.lower(): html.unescape(value) for key, value in _ATTR.findall(attrs)}
        href = values.get("href", "").strip()
        title = _clean(values.get("title") or _TAG.sub(" ", inner))
        if href and title:
            found.append((href, title))
    return found


def _names(symbol: str, company: str) -> list[str]:
    found = []
    for raw in (company, symbol):
        text = re.sub(r"\b(ltd|limited|inc|corp)\b\.?", "", raw or "", flags=re.IGNORECASE)
        text = text.strip(" .,-")
        if len(text) >= 3 and text.upper() not in {item.upper() for item in found}:
            found.append(text)
    return found


def _mentions(text: str, names: list[str]) -> bool:
    for name in names:
        if re.search(rf"\b{re.escape(name)}\b", text, flags=re.IGNORECASE):
            return True
    return False


def _text(get, url: str) -> str:
    try:
        raw = get(url)
    except Exception:
        return ""
    if not isinstance(raw, (bytes, str)) or not raw:
        return ""
    page = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
    if "Access Denied" in page and "<html" in page.lower():
        return ""
    return page


def _json(text: str):
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _prefix(label: str, lines: list[str]) -> list[str]:
    return [f"{label}: {line}" for line in lines]


def _join(lines: list[str]) -> str:
    return "\n".join(lines[:24])


def _clean(value: str) -> str:
    return _SPACE.sub(" ", html.unescape(value)).strip()


def _headers(url: str) -> dict[str, str]:
    headers = {"User-Agent": _UA, "Accept": "*/*"}
    if "bseindia.com" in url:
        headers["Referer"] = "https://www.bseindia.com/"
    if "nseindia.com" in url:
        headers["Referer"] = "https://www.nseindia.com/"
        headers["Accept"] = "application/json,text/html"
    return headers
