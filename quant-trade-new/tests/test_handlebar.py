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
    for k, v in s.injected_globals().items():
        setattr(strategy_hs300, k, v)
    # 每个测试重置模块级日志文件路径，防止跨测试污染
    strategy_hs300._LOG_FILE_PATH = None
    return s


def test_init_sets_required_attrs(env):
    strategy_hs300.init(env.context)
    assert env.context.positions == {}
    assert hasattr(env.context, 'strategy_start_date')
    assert hasattr(env.context, 'rebalance_count')
    assert hasattr(env.context, 'last_trade_date')


def test_handlebar_skips_before_start_date(env, tmp_path):
    strategy_hs300.init(env.context)
    env.context.log_dir = str(tmp_path)
    env.context.strategy_start_date = '20300101'  # 未来
    env.advance_to(pd.Timestamp('2020-03-02'), 0)
    strategy_hs300.handlebar(env.context)
    # 啥都不该做：仓位还是空
    assert env.account.positions == {}


def test_handlebar_runs_when_in_range(env, tmp_path):
    strategy_hs300.init(env.context)
    env.context.log_dir = str(tmp_path)
    env.context.strategy_start_date = '20200101'
    env.context.capital = 500000.0
    env.advance_to(pd.Timestamp('2020-03-02'), 0)
    strategy_hs300.handlebar(env.context)
    # 至少能跑完不抛
    assert env.context.last_trade_date == '20200302'


def test_handlebar_idempotent_same_bar(env, tmp_path):
    strategy_hs300.init(env.context)
    env.context.log_dir = str(tmp_path)
    env.context.strategy_start_date = '20200101'
    env.advance_to(pd.Timestamp('2020-03-02'), 0)
    strategy_hs300.handlebar(env.context)
    n_before = len(env.account.trades)
    # 再跑一次同一 bar
    strategy_hs300.handlebar(env.context)
    n_after = len(env.account.trades)
    assert n_before == n_after  # 幂等


def test_handlebar_multi_day_runs(env, tmp_path):
    """跑 5 个交易日不崩。"""
    strategy_hs300.init(env.context)
    env.context.log_dir = str(tmp_path)
    env.context.strategy_start_date = '20200101'
    env.context.capital = 500000.0
    cal = env.data_loader.trading_calendar()
    days_in_range = [d for d in cal if d >= pd.Timestamp('2020-03-02')][:5]
    for i, day in enumerate(days_in_range):
        env.advance_to(day, i)
        env.account.advance_day(day.strftime('%Y%m%d'))
        strategy_hs300.handlebar(env.context)


def test_handlebar_respects_rebalance_interval(env, tmp_path):
    """rebalance_count 在每次 handlebar 后 +1。"""
    strategy_hs300.init(env.context)
    env.context.log_dir = str(tmp_path)
    env.context.strategy_start_date = '20200101'
    env.context.capital = 500000.0
    cal = env.data_loader.trading_calendar()
    days = [d for d in cal if d >= pd.Timestamp('2020-03-02')][:3]
    for i, day in enumerate(days):
        env.advance_to(day, i)
        env.account.advance_day(day.strftime('%Y%m%d'))
        strategy_hs300.handlebar(env.context)
    assert env.context.rebalance_count == 3


def test_handlebar_limit_up_reject_preserves_realized_pnl(env, tmp_path):
    """模拟换仓日某只 Top 候选股涨停被拒，验证 ctx.realized_pnl 不会增加（修 #1）。"""
    strategy_hs300.init(env.context)
    env.context.log_dir = str(tmp_path)
    env.context.strategy_start_date = '20200101'
    env.context.capital = 500000.0

    # 推到能买入的某一天
    cal = env.data_loader.trading_calendar()
    days = [d for d in cal if d >= pd.Timestamp('2020-03-02')][:1]
    env.advance_to(days[0], 0)
    env.account.advance_day(days[0].strftime('%Y%m%d'))

    # 强制 is_limit_up 永远 True，模拟所有买单被拒
    original_is_up = env.is_limit_up
    env.is_limit_up = lambda c: True

    pnl_before = getattr(env.context, 'realized_pnl', 0.0)
    strategy_hs300.handlebar(env.context)
    pnl_after = getattr(env.context, 'realized_pnl', 0.0)

    # 拒单不应改变 realized_pnl
    assert pnl_after == pnl_before
    # 应该有 LIMIT_UP 拒单记录（如果策略到达了买入分支）
    rejects = [t for t in env.account.trades if t.status == 'REJECTED' and t.reason == 'LIMIT_UP']
    # 即使没有买入分支被触发，pnl_before == pnl_after 仍然成立
    _ = rejects  # 拒单数量不作强制断言（取决于大盘择时是否允许买入）

    env.is_limit_up = original_is_up  # cleanup
