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
