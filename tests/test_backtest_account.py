from backtest_v1 import BacktestAccount, Position, CostConfig


def test_initial_state():
    acct = BacktestAccount(initial_cash=1_000_000, cost_config=CostConfig())
    assert acct.cash == 1_000_000
    assert acct.positions == {}
    assert acct.total_equity({}) == 1_000_000


def test_total_equity_with_positions():
    acct = BacktestAccount(initial_cash=500_000, cost_config=CostConfig())
    acct.positions['SH.600000'] = Position(
        code='SH.600000', volume=1000, open_price=9.0, open_date='2024-01-02', market_value=9000.0
    )
    # 取价函数：返回 SH.600000 = 10.0
    prices = {'SH.600000': 10.0}
    assert acct.total_equity(prices) == 500_000 + 10.0 * 1000


def test_snapshot_records_date_and_equity():
    acct = BacktestAccount(initial_cash=1_000_000, cost_config=CostConfig())
    acct.snapshot('2024-01-02', prices={})
    assert len(acct.snapshots) == 1
    snap = acct.snapshots[0]
    assert snap.date == '2024-01-02'
    assert snap.total_equity == 1_000_000
