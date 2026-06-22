from datetime import datetime
from backtest_v1 import (
    QMTShim, DataLoader, BacktestAccount, CostConfig, timetag_to_datetime
)


def _make_shim():
    loader = DataLoader(data_root='tests/fixtures/backtest')
    loader.load_daily()
    acct = BacktestAccount(initial_cash=1_000_000, cost_config=CostConfig())
    return QMTShim(loader, acct)


def test_advance_to_sets_barpos_and_timetag():
    shim = _make_shim()
    shim.advance_to(datetime(2024, 1, 2, 9, 35), bar_idx_global=0)
    assert shim.barpos == 0
    tt = shim.get_bar_timetag(0)
    assert timetag_to_datetime(tt, '%H:%M:%S') == '09:35:00'


def test_is_last_bar_always_true():
    shim = _make_shim()
    shim.advance_to(datetime(2024, 1, 2, 9, 35), 0)
    assert shim.is_last_bar() is True


def test_set_universe_stores():
    shim = _make_shim()
    shim.set_universe(['600000.SH', '000300.SH'])
    assert '600000.SH' in shim._universe


def test_get_sector_returns_loaded_stocks():
    shim = _make_shim()
    sector = shim.get_sector('000300.SH')
    assert '600000.SH' in sector


def test_get_instrumentdetail_returns_pre_close():
    shim = _make_shim()
    shim.advance_to(datetime(2024, 1, 4, 14, 55), bar_idx_global=2)
    detail = shim.get_instrumentdetail('600000.SH')
    # 前一日 close = 9.15
    assert abs(detail['PreClose'] - 9.15) < 1e-6
    assert abs(detail['UpStopPrice'] - round(9.15 * 1.1, 2)) < 1e-6
    assert detail['m_strInstrumentName'] == '浦发银行'


# ---------------------------------------------------------------------------
# Task 9: get_history_data + partial day bar
# Fixture: SH.600000_2024-01.txt has full 49 bars for 2024-01-04 (09:35–15:00)
# Expected values (from deterministic formula close=9.10+0.001*i, high=close+0.05):
#   bar 09:35 → i=0 → close=9.100, high=9.150
#   bar 14:55 → i=47 → close=9.147, high=9.197
#   max_high up to 14:55 (all 48 bars) = high[i=47] = 9.197 (monotone)
# ---------------------------------------------------------------------------
EXPECTED_1455_CLOSE = 9.147
EXPECTED_1455_MAX_HIGH = 9.197
EXPECTED_0935_HIGH = 9.150


def _make_shim_with_5m():
    """Shim with 5min data for 2024-01 loaded."""
    shim = _make_shim()
    shim.data_loader.ensure_month_loaded('2024-01')
    shim.set_universe(['600000.SH'])
    return shim


def test_get_history_data_returns_past_days_plus_partial_today():
    """get_history_data(N=3) at 14:55: 2 past days + 1 partial = 3 elements, last = partial close.
    Fixture has only 3 trading days (2024-01-02, 2024-01-03, 2024-01-04) so N<=3.
    """
    import numpy as np
    shim = _make_shim_with_5m()
    shim.advance_to(datetime(2024, 1, 4, 14, 55), bar_idx_global=100)
    res = shim.get_history_data(3, '1d', 'close')
    arr = res['600000.SH']
    assert isinstance(arr, np.ndarray), 'result must be numpy array'
    assert len(arr) == 3
    assert abs(arr[-1] - EXPECTED_1455_CLOSE) < 1e-3, (
        f'Last element should be partial-day close {EXPECTED_1455_CLOSE}, got {arr[-1]}'
    )


def test_partial_today_close_equals_current_5m_close():
    """At 14:55, partial-day close is the 5min bar close at 14:55."""
    import numpy as np
    shim = _make_shim_with_5m()
    shim.advance_to(datetime(2024, 1, 4, 14, 55), bar_idx_global=100)
    res = shim.get_history_data(3, '1d', 'close')
    arr = res['600000.SH']
    assert len(arr) == 3
    # last element = partial today close = 14:55 bar close
    assert abs(arr[-1] - EXPECTED_1455_CLOSE) < 1e-3


def test_partial_today_high_is_max_of_5m_high_so_far():
    """At 14:55, today's high = max of all 5min bar highs up to 14:55."""
    import numpy as np
    shim = _make_shim_with_5m()
    shim.advance_to(datetime(2024, 1, 4, 14, 55), bar_idx_global=100)
    res = shim.get_history_data(3, '1d', 'high')
    arr = res['600000.SH']
    # max high across all 48 bars i=0..47: high = 9.10+0.001*i+0.05, max at i=47 = 9.197
    assert abs(arr[-1] - EXPECTED_1455_MAX_HIGH) < 1e-3, (
        f'Expected max high {EXPECTED_1455_MAX_HIGH}, got {arr[-1]}'
    )


def test_history_excludes_future_bars():
    """At 09:35, today's high must equal only the 09:35 bar high (no future bars)."""
    import numpy as np
    shim = _make_shim_with_5m()
    shim.advance_to(datetime(2024, 1, 4, 9, 35), bar_idx_global=50)
    res = shim.get_history_data(3, '1d', 'high')
    arr = res['600000.SH']
    # Only the 09:35 bar (i=0, high=9.150) is visible; later bars must NOT be included
    assert abs(arr[-1] - EXPECTED_0935_HIGH) < 1e-3, (
        f'Expected high {EXPECTED_0935_HIGH} (09:35 only), got {arr[-1]}'
    )


def test_get_history_data_raises_for_non_1d():
    """get_history_data with period!='1d' must raise NotImplementedError."""
    import pytest
    shim = _make_shim_with_5m()
    shim.advance_to(datetime(2024, 1, 4, 14, 55), bar_idx_global=100)
    with pytest.raises(NotImplementedError):
        shim.get_history_data(5, '5m', 'close')


# ---------------------------------------------------------------------------
# Task 10: passorder + get_trade_detail_data
# ---------------------------------------------------------------------------

def test_passorder_buy_enqueues_to_account():
    shim = _make_shim()
    shim.advance_to(datetime(2024, 1, 2, 14, 55), 0)
    shim.passorder(23, 1101, '8890358835', '600000.SH', 5, 9.0, 1000,
                   '价格类型', 1, '信号买入', 1)
    assert len(shim.account.pending_orders) == 1
    o = shim.account.pending_orders[0]
    assert o.side == 'BUY' and o.code == '600000.SH' and o.volume == 1000


def test_passorder_sell_enqueues():
    shim = _make_shim()
    shim.advance_to(datetime(2024, 1, 5, 14, 55), 0)
    shim.passorder(24, 1101, '8890358835', '600000.SH', 5, 9.5, 500,
                   '价格类型', 1, '止盈', 1)
    o = shim.account.pending_orders[0]
    assert o.side == 'SELL' and o.volume == 500


def test_get_trade_detail_data_account_returns_balance():
    shim = _make_shim()
    res = shim.get_trade_detail_data('8890358835', 'STOCK', 'ACCOUNT')
    assert len(res) == 1
    assert hasattr(res[0], 'm_dBalance')
    assert res[0].m_dBalance == 1_000_000


def test_get_trade_detail_data_position_lists_holdings():
    from backtest_v1 import Position
    shim = _make_shim()
    shim.account.positions['600000.SH'] = Position(
        code='600000.SH', volume=1000, open_price=9.0, open_date='2024-01-02', market_value=9000.0
    )
    res = shim.get_trade_detail_data('8890358835', 'STOCK', 'POSITION')
    assert len(res) == 1
    p = res[0]
    assert p.m_strInstrumentID == '600000.SH'
    assert p.m_nVolume == 1000
    assert p.m_nCanUseVolume == 1000 - 0  # T+1 锁定情况由 caller 自己算
    assert p.m_dOpenPrice == 9.0
