"""Tables in jakshwealth_trading. Created by Alembic, not create_all."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from typing import Optional


class TradingBase(DeclarativeBase):
    """Metadata for the trading database only."""


class GttAttempt(TradingBase):
    __tablename__ = "gtt_attempts"

    attempt_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    platform_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid, nullable=True)
    zerodha_user_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    tradingsymbol: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    exchange: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    trigger_type: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    trigger_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_price: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    transaction_type: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    quantity: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    price: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    order_type: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    product: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    confirm_live: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    trigger_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    kite_error_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class OrderCommand(TradingBase):
    """Filled only when this app calls place, modify, or cancel. It does not do that today."""

    __tablename__ = "order_commands"

    command_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    platform_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid, nullable=True)
    zerodha_user_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    variety: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    exchange: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tradingsymbol: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    transaction_type: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    quantity: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    product: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    order_type: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    price: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    trigger_price: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    validity: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    disclosed_quantity: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tag: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    order_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    http_failure_body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OrderEvent(TradingBase):
    __tablename__ = "order_events"

    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    platform_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid, nullable=True)
    zerodha_user_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    checksum_valid: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    placed_by: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    order_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    exchange_order_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    parent_order_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status_message_raw: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    order_timestamp: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    exchange_update_timestamp: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    exchange_timestamp: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    variety: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    modified: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    exchange: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tradingsymbol: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    instrument_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    order_type: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    transaction_type: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    validity: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    product: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    quantity: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    disclosed_quantity: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    price: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    trigger_price: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    average_price: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    filled_quantity: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    pending_quantity: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cancelled_quantity: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    market_protection: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    meta: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    tag: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    guid: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)


class TradeRow(TradingBase):
    __tablename__ = "trades"

    trade_row_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    platform_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    trade_id: Mapped[str] = mapped_column(Text, nullable=False)
    order_id: Mapped[str] = mapped_column(Text, nullable=False)
    exchange: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tradingsymbol: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    instrument_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    product: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    average_price: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    quantity: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    exchange_order_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    transaction_type: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    fill_timestamp: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    order_timestamp: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    exchange_timestamp: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)


class RejectedPostback(TradingBase):
    __tablename__ = "rejected_postbacks"

    rejected_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_body: Mapped[str] = mapped_column(Text, nullable=False)


class AlgoSignalRecord(TradingBase):
    """Algo-generated buy/sell signals persisted for history and backtesting."""

    __tablename__ = "algo_signals"

    signal_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    platform_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid, nullable=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(8), nullable=False)  # BUY or SELL
    entry_price: Mapped[float] = mapped_column(nullable=False)
    stop_loss: Mapped[Optional[float]] = mapped_column(nullable=True)
    target: Mapped[Optional[float]] = mapped_column(nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SignalScanResult(TradingBase):
    """Individual stock crossover found in a signal scan for history and analysis."""

    __tablename__ = "signal_scan_results"

    result_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    scan_job_id: Mapped[str] = mapped_column(String(32), nullable=False)
    platform_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid, nullable=True)
    scan_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ticker: Mapped[str] = mapped_column(String(32), nullable=False)
    company: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    crossover_type: Mapped[str] = mapped_column(String(16), nullable=False)  # bullish or bearish
    crossover_date: Mapped[str] = mapped_column(String(16), nullable=False)
    close: Mapped[float] = mapped_column(nullable=False)
    short_sma: Mapped[float] = mapped_column(nullable=False)
    long_sma: Mapped[float] = mapped_column(nullable=False)
    trend_sma: Mapped[Optional[float]] = mapped_column(nullable=True)
    trend_bias: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)  # above or below
    rank: Mapped[int] = mapped_column(nullable=False)
    scan_mode: Mapped[str] = mapped_column(String(16), nullable=False)  # crossover or price
    universe: Mapped[str] = mapped_column(String(16), nullable=False)  # nifty100 or all_nse


class SignalTrade(TradingBase):
    """Trade executed based on a signal scan result for P&L tracking and backtesting."""

    __tablename__ = "signal_trades"

    trade_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    platform_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid, nullable=True)
    signal_result_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    ticker: Mapped[str] = mapped_column(String(32), nullable=False)
    signal_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entry_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entry_price: Mapped[float] = mapped_column(nullable=False)
    entry_quantity: Mapped[int] = mapped_column(nullable=False)
    exit_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_price: Mapped[Optional[float]] = mapped_column(nullable=True)
    exit_quantity: Mapped[Optional[int]] = mapped_column(nullable=True)
    transaction_type: Mapped[str] = mapped_column(String(8), nullable=False)  # BUY or SELL
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # pending, open, closed, cancelled
    pnl: Mapped[Optional[float]] = mapped_column(nullable=True)  # Profit/Loss amount
    pnl_percent: Mapped[Optional[float]] = mapped_column(nullable=True)  # Profit/Loss percentage
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class StrategyPerformance(TradingBase):
    """Daily/monthly strategy performance metrics for analysis and backtesting."""

    __tablename__ = "strategy_performance"

    perf_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    platform_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid, nullable=True)
    period_date: Mapped[str] = mapped_column(String(16), nullable=False)  # YYYY-MM-DD
    period_type: Mapped[str] = mapped_column(String(16), nullable=False)  # daily or monthly
    scan_type: Mapped[str] = mapped_column(String(16), nullable=False)  # short_term or long_term
    universe: Mapped[str] = mapped_column(String(16), nullable=False)  # nifty100 or all_nse
    total_signals: Mapped[int] = mapped_column(nullable=False)  # Total crossovers found
    total_trades: Mapped[int] = mapped_column(nullable=False)  # Total trades executed
    winning_trades: Mapped[int] = mapped_column(nullable=False)
    losing_trades: Mapped[int] = mapped_column(nullable=False)
    total_pnl: Mapped[float] = mapped_column(nullable=False)  # Total P&L
    avg_pnl_per_trade: Mapped[float] = mapped_column(nullable=False)
    win_rate: Mapped[float] = mapped_column(nullable=False)  # winning_trades / total_trades
    max_gain: Mapped[float] = mapped_column(nullable=False)
    max_loss: Mapped[float] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
