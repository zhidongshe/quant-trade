import pandas as pd
from backtest_v1 import DataLoader

def test_load_daily_returns_dataframe_per_stock():
    loader = DataLoader(data_root='tests/fixtures/backtest')
    loader.load_daily()
    assert 'SH.600000' in loader.daily_df
    df = loader.daily_df['SH.600000']
    assert len(df) == 3
    assert list(df.columns) == ['open', 'high', 'low', 'close', 'volume']
    assert df.index[0] == pd.Timestamp('2024-01-02')
    assert df.loc['2024-01-02', 'close'] == 9.05

def test_list_stocks_includes_loaded():
    loader = DataLoader(data_root='tests/fixtures/backtest')
    loader.load_daily()
    assert 'SH.600000' in loader.list_stocks()

def test_ensure_month_loaded_brings_in_data():
    loader = DataLoader(data_root='tests/fixtures/backtest')
    loader.ensure_month_loaded('2024-01')
    assert 'SH.600000' in loader.m5_df
    df = loader.m5_df['SH.600000']
    assert len(df) == 2
    assert df.index[0] == pd.Timestamp('2024-01-02 09:35:00')

def test_ensure_month_loaded_keeps_current_and_prev_only():
    loader = DataLoader(data_root='tests/fixtures/backtest')
    loader.ensure_month_loaded('2024-01')
    loader.ensure_month_loaded('2024-02')
    loader.ensure_month_loaded('2024-03')
    df = loader.m5_df['SH.600000']
    # 进入 03 月后只保留 02+03
    months_present = sorted(set(df.index.strftime('%Y-%m').unique()))
    assert months_present == ['2024-02', '2024-03']

def test_adj_factor_detects_10_for_10_split(tmp_path):
    # 造一个有 10送10（除权日 close 减半）的 fixture
    p = tmp_path / 'data_a'
    p.mkdir(parents=True)
    csv = p / 'TEST.000001_day.txt'
    csv.write_text(
        "code,name,time_key,high,open,low,close,turnover\n"
        "TEST.000001,T,2024-01-02 00:00:00,20.0,20.0,20.0,20.0,1.0\n"
        "TEST.000001,T,2024-01-03 00:00:00,20.5,20.0,20.0,20.5,1.0\n"
        "TEST.000001,T,2024-01-04 00:00:00,10.3,10.2,10.1,10.25,1.0\n"  # 除权
        "TEST.000001,T,2024-01-05 00:00:00,10.4,10.25,10.2,10.3,1.0\n"
    )
    loader = DataLoader(data_root=str(tmp_path))
    loader.load_daily()
    loader.compute_adj_factors()
    factor = loader.adj_factor['TEST.000001']
    # 除权日及之前的因子应≈0.5，之后≈1.0
    assert abs(factor.loc['2024-01-03'] - 0.5) < 0.01
    assert abs(factor.loc['2024-01-04'] - 1.0) < 0.01

def test_adjusted_smooths_split(tmp_path):
    p = tmp_path / 'data_a'
    p.mkdir(parents=True)
    csv = p / 'TEST.000001_day.txt'
    csv.write_text(
        "code,name,time_key,high,open,low,close,turnover\n"
        "TEST.000001,T,2024-01-02 00:00:00,20.0,20.0,20.0,20.0,1.0\n"
        "TEST.000001,T,2024-01-03 00:00:00,20.5,20.0,20.0,20.5,1.0\n"
        "TEST.000001,T,2024-01-04 00:00:00,10.3,10.2,10.1,10.25,1.0\n"
        "TEST.000001,T,2024-01-05 00:00:00,10.4,10.25,10.2,10.3,1.0\n"
    )
    loader = DataLoader(data_root=str(tmp_path))
    loader.load_daily()
    loader.compute_adj_factors()
    raw = loader.daily_df['TEST.000001']['close']
    adj = loader.adjusted('TEST.000001', raw)
    # 复权后 01-03 应≈10.25（=20.5*0.5），01-04≈10.25，连续无跳变
    assert abs(adj.loc['2024-01-03'] - 10.25) < 0.02
    assert abs(adj.loc['2024-01-04'] - 10.25) < 0.02

def test_load_daily_auto_calls_compute_adj_factors(tmp_path):
    p = tmp_path / 'data_a'
    p.mkdir(parents=True)
    csv = p / 'TEST.000001_day.txt'
    csv.write_text(
        "code,name,time_key,high,open,low,close,turnover\n"
        "TEST.000001,T,2024-01-02 00:00:00,20.0,20.0,20.0,20.0,1.0\n"
        "TEST.000001,T,2024-01-03 00:00:00,20.5,20.0,20.0,20.5,1.0\n"
        "TEST.000001,T,2024-01-04 00:00:00,10.3,10.2,10.1,10.25,1.0\n"
    )
    loader = DataLoader(data_root=str(tmp_path))
    loader.load_daily()
    # compute_adj_factors 应在 load_daily 末尾自动调用
    assert 'TEST.000001' in loader.adj_factor
    assert len(loader.adj_factor['TEST.000001']) == 3
