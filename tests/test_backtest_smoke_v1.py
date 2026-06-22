import os
import pandas as pd
import pytest
from backtest_v1 import main

V1_EXISTS = os.path.exists('hs300_trend_strategy_single_file_v1.py')
DATA_EXISTS = os.path.isdir('300data/data_a') and os.path.isdir('300data/data_a_5m')

@pytest.mark.skipif(not (V1_EXISTS and DATA_EXISTS), reason='缺 v1 或 300data')
def test_smoke_recent_3_months(tmp_path):
    out_dir = str(tmp_path / 'smoke_out')
    main([
        '--start', '2025-10-01', '--end', '2025-12-31',
        '--initial-cash', '1000000',
        '--output-dir', out_dir,
    ])
    # 输出目录应存在，至少一个时间戳子目录
    subs = list(os.listdir(out_dir))
    assert len(subs) == 1
    run_dir = os.path.join(out_dir, subs[0])
    metrics_csv = os.path.join(run_dir, 'metrics.csv')
    trades_csv = os.path.join(run_dir, 'trades.csv')
    assert os.path.exists(metrics_csv)
    assert os.path.exists(trades_csv)
    # trades 数在合理区间（>0 且 < 5000）
    trades_df = pd.read_csv(trades_csv)
    n_real = len(trades_df[~trades_df['side'].str.endswith('_REJECTED')])
    assert 0 < n_real < 5000, f'real trades = {n_real}'
