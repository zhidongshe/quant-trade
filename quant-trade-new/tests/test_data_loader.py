import pytest
import pandas as pd
from datetime import date
from backtest.data_loader import DataLoader


DATA_ROOT = "../300data/data_a"  # 相对于 quant-trade-new/ 的位置


@pytest.fixture(scope="session")
def loader():
    dl = DataLoader(DATA_ROOT)
    dl.load(start=date(2020, 1, 1), end=date(2020, 12, 31), warmup_days=120)
    return dl


def test_loads_index():
    dl = DataLoader(DATA_ROOT)
    dl.load(start=date(2020, 1, 1), end=date(2020, 12, 31), warmup_days=120)
    assert 'SH.000300' in dl.daily_df


def test_index_dataframe_has_required_columns(loader):
    df = loader.daily_df['SH.000300']
    assert 'close' in df.columns
    assert 'volume' in df.columns
    assert 'open' in df.columns
    assert 'high' in df.columns
    assert 'low' in df.columns


def test_loaded_range_includes_warmup(loader):
    df = loader.daily_df['SH.000300']
    # warmup 120 个交易日 ≈ 半年自然日，至少要覆盖到 2019-08 之前
    assert df.index.min() <= pd.Timestamp('2019-08-01')
    assert df.index.max() >= pd.Timestamp('2020-12-30')


def test_loaded_range_does_not_overshoot_end(loader):
    df = loader.daily_df['SH.000300']
    assert df.index.max() <= pd.Timestamp('2020-12-31')


def test_universe_size_near_300(loader):
    codes = loader.universe_codes()
    assert 295 <= len(codes) <= 305


def test_trading_calendar_in_range(loader):
    cal = loader.trading_calendar()
    assert cal.min() >= pd.Timestamp('2020-01-01')
    assert cal.max() <= pd.Timestamp('2020-12-31')
    # 2020 年大约 243 个交易日
    assert 240 <= len(cal) <= 250


def test_data_quality_log_detects_maotai_2020_glitch():
    """茅台 2020-07-15 → 2020-07-16 跳水 9.01% 应被 data_quality_log 捕获。"""
    dl = DataLoader(DATA_ROOT)
    dl.load(start=date(2020, 7, 1), end=date(2020, 8, 1), warmup_days=120)
    suspicious = [m for m in dl.data_quality_log
                  if 'SH.600519' in m and '2020-07-16' in m]
    assert len(suspicious) >= 1


def test_missing_index_file_raises():
    with pytest.raises(Exception, match=r"SH\.000300|index|指数"):
        dl = DataLoader("/nonexistent/path")
        dl.load(start=date(2020, 1, 1), end=date(2020, 12, 31), warmup_days=120)


def test_warmup_insufficient_raises():
    """请求 start 早于数据最早日期 + warmup，应报错。"""
    dl = DataLoader(DATA_ROOT)
    # 数据最早 2019-06-17，要 120 个交易日 warmup → start 至少 2019-12 左右
    with pytest.raises(Exception, match=r"warmup|start|数据"):
        dl.load(start=date(2019, 7, 1), end=date(2019, 12, 31), warmup_days=120)
