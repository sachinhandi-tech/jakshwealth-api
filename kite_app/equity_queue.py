"""SQS batches for the equity read. The access token never goes in a message."""

from __future__ import annotations

import json
import logging
import os
import time

logger = logging.getLogger("kite_app.equity_queue")

SEND_BATCH = 10
SCREEN_BATCH = 25
LONG_POLL_SECONDS = 20
VISIBILITY_SECONDS = 900
QUEUE_NAME = "kite-algo-setup-equity"

_URL = ""
_CHECKED = 0.0


def queue_url(client=None) -> str:
    """Return the queue URL, or an empty string when the queue is not deployed yet."""
    global _URL, _CHECKED
    configured = os.environ.get("EQUITY_QUEUE_URL", "").strip()
    if configured:
        return configured
    if _URL:
        return _URL
    if _CHECKED and time.monotonic() - _CHECKED < 60:
        return ""
    _CHECKED = time.monotonic()
    try:
        found = (client or _client()).get_queue_url(
            QueueName=os.environ.get("EQUITY_QUEUE_NAME", QUEUE_NAME).strip() or QUEUE_NAME,
        )
        _URL = str(found.get("QueueUrl") or "")
    except Exception:
        logger.info("equity queue is not available")
        return ""
    return _URL


def enqueue_equity_pass(platform_user_id: str, delay_seconds: int = 0, wave: int = 0) -> bool:
    body = {"kind": "equity_pass", "platform_user_id": platform_user_id, "wave": int(wave)}
    return send_bodies([body], delay_seconds=delay_seconds) == 1


def enqueue_screen_batches(platform_user_id: str, symbols: list[str]) -> int:
    bodies = []
    for offset in range(0, len(symbols), SCREEN_BATCH):
        chunk = [symbol for symbol in symbols[offset:offset + SCREEN_BATCH] if symbol]
        if chunk:
            bodies.append({"kind": "screen", "platform_user_id": platform_user_id, "symbols": chunk})
    if not bodies:
        return 0
    send_bodies(bodies)
    return sum(len(body["symbols"]) for body in bodies)


def enqueue_reviews(platform_user_id: str, symbols: list[str]) -> int:
    bodies = [
        {"kind": "review", "platform_user_id": platform_user_id, "symbol": symbol}
        for symbol in symbols
        if symbol
    ]
    if not bodies:
        return 0
    send_bodies(bodies)
    return len(bodies)


def send_bodies(bodies: list[dict], delay_seconds: int = 0, client=None) -> int:
    """SendMessageBatch allows 10 entries. A failed entry is raised so the caller can retry."""
    url = queue_url(client)
    if not url or not bodies:
        return 0
    sender = client or _client()
    delay = max(0, min(int(delay_seconds), 900))
    sent = 0
    for offset in range(0, len(bodies), SEND_BATCH):
        chunk = bodies[offset:offset + SEND_BATCH]
        entries = []
        for index, body in enumerate(chunk):
            entries.append({
                "Id": f"m{offset + index}",
                "MessageBody": json.dumps(body, sort_keys=True),
                "DelaySeconds": delay,
            })
        result = sender.send_message_batch(QueueUrl=url, Entries=entries)
        failed = result.get("Failed") or []
        if failed:
            raise RuntimeError("equity batch was not accepted")
        sent += len(result.get("Successful") or [])
    return sent


def receive_batch(client=None) -> list[dict]:
    url = queue_url(client)
    if not url:
        return []
    response = (client or _client()).receive_message(
        QueueUrl=url,
        MaxNumberOfMessages=SEND_BATCH,
        WaitTimeSeconds=LONG_POLL_SECONDS,
        VisibilityTimeout=VISIBILITY_SECONDS,
    )
    found = []
    for item in response.get("Messages") or []:
        receipt = str(item.get("ReceiptHandle") or "")
        if not receipt:
            continue
        try:
            body = json.loads(item.get("Body") or "")
        except json.JSONDecodeError:
            body = {"kind": "invalid"}
        if isinstance(body, dict):
            found.append({"receipt": receipt, "body": body})
    return found


def delete_batch(receipts: list[str], client=None) -> None:
    url = queue_url(client)
    if not url:
        return
    sender = client or _client()
    for offset in range(0, len(receipts), SEND_BATCH):
        chunk = [receipt for receipt in receipts[offset:offset + SEND_BATCH] if receipt]
        if not chunk:
            continue
        sender.delete_message_batch(
            QueueUrl=url,
            Entries=[{"Id": f"d{index}", "ReceiptHandle": receipt} for index, receipt in enumerate(chunk)],
        )


def extend_visibility(receipt: str, client=None) -> None:
    url = queue_url(client)
    if not url or not receipt:
        return
    (client or _client()).change_message_visibility(
        QueueUrl=url,
        ReceiptHandle=receipt,
        VisibilityTimeout=VISIBILITY_SECONDS,
    )


def _client():
    import boto3

    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "ap-south-2"
    return boto3.client("sqs", region_name=region)
