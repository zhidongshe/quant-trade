import numpy as np
from strategy_hs300 import check_market_trend


def test_market_returns_false_with_short_data():
    assert check_market_trend(np.array([1.0] * 10)) is False
    assert check_market_trend(None) is False


def test_market_returns_false_on_3pct_crash():
    prices = np.array([100.0] * 80 + [85.0])  # 当日 -15%
    assert check_market_trend(prices) is False


def test_market_ok_when_above_ma20_and_macd_positive():
    prices = np.array([10.0 + i * 0.1 for i in range(70)])  # 单调升
    assert check_market_trend(prices) is True


def test_market_not_ok_below_ma20():
    rising = np.array([20.0 + i * 0.1 for i in range(70)])
    rising[-1] = 18.0  # 大幅低于均线但不触发单日 -3% 拦截
    rising[-2] = 18.3
    assert check_market_trend(rising) is False


def test_market_not_ok_when_macd_negative():
    # 长期下跌后微反弹
    prices = np.array([30.0 - i * 0.2 for i in range(70)])
    assert check_market_trend(prices) is False
