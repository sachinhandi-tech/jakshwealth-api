"""High-volume breakout and retest, then rank and reject traps.

Layer 1 keeps a name only when the 20 EMA has crossed above the 50 SMA
inside the last 20 sessions and a 3x volume breakout has been retested.
Layer 2 ranks those names by ATR, RSI, and 20-session relative strength.
Layer 3 drops blow-off and failed-retest bars. Sector membership is not
on this feed. Filings, news, and lawsuits come only from the research tools.
"""

from __future__ import annotations

from typing import Optional

from decimal import Decimal

from kite_app.breakout_scan import PRICE_LOOKBACK, _scan_stock
from kite_app.gtt_orders import EQUITY_BUDGET_INR, share_quantity
from kite_app.signals import exponential_moving_average, simple_moving_average

EMA_WINDOW = 20
SMA_WINDOW = 50
CROSS_LOOKBACK = 20
ATR_WINDOW = 14
RSI_WINDOW = 14
REWARD_R = 2
STOP_BUFFER = 0.005
RSI_TRAP = 80
BLOWOFF_ATR = 2.5
TOP_CANDIDATES = 5
MAX_HOLD_DAYS = 20


def select_setups(stocks: list[dict], limit: int = TOP_CANDIDATES) -> dict:
    """Return the top ranked setups and the rows that failed a real check."""
    accepted = []
    trapped = []
    rejected = []
    for stock in stocks:
        decision = evaluate_stock(stock)
        if decision is None:
            rejected.append({
                "symbol": stock.get("symbol") or "",
                "reason": "No 20 EMA cross of the 50 SMA with a 3x volume breakout retest.",
            })
            continue
        if decision["traps"]:
            trapped.append(decision)
            rejected.append({
                "symbol": decision["symbol"],
                "reason": " ".join(decision["traps"]),
            })
            continue
        accepted.append(decision)
    accepted.sort(key=lambda item: (-item["score"], item["symbol"]))
    chosen = accepted[:limit]
    for rank, item in enumerate(chosen, start=1):
        item["rank"] = rank
    sell_book = [item for item in trapped if item["desk"]["book_call"] == "sell"][:limit]
    from kite_app.algo_review import review_setups

    review_setups(chosen)
    review_setups(sell_book)
    return {
        "scanned": len(stocks),
        "accepted": len(accepted),
        "setups": chosen,
        "sell_calls": [item for item in sell_book if item.get("ai_decision") == "sell"],
        "rejected": rejected,
    }


def evaluate_stock(stock: dict) -> Optional[dict]:
    candles = stock.get("candles") or []
    closes = [float(item["close"]) for item in candles]
    cross_index = _trend_cross_index(closes)
    breakout = _scan_stock({
        "symbol": stock.get("symbol") or "",
        "company_name": stock.get("company_name") or stock.get("symbol") or "",
        "instrument_token": stock.get("instrument_token"),
        "candles": candles,
    })
    if cross_index is None or breakout is None:
        return None
    entry = float(breakout["midpoint"])
    stop = float(breakout["breakout_low"]) * (1 - STOP_BUFFER)
    last_close = float(candles[-1]["close"])
    if not stop < entry < last_close:
        return None
    risk = entry - stop
    target = entry + REWARD_R * risk
    if target <= last_close:
        return None
    atr = _atr(candles)
    rsi = _rsi(closes)
    if atr is None or rsi is None or atr <= 0:
        return None
    policy = _market_policy(stock.get("exchange") or "NSE", stock.get("instrument_type") or "EQ")
    size = _order_size(policy, entry)
    traps = _traps(candles, breakout, rsi, atr)
    strength = _relative_strength(closes)
    score = _score(breakout["vol_multiple"], rsi, atr / last_close, strength)
    reason = _reason(breakout, cross_index, rsi, atr, strength, policy, traps)
    desk = _desk(candles, breakout, entry, stop, target, atr, rsi, traps, float(breakout["vol_multiple"]))
    return {
        "symbol": breakout["symbol"],
        "company_name": breakout["company_name"],
        "exchange": policy["exchange"],
        "segment": policy["segment"],
        "gtt_tradable": policy["gtt"],
        "product": policy["product"],
        "quantity_basis": size["quantity_basis"],
        "budget_inr": size["budget_inr"],
        "quantity": size["quantity"],
        "entry": round(entry, 4),
        "stop": round(stop, 4),
        "target": round(target, 4),
        "reward_r": REWARD_R,
        "last_close": round(last_close, 4),
        "rsi": round(rsi, 2),
        "atr": round(atr, 4),
        "relative_strength": round(strength, 4),
        "volume_multiple": round(float(breakout["vol_multiple"]), 2),
        "score": round(score, 2),
        "traps": traps,
        "desk": desk,
        "reason": reason,
    }


def walk_exit(future: list[dict], entry: float, stop: float, target: float, max_hold: int = MAX_HOLD_DAYS) -> dict:
    """Exit at the stop or the target. A bar that hits both is a stop."""
    risk = entry - stop
    if risk <= 0:
        raise ValueError("Stop must be below the entry.")
    window = future[:max_hold]
    for offset, bar in enumerate(window, start=1):
        if float(bar["low"]) <= stop:
            return _exit(offset, stop, entry, risk, "stop")
        if float(bar["high"]) >= target:
            return _exit(offset, target, entry, risk, "target")
    if not window:
        return _exit(0, entry, entry, risk, "no_bars")
    return _exit(len(window), float(window[-1]["close"]), entry, risk, "time")


def backtest_symbol(stock: dict) -> dict:
    """Replay one symbol. A decision on day t is filled at the next open."""
    candles = stock.get("candles") or []
    trades = []
    index = SMA_WINDOW
    while index < len(candles) - 1:
        sample = dict(stock)
        sample["candles"] = candles[: index + 1]
        decision = evaluate_stock(sample)
        if decision is None or decision["traps"] or not decision["gtt_tradable"]:
            index += 1
            continue
        filled = float(candles[index + 1]["open"])
        risk = decision["entry"] - decision["stop"]
        if risk <= 0 or filled <= decision["stop"]:
            index += 1
            continue
        stop = filled - risk
        target = filled + REWARD_R * risk
        outcome = walk_exit(candles[index + 1:], filled, stop, target)
        trades.append({
            "signal_date": candles[index]["date"],
            "exit_reason": outcome["exit_reason"],
            "r_multiple": outcome["r_multiple"],
        })
        index += max(outcome["bars_held"], 1)
    return _summary(stock.get("symbol") or "", trades)


def _trend_cross_index(closes: list[float]) -> Optional[int]:
    fast = exponential_moving_average(closes, EMA_WINDOW)
    slow = simple_moving_average(closes, SMA_WINDOW)
    if len(closes) < SMA_WINDOW + 1 or fast[-1] is None or slow[-1] is None:
        return None
    if fast[-1] <= slow[-1]:
        return None
    start = max(SMA_WINDOW, len(closes) - CROSS_LOOKBACK)
    found = None
    for index in range(start, len(closes)):
        if None in (fast[index - 1], slow[index - 1], fast[index], slow[index]):
            continue
        if fast[index - 1] <= slow[index - 1] and fast[index] > slow[index]:
            found = index
    return found


def _atr(candles: list[dict]) -> Optional[float]:
    if len(candles) < ATR_WINDOW + 1:
        return None
    ranges = []
    for index in range(1, len(candles)):
        high = float(candles[index]["high"])
        low = float(candles[index]["low"])
        previous = float(candles[index - 1]["close"])
        ranges.append(max(high - low, abs(high - previous), abs(low - previous)))
    value = sum(ranges[:ATR_WINDOW]) / ATR_WINDOW
    for item in ranges[ATR_WINDOW:]:
        value = (value * (ATR_WINDOW - 1) + item) / ATR_WINDOW
    return value


def _rsi(closes: list[float]) -> Optional[float]:
    if len(closes) < RSI_WINDOW + 1:
        return None
    gains = []
    losses = []
    for index in range(1, len(closes)):
        change = closes[index] - closes[index - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    average_gain = sum(gains[:RSI_WINDOW]) / RSI_WINDOW
    average_loss = sum(losses[:RSI_WINDOW]) / RSI_WINDOW
    for index in range(RSI_WINDOW, len(gains)):
        average_gain = (average_gain * (RSI_WINDOW - 1) + gains[index]) / RSI_WINDOW
        average_loss = (average_loss * (RSI_WINDOW - 1) + losses[index]) / RSI_WINDOW
    if average_loss == 0:
        return 100.0
    relative = average_gain / average_loss
    return 100 - (100 / (1 + relative))


def _relative_strength(closes: list[float]) -> float:
    if len(closes) <= EMA_WINDOW or closes[-EMA_WINDOW - 1] == 0:
        return 0.0
    return (closes[-1] / closes[-EMA_WINDOW - 1]) - 1


def _score(volume_multiple: float, rsi: float, atr_percent: float, strength: float) -> float:
    volume_points = min(max(volume_multiple, 0) / 6, 1) * 35
    if 50 <= rsi <= 70:
        rsi_points = 30
    elif 40 <= rsi < 50 or 70 < rsi < RSI_TRAP:
        rsi_points = 15
    else:
        rsi_points = 0
    if 0.01 <= atr_percent <= 0.04:
        atr_points = 20
    elif atr_percent < 0.06:
        atr_points = 10
    else:
        atr_points = 0
    strength_points = min(max(strength, 0), 0.2) / 0.2 * 15
    return volume_points + rsi_points + atr_points + strength_points


def _traps(candles: list[dict], breakout: dict, rsi: float, atr: float) -> list[str]:
    found = []
    latest = candles[-1]
    true_range = max(
        float(latest["high"]) - float(latest["low"]),
        abs(float(latest["high"]) - float(candles[-2]["close"])),
        abs(float(latest["low"]) - float(candles[-2]["close"])),
    )
    if rsi >= RSI_TRAP:
        found.append(f"RSI is {rsi:.1f}, which is a blow-off reading.")
    if true_range > BLOWOFF_ATR * atr:
        found.append("The last bar is wider than 2.5 ATR.")
    if float(latest["close"]) < float(breakout["breakout_low"]):
        found.append("The close is back under the breakout low.")
    return found


def _market_policy(exchange: str, instrument_type: str) -> dict:
    market = exchange.upper()
    kind = instrument_type.upper()
    if market == "NSE" and kind in {"", "EQ"}:
        return {"exchange": "NSE", "segment": "equity", "gtt": True, "product": "CNC"}
    if market == "NFO" and kind in {"FUT", "CE", "PE"}:
        return {"exchange": "NFO", "segment": "stock_derivative", "gtt": True, "product": "NRML"}
    if market == "MCX" and kind == "FUT":
        return {"exchange": "MCX", "segment": "commodity_future", "gtt": True, "product": "NRML"}
    return {"exchange": market or "NSE", "segment": "unsupported", "gtt": False, "product": ""}


def _desk(candles: list[dict], breakout: dict, entry: float, stop: float, target: float, atr: float, rsi: float, traps: list[str], volume_multiple: float) -> dict:
    """Figures a risk desk can check. Missing history stays null."""
    closes = [float(item["close"]) for item in candles]
    highs = [float(item["high"]) for item in candles]
    volumes = [float(item["volume"]) for item in candles]
    ema = exponential_moving_average(closes, EMA_WINDOW)[-1]
    sma = simple_moving_average(closes, SMA_WINDOW)[-1]
    sma_long = simple_moving_average(closes, 200)[-1]
    last = candles[-1]
    previous_close = float(candles[-2]["close"])
    high = float(last["high"])
    low = float(last["low"])
    close = float(last["close"])
    span = high - low
    close_location = 0.5 if span <= 0 else (close - low) / span
    risk = entry - stop
    up_volume = 0.0
    down_volume = 0.0
    start = max(1, len(closes) - PRICE_LOOKBACK)
    for index in range(start, len(closes)):
        if closes[index] >= closes[index - 1]:
            up_volume += volumes[index]
        else:
            down_volume += volumes[index]
    average_volume = sum(volumes[-PRICE_LOOKBACK:]) / min(PRICE_LOOKBACK, len(volumes))
    prior_rsi = _rsi(closes[:-5]) if len(closes) > RSI_WINDOW + 6 else None
    true_range = max(high - low, abs(high - previous_close), abs(low - previous_close))
    return_5 = 0.0 if len(closes) < 6 or closes[-6] == 0 else (closes[-1] / closes[-6]) - 1
    packet = {
        "ema20": _plain(ema),
        "sma50": _plain(sma),
        "sma200": _plain(sma_long),
        "trend_stack": ema is not None and sma is not None and close > ema > sma,
        "close_location": round(close_location, 4),
        "risk_pct": round(risk / entry, 4) if entry else None,
        "stop_in_atr": round(risk / atr, 4) if atr else None,
        "room_r": round((target - close) / risk, 4) if risk else None,
        "atr_pct": round(atr / close, 4) if close else None,
        "rsi_five_sessions_ago": None if prior_rsi is None else round(prior_rsi, 2),
        "up_volume_20": round(up_volume, 2),
        "down_volume_20": round(down_volume, 2),
        "up_down_volume_ratio": None if down_volume <= 0 else round(up_volume / down_volume, 4),
        "average_volume_20": round(average_volume, 2),
        "distance_from_20d_high_pct": round((max(highs[-PRICE_LOOKBACK:]) - close) / close, 4) if close else None,
        "breakout_low": round(float(breakout["breakout_low"]), 4),
        "breakout_high": round(float(breakout["breakout_high"]), 4),
        "days_since_breakout": breakout["days_since"],
        "above_breakout_low": close >= float(breakout["breakout_low"]),
        "higher_low": low > float(breakout["breakout_low"]),
        "last_true_range_atr": round(true_range / atr, 4) if atr else None,
        "gap_pct": round((float(last["open"]) - previous_close) / previous_close, 4) if previous_close else None,
        "return_5": round(return_5, 4),
        "return_20": round(_relative_strength(closes), 4),
        "sessions": len(candles),
        "tape": [_tape_bar(bar) for bar in candles[-12:]],
    }
    packet["book_call"] = _book_call(packet, traps, volume_multiple, rsi, entry, stop, target, close)
    return packet


def _book_call(packet: dict, traps: list[str], volume_multiple: float, rsi: float, entry: float, stop: float, target: float, last_close: float) -> str:
    """Arithmetic only. The model confirms or vetoes this. It cannot invent the other side."""
    broken = bool(traps) or rsi >= RSI_TRAP or (packet["last_true_range_atr"] or 0) > BLOWOFF_ATR or not packet["above_breakout_low"]
    if broken:
        return "sell"
    if stop < entry < last_close < target and volume_multiple >= 3 and rsi < RSI_TRAP:
        return "buy"
    return "stand_aside"


def _tape_bar(bar: dict) -> dict:
    return {
        "date": bar["date"],
        "open": round(float(bar["open"]), 4),
        "high": round(float(bar["high"]), 4),
        "low": round(float(bar["low"]), 4),
        "close": round(float(bar["close"]), 4),
        "volume": round(float(bar["volume"]), 2),
    }


def _plain(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return round(float(value), 4)


def _order_size(policy: dict, entry: float) -> dict:
    if policy["segment"] == "equity":
        return {
            "quantity_basis": "equity_notional",
            "budget_inr": int(EQUITY_BUDGET_INR),
            "quantity": share_quantity(Decimal(str(entry))),
        }
    if policy["segment"] in {"stock_derivative", "commodity_future"}:
        return {"quantity_basis": "one_lot", "budget_inr": None, "quantity": None}
    return {"quantity_basis": "unsupported", "budget_inr": None, "quantity": None}


def _reason(breakout: dict, cross_index: int, rsi: float, atr: float, strength: float, policy: dict, traps: list[str]) -> str:
    text = (
        f"{breakout['symbol']} retested the {breakout['breakout_date']} breakout. "
        f"Volume was {float(breakout['vol_multiple']):.2f} times the prior 20-day average and the 20 EMA crossed above the 50 SMA. "
        f"RSI {rsi:.1f}, ATR {atr:.2f}, 20-session return {strength:.1%}. "
        "Sector momentum is not scored because this feed has no sector map. "
        "Filings, news, and lawsuits are read through the research tools before the call."
    )
    if policy["segment"] == "equity":
        text += " The buy is one lakh rupees of shares, sized from the entry. A confirmed holding can place one NSE CNC two-leg sell GTT at the stop and the 2R target."
    elif policy["segment"] == "stock_derivative":
        text += " The order is one lot on NFO, product NRML, and it is not an equity delivery order."
    elif policy["segment"] == "commodity_future":
        text += " The order is one lot on MCX, product NRML, and it is not an equity delivery order."
    else:
        text += " This contract is not sent to Kite."
    if traps:
        text += " " + " ".join(traps)
    return text


def _exit(bars_held: int, price: float, entry: float, risk: float, reason: str) -> dict:
    return {
        "bars_held": bars_held,
        "exit_price": round(price, 4),
        "r_multiple": round((price - entry) / risk, 4),
        "exit_reason": reason,
    }


def _summary(symbol: str, trades: list[dict]) -> dict:
    multiples = [item["r_multiple"] for item in trades]
    wins = [item for item in multiples if item > 0]
    equity = 0.0
    peak = 0.0
    drawdown = 0.0
    for item in multiples:
        equity += item
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    count = len(trades)
    return {
        "symbol": symbol,
        "trades": count,
        "wins": len(wins),
        "losses": count - len(wins),
        "win_rate": 0 if count == 0 else round(len(wins) / count, 4),
        "expectancy_r": 0 if count == 0 else round(sum(multiples) / count, 4),
        "max_drawdown_r": round(drawdown, 4),
        "history": trades,
    }
