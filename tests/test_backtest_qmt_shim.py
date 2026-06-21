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
    shim.set_universe(['SH.600000', '000300.SH'])
    assert 'SH.600000' in shim._universe


def test_get_sector_returns_loaded_stocks():
    shim = _make_shim()
    sector = shim.get_sector('000300.SH')
    assert 'SH.600000' in sector


def test_get_instrumentdetail_returns_pre_close():
    shim = _make_shim()
    shim.advance_to(datetime(2024, 1, 4, 14, 55), bar_idx_global=2)
    detail = shim.get_instrumentdetail('SH.600000')
    # 前一日 close = 9.15
    assert abs(detail['PreClose'] - 9.15) < 1e-6
    assert abs(detail['UpStopPrice'] - round(9.15 * 1.1, 2)) < 1e-6
    assert detail['InstrumentName'] == '浦发银行'
