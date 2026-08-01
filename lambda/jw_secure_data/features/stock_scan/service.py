"""NSE weekly HH-HL structural breakout scanner (from technicalsStock)."""

from __future__ import annotations

import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd
import yfinance as yf

DEFAULT_PIVOT_LEFT = 3
DEFAULT_PIVOT_RIGHT = 3
DEFAULT_SMA_LEN = 40
DEFAULT_RSI_LEN = 14
DEFAULT_VOL_FAST_LEN = 10
DEFAULT_VOL_SLOW_LEN = 20
DEFAULT_VOL_MULTIPLIER = 1.5
DEFAULT_LOOKBACK_YEARS = 5
DEFAULT_MIN_SCORE = 80
DEFAULT_SLEEP = 0.0
DEFAULT_MAX_WORKERS = 8
# API Gateway REST integrations time out at ~29s regardless of Lambda timeout.
API_GATEWAY_SYNC_BUDGET_SEC = 29

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DEFAULT_UNIVERSE_CSV = DATA_DIR / "indian_stocks.csv"

UNIVERSE_SEGMENTS: dict[str, dict[str, str]] = {
    "midcap": {
        "label": "Nifty Midcap 150",
        "file": "nifty_midcap150.csv",
    },
    "smallcap": {
        "label": "Nifty Smallcap 250",
        "file": "nifty_smallcap250.csv",
    },
    "custom": {
        "label": "Custom watchlist",
        "file": "",
    },
}
DEFAULT_UNIVERSE_SEGMENT = "midcap"


def normalize_nse_symbol(raw_symbol: str) -> str:
    if raw_symbol is None:
        return ""

    symbol = str(raw_symbol).strip().upper()
    if not symbol or symbol == "NAN":
        return ""

    if symbol.startswith("NSE:"):
        symbol = symbol.replace("NSE:", "", 1)

    if symbol.endswith(".NS"):
        return symbol

    if "." not in symbol:
        return f"{symbol}.NS"

    return symbol


def load_symbols_from_csv(csv_path: Path | str) -> list[str]:
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"Universe CSV not found: {path}")

    df = pd.read_csv(path)
    if df.empty:
        raise ValueError("Universe CSV is empty.")

    possible_cols = ["Symbol", "SYMBOL", "symbol", "Ticker", "ticker", "tradingsymbol", "TRADINGSYMBOL"]
    symbol_col = next((col for col in possible_cols if col in df.columns), None)
    if symbol_col is None:
        raise ValueError("Could not find a symbol column in universe CSV.")

    symbols = [normalize_nse_symbol(x) for x in df[symbol_col].dropna().tolist()]
    symbols = sorted(set(symbol for symbol in symbols if symbol))
    if not symbols:
        raise ValueError("No valid symbols found in universe CSV.")
    return symbols


def resolve_universe_csv(segment: str | None = None) -> Path:
    key = (segment or DEFAULT_UNIVERSE_SEGMENT).strip().lower()
    if key not in UNIVERSE_SEGMENTS:
        known = ", ".join(sorted(UNIVERSE_SEGMENTS))
        raise ValueError(f"Unknown universe segment '{segment}'. Expected one of: {known}")
    if key == "custom":
        raise ValueError("Custom universe uses symbols from the request body, not a CSV.")
    return DATA_DIR / UNIVERSE_SEGMENTS[key]["file"]


def universe_symbols(segment: str | None = None, limit: int | None = None) -> list[str]:
    symbols = load_symbols_from_csv(resolve_universe_csv(segment))
    if limit is not None and limit > 0:
        return symbols[:limit]
    return symbols


def default_universe_symbols(limit: int | None = None) -> list[str]:
    return universe_symbols(DEFAULT_UNIVERSE_SEGMENT, limit)


def universe_info(segment: str | None = None) -> dict[str, Any]:
    key = (segment or DEFAULT_UNIVERSE_SEGMENT).strip().lower()
    if key not in UNIVERSE_SEGMENTS:
        known = ", ".join(sorted(UNIVERSE_SEGMENTS))
        raise ValueError(f"Unknown universe segment '{segment}'. Expected one of: {known}")
    meta = UNIVERSE_SEGMENTS[key]
    if key == "custom":
        return {
            "segment": key,
            "label": meta["label"],
            "source": "user-provided symbols",
            "symbolCount": 0,
            "sampleSymbols": [],
        }
    csv_path = resolve_universe_csv(key)
    symbols = universe_symbols(key)
    return {
        "segment": key,
        "label": meta["label"],
        "source": csv_path.name,
        "symbolCount": len(symbols),
        "sampleSymbols": symbols[:10],
    }


def _passes_ranked_filter(row: dict[str, Any], min_score: int, strict_rsi_30: bool) -> bool:
    if row.get("Scan_Status") != "OK":
        return False
    if int(row.get("Score", 0)) < min_score:
        return False
    if strict_rsi_30 and not row.get("RSI_Valid"):
        return False
    return True


def calculate_rsi(close: pd.Series, length: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    avg_loss = loss.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50)


def detect_pivots(df: pd.DataFrame, left: int = 3, right: int = 3) -> pd.DataFrame:
    out = df.copy()
    out["pivot_high"] = np.nan
    out["pivot_low"] = np.nan

    highs = out["High"].to_numpy(dtype=float)
    lows = out["Low"].to_numpy(dtype=float)

    for i in range(left, len(out) - right):
        left_highs = highs[i - left:i]
        right_highs = highs[i + 1:i + right + 1]
        left_lows = lows[i - left:i]
        right_lows = lows[i + 1:i + right + 1]

        if highs[i] > np.max(left_highs) and highs[i] > np.max(right_highs):
            out.iloc[i, out.columns.get_loc("pivot_high")] = highs[i]

        if lows[i] < np.min(left_lows) and lows[i] < np.min(right_lows):
            out.iloc[i, out.columns.get_loc("pivot_low")] = lows[i]

    return out


def download_weekly_data(symbol: str, lookback_years: int) -> pd.DataFrame:
    end_dt = datetime.today()
    start_dt = end_dt - timedelta(days=(lookback_years * 365 + 365))

    df = yf.download(
        symbol,
        start=start_dt.strftime("%Y-%m-%d"),
        end=end_dt.strftime("%Y-%m-%d"),
        interval="1wk",
        auto_adjust=True,
        progress=False,
        threads=False,
    )

    if df is None or df.empty:
        return pd.DataFrame()

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]

    required = ["Open", "High", "Low", "Close", "Volume"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        return pd.DataFrame()

    df = df[required].copy().dropna()
    df = df[df["Volume"].fillna(0) > 0]
    return df


def scan_symbol(
    symbol: str,
    *,
    pivot_left: int = DEFAULT_PIVOT_LEFT,
    pivot_right: int = DEFAULT_PIVOT_RIGHT,
    sma_len: int = DEFAULT_SMA_LEN,
    rsi_len: int = DEFAULT_RSI_LEN,
    vol_fast_len: int = DEFAULT_VOL_FAST_LEN,
    vol_slow_len: int = DEFAULT_VOL_SLOW_LEN,
    vol_multiplier: float = DEFAULT_VOL_MULTIPLIER,
    lookback_years: int = DEFAULT_LOOKBACK_YEARS,
    strict_rsi_30: bool = True,
) -> dict[str, Any]:
    try:
        df = download_weekly_data(symbol, lookback_years)

        if df.empty or len(df) < max(120, sma_len + 30, vol_slow_len + 30):
            return {"Symbol": symbol, "Scan_Status": "NO_DATA_OR_INSUFFICIENT_HISTORY"}

        max_bars = lookback_years * 52
        df = df.tail(max_bars).copy()

        df["SMA40"] = df["Close"].rolling(sma_len).mean()
        df["VolMA10"] = df["Volume"].rolling(vol_fast_len).mean()
        df["VolMA20"] = df["Volume"].rolling(vol_slow_len).mean()
        df["RSI14"] = calculate_rsi(df["Close"], rsi_len)
        df = detect_pivots(df, pivot_left, pivot_right)

        pivot_highs = df[df["pivot_high"].notna()][["pivot_high"]]
        pivot_lows = df[df["pivot_low"].notna()][["pivot_low"]]

        if len(pivot_highs) < 2 or len(pivot_lows) < 2:
            return {"Symbol": symbol, "Scan_Status": "INSUFFICIENT_PIVOTS"}

        prev_ph_idx = pivot_highs.index[-2]
        curr_ph_idx = pivot_highs.index[-1]
        prev_ph = float(pivot_highs["pivot_high"].iloc[-2])
        curr_ph = float(pivot_highs["pivot_high"].iloc[-1])

        prev_pl_idx = pivot_lows.index[-2]
        curr_pl_idx = pivot_lows.index[-1]
        prev_pl = float(pivot_lows["pivot_low"].iloc[-2])
        curr_pl = float(pivot_lows["pivot_low"].iloc[-1])

        latest = df.iloc[-1]
        previous = df.iloc[-2]

        higher_high = curr_ph > prev_ph
        higher_low = curr_pl > prev_pl
        boundary_respected = curr_pl > prev_ph
        pullback_after_high = curr_pl_idx > curr_ph_idx
        breakout_trigger = previous["Close"] <= curr_ph and latest["Close"] > curr_ph

        above_sma40 = latest["Close"] > latest["SMA40"]
        volume_expansion_20 = latest["Volume"] > (vol_multiplier * latest["VolMA20"])
        volume_expansion_10 = latest["Volume"] > (vol_multiplier * latest["VolMA10"])
        volume_expansion = volume_expansion_20 or volume_expansion_10

        rsi_recent_10_low = float(df["RSI14"].tail(10).min())
        rsi_recent_15_low = float(df["RSI14"].tail(15).min())
        rsi_cooling_threshold = 30 if strict_rsi_30 else 35
        rsi_was_cool = min(rsi_recent_10_low, rsi_recent_15_low) < rsi_cooling_threshold
        rsi_rising = latest["RSI14"] > previous["RSI14"]
        not_overextended_before_breakout = previous["RSI14"] < 70
        rsi_valid = rsi_was_cool and rsi_rising and not_overextended_before_breakout

        score = 0
        score += 20 if higher_high else 0
        score += 20 if higher_low else 0
        score += 20 if boundary_respected else 0
        score += 10 if pullback_after_high else 0
        score += 10 if above_sma40 else 0
        score += 10 if volume_expansion else 0
        score += 5 if rsi_was_cool and rsi_rising else 0
        score += 5 if not_overextended_before_breakout else 0

        final_signal = all(
            [
                higher_high,
                higher_low,
                boundary_respected,
                pullback_after_high,
                breakout_trigger,
                above_sma40,
                volume_expansion,
                rsi_valid,
            ]
        )

        near_breakout_pct = ((curr_ph - latest["Close"]) / curr_ph) * 100 if curr_ph else np.nan
        near_setup = (
            higher_high
            and higher_low
            and boundary_respected
            and pullback_after_high
            and above_sma40
            and volume_expansion
            and rsi_rising
            and latest["Close"] <= curr_ph
            and near_breakout_pct <= 5
        )

        return {
            "Symbol": symbol,
            "Scan_Status": "OK",
            "Final_Signal": bool(final_signal),
            "Near_Setup_Within_5pct": bool(near_setup),
            "Score": int(score),
            "Close": round(float(latest["Close"]), 2),
            "Current_HH": round(curr_ph, 2),
            "Previous_HH": round(prev_ph, 2),
            "Current_HL": round(curr_pl, 2),
            "Previous_HL": round(prev_pl, 2),
            "Boundary_Gap_pct": round(((curr_pl - prev_ph) / prev_ph) * 100, 2) if prev_ph else np.nan,
            "Distance_To_Breakout_pct": round(float(near_breakout_pct), 2),
            "SMA40": round(float(latest["SMA40"]), 2) if pd.notna(latest["SMA40"]) else np.nan,
            "Volume": int(latest["Volume"]),
            "VolMA10": int(latest["VolMA10"]) if pd.notna(latest["VolMA10"]) else 0,
            "VolMA20": int(latest["VolMA20"]) if pd.notna(latest["VolMA20"]) else 0,
            "RSI14": round(float(latest["RSI14"]), 2),
            "RSI_Previous": round(float(previous["RSI14"]), 2),
            "RSI_Recent_10W_Low": round(rsi_recent_10_low, 2),
            "RSI_Recent_15W_Low": round(rsi_recent_15_low, 2),
            "Higher_High": bool(higher_high),
            "Higher_Low": bool(higher_low),
            "Boundary_Respected": bool(boundary_respected),
            "Pullback_After_HH": bool(pullback_after_high),
            "Breakout_Trigger": bool(breakout_trigger),
            "Above_SMA40": bool(above_sma40),
            "Volume_Expansion_10_or_20": bool(volume_expansion),
            "RSI_Valid": bool(rsi_valid),
            "Prev_HH_Date": str(pd.to_datetime(prev_ph_idx).date()),
            "Curr_HH_Date": str(pd.to_datetime(curr_ph_idx).date()),
            "Prev_HL_Date": str(pd.to_datetime(prev_pl_idx).date()),
            "Curr_HL_Date": str(pd.to_datetime(curr_pl_idx).date()),
            "Latest_Weekly_Candle_Date": str(pd.to_datetime(df.index[-1]).date()),
        }

    except Exception as exc:
        return {
            "Symbol": symbol,
            "Scan_Status": f"ERROR: {type(exc).__name__}: {exc}",
        }


def _sanitize_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _sanitize_record(record: dict[str, Any]) -> dict[str, Any]:
    return {key: _sanitize_value(value) for key, value in record.items()}


def _scan_options_kwargs(options: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in options.items() if k not in {"min_score", "sleep", "max_workers"}}


def _scan_symbols(
    symbols: list[str],
    options: dict[str, Any],
    *,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[dict[str, Any]]:
    scan_kwargs = _scan_options_kwargs(options)
    max_workers = max(1, min(int(options.get("max_workers", DEFAULT_MAX_WORKERS)), 16))
    sleep = float(options.get("sleep", DEFAULT_SLEEP))
    total = len(symbols)

    def report(completed: int) -> None:
        if on_progress is not None:
            on_progress(completed, total)

    if len(symbols) <= 1 or max_workers == 1:
        rows: list[dict[str, Any]] = []
        for index, symbol in enumerate(symbols, start=1):
            row = scan_symbol(symbol, **scan_kwargs)
            if row:
                rows.append(row)
            report(index)
            if sleep > 0:
                time.sleep(sleep)
        return rows

    rows = []
    completed = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(scan_symbol, symbol, **scan_kwargs) for symbol in symbols]
        for future in as_completed(futures):
            row = future.result()
            if row:
                rows.append(row)
            completed += 1
            report(completed)
    return rows


def _normalize_options(payload: dict[str, Any]) -> dict[str, Any]:
    strict_raw = payload.get("strictRsi30", True)
    if isinstance(strict_raw, str):
        strict_rsi_30 = strict_raw.lower() != "false"
    else:
        strict_rsi_30 = bool(strict_raw)

    return {
        "pivot_left": int(payload.get("pivotLeft", DEFAULT_PIVOT_LEFT)),
        "pivot_right": int(payload.get("pivotRight", DEFAULT_PIVOT_RIGHT)),
        "sma_len": int(payload.get("smaLen", DEFAULT_SMA_LEN)),
        "rsi_len": int(payload.get("rsiLen", DEFAULT_RSI_LEN)),
        "vol_fast_len": int(payload.get("volFastLen", DEFAULT_VOL_FAST_LEN)),
        "vol_slow_len": int(payload.get("volSlowLen", DEFAULT_VOL_SLOW_LEN)),
        "vol_multiplier": float(payload.get("volMultiplier", DEFAULT_VOL_MULTIPLIER)),
        "lookback_years": int(payload.get("lookbackYears", DEFAULT_LOOKBACK_YEARS)),
        "strict_rsi_30": strict_rsi_30,
        "min_score": int(payload.get("minScore", DEFAULT_MIN_SCORE)),
        "sleep": float(payload.get("sleep", DEFAULT_SLEEP)),
        "max_workers": int(payload.get("maxWorkers", DEFAULT_MAX_WORKERS)),
    }


def resolve_scan_symbols(payload: dict[str, Any]) -> list[str]:
    """Resolve the symbol list for a scan request (shared by sync and async paths)."""
    segment = payload.get("universeSegment") or payload.get("segment")
    raw_symbols = payload.get("symbols")
    if isinstance(raw_symbols, list) and raw_symbols:
        symbols = sorted(set(normalize_nse_symbol(s) for s in raw_symbols if str(s).strip()))
        return [s for s in symbols if s]

    limit = payload.get("symbolLimit")
    symbol_limit = int(limit) if limit is not None else None
    return universe_symbols(str(segment) if segment else None, symbol_limit)


def run_scan(
    payload: dict[str, Any],
    *,
    on_progress: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    options = _normalize_options(payload)

    segment = payload.get("universeSegment") or payload.get("segment")
    raw_symbols = payload.get("symbols")
    if isinstance(raw_symbols, list) and raw_symbols:
        symbols = resolve_scan_symbols(payload)
        resolved_segment = "custom"
    else:
        resolved_segment = (str(segment).strip().lower() if segment else DEFAULT_UNIVERSE_SEGMENT)
        symbols = resolve_scan_symbols(payload)

    if not symbols:
        raise ValueError("No symbols to scan.")

    rows = _scan_symbols(symbols, options, on_progress=on_progress)

    results = pd.DataFrame(rows)
    if results.empty:
        return {
            "scannedCount": len(symbols),
            "universeSegment": resolved_segment,
            "minScore": options["min_score"],
            "strictRsi30": options["strict_rsi_30"],
            "results": [],
            "finalSignals": [],
            "rankedCandidates": [],
            "finalSignalCount": 0,
            "rankedCandidateCount": 0,
        }

    sort_cols = [c for c in ["Final_Signal", "Score", "Distance_To_Breakout_pct"] if c in results.columns]
    if sort_cols:
        ascending = [False if c in ["Final_Signal", "Score"] else True for c in sort_cols]
        results = results.sort_values(sort_cols, ascending=ascending)

    records = [_sanitize_record(record) for record in results.to_dict(orient="records")]
    final_signals = [r for r in records if r.get("Final_Signal") is True]
    ranked_candidates = [
        r
        for r in records
        if _passes_ranked_filter(r, options["min_score"], options["strict_rsi_30"])
    ]

    return {
        "scannedCount": len(symbols),
        "universeSegment": resolved_segment,
        "minScore": options["min_score"],
        "strictRsi30": options["strict_rsi_30"],
        "results": records,
        "finalSignals": final_signals,
        "rankedCandidates": ranked_candidates,
        "finalSignalCount": len(final_signals),
        "rankedCandidateCount": len(ranked_candidates),
    }
