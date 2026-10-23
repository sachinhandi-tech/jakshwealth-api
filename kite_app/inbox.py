"""Algo signals persisted to database for history and backtesting."""

from __future__ import annotations

import uuid
from collections import deque
from datetime import datetime

_inbox: deque[dict] = deque(maxlen=50)


def remember(payload: dict) -> None:
    """Store algo signal in memory and database."""
    _inbox.appendleft(payload)
    _save_to_database(payload)


def recent_signals() -> list[dict]:
    """Return recent signals from memory."""
    return list(_inbox)


def _save_to_database(payload: dict) -> None:
    """Persist algo signal to database for history and backtesting."""
    try:
        from kite_app.persistence import trading_session
        from kite_app.trading_models import AlgoSignalRecord

        db = trading_session()
        try:
            AlgoSignalRecord.__table__.create(db.get_bind(), checkfirst=True)
            signal = AlgoSignalRecord(
                signal_id=uuid.uuid4(),
                platform_user_id=None,  # Would be set from context
                symbol=payload.get("symbol", ""),
                transaction_type=payload.get("transaction_type", ""),
                entry_price=float(payload.get("entry_price", 0)),
                stop_loss=float(payload.get("stop_loss")) if payload.get("stop_loss") else None,
                target=float(payload.get("target")) if payload.get("target") else None,
                source=payload.get("source", "algo"),
                received_at=datetime.now(),
            )
            db.add(signal)
            db.commit()
        finally:
            db.close()
    except Exception as exc:
        import logging
        logging.getLogger("kite_app.inbox").info("algo signal was not stored %s", type(exc).__name__)
