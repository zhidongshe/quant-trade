from pathlib import Path
import pytest
from datetime import date
import pandas as pd
from backtest.data_loader import DataLoader
from backtest.account import Account
from backtest.shim import Shim
from backtest.strategy_loader import load_strategy


STRATEGY_PATH = Path(__file__).parent.parent / 'strategy_hs300.py'
DATA_ROOT = "../300data/data_a"


def test_loads_strategy_with_injected_globals(tmp_path):
    dl = DataLoader(DATA_ROOT)
    dl.load(start=date(2020, 1, 1), end=date(2020, 6, 30), warmup_days=120)
    acct = Account(initial_capital=500000.0)
    shim = Shim(dl, acct, run_dir=tmp_path)
    mod = load_strategy(STRATEGY_PATH, shim.injected_globals())
    assert hasattr(mod, 'init')
    assert hasattr(mod, 'handlebar')
    assert hasattr(mod, 'Position')


def test_strategy_can_init_via_loader(tmp_path):
    dl = DataLoader(DATA_ROOT)
    dl.load(start=date(2020, 1, 1), end=date(2020, 6, 30), warmup_days=120)
    acct = Account(initial_capital=500000.0)
    shim = Shim(dl, acct, run_dir=tmp_path)
    mod = load_strategy(STRATEGY_PATH, shim.injected_globals())
    mod.init(shim.context)
    assert shim.context.positions == {}


def test_loader_returns_isolated_module(tmp_path):
    """两次加载是独立模块。"""
    dl = DataLoader(DATA_ROOT)
    dl.load(start=date(2020, 1, 1), end=date(2020, 6, 30), warmup_days=120)
    acct = Account(initial_capital=500000.0)
    shim = Shim(dl, acct, run_dir=tmp_path)
    m1 = load_strategy(STRATEGY_PATH, shim.injected_globals())
    m2 = load_strategy(STRATEGY_PATH, shim.injected_globals())
    assert m1 is not m2
