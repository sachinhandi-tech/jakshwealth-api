import json

from kite_app.algo_review import _read_source
from kite_app.market_research import lookup_text


def _pages(url: str) -> bytes:
    if url == "https://www.nseindia.com/":
        return b"ok"
    if "corporate-announcements" in url and "symbol=INFY" in url:
        return json.dumps({"data": [{"desc": "Outcome of board meeting", "an_dt": "02-Oct-2026"}]}).encode()
    if "PeerSmartSearch" in url:
        return json.dumps([{"scrip_cd": "500209", "Scrip_Id": "INFY", "scrip_name": "INFOSYS LTD"}]).encode()
    if "AnnGetData" in url and "strScrip=500209" in url:
        return json.dumps({"Table": [{"NEWSSUB": "Analyst meet intimation", "News_submission_dt": "2026-10-03T10:00:00"}]}).encode()
    if "news.google.com" in url:
        return b"""<rss><channel><item><title>Infosys wins a deal</title><pubDate>Fri, 03 Oct 2026</pubDate></item></channel></rss>"""
    if "sebi.gov.in" in url and "search=Infosys" in url:
        return """
        <a href="https://www.sebi.gov.in/filings/buybacks/nov-2025/infosys-limited.html" title="Infosys Limited buyback">Infosys Limited buyback</a>
        <a href="https://www.sebi.gov.in/enforcement/orders/sep-2024/final-order-infosys.html" title="Final order in the matter of Infosys Ltd">Final order in the matter of Infosys Ltd</a>
        <a href="https://www.sebi.gov.in/enforcement/orders/nov-2024/hcl-infosystems.html" title="Exemption order in the matter of HCL Infosystems Limited">HCL Infosystems</a>
        """.encode()
    if "Access Denied" in url:
        return b"<html><title>Access Denied</title></html>"
    raise AssertionError(url)


def test_filings_keep_nse_bse_and_sebi_text_for_the_company():
    text = lookup_text("read_filings", "INFY", "Infosys Limited", get=_pages)
    assert "NSE: 02-Oct-2026 Outcome of board meeting" in text
    assert "BSE: 2026-10-03T10:00:00 Analyst meet intimation" in text
    assert "SEBI filing: Infosys Limited buyback" in text
    assert "HCL Infosystems" not in text
    assert "Final order" not in text


def test_news_and_orders_use_only_the_returned_text():
    news = lookup_text("read_news", "INFY", "Infosys Limited", get=_pages)
    orders = lookup_text("read_lawsuits", "INFY", "Infosys Limited", get=_pages)
    assert news == "News: Fri, 03 Oct 2026 Infosys wins a deal"
    assert "Final order in the matter of Infosys Ltd" in orders
    assert "HCL Infosystems" not in orders
    assert "buyback" not in orders


def test_denied_and_failed_sources_are_not_turned_into_a_story():
    def denied(url):
        if "nseindia.com" in url or "bseindia.com" in url:
            return b"<HTML><TITLE>Access Denied</TITLE></HTML>"
        if "news.google.com" in url:
            raise OSError("down")
        if "sebi.gov.in" in url:
            return b"<a href='https://www.sebi.gov.in/enforcement/orders/x.html' title='Unrelated order'>Unrelated order</a>"
        raise AssertionError(url)

    missed = _read_source("read_filings", {"symbol": "INFY", "company_name": "Infosys Limited"}, get=denied)
    assert missed["status"] == "unavailable"
    assert missed["text"] == "This source returned no text."
    news = _read_source("read_news", {"symbol": "INFY", "company_name": "Infosys Limited"}, get=denied)
    assert news["status"] == "unavailable"
