"""Combined book for the final call.

A name is sent to the model only when the backend has already passed it on
all three screens: the moving-average crossover list, the price and volume
expansion list, and the RSI momentum and ATR screen. Sector membership is
not on this feed. Filings, news, and lawsuits come only from the research tools.
"""

from __future__ import annotations

from typing import Optional

from decimal import Decimal

from kite_app.breakout_scan import PRICE_LOOKBACK, _scan_stock
from kite_app.gtt_orders import EQUITY_BUDGET_INR, share_quantity
from kite_app.signals import exponential_moving_average, latest_price_cross, simple_moving_average

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


def select_setups(stocks: list[dict], limit: int = TOP_CANDIDATES, review: bool = True) -> dict:
    """Return the top ranked setups and the rows that failed a real check."""
    accepted = []
    trapped = []
    rejected = []
    for stock in stocks:
        decision = evaluate_stock(stock)
        if decision is None:
            if not (stock.get("candles") or []) and (stock.get("on_moving_average_list") or stock.get("bearish_cross")):
                reason = "This moving-average name has no saved history, so it was not read."
            else:
                reason = "This name did not pass the moving-average, price-volume, and RSI momentum screens together."
            rejected.append({
                "symbol": stock.get("symbol") or "",
                "reason": reason,
            })
            continue
        if not all(decision["screens"].values()):
            rejected.append({
                "symbol": decision["symbol"],
                "reason": _missing_screen(decision["screens"]),
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
    accepted.sort(key=lambda item: (-item["screen_count"], -int(item["listed"]), -item["score"], item["symbol"]))
    chosen = accepted[:limit]
    for rank, item in enumerate(chosen, start=1):
        item["rank"] = rank
    sell_book = [item for item in trapped if item["desk"]["book_call"] == "sell"][:limit]
    if review:
        from kite_app.algo_review import review_setups

        review_setups(chosen)
        review_setups(sell_book)
    sell_calls = [item for item in sell_book if item.get("ai_decision") == "sell"]
    seen = {item["symbol"] for item in sell_calls}
    for item in chosen:
        if item.get("ai_decision") == "sell" and item["symbol"] not in seen:
            sell_calls.append(item)
    return {
        "scanned": len(stocks),
        "accepted": len(accepted),
        "setups": chosen,
        "sell_calls": sell_calls,
        "rejected": rejected,
    }


def combine_books(posted: list[dict], signals: list[dict], cached: list[dict]) -> list[dict]:
    """One row per symbol. Posted candles win. A signal marks the crossover list."""
    by_symbol: dict[str, dict] = {}
    for source in (cached, posted):
        for stock in source:
            symbol = str(stock.get("symbol") or "").upper()
            if not symbol or not stock.get("candles"):
                continue
            row = dict(stock)
            row["symbol"] = symbol
            previous = by_symbol.get(symbol)
            if previous and not row.get("exchange") and previous.get("exchange"):
                row["exchange"] = previous["exchange"]
            if source is posted:
                row["listed"] = True
            by_symbol[symbol] = row
    for signal in signals:
        symbol = str(signal.get("symbol") or "").upper()
        if not symbol:
            continue
        exchange = str(signal.get("exchange") or "").upper()
        row = dict(by_symbol.get(symbol) or {
            "symbol": symbol,
            "company_name": signal.get("company_name") or symbol,
            "exchange": exchange or "NSE",
            "instrument_type": "EQ",
            "candles": [],
        })
        row["symbol"] = symbol
        if exchange:
            row["exchange"] = exchange
        row["listed"] = True
        if not row.get("company_name"):
            row["company_name"] = signal.get("company_name") or symbol
        kind = str(signal.get("crossover_type") or "").lower()
        if kind == "bullish":
            row["on_moving_average_list"] = True
        elif kind == "bearish":
            row["bearish_cross"] = True
        by_symbol[symbol] = row
    return list(by_symbol.values())


def evaluate_stock(stock: dict) -> Optional[dict]:
    candles = stock.get("candles") or []
    if len(candles) < 2:
        return None
    closes = [float(item["close"]) for item in candles]
    cross_index = _trend_cross_index(closes)
    long_cross = latest_price_cross(candles, 200, 120)
    long_bullish = isinstance(long_cross, dict) and long_cross.get("crossover_type") == "bullish"
    breakout = _scan_stock({
        "symbol": stock.get("symbol") or "",
        "company_name": stock.get("company_name") or stock.get("symbol") or "",
        "instrument_token": stock.get("instrument_token"),
        "candles": candles,
    })
    atr = _atr(candles)
    rsi = _rsi(closes)
    if atr is None or rsi is None or atr <= 0:
        return None
    last_close = float(candles[-1]["close"])
    strength = _relative_strength(closes)
    on_crossover_list = bool(stock.get("on_moving_average_list"))
    screens = {
        "moving_average": cross_index is not None or long_bullish or on_crossover_list,
        "price_volume": breakout is not None,
        "rsi_momentum_atr": _rsi_momentum(rsi, atr, last_close, strength),
    }
    bearish = bool(stock.get("bearish_cross"))
    if not any(screens.values()):
        return None
    levels = _levels(last_close, breakout, closes)
    if levels is None:
        entry = stop = target = None
    else:
        entry, stop, target = levels
    policy = _market_policy(stock.get("exchange") or "NSE", stock.get("instrument_type") or "EQ")
    size = _order_size(policy, entry if entry is not None else last_close)
    traps = _traps(candles, breakout, rsi, atr)
    volume_multiple = 0.0 if breakout is None else float(breakout["vol_multiple"])
    score = _score(volume_multiple, rsi, atr / last_close, strength)
    reason = _reason(stock, breakout, screens, rsi, atr, strength, policy, traps)
    desk = _desk(candles, breakout, entry, stop, target, atr, rsi, traps, volume_multiple, screens, bearish)
    symbol = str(stock.get("symbol") or (breakout or {}).get("symbol") or "")
    company = str(stock.get("company_name") or (breakout or {}).get("company_name") or symbol)
    return {
        "symbol": symbol,
        "company_name": company,
        "exchange": policy["exchange"],
        "segment": policy["segment"],
        "gtt_tradable": bool(policy["gtt"] and levels is not None),
        "product": policy["product"],
        "quantity_basis": size["quantity_basis"],
        "budget_inr": size["budget_inr"],
        "quantity": size["quantity"],
        "entry": None if entry is None else round(entry, 4),
        "stop": None if stop is None else round(stop, 4),
        "target": None if target is None else round(target, 4),
        "reward_r": REWARD_R,
        "last_close": round(last_close, 4),
        "rsi": round(rsi, 2),
        "atr": round(atr, 4),
        "relative_strength": round(strength, 4),
        "volume_multiple": round(volume_multiple, 2),
        "score": round(score, 2),
        "screen_count": sum(1 for value in screens.values() if value),
        "listed": bool(stock.get("listed") or on_crossover_list),
        "screens": screens,
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


def _rsi_momentum(rsi: float, atr: float, last_close: float, strength: float) -> bool:
    """The same RSI and ATR bands the ranker already scores in full."""
    if last_close <= 0 or strength <= 0:
        return False
    atr_percent = atr / last_close
    return 50 <= rsi <= 70 and 0.01 <= atr_percent <= 0.04


def _levels(last_close: float, breakout: Optional[dict], closes: list[float]) -> Optional[tuple[float, float, float]]:
    """Entry, stop, and 2R target. The breakout levels win. Otherwise the 50 SMA is the limit."""
    if breakout is not None:
        entry = float(breakout["midpoint"])
        stop = float(breakout["breakout_low"]) * (1 - STOP_BUFFER)
        if stop < entry < last_close:
            target = entry + REWARD_R * (entry - stop)
            if target > last_close:
                return entry, stop, target
    slow = simple_moving_average(closes, SMA_WINDOW)[-1]
    if slow is None:
        return None
    entry = float(slow)
    stop = entry * (1 - STOP_BUFFER)
    if not stop < entry < last_close:
        return None
    target = entry + REWARD_R * (entry - stop)
    if target <= last_close:
        return None
    return entry, stop, target


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


def _traps(candles: list[dict], breakout: Optional[dict], rsi: float, atr: float) -> list[str]:
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
    if breakout is not None and float(latest["close"]) < float(breakout["breakout_low"]):
        found.append("The close is back under the breakout low.")
    return found


def _market_policy(exchange: str, instrument_type: str) -> dict:
    market = exchange.upper()
    kind = instrument_type.upper()
    if market in {"NSE", "BSE"} and kind in {"", "EQ"}:
        return {"exchange": market, "segment": "equity", "gtt": True, "product": "CNC"}
    if market == "NFO" and kind in {"FUT", "CE", "PE"}:
        return {"exchange": "NFO", "segment": "stock_derivative", "gtt": True, "product": "NRML"}
    if market == "MCX" and kind == "FUT":
        return {"exchange": "MCX", "segment": "commodity_future", "gtt": True, "product": "NRML"}
    return {"exchange": market or "NSE", "segment": "unsupported", "gtt": False, "product": ""}


def _desk(candles: list[dict], breakout: Optional[dict], entry: Optional[float], stop: Optional[float], target: Optional[float], atr: float, rsi: float, traps: list[str], volume_multiple: float, screens: dict, bearish: bool) -> dict:
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
    risk = None if entry is None or stop is None else entry - stop
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
        "risk_pct": round(risk / entry, 4) if risk and entry else None,
        "stop_in_atr": round(risk / atr, 4) if risk and atr else None,
        "room_r": round((target - close) / risk, 4) if risk and target is not None else None,
        "atr_pct": round(atr / close, 4) if close else None,
        "rsi_five_sessions_ago": None if prior_rsi is None else round(prior_rsi, 2),
        "up_volume_20": round(up_volume, 2),
        "down_volume_20": round(down_volume, 2),
        "up_down_volume_ratio": None if down_volume <= 0 else round(up_volume / down_volume, 4),
        "average_volume_20": round(average_volume, 2),
        "distance_from_20d_high_pct": round((max(highs[-PRICE_LOOKBACK:]) - close) / close, 4) if close else None,
        "breakout_low": None if breakout is None else round(float(breakout["breakout_low"]), 4),
        "breakout_high": None if breakout is None else round(float(breakout["breakout_high"]), 4),
        "days_since_breakout": None if breakout is None else breakout["days_since"],
        "above_breakout_low": True if breakout is None else close >= float(breakout["breakout_low"]),
        "higher_low": None if breakout is None else low > float(breakout["breakout_low"]),
        "screens": screens,
        "last_true_range_atr": round(true_range / atr, 4) if atr else None,
        "gap_pct": round((float(last["open"]) - previous_close) / previous_close, 4) if previous_close else None,
        "return_5": round(return_5, 4),
        "return_20": round(_relative_strength(closes), 4),
        "sessions": len(candles),
        "tape": [_tape_bar(bar) for bar in candles[-12:]],
    }
    packet["book_call"] = _book_call(packet, traps, rsi, entry, stop, target, close, screens, bearish)
    return packet


def _book_call(packet: dict, traps: list[str], rsi: float, entry: Optional[float], stop: Optional[float], target: Optional[float], last_close: float, screens: dict, bearish: bool) -> str:
    """Arithmetic only. The model confirms or vetoes this. It cannot invent the other side."""
    broken = bool(traps) or rsi >= RSI_TRAP or (packet["last_true_range_atr"] or 0) > BLOWOFF_ATR or not packet["above_breakout_low"]
    if broken:
        return "sell"
    if (
        entry is not None
        and stop is not None
        and target is not None
        and stop < entry < last_close < target
        and rsi < RSI_TRAP
        and all(screens.values())
    ):
        return "buy"
    if bearish:
        return "sell"
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


def _missing_screen(screens: dict) -> str:
    labels = (
        ("moving_average", "moving-average crossover"),
        ("price_volume", "price and volume expansion"),
        ("rsi_momentum_atr", "RSI momentum and ATR"),
    )
    missing = [label for key, label in labels if not screens.get(key)]
    if len(missing) == 1:
        return f"This name is not on the {missing[0]} screen, so it is not sent to the model."
    joined = ", ".join(missing[:-1]) + " and " + missing[-1]
    return f"This name is not on the {joined} screens, so it is not sent to the model."


def _reason(stock: dict, breakout: Optional[dict], screens: dict, rsi: float, atr: float, strength: float, policy: dict, traps: list[str]) -> str:
    symbol = str(stock.get("symbol") or (breakout or {}).get("symbol") or "")
    names = []
    if screens.get("moving_average"):
        names.append("the moving-average crossover list")
    if screens.get("price_volume"):
        names.append("the price and volume expansion list")
    if screens.get("rsi_momentum_atr"):
        names.append("the RSI momentum and ATR list")
    text = f"{symbol} is on {' and '.join(names)}. "
    if breakout is not None:
        text += (
            f"It retested the {breakout['breakout_date']} breakout. "
            f"Volume was {float(breakout['vol_multiple']):.2f} times the prior 20-day average. "
        )
    text += (
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
