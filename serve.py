#!/usr/bin/env python3
"""Local development server for jakshwealth-api.

Routes HTTP requests to the matching Lambda handler based on each Lambda's
``integration.json``. All endpoints are public (no authorizer).

Each Lambda is fully self-contained, so the runner isolates per-Lambda modules
(``config``, ``logger``, ...) between invocations.

Usage:
    cp config.local.example.json config.local.json   # optional local overrides
    export ENVIRONMENT=local
    pip install -r requirements.txt
    python serve.py
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

from flask import Flask, Response, request

ROOT = Path(__file__).resolve().parent
LAMBDA_DIR = ROOT / "lambda"

_cors_module = None


def _cors():
    global _cors_module
    if _cors_module is None:
        spec = importlib.util.spec_from_file_location(
            "jw_cors", LAMBDA_DIR / "jw_app_config" / "cors.py"
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        _cors_module = module
    return _cors_module

app = Flask(__name__)

routes: dict[str, str] = {}
route_meta: dict[str, dict] = {}
_handler_cache: dict[str, object] = {}
_bootstrapped = False


def _load_app_config() -> None:
    """Fetch AWS secrets and apply local overrides once when the server starts."""
    if os.environ.get("_JW_CONFIG_LOADED") == "1":
        return
    config_path = LAMBDA_DIR / "jw_app_config"
    if str(config_path) not in sys.path:
        sys.path.insert(0, str(config_path))
    config_file = config_path / "config.py"
    spec = importlib.util.spec_from_file_location("jw_bootstrap_config", config_file)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    module.load_config()
    print("[serve] application config loaded at startup", flush=True)


def bootstrap() -> None:
    global _bootstrapped
    if _bootstrapped:
        return
    os.environ.setdefault("ENVIRONMENT", "local")
    os.environ.setdefault("LOCAL_CONFIG_FILE", str(ROOT / "config.local.json"))
    os.environ.setdefault("FEATURE_FLAGS_OVERRIDE_FILE", str(ROOT / "feature_flags.local.json"))
    _load_app_config()
    _load_routes()
    if os.environ.get("PREWARM_LAMBDAS", "true").lower() == "true":
        _prewarm_handlers()
    _bootstrapped = True


def _load_routes() -> None:
    global routes, route_meta
    routes, route_meta = {}, {}
    for entry in sorted(LAMBDA_DIR.iterdir()):
        integration = entry / "integration.json"
        if not entry.is_dir() or not integration.exists():
            continue
        meta = json.loads(integration.read_text(encoding="utf-8"))
        full_path = meta["full_path"].strip("/") + "/"
        routes[full_path] = entry.name
        route_meta[full_path] = meta


def _resolve_lambda(path: str) -> tuple[str | None, str]:
    normalized = path if path.endswith("/") else path + "/"
    if normalized in routes:
        return routes[normalized], normalized
    for prefix, name in sorted(routes.items(), key=lambda item: -len(item[0])):
        if normalized.startswith(prefix):
            return name, prefix
    return None, ""


def _evict_other_lambda_modules(lambda_path: Path) -> None:
    """Remove imported modules from other Lambdas to avoid name collisions."""
    for name, module in list(sys.modules.items()):
        module_file = getattr(module, "__file__", None) or ""
        if module_file.startswith(str(LAMBDA_DIR)) and not module_file.startswith(str(lambda_path)):
            del sys.modules[name]


def _prioritize_lambda_path(lambda_path: Path) -> None:
    """Ensure this Lambda's directory wins ``import`` resolution for shared module names."""
    path_str = str(lambda_path)
    if path_str in sys.path:
        sys.path.remove(path_str)
    sys.path.insert(0, path_str)


def _load_handler(lambda_name: str):
    """Load a Lambda handler once and cache it for the life of the dev server."""
    if lambda_name in _handler_cache:
        return _handler_cache[lambda_name]

    lambda_path = LAMBDA_DIR / lambda_name
    _evict_other_lambda_modules(lambda_path)
    _prioritize_lambda_path(lambda_path)

    spec = importlib.util.spec_from_file_location(
        f"jw_handler_{lambda_name}", lambda_path / "handler.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    _handler_cache[lambda_name] = module
    return module


def _prewarm_handlers() -> None:
    """Import Lambdas at startup so the first HTTP request is not a cold start."""
    for lambda_name in sorted(set(routes.values())):
        try:
            _load_handler(lambda_name)
            print(f"[serve] prewarmed {lambda_name}", flush=True)
        except Exception as exc:
            print(f"[serve] prewarm skipped {lambda_name}: {exc}", flush=True)


def _invoke_lambda(lambda_name: str, event: dict) -> dict:
    """Invoke a cached Lambda handler."""
    lambda_path = LAMBDA_DIR / lambda_name
    _evict_other_lambda_modules(lambda_path)
    _prioritize_lambda_path(lambda_path)
    return _load_handler(lambda_name).handler(event, None)


def _header(headers: dict, name: str):
    target = name.lower()
    for key, value in headers.items():
        if isinstance(key, str) and key.lower() == target and value:
            return value
    return None


def _normalize_headers(raw_headers, environ=None) -> dict:
    """Build headers including underscore custom names (e.g. auth_code)."""
    headers = dict(raw_headers)
    if environ:
        for key, value in environ.items():
            if key.startswith("HTTP_") and value:
                wsgi_name = key[5:].lower()
                headers[wsgi_name] = value
                headers[wsgi_name.replace("_", "-")] = value
    for key in list(headers.keys()):
        if isinstance(key, str):
            headers.setdefault(key.replace("-", "_"), headers[key])
            headers.setdefault(key.lower(), headers[key])
    return headers


def _bind_request_origin(headers: dict) -> None:
    _cors().bind_request_origin({"headers": headers})


def _clear_request_origin() -> None:
    _cors().clear_request_origin()


def _cors_headers_for_request() -> dict[str, str]:
    return _cors().cors_headers("GET,POST,OPTIONS", json_response=False)


def _deny(message: str, status: int) -> Response:
    return Response(
        json.dumps({"message": message}),
        status=status,
        mimetype="application/json",
        headers=_cors_headers_for_request(),
    )


def _authorize(lambda_name, meta, method, endpoint, headers):
    """All routes are public for this personal deployment."""
    del lambda_name, meta, method, endpoint, headers
    return True, None, None


def _to_flask_response(lambda_response: dict) -> Response:
    return Response(
        lambda_response.get("body", "") or "",
        status=lambda_response.get("statusCode", 200),
        headers=lambda_response.get("headers", {}),
    )


@app.route("/", defaults={"path": ""}, methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
@app.route("/<path:path>", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
def handle(path):
    full_path = path if path.startswith("jw-api/") else f"jw-api/{path}"
    lambda_name, route_key = _resolve_lambda(full_path)
    if not lambda_name:
        return _deny(f"No lambda for path: {full_path}", 404)

    headers = _normalize_headers(dict(request.headers), request.environ)
    _bind_request_origin(headers)
    try:
        endpoint = route_key.rstrip("/").split("/")[-1]

        allowed, authorizer_context, error_response = _authorize(
            lambda_name, route_meta.get(route_key, {}), request.method, endpoint, headers
        )
        if not allowed:
            return error_response

        event = {
            "path": full_path,
            "httpMethod": request.method,
            "headers": headers,
            "body": request.get_data(as_text=True),
            "queryStringParameters": request.args.to_dict() or {},
            "pathParameters": {},
        }
        if authorizer_context:
            event["requestContext"] = {"authorizer": authorizer_context}

        try:
            response = _invoke_lambda(lambda_name, event)
        except Exception:
            return _deny("Internal server error", 500)
        return _to_flask_response(response)
    finally:
        _clear_request_origin()


bootstrap()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "3000"))
    print(f"JakshWealth API local server on http://0.0.0.0:{port} (ENVIRONMENT={os.environ['ENVIRONMENT']})")
    for route, name in sorted(routes.items()):
        print(f"  /{route} -> {name}")
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG", "false").lower() == "true")
