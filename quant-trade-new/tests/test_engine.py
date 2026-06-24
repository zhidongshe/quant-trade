"""Tests for Engine 主循环 (Task 13)."""
import pytest
from pathlib import Path
from datetime import date
import pandas as pd
from backtest.data_loader import DataLoader
from backtest.account import Account
from backtest.shim import Shim
from backtest.strategy_loader import load_strategy
from backtest.engine import Engine
from backtest.cli import RunConfig


STRATEGY_PATH = Path(__file__).parent.parent / 'strategy_hs300.py'
DATA_ROOT = "../300data/data_a"


def make_config(start, end, tmp_path):
    return RunConfig(
        start_date=start, end_date=end,
        initial_capital=500000.0,
        data_root=DATA_ROOT, results_dir=str(tmp_path),
        commission_rate=0.0001, commission_min=5.0,
        stamp_rate=0.001, transfer_rate=0.00001, slippage_rate=0.0005,
        max_positions=5, rebalance_interval=10, warmup_days=120,
    )


def test_engine_runs_5_days(tmp_path):
    cfg = make_config(date(2020, 3, 1), date(2020, 3, 10), tmp_path)
    dl = DataLoader(cfg.data_root)
    dl.load(cfg.start_date, cfg.end_date, cfg.warmup_days)
    acct = Account(cfg.initial_capital)
    shim = Shim(dl, acct, run_dir=tmp_path)
    strat = load_strategy(STRATEGY_PATH, shim.injected_globals())

    engine = Engine(dl, acct, shim, strat, cfg)
    engine.run()

    # snapshot 数量等于交易日数量（2020-03 区间约 6-7 个）
    assert 5 <= len(acct.snapshots) <= 10


def test_engine_snapshot_equity_starts_at_capital(tmp_path):
    cfg = make_config(date(2020, 3, 1), date(2020, 3, 10), tmp_path)
    dl = DataLoader(cfg.data_root)
    dl.load(cfg.start_date, cfg.end_date, cfg.warmup_days)
    acct = Account(cfg.initial_capital)
    shim = Shim(dl, acct, run_dir=tmp_path)
    strat = load_strategy(STRATEGY_PATH, shim.injected_globals())

    engine = Engine(dl, acct, shim, strat, cfg)
    engine.run()
    # 第一个 snapshot 应在 cfg.start 之后（warmup 早期 strategy_start_date 拦截）
    assert acct.snapshots[0].total_equity <= cfg.initial_capital * 1.05  # 允许略有买入波动


def test_engine_overwrites_strategy_start_date(tmp_path):
    """覆写：strategy.init 设的 today 被 Engine 改为 cfg.start。"""
    cfg = make_config(date(2020, 3, 1), date(2020, 3, 10), tmp_path)
    dl = DataLoader(cfg.data_root)
    dl.load(cfg.start_date, cfg.end_date, cfg.warmup_days)
    acct = Account(cfg.initial_capital)
    shim = Shim(dl, acct, run_dir=tmp_path)
    strat = load_strategy(STRATEGY_PATH, shim.injected_globals())

    engine = Engine(dl, acct, shim, strat, cfg)
    engine.run()
    assert shim.context.strategy_start_date == '20200301'


def test_engine_overwrites_capital(tmp_path):
    cfg = make_config(date(2020, 3, 1), date(2020, 3, 10), tmp_path)
    dl = DataLoader(cfg.data_root)
    dl.load(cfg.start_date, cfg.end_date, cfg.warmup_days)
    acct = Account(cfg.initial_capital)
    shim = Shim(dl, acct, run_dir=tmp_path)
    strat = load_strategy(STRATEGY_PATH, shim.injected_globals())

    engine = Engine(dl, acct, shim, strat, cfg)
    engine.run()
    assert shim.context.capital == 500000.0  # 不是 strategy init 的 100000
