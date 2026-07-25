"""Environment-driven configuration loader.

Each Lambda resolves its deployment environment from the ``ENVIRONMENT``
variable (``local``, ``dev``, ``test`` or ``prod``) and loads a single AWS
Secrets Manager secret named ``{environment}/jakshwealth/config`` into the process
environment.
"""

from __future__ import annotations

import json
import os
import time

from jw_log import ConfigError, ExternalServiceError, call_external, emit

ENVIRONMENT = "ENVIRONMENT"
LOCAL = "local"
VALID_ENVIRONMENTS = ("local", "dev", "test", "prod")

_SECRET_TEMPLATE = "{environment}/jakshwealth/config"
_LOCAL_CONFIG_FILE = "LOCAL_CONFIG_FILE"
_DEFAULT_LOCAL_CONFIG_FILE = "config.local.json"
_SKIP_AWS = "CONFIG_SKIP_AWS"
_LOADED_FLAG = "_JW_CONFIG_LOADED"

_loaded = False


def environment() -> str:
    return (os.environ.get(ENVIRONMENT) or LOCAL).strip().lower()


def secret_name(env: str | None = None) -> str:
    env = env or environment()
    source = "dev" if env == LOCAL else env
    return _SECRET_TEMPLATE.format(environment=source)


def _skip_aws() -> bool:
    return os.environ.get(_SKIP_AWS, "false").strip().lower() == "true"


def _fetch_secret(name: str) -> dict:
    import boto3
    from botocore.config import Config as BotoConfig

    region = (
        os.environ.get("AWS_REGION")
        or os.environ.get("AWS_DEFAULT_REGION")
        or "ap-south-2"
    )
    boto_config = BotoConfig(
        connect_timeout=5,
        read_timeout=10,
        retries={"max_attempts": 1},
    )

    def _get_secret_value():
        client = boto3.client("secretsmanager", region_name=region, config=boto_config)
        return client.get_secret_value(SecretId=name)

    response = call_external(
        "secretsmanager",
        "GetSecretValue",
        _get_secret_value,
        secretName=name,
        region=region,
    )
    return json.loads(response["SecretString"])


def _local_overrides() -> dict:
    path = os.environ.get(_LOCAL_CONFIG_FILE, _DEFAULT_LOCAL_CONFIG_FILE)
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


_PLACEHOLDER_PREFIXES = ("replace-with-", "your-", "changeme", "todo")


def _is_meaningful_override(value) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return False
        lower = stripped.lower()
        if any(lower.startswith(prefix) for prefix in _PLACEHOLDER_PREFIXES):
            return False
    return True


def _apply_local_overrides(base: dict, overrides: dict) -> dict:
    merged = dict(base)
    for key, value in overrides.items():
        if str(key).startswith("_"):
            continue
        if _is_meaningful_override(value):
            merged[key] = value
    return merged


def required_global_groups() -> list[str]:
    explicit = os.environ.get("JW_REQUIRED_GROUPS", "").strip()
    if explicit:
        return [group.strip() for group in explicit.split(",") if group.strip()]

    groups = []
    for key in ("USER_GG", "ADMIN_GG"):
        value = os.environ.get(key, "").strip()
        if value:
            groups.append(value)
    return groups


def _normalize_config(values: dict) -> dict:
    normalized = dict(values)
    if not normalized.get("JW_REQUIRED_GROUPS"):
        groups = [
            str(normalized.get(key) or "").strip()
            for key in ("USER_GG", "ADMIN_GG")
            if str(normalized.get(key) or "").strip()
        ]
        if groups:
            normalized["JW_REQUIRED_GROUPS"] = ",".join(groups)
    if not normalized.get("DB_USER") and normalized.get("DB_USERNAME"):
        normalized["DB_USER"] = normalized["DB_USERNAME"]
    if not normalized.get("OKTA_ISSUER") and normalized.get("OKTA_URL"):
        url = str(normalized["OKTA_URL"]).rstrip("/")
        if url.endswith("/v1"):
            normalized["OKTA_ISSUER"] = url[:-3]
    if not normalized.get("OKTA_CLIENT_ID") and normalized.get("OKTA_CLIENT"):
        normalized["OKTA_CLIENT_ID"] = normalized["OKTA_CLIENT"]
    return normalized


def load_config(force: bool = False) -> None:
    global _loaded
    started = time.monotonic()
    if (_loaded or os.environ.get(_LOADED_FLAG) == "1") and not force:
        return

    env = environment()
    if env not in VALID_ENVIRONMENTS:
        raise ValueError(
            f"{ENVIRONMENT}={env!r} is invalid; expected one of {VALID_ENVIRONMENTS}"
        )

    values: dict = {}
    if not _skip_aws():
        name = secret_name(env)
        try:
            values.update(_fetch_secret(name))
        except ExternalServiceError as exc:
            if env != LOCAL:
                raise ConfigError(
                    f"Unable to load secret {name!r}: {exc}",
                    op="load_secret",
                    code=exc.code,
                    hint=exc.hint,
                    reason=exc.reason,
                ) from exc
            emit(
                "config.warn",
                lvl="ERROR",
                secretName=name,
                err=str(exc),
                hint=exc.hint,
                awsCode=exc.code,
                reason=exc.reason,
            )

    if env == LOCAL:
        values = _apply_local_overrides(values, _local_overrides())

    values = _normalize_config(values)
    for key, value in values.items():
        if str(key).startswith("_"):
            continue
        os.environ.setdefault(key, "" if value is None else str(value))
    os.environ.setdefault(ENVIRONMENT, env)
    os.environ[_LOADED_FLAG] = "1"
    _loaded = True

    emit(
        "config.loaded",
        environment=env,
        skipAws=_skip_aws(),
        keys=len(values),
        groups=required_global_groups(),
        ms=int((time.monotonic() - started) * 1000),
    )
