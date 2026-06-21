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
