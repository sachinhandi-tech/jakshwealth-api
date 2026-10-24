"""Final call. The model reads filings, news, and lawsuits, then confirms or vetoes the book."""

from __future__ import annotations

import json
import os
import re
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
_CHECKS = ("trend", "participation", "volatility", "asymmetry", "invalidation")
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
    "You are the portfolio manager making the final buy, sell, or stand-aside call. "
    "Before the call, use read_filings, read_news, and read_lawsuits for this symbol. "
    "Use only the tool text for filings, news, and lawsuits. Do not invent filings, news, or lawsuits. "
    "If a tool says the source is not connected or returned no text, that source was not read. "
    "Then work the book in this order: trend, participation, volatility, asymmetry, invalidation. "
    "Use the numbers in the payload, including the tape, and the tool text. "
    "This name already passed the moving-average crossover, the price and volume expansion, and the RSI momentum and ATR screen. "
    "A false screen was not seen. "
    "book_call is the arithmetic. Confirm it or veto it. "
    "Do not call buy unless book_call is buy, every check passes, and all three sources were read. "
    "Do not call sell unless book_call is sell, invalidation fails, and all three sources were read. "
    "A missing 200-session average is not a pass. Do not invent it. "
    "A sell is a call only. It is not an order. "
    "After the tools, reply with JSON only: "
    "{\"decision\":\"buy\" or \"sell\" or \"stand_aside\", "
    "\"reason\":\"cite at least two figures\", "
    "\"checks\":{\"trend\":\"pass\" or \"fail\", \"participation\":\"pass\" or \"fail\", "
    "\"volatility\":\"pass\" or \"fail\", \"asymmetry\":\"pass\" or \"fail\", "
    "\"invalidation\":\"pass\" or \"fail\"}}."
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
            parsed, sources = _split(caller(key, model, _facts(item)))
        except Exception as exc:
            detail = str(exc).strip() if isinstance(exc, ModelCallError) else type(exc).__name__
            _stamp(item, "unavailable", f"The model did not answer ({detail}), so this name is not approved.")
            continue
        if parsed is None:
            _stamp(item, "unavailable", "The model answer could not be read, so this name is not approved.")
            continue
        decision, reason, checks = parsed
        if sources is not None and not _research_ready(sources):
            _finish(item, "stand_aside", reason, checks, False, "Filings, news, and lawsuits were not all read, so there is no order.")
            continue
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
        "desk": dict(item.get("desk") or {}),
    }


def _ask_model(key: str, model: str, facts: dict) -> tuple:
    if model.lower().startswith("grok"):
        return _ask_grok(key, model, facts)
    return _ask_claude(key, model, facts)


def _ask_grok(key: str, model: str, facts: dict) -> tuple:
    """Read filings, news, and lawsuits through the xAI responses API. The key stays in the header."""
    tools = [
        {
            "type": "function",
            "name": name,
            "description": "Read this symbol from the connected source. Use only the text that comes back.",
            "parameters": {
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
    body = {
        "model": model,
        "input": [{"role": "user", "content": _INSTRUCTION + "\n" + json.dumps(facts, sort_keys=True)}],
        "temperature": 0,
        "max_output_tokens": 1200,
        "store": True,
        "tools": tools,
        "search_parameters": {"mode": "off"},
    }
    sources = []
    for _ in range(4):
        payload = _post_json(XAI_URL, {"authorization": f"Bearer {key}"}, body)
        output = payload.get("output") or []
        calls = [item for item in output if isinstance(item, dict) and item.get("type") == "function_call"]
        if not calls:
            try:
                decision, reason, checks = _parse_decision(_xai_text(output))
            except json.JSONDecodeError:
                return None, "", None, sources
            return decision, reason, checks, sources
        results = []
        for call in calls:
            function = call.get("function") if isinstance(call.get("function"), dict) else {}
            observed = _read_source(str(call.get("name") or function.get("name") or ""), facts)
            sources.append(observed)
            results.append({
                "type": "function_call_output",
                "call_id": call.get("call_id") or call.get("id"),
                "output": observed["text"],
            })
        body = {
            "model": model,
            "previous_response_id": payload.get("id"),
            "input": results,
            "temperature": 0,
            "max_output_tokens": 1200,
            "store": True,
            "tools": tools,
            "search_parameters": {"mode": "off"},
        }
    raise ModelCallError("research tools did not finish")


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
    messages = [{
        "role": "user",
        "content": _INSTRUCTION + "\n" + json.dumps(facts, sort_keys=True),
    }]
    sources = []
    for _ in range(4):
        payload = _post_messages(key, model, messages)
        content = payload.get("content") or []
        tool_uses = [part for part in content if isinstance(part, dict) and part.get("type") == "tool_use"]
        if not tool_uses:
            text = "".join(
                part.get("text", "")
                for part in content
                if isinstance(part, dict)
            )
            decision, reason, checks = _parse_decision(text)
            return decision, reason, checks, sources
        messages.append({"role": "assistant", "content": content})
        results = []
        for call in tool_uses:
            observed = _read_source(str(call.get("name") or ""), facts)
            sources.append(observed)
            results.append({
                "type": "tool_result",
                "tool_use_id": call.get("id"),
                "content": observed["text"],
            })
        messages.append({"role": "user", "content": results})
    raise ModelCallError("research tools did not finish")


def _post_messages(key: str, model: str, messages: list) -> dict:
    return _post_json(
        ANTHROPIC_URL,
        {"x-api-key": key, "anthropic-version": ANTHROPIC_VERSION},
        {
            "model": model,
            "max_tokens": 1200,
            "temperature": 0,
            "tools": _TOOLS,
            "messages": messages,
        },
    )


def _post_json(url: str, headers: dict, payload: dict) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise ModelCallError(_http_fault(exc)) from None
    except urllib.error.URLError as exc:
        reason = str(getattr(exc, "reason", "") or "")
        if "timed out" in reason.lower():
            raise ModelCallError("timed out") from None
        raise ModelCallError(type(exc.reason).__name__ if exc.reason is not None else "URLError") from None
    except TimeoutError:
        raise ModelCallError("timed out") from None


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


def _read_source(name: str, facts: dict, get=None) -> dict:
    """Return source text. A failed lookup does not invent a filing, a story, or a case."""
    if name not in _TOOL_NAMES:
        return {"name": name, "status": "unavailable", "text": "This source is not connected."}
    try:
        text = lookup_text(name, str(facts.get("symbol") or ""), str(facts.get("company_name") or ""), get=get)
    except Exception:
        return {"name": name, "status": "unavailable", "text": "This source did not answer."}
    cleaned = str(text or "").strip()
    if not cleaned:
        return {"name": name, "status": "unavailable", "text": "This source returned no text."}
    return {"name": name, "status": "ready", "text": cleaned[:8000]}


def _research_ready(sources) -> bool:
    if not isinstance(sources, list):
        return False
    ready = {
        item.get("name")
        for item in sources
        if isinstance(item, dict) and item.get("status") == "ready"
    }
    return set(_TOOL_NAMES) <= ready


def _split(result) -> tuple:
    sources = None
    if isinstance(result, tuple) and len(result) == 4:
        sources = result[3]
        result = result[:3]
    return _unpack(result), sources


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
    return parsed.get("decision"), parsed.get("reason"), parsed.get("checks")


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
    elif decision == "block":
        decision = "stand_aside"
    if decision not in {"buy", "sell", "stand_aside"} or not any(character.isdigit() for character in reason):
        return None
    checks = _clean_checks(result[2])
    if checks is None:
        return None
    return decision, reason, checks


def _clean_checks(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    checks = {}
    for name in _CHECKS:
        value = str(raw.get(name) or "").strip().lower()
        if value not in {"pass", "fail"}:
            return None
        checks[name] = value
    return checks


def _resolve(item: dict, decision: str, checks: dict) -> tuple[str, bool, str]:
    book = str((item.get("desk") or {}).get("book_call") or "stand_aside")
    if decision == "buy" and book == "buy" and all(value == "pass" for value in checks.values()) and _geometry(item) and not item.get("traps"):
        if item.get("gtt_tradable"):
            return "buy", True, ""
        return "buy", False, "The call is buy, and it is not sent as a delivery GTT."
    if decision == "sell" and book == "sell" and checks["invalidation"] == "fail":
        return "sell", False, "This sell is a call only. No short GTT is sent."
    if decision == "stand_aside" and book == "stand_aside":
        return "stand_aside", False, ""
    return "stand_aside", False, "The book does not support that call, so there is no order."


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
