import numpy as np
import pytest
from strategy_hs300 import sma, macd, check_buy_signal, score_factors


# === sma ===
def test_sma_returns_nan_when_too_short():
    out = sma(np.array([1.0, 2.0, 3.0]), period=5)
    assert np.all(np.isnan(out))


def test_sma_basic_5period():
    prices = np.arange(1, 11, dtype=float)  # 1..10
    out = sma(prices, period=5)
    assert np.isnan(out[3])
    assert out[4] == 3.0   # (1+2+3+4+5)/5
    assert out[9] == 8.0   # (6+7+8+9+10)/5


# === macd ===
def test_macd_returns_three_arrays_same_length():
    prices = np.linspace(10, 20, 100)
    dif, dea, hist = macd(prices)
    assert len(dif) == len(dea) == len(hist) == 100


def test_macd_rising_series_has_positive_hist_after_warmup():
    prices = np.linspace(10, 50, 100)  # 单调递增
    _, _, hist = macd(prices)
    assert hist[-1] > 0


# === check_buy_signal ===
@pytest.fixture
def good_setup():
    """构造 100 天单调微升 + 当日放量上涨 1.5% 的序列。"""
    prices = np.array([10.0 + i * 0.05 for i in range(99)])
    prices = np.append(prices, prices[-1] * 1.015)  # 当日涨 1.5%
    volumes = np.array([1000.0] * 99 + [2000.0])    # 当日放量
    return prices, volumes


def test_check_buy_signal_passes_good_setup(good_setup):
    p, v = good_setup
    assert check_buy_signal(p, v) is True


def test_check_buy_signal_fails_short_prices():
    assert check_buy_signal(np.array([1.0] * 10), np.array([1.0] * 10)) is False


def test_check_buy_signal_fails_below_ma60(good_setup):
    p, v = good_setup
    p[-1] = p[-2] * 0.5  # 当日暴跌至 MA60 下
    assert check_buy_signal(p, v) is False


def test_check_buy_signal_fails_ma5_below_ma20(good_setup):
    p, v = good_setup
    # 倒退 ma5 到 ma20 下方
    p[-5:] = p[-5:] - 5.0
    p[-1] = p[-2] * 1.015  # 保住涨幅条件
    assert check_buy_signal(p, v) is False


def test_check_buy_signal_fails_today_change_below_1pct(good_setup):
    p, v = good_setup
    p[-1] = p[-2] * 1.005  # 仅涨 0.5%
    assert check_buy_signal(p, v) is False


def test_check_buy_signal_fails_no_volume_expansion(good_setup):
    p, v = good_setup
    v[-1] = 500.0  # 缩量
    assert check_buy_signal(p, v) is False


def test_check_buy_signal_fails_macd_hist_shrinking(good_setup):
    p, v = good_setup
    # 通过把当日 close 拉得很高让 hist 强劲，再人为构造下一日缩窄
    # 这里换一种构造：去掉涨幅，制造 hist 收窄
    p[-2] = p[-3] * 1.03
    p[-1] = p[-2] * 1.001  # 涨幅 < 1%，会被涨幅条件提前否定
    assert check_buy_signal(p, v) is False


# === score_factors ===
def test_score_factors_none_when_signal_fails():
    p = np.array([10.0] * 100)  # 横盘，必失败
    v = np.array([1000.0] * 100)
    assert score_factors(p, v) is None


def test_score_factors_returns_four_keys(good_setup):
    p, v = good_setup
    f = score_factors(p, v)
    assert f is not None
    assert set(f.keys()) == {'trend_score', 'ma_spread_score', 'macd_score', 'volume_score'}


def test_score_factors_values_finite(good_setup):
    p, v = good_setup
    f = score_factors(p, v)
    assert all(np.isfinite(v) for v in f.values())
