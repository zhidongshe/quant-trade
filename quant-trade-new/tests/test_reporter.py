import pytest
from pathlib import Path
from datetime import date
from backtest.account import Account, Snapshot, Trade
from backtest.reporter import Reporter
from backtest.cli import RunConfig


def make_config(start, end, tmp_path):
    return RunConfig(
        start_date=start, end_date=end, initial_capital=500000.0,
        data_root='', results_dir=str(tmp_path),
        commission_rate=0.0001, commission_min=5.0,
        stamp_rate=0.001, transfer_rate=0.00001, slippage_rate=0.0005,
        max_positions=5, rebalance_interval=10, warmup_days=120,
    )


def fake_account_with_snapshots(snapshots_data):
    a = Account(initial_capital=500000.0)
    for date_str, equity in snapshots_data:
        a.snapshots.append(Snapshot(
            date=date_str, cash=equity, position_value=0.0,
            total_equity=equity, n_positions=0, daily_return=0.0,
        ))
    return a


def test_single_year_period_label(tmp_path):
    cfg = make_config(date(2020, 1, 1), date(2020, 12, 31), tmp_path)
    a = fake_account_with_snapshots([
        ('20200102', 500000.0), ('20201231', 550000.0)
    ])
    r = Reporter(a, cfg, run_dir=tmp_path)
    periods = r.compute_periods()
    labels = [p.label for p in periods]
    assert '2020' in labels
    assert 'total' in labels


def test_cross_year_periods(tmp_path):
    cfg = make_config(date(2020, 1, 1), date(2021, 12, 31), tmp_path)
    a = fake_account_with_snapshots([
        ('20200102', 500000.0), ('20201231', 550000.0),
        ('20210104', 550000.0), ('20211231', 600000.0),
    ])
    r = Reporter(a, cfg, run_dir=tmp_path)
    periods = r.compute_periods()
    labels = [p.label for p in periods]
    assert '2020' in labels
    assert '2021' in labels
    assert 'total' in labels


def test_partial_year_label(tmp_path):
    cfg = make_config(date(2020, 3, 15), date(2021, 8, 30), tmp_path)
    a = fake_account_with_snapshots([
        ('20200316', 500000.0), ('20201231', 540000.0),
        ('20210104', 540000.0), ('20210830', 600000.0),
    ])
    r = Reporter(a, cfg, run_dir=tmp_path)
    periods = r.compute_periods()
    labels = [p.label for p in periods]
    assert any('2020' in l and '03-15' in l for l in labels)
    assert any('2021' in l and '08-30' in l for l in labels)


def test_avg_holding_days_computed_from_trades(tmp_path):
    """从 buy/sell 配对的持有天数算均值（FIFO）。"""
    cfg = make_config(date(2020, 1, 1), date(2020, 12, 31), tmp_path)
    a = fake_account_with_snapshots([
        ('20200102', 500000.0), ('20201231', 550000.0)
    ])
    a.trades = [
        Trade(trade_id=1, date='20200110', code='SH.600000', name='浦发',
              side='buy', volume=1000, price=10.0, amount=10000.0,
              cost=5.0, reason='buy_signal', status='FILLED'),
        Trade(trade_id=2, date='20200120', code='SH.600000', name='浦发',
              side='sell', volume=1000, price=11.0, amount=11000.0,
              cost=15.0, reason='trailing_stop', status='FILLED', realized_pnl=985.0),
    ]
    r = Reporter(a, cfg, run_dir=tmp_path)
    period = r.compute_periods()[0]  # 2020 行
    m = r.compute_metrics(period)
    assert m['avg_holding_days'] == 10.0  # 2020-01-10 → 2020-01-20


def test_write_all_creates_files(tmp_path):
    cfg = make_config(date(2020, 1, 1), date(2020, 12, 31), tmp_path)
    a = fake_account_with_snapshots([
        ('20200102', 500000.0), ('20201231', 550000.0)
    ])
    r = Reporter(a, cfg, run_dir=tmp_path)
    r.write_all()
    assert (tmp_path / 'metrics.csv').exists()
    assert (tmp_path / 'snapshots.csv').exists()
    assert (tmp_path / 'trades.csv').exists()
    assert (tmp_path / 'equity.png').exists()
    assert (tmp_path / 'run_config.json').exists()
