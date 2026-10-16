from datetime import date, timedelta

from kite_app.signals import (
    exponential_moving_average,
    latest_crossover,
    latest_price_cross,
    parse_nifty100_csv,
    simple_moving_average,
    weighted_moving_average,
)


def test_simple_moving_average():
    averages = simple_moving_average([1, 2, 3, 4, 5], 3)
    assert averages[:2] == [None, None]
    assert averages[2:] == [2, 3, 4]


def test_exponential_moving_average_uses_the_standard_smoothing_factor():
    averages = exponential_moving_average([1, 2, 3, 4, 5], 3)
    assert averages[:2] == [None, None]
    assert averages[2:] == [2, 3, 4]


def test_weighted_moving_average_weights_the_newest_close_highest():
    averages = weighted_moving_average([1, 2, 3, 4, 5], 3)
    assert averages[:2] == [None, None]
    assert averages[2] == 14 / 6
    assert averages[3] == 20 / 6
    assert averages[4] == 26 / 6


def test_latest_crossover_accepts_ema_and_wma():
    start = date(2026, 3, 1)
    flat = [{"date": start + timedelta(days=index), "close": 10} for index in range(8)]
    rising = [{"date": start + timedelta(days=8 + index), "close": 14 + index * 3} for index in range(5)]
    candles = flat + rising
    for ma_type in ("ema", "wma"):
        found = latest_crossover(candles, short_window=2, long_window=4, lookback_days=10, ma_type=ma_type)
        assert found is not None
        assert found["crossover_type"] == "bullish"


def test_short_term_can_cross_an_ema_through_an_sma_and_keep_the_200_trend():
    start = date(2026, 4, 1)
    flat = [{"date": start + timedelta(days=index), "close": 10} for index in range(8)]
    rising = [{"date": start + timedelta(days=8 + index), "close": 14 + index * 3} for index in range(6)]
    found = latest_crossover(
        flat + rising,
        short_window=2,
        long_window=4,
        lookback_days=10,
        short_type="ema",
        long_type="sma",
        trend_window=3,
    )
    assert found is not None
    assert found["crossover_type"] == "bullish"
    assert found["trend_sma"] is not None
    assert found["trend_bias"] == "above"


def test_long_term_price_crosses_through_the_sma():
    start = date(2026, 5, 1)
    flat = [{"date": start + timedelta(days=index), "close": 10} for index in range(6)]
    rising = [{"date": start + timedelta(days=6 + index), "close": 16 + index} for index in range(3)]
    found = latest_price_cross(flat + rising, window=4, lookback_days=8)
    assert found is not None
    assert found["crossover_type"] == "bullish"
    assert found["trend_bias"] == "above"


def test_latest_crossover_keeps_the_newest_cross_inside_lookback():
    start = date(2026, 1, 1)
    flat = [{"date": start + timedelta(days=index), "close": 10} for index in range(6)]
    rising = [{"date": start + timedelta(days=6 + index), "close": 12 + index * 2} for index in range(4)]
    candles = flat + rising

    found = latest_crossover(candles, short_window=2, long_window=4, lookback_days=8)

    assert found is not None
    assert found["crossover_type"] == "bullish"
    assert found["crossover_date"] == candles[-1]["date"].isoformat() or found["short_sma"] > found["long_sma"]


def test_bearish_crossover():
    start = date(2026, 2, 1)
    high = [{"date": start + timedelta(days=index), "close": 20} for index in range(6)]
    falling = [{"date": start + timedelta(days=6 + index), "close": 16 - index * 3} for index in range(4)]
    found = latest_crossover(high + falling, short_window=2, long_window=4, lookback_days=10)
    assert found is not None
    assert found["crossover_type"] == "bearish"


def test_parse_nifty100_csv_reads_symbol_and_company():
    text = "\n".join(
        [
            "Company Name,Industry,Symbol,Series,ISIN Code",
            *[f"Company {index},Sector,SYM{index},EQ,INE{index:06d}" for index in range(60)],
        ]
    )
    rows = parse_nifty100_csv(text)
    assert rows[0] == {"ticker": "SYM0", "company": "Company 0"}
    assert len(rows) == 60
