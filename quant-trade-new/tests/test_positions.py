import numpy as np
from strategy_hs300 import (
    Position, check_hard_stop, check_crash, check_trend_break,
    check_trailing_stop, position_size, HARD_STOP_PCT,
)


def make_pos(buy_price=100.0):
    return Position(stockcode='SH.600000', buy_price=buy_price,
                    buy_date='20200101', volume=1000)


# === hard_stop ===
def test_hard_stop_triggers_at_threshold():
    pos = make_pos(100.0)
    # v1 _evaluate_and_execute_sells 传入 HARD_STOP_PCT (=0.05)
    assert check_hard_stop(pos, 95.0, HARD_STOP_PCT) is True


def test_hard_stop_not_triggered_above():
    pos = make_pos(100.0)
    assert check_hard_stop(pos, 95.5, HARD_STOP_PCT) is False


# === crash ===
def test_crash_triggers_at_7pct():
    prices = np.array([100.0, 93.0])
    assert check_crash(prices) is True


def test_crash_not_triggered_at_6pct():
    prices = np.array([100.0, 94.0])
    assert check_crash(prices) is False


def test_crash_returns_false_with_one_bar():
    assert check_crash(np.array([100.0])) is False


# === trend_break ===
def test_trend_break_double_confirm():
    # 跌破 MA20 + MACD 衰竭（hist[-1] <= 0 且 hist[-1] <= hist[-2]）
    hist = np.array([0.5, 0.3, -0.1])
    assert check_trend_break(99.0, ma20=100.0, hist=hist) is True


def test_trend_break_macd_alone_not_enough():
    hist = np.array([0.5, 0.3, -0.1])
    assert check_trend_break(101.0, ma20=100.0, hist=hist) is False


def test_trend_break_ma_alone_not_enough():
    hist = np.array([0.1, 0.2, 0.3])  # 仍扩大
    assert check_trend_break(99.0, ma20=100.0, hist=hist) is False


# === trailing_stop ===
def test_trailing_stop_not_triggered_below_threshold():
    pos = make_pos(100.0)
    pos.highest_price = 105.0  # 仅 5% < PROFIT_THRESHOLD 10%
    # v1 _evaluate_and_execute_sells 传入 (PROFIT_THRESHOLD=0.10, TRAILING_PULLBACK=0.08)
    assert check_trailing_stop(pos, current_price=102.0,
                               profit_threshold=0.10, pullback_pct=0.08) is False


def test_trailing_stop_triggers_after_high():
    pos = make_pos(100.0)
    pos.highest_price = 120.0  # 已盈利 20% > 10%
    # 从 120 跌至 110.4 = 跌 8% → 触发
    assert check_trailing_stop(pos, current_price=110.4,
                               profit_threshold=0.10, pullback_pct=0.08) is True


def test_position_size_uses_min_of_per_stock_and_cash():
    assert position_size(total_assets=1000000, available_cash=300000, max_positions=5) == 200000
    assert position_size(total_assets=1000000, available_cash=100000, max_positions=5) == 100000
