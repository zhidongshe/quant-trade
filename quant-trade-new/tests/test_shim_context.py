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
    # get_history_data returns strategy-form codes for active_universe stocks and index
    # The index (000300.SH) is always included in strategy form
    assert '000300.SH' in hist
    assert len(hist['000300.SH']) == 60


def test_get_history_data_last_is_today(shim):
    """最后一根 = 当日 close。"""
    hist = shim.context.get_history_data(5, '1d', 'close')
    # shim 当前日是 2020-03-02，index 用策略形态
    expected = shim.data_loader.daily_df['SH.000300'].loc['2020-03-02', 'close']
    assert hist['000300.SH'][-1] == pytest.approx(expected)


def test_get_history_data_short_returns_short(shim):
    """请求 10000 但只有几百天数据，返回短列表不报错。"""
    hist = shim.context.get_history_data(10000, '1d', 'close')
    assert len(hist['000300.SH']) < 1000


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


def test_get_history_data_uses_strategy_form_keys_including_index():
    """get_history_data 返回的所有 key 必须是策略形态（含指数），
    以便 v1 策略 `if '000300.SH' in hist:` 能命中。Regression for spec drift bug."""
    dl = DataLoader(DATA_ROOT)
    dl.load(start=date(2020, 1, 1), end=date(2020, 6, 30), warmup_days=120)
    acct = Account(initial_capital=500000.0)
    run_dir = Path(__file__).parent / 'tmp' / 'run_reg'
    run_dir.mkdir(parents=True, exist_ok=True)
    s = Shim(dl, acct, run_dir=run_dir)
    s.context.set_universe(['600000.SH', '000300.SH'])
    s.advance_to(pd.Timestamp('2020-03-02'), barpos=0)

    hist = s.context.get_history_data(10, '1d', 'close')
    # All keys must be in strategy form
    assert '000300.SH' in hist, "Index must be in strategy form (000300.SH)"
    assert 'SH.000300' not in hist, "Index must NOT be in data form (SH.000300)"
    assert '600000.SH' in hist, "Stock must be in strategy form (600000.SH)"
    assert len(hist['000300.SH']) == 10
    assert len(hist['600000.SH']) == 10
