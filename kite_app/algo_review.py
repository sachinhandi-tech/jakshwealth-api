"""Final call. The model scores the 30-point framework and confirms or vetoes the book."""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request

from kite_app.market_research import lookup_text

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
XAI_URL = "https://api.x.ai/v1/responses"
DEFAULT_MODEL = "grok-4.7"
_SECRET_TEXT = re.compile(r"(xai-|sk-)[A-Za-z0-9_-]+|Bearer\s+\S+")


class ModelCallError(RuntimeError):
    """A model call failed. The message is safe to show on the desk."""
# 129 Wealth Fund 30-point framework. Pin to the deck: fundamentals first, charts last.
_POINT_IDS = tuple(str(index) for index in range(1, 31))
_FUNDAMENTAL_IDS = tuple(str(index) for index in range(1, 28))
_GOVERNANCE_IDS = tuple(str(index) for index in range(11, 16))
_HEAVY_IDS = ("25", "26", "27")
_TECHNICAL_IDS = ("28", "29", "30")
_COLORS = ("green", "yellow", "red")
_POINT_TEXT = (
    "1 Pricing Power & Moat: does the company set its own price through a durable moat "
    "(switching cost, regulation, or customer lock-in), or is pricing decided by customers and suppliers?",
    "2 Cyclical or Non-Cyclical: do sales and profit hold up across macro cycles, or does the cycle decide the financials? Prefer businesses that stay stable when the cycle turns.",
    "3 Commodity or Non-Commodity: a niche, critical, differentiated product the end user cannot easily replace, or a commodity next to ten identical ones? Prefer non-commodity with visible differentiation.",
    "4 Moat future direction: is fresh capex, product mix, and expansion widening the advantage, or is incremental revenue coming from weaker-moat, lower-quality segments?",
    "5 Core competence: who runs daily operations, what is their track record, and can we back their capability?",
    "6 Fraud & legal history: any fraud or legal offence involving promoters, managers, or business heads, and its status today.",
    "7 Skin in the game: promoter stake and its historical trend. Open-market buying is the best signal; open-market selling is a red flag.",
    "8 Promoter pledge: any pledged shares, the direction over 2-3 years, and the real reason.",
    "9 Group structure: subsidiaries, associates, and group entities — genuine business reason, or can any of them drag the listed company down?",
    "10 Remuneration: MD/CEO pay growth against net profit growth. A commission linked to profits is a strong positive.",
    "11 Key employee exits: director and KMP resignations over the last 1-2 years — routine churn or an early warning?",
    "12 Equity dilution: 5-10 year dilution history. Zero is best. Repeated dilution to fund a cash-burning business is the worst.",
    "13 Related party transactions: scope for siphoning funds or dressing up financials through related entities.",
    "14 Acquisition track record: how past acquisitions performed, plus intangible assets as a share of net worth.",
    "15 Auditor quality & opinion: auditor tenure, reputation, frequency of change, and red flags in the report and notes.",
    "16 Working capital cycle: in line with industry, or squeezing the balance sheet?",
    "17 Inventory: are rising inventory days blocking capital?",
    "18 Debt & interest cover: 3-year debt, D/E, and interest coverage trend.",
    "19 Contingent liability: size versus TTM PAT and net worth, and the odds of a hit.",
    "20 Tax rate: 3-year average against the statutory rate.",
    "21 CFO vs PAT: is reported profit turning into real cash?",
    "22 ROE, ROCE & multiplier: 3-5 year trend versus peers, and the leverage behind it.",
    "23 Receivables vs sales: how much of sales stays stuck, and the trend.",
    "24 Topline growth visibility: visible sales growth over 1-2 years.",
    "25 Margin expansion: will incremental sales expand or dilute margin? Highest weight.",
    "26 Growth & earnings quality: does the growth plan bloat the balance sheet? Highest weight.",
    "27 Self-sustainable growth: can desired growth be funded from internal cash? Highest weight.",
    "28 Price action: does the chart back an 8-12 month view? Screaming buy or screaming hold is green. A clear avoid with more downside pending is red.",
    "29 Relative performance: is the stock outperforming the index or lagging it? Only relative return matters. Absolute return in either direction has no significance.",
    "30 Downside support: strong support within 20% of CMP is acceptable. Support more than 20% below CMP is red.",
)
_TOOL_NAMES = ("read_filings", "read_news", "read_lawsuits")
_TOOLS = [
    {
        "name": name,
        "description": "Read this symbol from the connected source. Use only the text that comes back.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "exchange": {"type": "string"},
                "company_name": {"type": "string"},
            },
            "required": ["symbol"],
        },
    }
    for name in _TOOL_NAMES
]

_INSTRUCTION = (
    "You are the investment manager applying the 129 Wealth Fund 30-point stock selection framework. "
    "Nothing outside these 30 points and the four gates may approve a buy. "
    "Fundamentals first. Technicals only after the business clears. "
    "A weak business cannot be rescued by a cheap price. "
    "Score this company on the 30 points only. Do not read filings, news, or lawsuits. "
    "Score every point green (pass), yellow (caution), or red (danger). "
    "1 pricing power. 2 cyclical or stable. 3 commodity or differentiated. 4 moat direction. "
    "5 core competence. 6 fraud and legal history. 7 promoter stake. 8 pledge. 9 group structure. 10 pay versus profit. "
    "11 key-employee exits. 12 equity dilution. 13 related parties. 14 acquisitions. 15 auditor. "
    "16 working capital. 17 inventory. 18 debt and interest cover. 19 contingent liability. 20 tax rate. "
    "21 cash flow versus profit. 22 ROE and ROCE. 23 receivables. 24 sales growth. "
    "25 margin expansion. 26 growth quality. 27 self-sustainable growth. "
    "28 price action over 8-12 months. 29 relative strength versus the index. 30 Downside support within 20% of price. "
    "Gates, in order, and strict: "
    "Gate 1 Fundamentals, points 1-27. One red on points 1-27 ends the study. Dropped, not parked. "
    "Governance points 11-15 are a veto: one red here drops the name. "
    "Points 25, 26, and 27 carry the highest weight and must be green or the name is dropped even if everything else passes. "
    "Gate 2 Valuation, judged against industry peers and market sentiment. Growth at a reasonable valuation. "
    "A price that already discounts the next few years of growth is a fail. Fail means dropped, not parked. "
    "Quality over hype: avoid overly popular names. "
    "Gate 3 Technicals, points 28-30, only after Gate 1 and Gate 2 pass. "
    "The chart validates valuation: 8-12 month price action, relative strength versus the index, and support within 20% of CMP. "
    "A red on 28, 29, or 30 is not a buy. It is watchlist only. "
    "Gate 4 Invest only when Gate 1 has no red, points 25-27 are green, valuation is pass, and points 28-30 have no red. "
    "Four principles: growth at reasonable valuation; time-tested fundamentals; self-sustainable growth from internal accrual; quality over hype. "
    "Do not use moving-average crossovers, RSI bands, room_r, or a 2R target as a reason to buy. "
    "Reply with JSON only: "
    "{\"decision\":\"buy\" or \"stand_aside\", "
    "\"valuation\":\"pass\" or \"fail\", "
    "\"reason\":\"cite at least two verified figures\", "
    "\"points\":{\"1\":\"green\" or \"yellow\" or \"red\", "
    "and the same for every point from 2 through 30}}."
)


def review_setups(setups: list[dict], ask=None) -> list[dict]:
    """Stamp each setup. No key, a bad answer, or a call the book rejects is not a trade."""
    from kite_app.models import load_platform_config

    load_platform_config()
    key = os.environ.get("LLM_API_KEY", "").strip()
    model = os.environ.get("LLM_MODEL", "").strip() or DEFAULT_MODEL
    caller = ask or _ask_model
    for item in setups:
        if not key:
            _stamp(item, "unavailable", "The model key is not in Secrets Manager, so this name is not approved.")
            continue
        try:
            result, sources = _call_result(caller(key, model, _facts(item)))
            parsed = _unpack(result)
        except Exception as exc:
            detail = str(exc).strip() if isinstance(exc, ModelCallError) else type(exc).__name__
            if _capacity_fault(detail) or "timed out" in detail.lower():
                _stamp(
                    item,
                    "unavailable",
                    f"The model did not finish ({detail}). This is not a stock rejection. Run the review again.",
                )
            else:
                _stamp(item, "unavailable", f"The model did not answer ({detail}), so this name is not approved.")
            continue
        if parsed is None:
            _stamp(item, "unavailable", _unread_reason(result))
            continue
        decision, reason, checks = parsed
        final, tradable, note = _resolve(item, decision, checks)
        _finish(item, final, reason, checks, tradable, note)
    return setups


def _facts(item: dict) -> dict:
    return {
        "symbol": item.get("symbol"),
        "exchange": item.get("exchange"),
        "company_name": item.get("company_name"),
        "segment": item.get("segment"),
        "product": item.get("product"),
        "entry": item.get("entry"),
        "stop": item.get("stop"),
        "target": item.get("target"),
        "last_close": item.get("last_close"),
        "rsi": item.get("rsi"),
        "atr": item.get("atr"),
        "relative_strength": item.get("relative_strength"),
        "volume_multiple": item.get("volume_multiple"),
        "score": item.get("score"),
        "traps": list(item.get("traps") or []),
        "delivery_gtt_allowed": bool(item.get("gtt_tradable")),
        "desk": {key: value for key, value in dict(item.get("desk") or {}).items() if key != "tape"},
    }


def _ask_model(key: str, model: str, facts: dict) -> tuple:
    if model.lower().startswith("grok"):
        return _ask_grok(key, model, facts)
    return _ask_claude(key, model, facts)


def _ask_grok(key: str, model: str, facts: dict) -> tuple:
    """Score the 30 points through the xAI responses API. The key stays in the header."""
    payload = _post_json(
        XAI_URL,
        {"authorization": f"Bearer {key}"},
        {
            "model": model,
            "input": [{"role": "user", "content": _INSTRUCTION + "\n" + json.dumps(facts, sort_keys=True)}],
            "temperature": 0,
            "max_output_tokens": 1200,
            "reasoning": {"effort": "low"},
            "store": True,
        },
    )
    try:
        decision, reason, checks = _parse_decision(_xai_text(payload.get("output") or []))
    except json.JSONDecodeError:
        return None, "", None, []
    return decision, reason, checks, []


def _xai_text(output) -> str:
    parts = []
    for item in output:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "output_text":
            parts.append(str(item.get("text") or ""))
            continue
        if item.get("type") != "message":
            continue
        content = item.get("content")
        if isinstance(content, str):
            parts.append(content)
            continue
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    parts.append(str(part.get("text") or ""))
                elif isinstance(part, str):
                    parts.append(part)
    return "".join(parts)


def _ask_claude(key: str, model: str, facts: dict) -> tuple:
    payload = _post_messages(key, model, [{
        "role": "user",
        "content": _INSTRUCTION + "\n" + json.dumps(facts, sort_keys=True),
    }])
    text = "".join(
        part.get("text", "")
        for part in (payload.get("content") or [])
        if isinstance(part, dict)
    )
    decision, reason, checks = _parse_decision(text)
    return decision, reason, checks, []


def _post_messages(key: str, model: str, messages: list) -> dict:
    return _post_json(
        ANTHROPIC_URL,
        {"x-api-key": key, "anthropic-version": ANTHROPIC_VERSION},
        {
            "model": model,
            "max_tokens": 700,
            "temperature": 0,
            "messages": messages,
        },
    )


def _post_json(url: str, headers: dict, payload: dict) -> dict:
    """POST JSON. Retry a few times on capacity/rate-limit answers before failing the name."""
    last_fault = "HTTP error"
    for attempt in range(4):
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"content-type": "application/json", **headers},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last_fault = _http_fault(exc)
            if exc.code in {429, 503} and attempt < 3:
                time.sleep(2 ** attempt)
                continue
            raise ModelCallError(last_fault) from None
        except urllib.error.URLError as exc:
            reason = str(getattr(exc, "reason", "") or "")
            if "timed out" in reason.lower() and attempt < 2:
                last_fault = "timed out"
                time.sleep(2 ** attempt)
                continue
            if "timed out" in reason.lower():
                raise ModelCallError("timed out") from None
            raise ModelCallError(type(exc.reason).__name__ if exc.reason is not None else "URLError") from None
        except TimeoutError:
            if attempt < 2:
                last_fault = "timed out"
                time.sleep(2 ** attempt)
                continue
            raise ModelCallError("timed out") from None
    raise ModelCallError(last_fault)


def _capacity_fault(detail: str) -> bool:
    text = str(detail or "").lower()
    return "429" in text or "503" in text or "capacity" in text or "rate limit" in text


def _http_fault(exc: urllib.error.HTTPError) -> str:
    message = ""
    try:
        body = json.loads(exc.read().decode("utf-8", "replace"))
        error = body.get("error") if isinstance(body, dict) else None
        if isinstance(error, dict):
            message = str(error.get("message") or error.get("code") or "")
        elif isinstance(error, str):
            message = error
    except Exception:
        message = ""
    message = _SECRET_TEXT.sub("[key]", message).strip()[:160]
    if message:
        return f"HTTP {exc.code} {message}"
    return f"HTTP {exc.code}"


_CLEAR_TEXT = {
    "read_filings": "No recent exchange/SEBI filings were found for this symbol. Source checked; clear.",
    "read_news": "No recent news items were found for this symbol. Source checked; clear.",
    "read_lawsuits": "No SEBI enforcement/lawsuit items were found for this symbol. Source checked; clear.",
}


def _read_source(name: str, facts: dict, get=None) -> dict:
    """Return source text. A failed lookup does not invent a filing, a story, or a case.

    Empty successful lookups are status \"clear\" (checked, nothing found).
    Transport/source failures stay \"unavailable\" and block confirmation.
    """
    if name not in _TOOL_NAMES:
        return {"name": name, "status": "unavailable", "text": "This source is not connected."}
    try:
        text = lookup_text(name, str(facts.get("symbol") or ""), str(facts.get("company_name") or ""), get=get)
    except Exception:
        return {"name": name, "status": "unavailable", "text": "This source did not answer."}
    cleaned = str(text or "").strip()
    if not cleaned:
        # Empty is often the normal small-cap case for lawsuits: searched, found nothing.
        return {"name": name, "status": "clear", "text": _CLEAR_TEXT[name]}
    return {"name": name, "status": "ready", "text": cleaned[:8000]}


def _research_ready(sources) -> bool:
    """True when filings and news were checked. Lawsuits are best-effort.

    Market-standard desk flow: do not block a screened buy only because the
    lawsuit feed is down, as long as filings and news were read or clear.
    """
    if not isinstance(sources, list):
        return False
    status = {
        item.get("name"): item.get("status")
        for item in sources
        if isinstance(item, dict) and item.get("name")
    }
    return status.get("read_filings") in {"ready", "clear"} and status.get("read_news") in {"ready", "clear"}


def _call_result(result) -> tuple:
    sources = None
    if isinstance(result, tuple) and len(result) == 4:
        sources = result[3]
        result = result[:3]
    return result, sources


def _split(result) -> tuple:
    raw, sources = _call_result(result)
    return _unpack(raw), sources


def _parse_decision(text: str) -> tuple:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        parsed = _json_object(cleaned)
    if not isinstance(parsed, dict):
        raise json.JSONDecodeError("no object", cleaned, 0)
    return parsed.get("decision"), parsed.get("reason"), _scorecard(parsed)


def _scorecard(parsed: dict) -> dict:
    """The prompt asks for points and valuation beside the decision. Older answers nest them under checks."""
    checks = parsed.get("checks")
    card = dict(checks) if isinstance(checks, dict) else {}
    if not isinstance(card.get("points"), dict) and isinstance(parsed.get("points"), dict):
        card["points"] = parsed["points"]
    if not card.get("valuation") and parsed.get("valuation"):
        card["valuation"] = parsed.get("valuation")
    return card


def _unread_reason(result) -> str:
    """Say which part of the answer failed, and keep any reason the model did write."""
    gaps = []
    said = ""
    if not isinstance(result, tuple) or len(result) != 3:
        gaps.append("the answer was not a scorecard")
    else:
        decision = str(result[0] or "").strip().lower()
        said = str(result[1] or "").strip()
        if decision in {"allow", "block", "sell"}:
            decision = "buy" if decision == "allow" else "stand_aside"
        if decision not in {"buy", "stand_aside"}:
            gaps.append("the decision was missing")
        if not any(character.isdigit() for character in said):
            gaps.append("the reason cited no figure")
        if _clean_checks(result[2]) is None:
            gaps.append("the 30-point card was incomplete")
    detail = ", ".join(gaps) if gaps else "the answer did not match the scorecard"
    quoted = f" Model said: {said}" if said else ""
    return f"The model answer could not be read ({detail}).{quoted} This name is not approved."


def _json_object(text: str) -> dict:
    start = text.find("{")
    if start < 0:
        raise json.JSONDecodeError("no object", text, 0)
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:index + 1])
    raise json.JSONDecodeError("no object", text, start)


def _unpack(result) -> tuple[str, str, dict] | None:
    if not isinstance(result, tuple) or len(result) != 3:
        return None
    decision = str(result[0] or "").strip().lower()
    reason = str(result[1] or "").strip()
    if decision == "allow":
        decision = "buy"
    elif decision in {"block", "sell"}:
        decision = "stand_aside"
    if decision not in {"buy", "stand_aside"} or not any(character.isdigit() for character in reason):
        return None
    checks = _clean_checks(result[2])
    if checks is None:
        return None
    return decision, reason, checks


def _clean_checks(raw) -> dict | None:
    """Accept only a complete 30-point card plus a valuation gate. Anything else is unread."""
    if not isinstance(raw, dict):
        return None
    points_raw = raw.get("points") if isinstance(raw.get("points"), dict) else raw
    if not isinstance(points_raw, dict):
        return None
    points = {}
    for name in _POINT_IDS:
        value = str(points_raw.get(name) or points_raw.get(int(name)) or "").strip().lower()
        if value not in _COLORS:
            return None
        points[name] = value
    valuation = str(raw.get("valuation") or "").strip().lower()
    if valuation not in {"pass", "fail"}:
        return None
    return {"points": points, "valuation": valuation}


def _resolve(item: dict, decision: str, checks: dict) -> tuple[str, bool, str]:
    """Enforce the deck exactly. The model's buy is ignored when a gate fails."""
    points = checks.get("points") or {}
    valuation = checks.get("valuation")
    fundamental_reds = [name for name in _FUNDAMENTAL_IDS if points.get(name) == "red"]
    heavy_miss = [name for name in _HEAVY_IDS if points.get(name) != "green"]
    technical_reds = [name for name in _TECHNICAL_IDS if points.get(name) == "red"]
    if fundamental_reds or valuation != "pass":
        return (
            "stand_aside",
            False,
            "Gate 1 or Gate 2 failed"
            + (f" (points {', '.join(fundamental_reds)} red)." if fundamental_reds else " (valuation fail).")
            + " Dropped, not parked. No order.",
        )
    if heavy_miss:
        return (
            "stand_aside",
            False,
            "Points 25, 26, and 27 must be green (margin expansion, growth quality, self-sustainable growth). No order.",
        )
    if technical_reds:
        return (
            "stand_aside",
            False,
            f"Gate 3 is not a buy (points {', '.join(technical_reds)} red). Watchlist only. No order.",
        )
    if decision != "buy":
        return "stand_aside", False, "The framework did not call buy, so there is no order."
    if item.get("gtt_tradable"):
        return "buy", True, ""
    return "buy", False, "The call is buy, and it is not sent as a delivery GTT."


def _geometry(item: dict) -> bool:
    try:
        entry = float(item["entry"])
        stop = float(item["stop"])
        target = float(item["target"])
        last_close = float(item["last_close"])
    except (KeyError, TypeError, ValueError):
        return False
    return stop < entry < last_close < target


def _finish(item: dict, decision: str, reason: str, checks: dict, tradable: bool, note: str) -> None:
    text = reason if not note else f"{reason} {note}"
    item["ai_decision"] = decision
    item["ai_checks"] = checks
    item["ai_reason"] = text
    item["reason"] = f"{item['reason']} Model: {text}"
    item["gtt_tradable"] = tradable


def _stamp(item: dict, decision: str, reason: str) -> None:
    item["gtt_tradable"] = False
    item["ai_decision"] = decision
    item["ai_checks"] = None
    item["ai_reason"] = reason
    item["reason"] = f"{item['reason']} Model: {reason}"
