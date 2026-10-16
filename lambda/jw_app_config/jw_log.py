"""Unified structured logging for JakshWealth Lambdas.

Each line is one flat JSON object for CloudWatch Logs Insights, e.g.::

    fields @timestamp, evt, svc, rid, status, ms, dep, reason, hint
    | filter evt = "external.fail"

Handlers use :class:`Request`. Dependencies use :func:`call_external`.
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Callable
from typing import Any, TypeVar
from urllib.parse import urlparse

T = TypeVar("T")

_SENSITIVE = frozenset({
    "authorization", "auth_code", "code", "access_token", "accesstoken",
    "id_token", "refresh_token", "refreshtoken", "client_secret",
    "okta_client_secret", "okta_secret", "password", "db_password", "db_pass",
    "accesstoken", "refreshtoken",
})
_REDACTED = "***"

_AWS_HINTS: dict[str, str] = {
    "AccessDeniedException": (
        "Grant the Lambda execution role secretsmanager:GetSecretValue on the secret ARN."
    ),
    "ResourceNotFoundException": "Secret does not exist or the secret name/region is wrong.",
    "DecryptionFailure": "KMS decrypt denied — grant kms:Decrypt on the secret's CMK.",
    "InvalidParameterException": "Invalid Secrets Manager request parameter.",
    "UnrecognizedClientException": "AWS credentials are missing or invalid.",
}


class ExternalServiceError(RuntimeError):
    def __init__(
        self,
        *,
        dep: str,
        op: str,
        message: str,
        code: str | None = None,
        hint: str | None = None,
        reason: str | None = None,
    ) -> None:
        self.dep = dep
        self.op = op
        self.code = code
        self.hint = hint
        self.reason = reason
        text = f"{dep}/{op}: {message}"
        if hint:
            text = f"{text} — {hint}"
        super().__init__(text)


class ConfigError(ExternalServiceError):
    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(dep="config", op="load", message=message, **kwargs)


def _svc() -> str:
    return (
        os.environ.get("AWS_LAMBDA_FUNCTION_NAME")
        or os.environ.get("SERVICE_NAME")
        or "jw"
    )


def _env() -> str:
    return (os.environ.get("ENVIRONMENT") or "local").strip().lower()


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: (_REDACTED if str(key).lower() in _SENSITIVE else _redact(item))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    return value


def emit(evt: str, *, lvl: str = "INFO", **fields: Any) -> None:
    payload = {"evt": evt, "lvl": lvl, "svc": _svc(), "env": _env(), **_redact(fields)}
    line = json.dumps(payload, default=str, separators=(",", ":"))
    stream = sys.stderr if lvl == "ERROR" else sys.stdout
    print(line, file=stream, flush=True)


def classify_error(dep: str, exc: Exception) -> dict[str, Any]:
    from botocore.exceptions import (
        BotoCoreError,
        ClientError,
        ConnectTimeoutError,
        EndpointConnectionError,
        ReadTimeoutError,
    )

    out: dict[str, Any] = {"errType": type(exc).__name__, "err": str(exc)}

    if isinstance(exc, ClientError):
        error = exc.response.get("Error", {})
        code = error.get("Code", "ClientError")
        out["awsCode"] = code
        out["err"] = error.get("Message", str(exc))
        if hint := _AWS_HINTS.get(code):
            out["hint"] = hint
        if code in ("AccessDeniedException", "AccessDenied"):
            out["reason"] = "missing_iam_permission"
        elif code == "ResourceNotFoundException":
            out["reason"] = "resource_not_found"
        else:
            out["reason"] = "aws_api_error"
        return out

    if isinstance(exc, (ConnectTimeoutError, ReadTimeoutError)):
        out["reason"] = "connection_timeout"
        out["hint"] = (
            f"Timed out reaching {dep}. Check VPC endpoints, NAT gateway, "
            "security groups, and DNS."
        )
        return out

    if isinstance(exc, EndpointConnectionError):
        out["reason"] = "connection_failed"
        out["hint"] = (
            f"Cannot connect to {dep}. Check network path, VPC endpoints, and egress rules."
        )
        return out

    if isinstance(exc, BotoCoreError):
        out["reason"] = "aws_sdk_error"
        return out

    import requests

    if isinstance(exc, requests.Timeout):
        out["reason"] = "http_timeout"
        out["hint"] = f"HTTP request to {dep} timed out."
        return out

    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        out["reason"] = "http_error"
        out["httpStatus"] = exc.response.status_code
        return out

    out["reason"] = "unexpected_error"
    return out


def call_external(dep: str, op: str, fn: Callable[[], T], **meta: Any) -> T:
    started = time.monotonic()
    emit("external.start", dep=dep, op=op, **meta)
    try:
        result = fn()
    except ExternalServiceError:
        raise
    except Exception as exc:
        ms = int((time.monotonic() - started) * 1000)
        detail = classify_error(dep, exc)
        emit("external.fail", lvl="ERROR", dep=dep, op=op, ms=ms, **detail, **meta)
        raise ExternalServiceError(
            dep=dep,
            op=op,
            message=detail.get("err") or str(exc),
            code=detail.get("awsCode"),
            hint=detail.get("hint"),
            reason=detail.get("reason"),
        ) from exc

    ms = int((time.monotonic() - started) * 1000)
    emit("external.ok", dep=dep, op=op, ms=ms, **meta)
    return result


def _request_id(event: dict, context: Any) -> str:
    req_ctx = event.get("requestContext") or {}
    for candidate in (
        req_ctx.get("requestId"),
        getattr(context, "aws_request_id", None) if context else None,
        event.get("requestId"),
    ):
        if candidate:
            return str(candidate)
    return "unknown"


def _headers(event: dict) -> dict[str, str]:
    raw = event.get("headers") or {}
    return {
        key.lower().replace("_", "-"): str(value).strip()
        for key, value in raw.items()
        if isinstance(key, str) and value
    }


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in ("1", "true", "yes")


def _operation(event: dict) -> str | None:
    method = event.get("httpMethod")
    if method == "OPTIONS":
        return "options"
    headers = _headers(event)
    query = event.get("queryStringParameters") or {}
    if _truthy(query.get("bypass") or headers.get("bypass")):
        return "bypass_login"
    if headers.get("auth_code") or query.get("code") or query.get("auth_code"):
        return "authorization_code"
    if headers.get("refresh_token"):
        return "refresh_token"
    if headers.get("authorization"):
        return "validate_token"
    path = (event.get("path") or "").strip("/")
    if "secure-data/" in path:
        return path.split("secure-data/", 1)[-1] or "secure-data"
    if path.endswith("secure-data"):
        return "secure-data"
    if path.endswith("app-config"):
        return "app_config"
    return method.lower() if method else None


def _response_fields(response: dict) -> dict[str, Any]:
    fields: dict[str, Any] = {"status": int(response.get("statusCode", 0))}
    headers = response.get("headers") or {}
    location = headers.get("Location") or headers.get("location") or ""
    if fields["status"] in (301, 302, 303, 307, 308) or location:
        fields["redirect"] = True
        parsed = urlparse(location)
        if parsed.netloc:
            fields["redirectTo"] = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        else:
            fields["redirectTo"] = parsed.path or location.split("?", 1)[0].split("#", 1)[0]

    body = response.get("body")
    if body is not None:
        text = body if isinstance(body, str) else str(body)
        fields["bodyLen"] = len(text)
        if fields["status"] >= 400:
            try:
                parsed = json.loads(text) if isinstance(body, str) else body
                if isinstance(parsed, dict) and parsed.get("message"):
                    fields["errMsg"] = str(parsed["message"])
            except (json.JSONDecodeError, TypeError):
                pass
    return fields


class Request:
    """Per-invocation log context: one begin line, one end/fail line."""

    def __init__(self, service: str, event: dict | None, context: Any) -> None:
        self._service = service
        self._event = event or {}
        self._started = time.perf_counter()
        self.rid = _request_id(self._event, context)
        self._notes: dict[str, Any] = {}
        self._authorizer = (
            "authorizationToken" in self._event and "httpMethod" not in self._event
        )
        self._op = None if self._authorizer else _operation(self._event)

        if self._authorizer:
            emit(
                "authorizer.begin",
                svc=service,
                rid=self.rid,
                methodArn=self._event.get("methodArn"),
                hasToken=bool(self._event.get("authorizationToken")),
            )
        else:
            headers = _headers(self._event)
            query = self._event.get("queryStringParameters") or {}
            req_ctx = self._event.get("requestContext") or {}
            emit(
                "request.begin",
                svc=service,
                rid=self.rid,
                method=self._event.get("httpMethod"),
                path=self._event.get("path"),
                stage=req_ctx.get("stage"),
                op=self._op,
                origin=headers.get("origin"),
                hasAuth=bool(headers.get("authorization")),
                hasAuthCode=bool(
                    headers.get("auth_code") or query.get("code") or query.get("auth_code")
                ),
                hasRefresh=bool(headers.get("refresh_token")),
                wantsRedirect=_truthy(query.get("redirect") or headers.get("redirect")),
            )

    @property
    def trace_id(self) -> str:
        return self.rid

    def note(self, **fields: Any) -> None:
        self._notes.update(fields)

    def complete(self, response: dict) -> dict:
        ms = int((time.perf_counter() - self._started) * 1000)
        emit(
            "request.end",
            svc=self._service,
            rid=self.rid,
            ms=ms,
            op=self._op,
            **self._notes,
            **_response_fields(response),
        )
        return response

    def fail(self, exc: Exception, response: dict) -> dict:
        ms = int((time.perf_counter() - self._started) * 1000)
        fields: dict[str, Any] = {
            "svc": self._service,
            "rid": self.rid,
            "ms": ms,
            "op": self._op,
            "err": str(exc),
            **self._notes,
            **_response_fields(response),
        }
        if isinstance(exc, ExternalServiceError):
            fields.update(dep=exc.dep, extOp=exc.op, reason=exc.reason)
            if exc.code:
                fields["awsCode"] = exc.code
            if exc.hint:
                fields["hint"] = exc.hint
        emit("request.fail", lvl="ERROR", **fields)
        return response

    def complete_authorizer(self, policy: dict) -> dict:
        ms = int((time.perf_counter() - self._started) * 1000)
        statement = (policy.get("policyDocument", {}).get("Statement") or [{}])[0]
        emit(
            "authorizer.end",
            svc=self._service,
            rid=self.rid,
            ms=ms,
            effect=statement.get("Effect", "unknown"),
            policyPrincipal=policy.get("principalId"),
            **self._notes,
        )
        return policy

    def fail_authorizer(self, exc: Exception) -> None:
        ms = int((time.perf_counter() - self._started) * 1000)
        fields: dict[str, Any] = {
            "svc": self._service,
            "rid": self.rid,
            "ms": ms,
            "err": str(exc),
            **self._notes,
        }
        if isinstance(exc, ExternalServiceError):
            fields.update(dep=exc.dep, extOp=exc.op, reason=exc.reason, hint=exc.hint)
        emit("authorizer.fail", lvl="ERROR", **fields)


RequestTrace = Request
