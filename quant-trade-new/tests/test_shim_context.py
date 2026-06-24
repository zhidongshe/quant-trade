import pytest
import pandas as pd
from datetime import date
from pathlib import Path
from backtest.data_loader import DataLoader
from backtest.account import Account
from backtest.shim import Shim


DATA_ROOT = "../300data/data_a"


@pytest.fixture(scope="module")
def shim(tmp_path_factory):
    dl = DataLoader(DATA_ROOT)
    dl.load(start=date(2020, 1, 1), end=date(2020, 6, 30), warmup_days=120)
    acct = Account(initial_capital=500000.0)
    run_dir = tmp_path_factory.mktemp('run')
    s = Shim(dl, acct, run_dir=run_dir)
    s.advance_to(pd.Timestamp('2020-03-02'), barpos=0)
    return s


def test_context_has_required_attributes(shim):
    ctx = shim.context
    assert hasattr(ctx, 'barpos')
    assert hasattr(ctx, 'capital')
    assert hasattr(ctx, 'positions')


def test_get_sector_returns_universe(shim):
    codes = shim.context.get_sector('000300.SH')
    assert isinstance(codes, list)
    assert len(codes) > 200


def test_get_instrumentdetail_returns_name(shim):
    # get_instrumentdetail accepts both data-form and strategy-form
    detail = shim.context.get_instrumentdetail('SH.600000')
    assert 'm_strInstrumentName' in detail
    assert detail['m_strInstrumentName']  # 非空


def test_get_instrumentdetail_has_upstop_price(shim):
    detail = shim.context.get_instrumentdetail('SH.600000')
    assert 'UpStopPrice' in detail
    assert detail['UpStopPrice'] > 0


def test_get_history_data_basic(shim):
    hist = shim.context.get_history_data(60, '1d', 'close')
    # get_history_data returns strategy-form codes for active_universe stocks
    # The index (SH.000300) is always included
    assert 'SH.000300' in hist
    assert len(hist['SH.000300']) == 60


def test_get_history_data_last_is_today(shim):
    """最后一根 = 当日 close。"""
    hist = shim.context.get_history_data(5, '1d', 'close')
    # shim 当前日是 2020-03-02，index 用 data-form
    expected = shim.data_loader.daily_df['SH.000300'].loc['2020-03-02', 'close']
    assert hist['SH.000300'][-1] == pytest.approx(expected)


def test_get_history_data_short_returns_short(shim):
    """请求 10000 但只有几百天数据，返回短列表不报错。"""
    hist = shim.context.get_history_data(10000, '1d', 'close')
    assert len(hist['SH.000300']) < 1000


def test_get_history_data_rejects_non_daily(shim):
    with pytest.raises(NotImplementedError):
        shim.context.get_history_data(60, '5m', 'close')


def test_advance_to_increments_barpos(shim):
    shim.advance_to(pd.Timestamp('2020-03-03'), barpos=1)
    assert shim.context.barpos == 1


def test_set_universe_records_active(shim):
    shim.context.set_universe(['SH.600000', 'SH.600519'])
    assert 'SH.600000' in shim.context._active_universe


def test_to_data_code_converts_strategy_form(shim):
    """600000.SH → SH.600000"""
    assert shim._to_data_code('600000.SH') == 'SH.600000'


def test_to_strategy_code_converts_data_form(shim):
    """SH.600000 → 600000.SH"""
    assert shim._to_strategy_code('SH.600000') == '600000.SH'


def test_get_today_close_returns_float(shim):
    shim.advance_to(pd.Timestamp('2020-03-03'), barpos=1)
    c = shim.get_today_close('SH.600000')
    assert c is not None and c > 0


def test_get_history_data_includes_set_universe_codes(shim):
    """set_universe 设置的代码应出现在 get_history_data 结果里。"""
    shim.context.set_universe(['600000.SH', '600519.SH'])
    shim.advance_to(pd.Timestamp('2020-03-04'), barpos=2)
    hist = shim.context.get_history_data(10, '1d', 'close')
    # strategy-form keys
    assert '600000.SH' in hist
    assert '600519.SH' in hist
