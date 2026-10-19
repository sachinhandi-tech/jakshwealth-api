"""Local Kite Connect API. The access token is saved on disk and never sent to the browser."""

from __future__ import annotations

import json
import logging
import os
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

from kite_app.auth_router import router as zerodha_auth_router
from kite_app.kite_service import KiteAuthError, KiteService
from kite_app.signals import SignalScanError
from kite_app.univest import (
    UnivestParseError,
    dispatch,
    parse_univest,
    recent_attempts,
    recent_signals,
    record_attempt,
    remember,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("kite_app.univest")

app = FastAPI(title="JakshWealth Kite", version="1.0.0")
app.include_router(zerodha_auth_router)
service = KiteService()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


class LoginRequest(BaseModel):
    api_key: str = Field(min_length=1)
    api_secret: str = Field(min_length=1)
    request_token: str = Field(min_length=1)


class SessionStatus(BaseModel):
    authenticated: bool
    user_name: str | None = None
    user_id: str | None = None


class ProfileResponse(BaseModel):
    user_name: str
    user_id: str
    products: list[str]
    exchanges: list[str]


class SignalRequest(BaseModel):
    scan_mode: Literal["crossover", "price"] = "crossover"
    ma_type: Literal["sma", "ema", "wma"] = "ema"
    short_type: Literal["sma", "ema", "wma"] = "ema"
    long_type: Literal["sma", "ema", "wma"] = "sma"
    short_window: int = Field(default=20, ge=2, le=200)
    long_window: int = Field(default=50, ge=3, le=400)
    trend_window: int = Field(default=200, ge=0, le=400)
    lookback_days: int = Field(default=60, ge=1, le=400)
    max_stocks: int = Field(default=25, ge=1, le=100)


class SignalRow(BaseModel):
    rank: int
    ticker: str
    company: str
    crossover_type: str
    crossover_date: str
    close: float
    short_sma: float
    long_sma: float
    trend_sma: float | None = None
    trend_bias: Literal["above", "below"] | None = None


class SignalResponse(BaseModel):
    scan_mode: Literal["crossover", "price"] = "crossover"
    ma_type: Literal["sma", "ema", "wma"] = "ema"
    short_type: Literal["sma", "ema", "wma"] = "ema"
    long_type: Literal["sma", "ema", "wma"] = "sma"
    trend_window: int = 0
    short_window: int
    long_window: int
    lookback_days: int
    universe: int
    scanned: int
    skipped: int
    signals: list[SignalRow]


class AlgoSignal(BaseModel):
    model_config = ConfigDict(extra="allow")
    symbol: str
    transaction_type: str
    entry_price: float
    stop_loss: float | None = None
    target: float | None = None
    source: str = "univest"


class QuoteRow(BaseModel):
    symbol: str
    exchange: str
    last_price: float | None = None
    change_percent: float | None = None
    volume: int | None = None


def _auth_error(exc: KiteAuthError) -> HTTPException:
    missing = "log in" in str(exc).lower() or "no saved session" in str(exc).lower()
    return HTTPException(status_code=401 if missing else 400, detail=str(exc))


@app.get("/api/kite/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/kite/session", response_model=SessionStatus)
def session_status() -> dict:
    return service.session_status()


@app.post("/api/kite/login", response_model=SessionStatus)
def login(body: LoginRequest) -> dict:
    try:
        return service.login(body.api_key, body.api_secret, body.request_token)
    except KiteAuthError as exc:
        raise _auth_error(exc) from exc


@app.post("/api/kite/logout", response_model=SessionStatus)
def logout() -> dict:
    return service.logout()


@app.get("/api/kite/profile", response_model=ProfileResponse)
def profile() -> dict:
    try:
        return service.profile()
    except KiteAuthError as exc:
        raise _auth_error(exc) from exc


@app.get("/api/kite/quotes", response_model=list[QuoteRow])
def quotes() -> list[dict]:
    try:
        return service.quotes()
    except KiteAuthError as exc:
        raise _auth_error(exc) from exc


@app.post("/api/kite/signals", response_model=SignalResponse)
def signals(body: SignalRequest) -> dict:
    try:
        return service.scan_signals(
            body.short_window,
            body.long_window,
            body.lookback_days,
            body.max_stocks,
            body.ma_type,
            body.short_type,
            body.long_type,
            body.trend_window,
            body.scan_mode,
        )
    except SignalScanError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KiteAuthError as exc:
        raise _auth_error(exc) from exc


def _ingest_allowed(request: Request, secret: str | None) -> None:
    expected = os.environ.get("UNIVEST_INGEST_SECRET", "")
    host = request.client.host if request.client else ""
    if host in {"127.0.0.1", "::1"}:
        return
    if not expected:
        raise HTTPException(
            status_code=403,
            detail="Set UNIVEST_INGEST_SECRET before accepting notifications from a phone.",
        )
    if secret != expected:
        raise HTTPException(status_code=401, detail="Invalid Univest ingest secret.")


@app.post("/api/univest/notification")
async def univest_notification(request: Request) -> dict:
    _ingest_allowed(request, request.headers.get("x-univest-secret"))
    raw_body = (await request.body()).decode("utf-8", errors="replace").strip()
    if len(raw_body) > 4000:
        raw_body = raw_body[:4000]
    title = ""
    text = raw_body
    if "json" in request.headers.get("content-type", "").lower():
        try:
            data = json.loads(raw_body)
        except json.JSONDecodeError:
            logger.warning("Univest body was not valid JSON; parsing the raw text")
        else:
            if isinstance(data, dict):
                title = str(data.get("title") or "")
                text = str(data.get("text") or "")
    raw = "\n".join(part.strip() for part in (title, text) if part and part.strip())
    if not raw:
        logger.warning("Ignored Univest notification: empty body")
        record_attempt("", None, "Empty notification.")
        return {"accepted": False, "error": "Empty notification.", "payload": None, "dispatched": False}
    try:
        payload = parse_univest(raw)
    except UnivestParseError as exc:
        logger.warning("Ignored Univest notification: %s | text=%s", exc, raw[:180])
        record_attempt(raw, None, str(exc))
        return {"accepted": False, "error": str(exc), "payload": None, "dispatched": False}
    except Exception:
        logger.exception("Univest parser failed")
        record_attempt(raw, None, "The notification could not be parsed.")
        return {
            "accepted": False,
            "error": "The notification could not be parsed.",
            "payload": None,
            "dispatched": False,
        }
    record_attempt(raw, payload, None)
    delivery = dispatch(payload)
    if not delivery.get("dispatched"):
        remember(payload)
    return {
        "accepted": True,
        "payload": payload,
        "dispatched": bool(delivery.get("dispatched")),
        "dispatch_error": delivery.get("error"),
    }


@app.post("/api/kite/algo/signal")
def algo_signal(body: AlgoSignal) -> dict:
    payload = body.model_dump()
    remember(payload)
    logger.info("Algo inbox stored symbol=%s side=%s", payload.get("symbol"), payload.get("transaction_type"))
    return {"stored": True}


@app.get("/api/kite/algo/signals")
def algo_signals() -> dict:
    return {"signals": recent_signals(), "attempts": recent_attempts()}


