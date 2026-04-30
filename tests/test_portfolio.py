import sys
sys.path.insert(0, '/Users/shezhidong/Documents/代码库/quant-trade')

import numpy as np
import pytest
from strategy.portfolio import (
    Position, check_stop_loss, check_trend_break,
    check_trailing_stop, calculate_buy_amount
)


def test_position_creation():
    pos = Position(stockcode='000001.SZ', buy_price=10.0, buy_date='20240101', volume=1000)
    assert pos.stockcode == '000001.SZ'
    assert pos.buy_price == 10.0
    assert pos.highest_price == 10.0


def test_hard_stop_loss_triggered():
    """下跌3%应触发止损"""
    pos = Position('000001.SZ', buy_price=100.0, buy_date='20240101', volume=100)
    current_price = 96.9  # 下跌3.1%
    assert check_stop_loss(pos, current_price, hard_stop_pct=0.03) is True


def test_hard_stop_loss_not_triggered():
    """下跌2%不应触发"""
    pos = Position('000001.SZ', buy_price=100.0, buy_date='20240101', volume=100)
    current_price = 98.0
    assert check_stop_loss(pos, current_price, hard_stop_pct=0.03) is False


def test_trend_break_triggered():
    """收盘价跌破20日均线，应触发"""
    current_price = 95.0
    ma20 = 96.0
    assert check_trend_break(current_price, ma20) is True


def test_trend_break_not_triggered():
    """收盘价在20日均线上方，不应触发"""
    current_price = 97.0
    ma20 = 96.0
    assert check_trend_break(current_price, ma20) is False


def test_trailing_stop_not_triggered_yet():
    """盈利未超5%，不启动跟踪止盈"""
    pos = Position('000001.SZ', buy_price=100.0, buy_date='20240101', volume=100)
    current_price = 103.0  # 盈利3%，未达5%启动线
    assert check_trailing_stop(pos, current_price, profit_threshold=0.05, pullback_pct=0.05) is False


def test_trailing_stop_triggered():
    """盈利超5%后，从最高点回落5%，应触发"""
    pos = Position('000001.SZ', buy_price=100.0, buy_date='20240101', volume=100)
    pos.highest_price = 110.0  # 曾经涨到110（盈利10%）
    current_price = 104.4  # 从110回落5.09%，应触发
    assert check_trailing_stop(pos, current_price, profit_threshold=0.05, pullback_pct=0.05) is True


def test_trailing_stop_not_triggered_after_profit():
    """盈利超5%，但回落不足5%，不触发"""
    pos = Position('000001.SZ', buy_price=100.0, buy_date='20240101', volume=100)
    pos.highest_price = 110.0
    current_price = 105.0  # 从110回落4.55%，未达5%
    assert check_trailing_stop(pos, current_price, profit_threshold=0.05, pullback_pct=0.05) is False


def test_trailing_stop_updates_high():
    """跟踪止盈应动态更新最高价"""
    pos = Position('000001.SZ', buy_price=100.0, buy_date='20240101', volume=100)
    check_trailing_stop(pos, 106.0, profit_threshold=0.05, pullback_pct=0.05)
    assert pos.highest_price == 106.0
    check_trailing_stop(pos, 108.0, profit_threshold=0.05, pullback_pct=0.05)
    assert pos.highest_price == 108.0


def test_calculate_buy_amount_basic():
    """可用资金50万，应买入20万（单只20%上限）"""
    assert calculate_buy_amount(total_capital=1000000, available_cash=500000, max_positions=5) == 200000


def test_calculate_buy_amount_low_cash():
    """可用资金只剩8万，最多买8万"""
    assert calculate_buy_amount(total_capital=1000000, available_cash=80000, max_positions=5) == 80000


def test_calculate_buy_amount_rounding():
    """计算结果应为100的整数倍（A股最小交易单位）"""
    amount = calculate_buy_amount(total_capital=1000000, available_cash=123456, max_positions=5)
    assert amount % 100 == 0
