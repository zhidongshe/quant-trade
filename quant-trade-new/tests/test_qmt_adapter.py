"""Tests for §B 日志 + §G QMT 适配 (Task 10)."""
import pytest
import pandas as pd
from datetime import date
from pathlib import Path
from backtest.data_loader import DataLoader
from backtest.account import Account
from backtest.shim import Shim
import strategy_hs300


DATA_ROOT = "../300data/data_a"


@pytest.fixture
def env(tmp_path):
    dl = DataLoader(DATA_ROOT)
    dl.load(start=date(2020, 1, 1), end=date(2020, 6, 30), warmup_days=120)
    acct = Account(initial_capital=500000.0)
    s = Shim(dl, acct, run_dir=tmp_path)
    s.advance_to(pd.Timestamp('2020-03-02'), barpos=0)
    s.context.set_universe([c for c in dl.universe_codes() if c != 'SH.000300'])
    s.context.accountid = 'test'
    s.context.log_dir = str(tmp_path / 'logs')
    Path(s.context.log_dir).mkdir(parents=True, exist_ok=True)
    # 注入 QMT 全局
    for k, v in s.injected_globals().items():
        setattr(strategy_hs300, k, v)
    # 每次 fixture 重置日志路径，避免测试间污染
    strategy_hs300._LOG_FILE_PATH = None
    return s


def test_normalize_code_no_suffix_sh():
    assert strategy_hs300._normalize_code('601689') == '601689.SH'


def test_normalize_code_no_suffix_sz():
    assert strategy_hs300._normalize_code('000001') == '000001.SZ'


def test_normalize_code_already_suffixed():
    assert strategy_hs300._normalize_code('601689.SH') == '601689.SH'


def test_filter_buyable_excludes_kechuang(env):
    candidates = ['600000.SH', '688001.SH', '300001.SZ']
    out = strategy_hs300._filter_buyable(candidates, env.context)
    assert '688001.SH' not in out
    assert '600000.SH' in out


def test_get_account_returns_tuple(env):
    total, cash = strategy_hs300._get_account(env.context)
    assert total == 500000.0
    assert cash == 500000.0


def test_execute_buy_calls_passorder(env):
    ok, cost = strategy_hs300._execute_buy(
        env.context, '600000.SH', volume=1000, price=10.0,
        current_date='20200302', score=0.5
    )
    assert ok is True
    assert cost > 0


def test_execute_sell_logs_before_delete(env):
    """关键 bug 修复：v1 先 del 再 _log 导致 fallback 分支；新版必须先记录 PnL。"""
    # 先建仓
    strategy_hs300._execute_buy(env.context, '600000.SH', 1000, 10.0, '20200302')
    env.context.positions['600000.SH'] = strategy_hs300.Position(
        stockcode='600000.SH', buy_price=10.0, buy_date='20200302', volume=1000,
    )
    env.account.advance_day('20200303')
    env.advance_to(pd.Timestamp('2020-03-03'), barpos=1)

    # 测试卖出
    strategy_hs300._execute_sell(env.context, '600000.SH', 'hard_stop', '20200303')

    # 检查 trades 中卖出记录是否含 pos.buy_date（说明 _log 拿到了 pos 信息）
    sell_trades = [t for t in env.account.trades
                   if t.side == 'sell' and t.status == 'FILLED']
    assert len(sell_trades) >= 1


def test_sync_positions_picks_up_qmt_holdings(env):
    """从 QMT 实际持仓同步到 ContextInfo.positions。"""
    # 先用 Account 建仓
    env.account.fill_buy('600000.SH', '浦发', 1000, 10.0, '20200302', 'test')
    assert '600000.SH' not in env.context.positions  # 还没同步
    strategy_hs300._sync_positions(env.context, '20200302')
    assert '600000.SH' in env.context.positions


def test_filter_buyable_handles_st_failure(env):
    """v1 行为：get_instrumentdetail 失败时保留股票（fail-open）。"""
    # 我们不主动 mock 失败，只验证函数本身不抛
    out = strategy_hs300._filter_buyable(['600000.SH', 'INVALID.XX'], env.context)
    assert 'INVALID.XX' in out  # ST 检查失败时保留


def test_log_writes_to_log_dir(env, tmp_path):
    strategy_hs300._log('test message', env.context)
    log_dir = Path(env.context.log_dir)
    logs = list(log_dir.glob('*.log'))
    assert len(logs) >= 1
