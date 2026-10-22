"""Fan Zerodha full-mode ticks out to desk websocket clients. Tokens stay on the server."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Optional

TickCallback = Callable[[int, float], None]


class TickHub:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ticker = None
        self._connected = False
        self._listeners: dict[int, tuple[set[int], TickCallback]] = {}
        self._next_id = 0
        self._credentials: Optional[tuple[str, str]] = None
        self._platform_user_id = None

    def add(self, api_key: str, access_token: str, tokens: set[int], callback: TickCallback, platform_user_id=None) -> int:
        with self._lock:
            self._next_id += 1
            listener_id = self._next_id
            self._listeners[listener_id] = (set(tokens), callback)
            self._platform_user_id = platform_user_id
            pending = self._swap_ticker_locked(api_key, access_token)
            self._sync_locked()
        if pending is not None:
            pending.connect(threaded=True)
        return listener_id

    def remove(self, listener_id: int) -> None:
        with self._lock:
            self._listeners.pop(listener_id, None)
            if self._listeners:
                self._sync_locked()
                return
            ticker = self._ticker
            self._ticker = None
            self._connected = False
            self._credentials = None
        if ticker is not None:
            close = getattr(ticker, "close", None)
            if close is not None:
                close()

    def _swap_ticker_locked(self, api_key: str, access_token: str):
        credentials = (api_key, access_token)
        if self._ticker is not None and self._credentials == credentials:
            return None
        previous = self._ticker
        from kiteconnect import KiteTicker

        ticker = KiteTicker(api_key, access_token)
        ticker.on_ticks = self._on_ticks
        ticker.on_connect = self._on_connect
        ticker.on_order_update = self._on_order_update
        self._ticker = ticker
        self._credentials = credentials
        self._connected = False
        if previous is not None:
            close = getattr(previous, "close", None)
            if close is not None:
                close()
        return ticker

    def _on_connect(self, _ws, _response) -> None:
        with self._lock:
            self._connected = True
            self._sync_locked()

    def _on_order_update(self, _ws, data) -> None:
        from kite_app.trading_store import persist_socket_order

        if isinstance(data, dict):
            persist_socket_order(data, self._platform_user_id)

    def _on_ticks(self, _ws, ticks) -> None:
        parsed: list[tuple[int, float]] = []
        for tick in ticks or []:
            if not isinstance(tick, dict):
                continue
            token = tick.get("instrument_token")
            price = tick.get("last_price")
            try:
                token_id = int(token)
                last_price = float(price)
            except (TypeError, ValueError):
                continue
            parsed.append((token_id, last_price))
        if not parsed:
            return
        with self._lock:
            listeners = list(self._listeners.values())
        for token_id, last_price in parsed:
            for tokens, callback in listeners:
                if token_id in tokens:
                    callback(token_id, last_price)

    def _sync_locked(self) -> None:
        ticker = self._ticker
        if ticker is None or not self._connected:
            return
        tokens = sorted({token for subscribed, _callback in self._listeners.values() for token in subscribed})
        if not tokens:
            return
        ticker.subscribe(tokens)
        mode = getattr(ticker, "MODE_FULL", "full")
        ticker.set_mode(mode, tokens)


hub = TickHub()
