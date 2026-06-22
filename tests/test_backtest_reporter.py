from backtest_v1 import Reporter, Snapshot, Trade
from datetime import datetime
import pandas as pd


def test_write_all_creates_4_files(tmp_path):
    r = Reporter()
    snaps = [Snapshot('2024-01-02', 1000, 1000, 0, []), Snapshot('2024-01-03', 1100, 1100, 0, [])]
    trades = [Trade(datetime(2024,1,3,15), 'SH.600000', '浦发', 'BUY', 10, 100, 1000, 1, 0, 0, 999, '买')]
    hs300 = pd.Series([3000, 3030], index=pd.to_datetime(['2024-01-02', '2024-01-03']))
    r.write_all(str(tmp_path), snaps, trades, hs300, periods=[('2024-01-01', '2024-01-31')])
    assert (tmp_path / 'metrics.csv').exists()
    assert (tmp_path / 'trades.csv').exists()
    assert (tmp_path / 'daily_snapshot.csv').exists()
    assert (tmp_path / 'equity_curve.png').exists()


def test_compute_return_simple():
    snaps = [
        Snapshot('2024-01-02', cash=1000, total_equity=1000, position_count=0, positions=[]),
        Snapshot('2024-12-31', cash=1200, total_equity=1200, position_count=0, positions=[]),
    ]
    r = Reporter()
    metrics = r.compute_metrics(snaps, trades=[], periods=[('2024-01-01', '2024-12-31')])
    assert len(metrics) == 1
    assert abs(metrics[0]['return'] - 0.2) < 1e-6


def test_max_drawdown_known():
    eq = [100, 120, 90, 110, 80, 130]
    snaps = [Snapshot(f'2024-01-0{i+1}', cash=v, total_equity=v, position_count=0, positions=[]) for i, v in enumerate(eq)]
    r = Reporter()
    metrics = r.compute_metrics(snaps, trades=[], periods=[('2024-01-01', '2024-01-06')])
    # 峰 120→谷 80，drawdown = -33.33%
    assert abs(metrics[0]['max_dd'] - (-1/3)) < 0.01


def test_win_rate_fifo_pairing():
    trades = [
        Trade(datetime(2024,1,2,15), 'A', 'a', 'BUY', 10, 100, 1000, 1, 0, 0, 0, '买'),
        Trade(datetime(2024,1,3,15), 'A', 'a', 'SELL', 12, 100, 1200, 1, 0.6, 0, 0, '卖'),  # 赚
        Trade(datetime(2024,1,4,15), 'A', 'a', 'BUY', 12, 100, 1200, 1, 0, 0, 0, '买'),
        Trade(datetime(2024,1,5,15), 'A', 'a', 'SELL', 10, 100, 1000, 1, 0.5, 0, 0, '卖'),  # 亏
    ]
    snaps = [Snapshot('2024-01-01', 10000, 10000, 0, []), Snapshot('2024-01-31', 10000, 10000, 0, [])]
    r = Reporter()
    metrics = r.compute_metrics(snaps, trades=trades, periods=[('2024-01-01', '2024-01-31')])
    assert abs(metrics[0]['win_rate'] - 0.5) < 1e-6
