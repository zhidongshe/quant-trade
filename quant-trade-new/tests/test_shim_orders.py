import pytest
import pandas as pd
from datetime import date
from backtest.data_loader import DataLoader
from backtest.account import Account
from backtest.shim import Shim


DATA_ROOT = "../300data/data_a"


@pytest.fixture
def shim(tmp_path):
    dl = DataLoader(DATA_ROOT)
    dl.load(start=date(2020, 1, 1), end=date(2020, 6, 30), warmup_days=120)
    acct = Account(initial_capital=500000.0)
    s = Shim(dl, acct, run_dir=tmp_path)
    s.advance_to(pd.Timestamp('2020-03-02'), barpos=0)
    s.context.set_universe([c for c in dl.universe_codes() if c != 'SH.000300'])
    s.context.accountid = 'test_acct'
    return s


def test_passorder_buy_fills(shim):
    # opcode 23 = 买, mode 1101 = 按股数, price_mode 5 = 最新价
    shim.passorder(23, 1101, 'test_acct', '600000.SH', 5, -1.0, 1000.0, shim.context)
    # 检查 Account 状态
    assert 'SH.600000' in shim.account.positions or '600000.SH' in shim.account.positions


def test_passorder_buy_cash_short_records_reject(shim):
    shim.account.cash = 100.0  # 现金极少
    shim.passorder(23, 1101, 'test_acct', '600000.SH', 5, -1.0, 100000.0, shim.context)
    rejects = [t for t in shim.account.trades
               if t.status == 'REJECTED' and t.reason == 'CASH_SHORT']
    assert len(rejects) == 1


def test_passorder_buy_limit_up_rejected(shim, monkeypatch):
    monkeypatch.setattr(shim, 'is_limit_up', lambda c: True)
    shim.passorder(23, 1101, 'test_acct', '600000.SH', 5, -1.0, 1000.0, shim.context)
    rejects = [t for t in shim.account.trades
               if t.status == 'REJECTED' and t.reason == 'LIMIT_UP']
    assert len(rejects) == 1


def test_passorder_sell_t1_locked_rejected(shim):
    shim.passorder(23, 1101, 'test_acct', '600000.SH', 5, -1.0, 1000.0, shim.context)
    # 当日卖
    shim.passorder(24, 1101, 'test_acct', '600000.SH', 5, -1.0, 1000.0, shim.context)
    rejects = [t for t in shim.account.trades
               if t.status == 'REJECTED' and t.reason == 'T1_LOCKED']
    assert len(rejects) == 1


def test_passorder_unsupported_opcode_raises(shim):
    with pytest.raises(NotImplementedError):
        shim.passorder(99, 1101, 'test_acct', '600000.SH', 5, -1.0, 1000.0, shim.context)


def test_get_trade_detail_data_account(shim):
    info = shim.get_trade_detail_data('test_acct', 'STOCK', 'ACCOUNT')
    assert len(info) == 1
    assert info[0].m_dBalance == 500000.0
    assert info[0].m_dAvailable == 500000.0


def test_get_trade_detail_data_position_t1_zero(shim):
    shim.passorder(23, 1101, 'test_acct', '600000.SH', 5, -1.0, 1000.0, shim.context)
    pos_list = shim.get_trade_detail_data('test_acct', 'STOCK', 'POSITION')
    assert len(pos_list) == 1
    assert pos_list[0].m_nCanUseVolume == 0  # T+1
    assert pos_list[0].m_nVolume == 1000


def test_get_trade_detail_data_position_after_advance(shim):
    shim.passorder(23, 1101, 'test_acct', '600000.SH', 5, -1.0, 1000.0, shim.context)
    shim.account.advance_day('20200303')
    pos_list = shim.get_trade_detail_data('test_acct', 'STOCK', 'POSITION')
    assert pos_list[0].m_nCanUseVolume == 1000


def test_timetag_to_datetime_format(shim):
    ms = int(pd.Timestamp('2020-03-02').timestamp() * 1000)
    out = shim.timetag_to_datetime(ms, '%Y%m%d')
    assert out == '20200302'


def test_injected_globals_completeness(shim):
    g = shim.injected_globals()
    assert 'passorder' in g
    assert 'get_trade_detail_data' in g
    assert 'timetag_to_datetime' in g
    assert 'np' in g
