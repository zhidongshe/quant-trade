"""TDD tests for backtest.account — Task 7."""
import pytest
from backtest.account import Account


def test_initial_state():
    a = Account(initial_capital=500000.0)
    assert a.cash == 500000.0
    assert a.positions == {}
    assert a.trades == []


def test_fill_buy_decreases_cash_increases_position():
    a = Account(initial_capital=500000.0)
    ok = a.fill_buy('SH.600000', '浦发银行', volume=1000, price=10.0,
                    date_str='20200101', reason='buy_signal')
    assert ok is True
    # 现金 = 50w - 1000*10 - 交易成本（~15.01 = 5+0.1+5=10.1元..）
    # 简化检查
    assert a.cash < 500000.0
    assert 'SH.600000' in a.positions
    assert a.positions['SH.600000'].volume == 1000
    assert a.positions['SH.600000'].can_use_volume == 0  # T+1


def test_t1_unlock_next_day():
    a = Account(initial_capital=500000.0)
    a.fill_buy('SH.600000', '浦发', volume=1000, price=10.0,
               date_str='20200101', reason='buy_signal')
    assert a.positions['SH.600000'].can_use_volume == 0
    a.advance_day('20200102')
    assert a.positions['SH.600000'].can_use_volume == 1000


def test_fill_sell_before_t1_rejected():
    a = Account(initial_capital=500000.0)
    a.fill_buy('SH.600000', '浦发', volume=1000, price=10.0,
               date_str='20200101', reason='buy_signal')
    # 当日卖
    ok = a.fill_sell('SH.600000', '浦发', volume=1000, price=10.5,
                     date_str='20200101', reason='hard_stop')
    assert ok is False
    # 应进 trades 作为拒单
    rejects = [t for t in a.trades if t.status == 'REJECTED' and t.reason == 'T1_LOCKED']
    assert len(rejects) == 1


def test_snapshot_equity_balance():
    a = Account(initial_capital=500000.0)
    a.fill_buy('SH.600000', '浦发', volume=1000, price=10.0,
               date_str='20200101', reason='buy_signal')
    snap = a.snapshot('20200101', close_prices={'SH.600000': 10.5})
    assert snap.cash == a.cash
    assert snap.position_value == pytest.approx(1000 * 10.5)
    assert snap.total_equity == pytest.approx(snap.cash + snap.position_value)
    assert snap.n_positions == 1


def test_fill_sell_releases_position():
    a = Account(initial_capital=500000.0)
    a.fill_buy('SH.600000', '浦发', volume=1000, price=10.0,
               date_str='20200101', reason='buy_signal')
    a.advance_day('20200102')
    ok = a.fill_sell('SH.600000', '浦发', volume=1000, price=10.5,
                     date_str='20200102', reason='hard_stop')
    assert ok is True
    assert 'SH.600000' not in a.positions
    assert a.cash > 500000.0 - 1000 * 10.0  # 至少回收了大部分本金
