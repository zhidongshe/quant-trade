import sys
sys.path.insert(0, '/Users/shezhidong/Documents/代码库/quant-trade')

import numpy as np
import pytest
from strategy.indicators import sma, macd, check_buy_signal


def test_sma_basic():
    prices = np.array([10.0, 11.0, 12.0, 13.0, 14.0, 15.0])
    result = sma(prices, period=3)
    expected = np.array([np.nan, np.nan, 11.0, 12.0, 13.0, 14.0])
    np.testing.assert_array_almost_equal(result, expected)


def test_sma_short_input():
    prices = np.array([10.0, 11.0])
    result = sma(prices, period=3)
    assert np.all(np.isnan(result))


def test_macd_basic():
    # 构造一个上涨序列，MACD应该为正
    prices = np.array([10.0] * 26 + [11.0] * 10)
    dif, dea, hist = macd(prices, fast=12, slow=26, signal=9)
    # 最后几个点的hist应该为正（上涨趋势）
    assert hist[-1] > 0
    assert dif[-1] > dea[-1]


def test_macd_flat():
    prices = np.array([10.0] * 50)
    dif, dea, hist = macd(prices, fast=12, slow=26, signal=9)
    # 平坦价格，后期dif/dea/hist都趋近于0
    assert abs(hist[-1]) < 1e-10


def test_buy_signal_all_pass():
    """三因子全部满足，应返回True"""
    # 构造一个明确上涨趋势： prices[i] = 10 + i*0.5
    prices = np.array([10.0 + i * 0.5 for i in range(70)])
    volumes = np.array([1000] * 70)
    # 最近一天放量
    volumes[-1] = 2000
    result = check_buy_signal(prices, volumes)
    assert result is True


def test_buy_signal_below_ma60():
    """价格低于60日均线，应返回False"""
    prices = np.array([100.0] * 69 + [50.0])  # 最后一天暴跌
    volumes = np.array([2000] * 70)
    result = check_buy_signal(prices, volumes)
    assert result is False


def test_buy_signal_macd_negative():
    """MACD柱状线为负，应返回False"""
    # 先涨后跌，MACD变负
    prices = np.array([10.0 + i * 0.3 for i in range(50)] + [25.0 - i * 0.5 for i in range(20)])
    volumes = np.array([2000] * 70)
    result = check_buy_signal(prices, volumes)
    assert result is False


def test_buy_signal_volume_low():
    """成交量未放大，应返回False"""
    prices = np.array([10.0 + i * 0.5 for i in range(70)])
    volumes = np.array([1000] * 70)  # 无放量
    result = check_buy_signal(prices, volumes)
    assert result is False
