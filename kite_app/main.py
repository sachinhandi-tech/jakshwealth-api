"""Local Kite Connect API. The access token is encrypted in the identity database and is never sent to the browser."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Literal, Optional, Union

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.cors import CORSMiddleware

from kiteconnect.exceptions import TokenException

from kite_app.auth_router import router as zerodha_auth_router
from kite_app.gtt_orders import GttRejected, gtt_state, live_gtt
from kite_app.inbox import recent_signals, remember
from kite_app.kite_service import KiteAuthError, KiteService
from kite_app.scan_jobs import enqueue_scan, read_scan
from kite_app.scanner_data import build_scanner_payload, ohlc_snapshot
from kite_app.signals import SignalScanError
from kite_app.request_context import platform_user_var, request_id_var
from kite_app.ticks import hub
from kite_app.saas_router import router as saas_router
from kite_app.saas_subscription import router as subscription_router
from kite_app.saas_admin import router as admin_router
from kite_app.saas_billing import router as billing_router
from kite_app.saas_whitelabel import router as whitelabel_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("kite_app")

app = FastAPI(title="JakshWealth Kite", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(zerodha_auth_router)
app.include_router(saas_router)
app.include_router(subscription_router)
app.include_router(admin_router)
app.include_router(billing_router)
app.include_router(whitelabel_router)
service = KiteService()

@app.middleware("http")
async def bind_request_context(request: Request, call_next):
    event = request.scope.get("aws.event") or {}
    context = event.get("requestContext") or {}
    incoming = (
        request.headers.get("x-amzn-requestid")
        or request.headers.get("x-request-id")
        or context.get("requestId")
    )
    request_token = request_id_var.set(str(incoming or uuid.uuid4()))
    user_token = platform_user_var.set(request.headers.get("x-platform-user-id"))
    try:
        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id_var.get() or ""
        return response
    finally:
        request_id_var.reset(request_token)
        platform_user_var.reset(user_token)


class LoginRequest(BaseModel):
    api_key: str = Field(min_length=1)
    request_token: str = Field(min_length=1)
    platform_user_id: Optional[uuid.UUID] = None


class SessionStatus(BaseModel):
    authenticated: bool
    user_name: Optional[str] = None
    user_id: Optional[str] = None
    platform_user_id: Optional[str] = None


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
    max_stocks: int = Field(default=100, ge=1, le=3080)
    scan_all_nse: bool = False


class SignalRow(BaseModel):
    rank: int
    ticker: str
    company: str
    crossover_type: str
    crossover_date: str
    close: float
    short_sma: float
    long_sma: float
    trend_sma: Optional[float] = None
    trend_bias: Optional[Literal["above", "below"]] = None


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
    stop_loss: Optional[float] = None
    target: Optional[float] = None
    source: str = "algo"


class QuoteRow(BaseModel):
    symbol: str
    exchange: str
    last_price: Optional[float] = None
    change_percent: Optional[float] = None
    volume: Optional[int] = None


class GttOrderIn(BaseModel):
    symbol: str
    quantity: int = 1
    buy_price: Optional[float] = None
    stoploss: Optional[float] = None
    last_price: Optional[float] = None


class GttStateRequest(BaseModel):
    orders: list[GttOrderIn] = Field(default_factory=list)


class LiveGttRequest(BaseModel):
    confirm_live: Optional[bool] = None
    orders: list[GttOrderIn] = Field(default_factory=list)


def _auth_error(exc: KiteAuthError) -> HTTPException:
    missing = "log in" in str(exc).lower() or "no saved session" in str(exc).lower()
    return HTTPException(status_code=401 if missing else 400, detail=str(exc))


@app.get("/api/kite/subscribers")
def subscribers() -> dict:
    from kite_app.identity_store import list_active_users

    try:
        return {"subscribers": list_active_users()}
    except Exception as exc:
        logger.info("subscriber list failed %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail=type(exc).__name__) from None


@app.get("/api/kite/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/kite/session", response_model=SessionStatus)
def session_status() -> dict:
    return service.session_status()


@app.post("/api/kite/login", response_model=SessionStatus)
def login(body: LoginRequest) -> dict:
    try:
        return service.login(body.request_token, body.platform_user_id)
    except KiteAuthError as exc:
        raise _auth_error(exc) from exc


@app.post("/api/kite/postback")
async def kite_postback(request: Request) -> JSONResponse:
    """Verify the postback checksum and commit it before answering.

    The URL of this route still has to be saved in the Kite developer console.
    That console step is outside this code.
    """
    from kite_app.trading_store import accept_postback

    raw = await request.body()
    result = accept_postback(raw)
    if not result["checksum_valid"]:
        return JSONResponse(status_code=400, content={"checksum_valid": False})
    return JSONResponse(status_code=200, content={"checksum_valid": True})


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


@app.post("/api/kite/signals")
def signals(body: SignalRequest) -> JSONResponse:
    try:
        record = service.require_session()
        params = service.scan_params(
            body.short_window,
            body.long_window,
            body.lookback_days,
            body.max_stocks,
            body.ma_type,
            body.short_type,
            body.long_type,
            body.trend_window,
            body.scan_mode,
            body.scan_all_nse,
        )
        job_id = enqueue_scan(record, params)
    except SignalScanError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KiteAuthError as exc:
        raise _auth_error(exc) from exc
    return JSONResponse(status_code=202, content={"job_id": job_id, "status": "running"})


@app.get("/api/kite/signals/{job_id}")
def signal_job(job_id: str) -> dict:
    job = read_scan(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="That scan was not found.")
    return job


@app.post("/api/kite/algo/signal")
def algo_signal(body: AlgoSignal) -> dict:
    payload = body.model_dump()
    remember(payload)
    logger.info("Algo inbox stored symbol=%s side=%s", payload.get("symbol"), payload.get("transaction_type"))
    return {"stored": True}


@app.get("/api/kite/algo/signals")
def algo_signals() -> dict:
    return {"signals": recent_signals()}


@app.get("/api/scanner-data")
def scanner_data() -> dict:
    try:
        kite = service._require_client()
        return build_scanner_payload(kite)
    except SignalScanError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TokenException as exc:
        service._drop_expired_session(exc)
        raise HTTPException(status_code=401, detail="Log in with a fresh request token. No saved session was found.") from exc
    except KiteAuthError as exc:
        raise _auth_error(exc) from exc


@app.get("/api/ohlc")
def ohlc(symbols: str = "") -> dict:
    try:
        kite = service._require_client()
        return ohlc_snapshot(kite, symbols.split(","))
    except SignalScanError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TokenException as exc:
        service._drop_expired_session(exc)
        raise HTTPException(status_code=401, detail="Log in with a fresh request token. No saved session was found.") from exc
    except KiteAuthError as exc:
        raise _auth_error(exc) from exc


@app.websocket("/ws/ticks")
async def ticks(websocket: WebSocket, tokens: str = "", mode: str = "full", platform_user_id: str = "") -> None:
    await websocket.accept()
    if mode != "full":
        await websocket.close(code=1008)
        return
    user_token = platform_user_var.set(platform_user_id or None)
    try:
        record = service.saved_session()
    finally:
        platform_user_var.reset(user_token)
    subscribed = set()
    for part in tokens.split(","):
        part = part.strip()
        if part.isdigit():
            subscribed.add(int(part))
    if record is None or not subscribed:
        await websocket.close(code=1008)
        return
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def publish(token: int, price: float) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, {"instrument_token": token, "last_price": price})

    listener_id = None
    try:
        listener_id = hub.add(
            str(record["api_key"]),
            str(record["access_token"]),
            subscribed,
            publish,
            platform_user_id=record.get("platform_user_id"),
        )
        while True:
            await websocket.send_json(await queue.get())
    except WebSocketDisconnect:
        return
    except Exception:
        await websocket.close(code=1011)
    finally:
        if listener_id is not None:
            hub.remove(listener_id)


def _gtt_orders(orders: list[GttOrderIn]) -> list[dict]:
    return [order.model_dump() for order in orders]


@app.post("/api/algo-orders/gtt-state")
def algo_gtt_state(body: GttStateRequest) -> dict:
    try:
        kite = service._require_client()
        return {"orders": gtt_state(kite, _gtt_orders(body.orders))}
    except SignalScanError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TokenException as exc:
        service._drop_expired_session(exc)
        raise HTTPException(status_code=401, detail="Log in with a fresh request token. No saved session was found.") from exc
    except KiteAuthError as exc:
        raise _auth_error(exc) from exc


@app.post("/api/algo-orders/live-gtt")
def algo_live_gtt(body: LiveGttRequest) -> dict:
    try:
        record = service.require_session()
        kite = service._require_client()
        return {
            "orders": live_gtt(
                kite,
                _gtt_orders(body.orders),
                body.confirm_live,
                platform_user_id=record.get("platform_user_id"),
                zerodha_user_id=record.get("user_id"),
            )
        }
    except GttRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SignalScanError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TokenException as exc:
        service._drop_expired_session(exc)
        raise HTTPException(status_code=401, detail="Log in with a fresh request token. No saved session was found.") from exc
    except KiteAuthError as exc:
        raise _auth_error(exc) from exc




@app.get("/api/kite/scan/{job_id}/progress")
def get_scan_progress(job_id: str) -> dict:
    """Get real-time scan progress (percentage, ETA, cache hits)."""
    from kite_app.scan_progress import get_progress
    from kite_app.models import get_sessionmaker
    
    db = get_sessionmaker()()
    try:
        progress = get_progress(db, job_id)
        if not progress:
            raise HTTPException(status_code=404, detail="Scan job not found")
        return progress
    finally:
        db.close()


@app.get("/api/kite/performance/metrics")
def get_perf_metrics() -> dict:
    """Get historical scan performance metrics (last 10 scans)."""
    from kite_app.scan_progress import get_performance_metrics as fetch_perf_metrics
    from kite_app.models import get_sessionmaker
    
    db = get_sessionmaker()()
    try:
        metrics = fetch_perf_metrics(db, limit=10)
        return {
            "scans": metrics,
            "latest": metrics[0] if metrics else None,
        }
    finally:
        db.close()


# ============================================================================
# App Config Endpoint - Consolidated from Lambda jw_app_config
# ============================================================================

@app.get("/jw-api/app-config")
async def get_app_config() -> dict:
    """Public application configuration (feature flags, version, environment)."""
    import os
    import sys
    sys.path.insert(0, "lambda/jw_app_config")
    try:
        import feature_flags as app_flags
    except ImportError:
        # Fallback if Lambda code not available
        app_flags = None
    
    def _features():
        if app_flags is None:
            return {"stockAnalysis": True, "aiChat": False}
        try:
            return app_flags.load_feature_flags()
        except Exception:
            return app_flags.default_feature_flags() if hasattr(app_flags, 'default_feature_flags') else {"stockAnalysis": True, "aiChat": False}
    
    def _can_manage_ai_chat():
        if app_flags is None:
            return False
        return app_flags.can_manage_ai_chat() if hasattr(app_flags, 'can_manage_ai_chat') else False
    
    return {
        "appName": "JakshWealth",
        "version": os.environ.get("APP_VERSION", "0.1.0"),
        "environment": (os.environ.get("ENVIRONMENT") or "dev").strip().lower(),
        "features": _features(),
        "enableAiChat": _can_manage_ai_chat(),
    }


# ============================================================================
# Secure Data Endpoints - Consolidated from Lambda jw_secure_data
# ============================================================================

@app.api_route("/jw-api/secure-data", methods=["GET", "POST"])
@app.api_route("/jw-api/secure-data/{path:path}", methods=["GET", "POST", "OPTIONS"])
async def secure_data_handler(request: Request, path: str = ""):
    """Protected endpoints with authorization context and feature dispatch."""
    import os
    import sys
    from datetime import datetime, timezone
    
    # Add Lambda paths to sys.path
    for lambda_path in ["lambda/jw_secure_data", "lambda/jw_app_config"]:
        if lambda_path not in sys.path:
            sys.path.insert(0, lambda_path)
    
    try:
        import feature_flags as secure_flags
        from features import FEATURE_ROUTES
        from routing import dispatch_feature_routes, route_suffix as get_route_suffix
    except ImportError as e:
        logger.warning(f"Secure data features not available: {e}")
        return JSONResponse(
            {"error": "Secure data service unavailable"},
            status_code=503
        )
    
    method = request.method
    
    # Handle OPTIONS
    if method == "OPTIONS":
        return JSONResponse(
            {},
            headers={
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Access-Control-Allow-Headers": "*",
            }
        )
    
    # Extract authorization from headers or AWS context
    authorizer = {}
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        try:
            import json as json_lib
            # Try to parse JWT or custom auth
            authorizer = {"principalId": auth_header[7:]}
        except Exception:
            pass
    
    # Also check x-platform-user-id header
    platform_user_id = request.headers.get("x-platform-user-id", "")
    if platform_user_id:
        authorizer["principalId"] = platform_user_id
    
    # For internal job handling
    if method in ("POST",):
        try:
            body = await request.json()
            if body.get("internal") == "stock_scan_job":
                job_id = str(body.get("jobId", "")).strip()
                if job_id:
                    from kite_app.scan_jobs import run_scan_job
                    run_scan_job(job_id)
                    return JSONResponse({"ok": True})
        except Exception:
            pass
    
    # Get route suffix
    suffix = path.lstrip("/") if path else ""
    
    # Basic secure data response if no suffix
    if not suffix or suffix == "/":
        return JSONResponse({
            "message": "You reached the protected secure-data endpoint.",
            "principalId": authorizer.get("principalId", ""),
            "servedAt": datetime.now(timezone.utc).isoformat(),
        })
    
    # Try feature routing
    try:
        feature_response = dispatch_feature_routes(
            FEATURE_ROUTES,
            suffix=suffix,
            event={"path": f"/jw-api/secure-data/{suffix}"},
            trace=None,
            authorizer=authorizer,
            method=method,
        )
        if feature_response is not None:
            return JSONResponse(feature_response)
    except Exception as e:
        logger.debug(f"Feature routing failed for {suffix}: {e}")
    
    return JSONResponse(
        {"error": f"Unknown secure-data route: {suffix}"},
        status_code=400
    )

