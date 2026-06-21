from datetime import datetime
from backtest_v1 import BacktestAccount, Position, Order, CostConfig


def test_buy_order_fills_and_deducts_cash():
    acct = BacktestAccount(initial_cash=100_000, cost_config=CostConfig())
    acct.submit_order(Order(
        bar_time=datetime(2024, 1, 2, 14, 55),
        code='SH.600000', side='BUY', volume=1000, reason='信号买入'
    ))
    acct.fill_orders(
        fill_price_provider=lambda code: 9.0,
        stock_name_provider=lambda code: '浦发银行',
        bar_time=datetime(2024, 1, 2, 15, 0),
    )
    assert len(acct.pending_orders) == 0
    assert 'SH.600000' in acct.positions
    pos = acct.positions['SH.600000']
    assert pos.volume == 1000
    # 滑点 0.1% → 实际成交价 9.009；amount = 9009；佣金 = max(9009*0.0003, 5) = 5
    # 沪市过户费 = 9009 * 1e-5 ≈ 0.09
    assert abs(acct.cash - (100_000 - 9009 - 5 - 0.09)) < 0.01
    assert len(acct.trades) == 1


def test_sell_order_releases_cash():
    acct = BacktestAccount(initial_cash=0, cost_config=CostConfig())
    acct.positions['SH.600000'] = __import__('backtest_v1').Position(
        code='SH.600000', volume=1000, open_price=8.0, open_date='2024-01-02', market_value=8000.0
    )
    acct.submit_order(Order(
        bar_time=datetime(2024, 1, 5, 14, 55),
        code='SH.600000', side='SELL', volume=1000, reason='止盈'
    ))
    acct.fill_orders(
        fill_price_provider=lambda code: 10.0,
        stock_name_provider=lambda code: '浦发银行',
        bar_time=datetime(2024, 1, 5, 15, 0),
    )
    # 卖价 10*(1-0.001)=9.99；amount=9990；佣金 max(9990*0.0003,5)=5
    # 印花税 9990*0.0005=4.995；过户费 9990*1e-5≈0.1
    expected_cash = 9990 - 5 - 4.995 - 0.1
    assert abs(acct.cash - expected_cash) < 0.01
    assert 'SH.600000' not in acct.positions


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


def test_snapshot_positions_are_isolated_from_later_mutations():
    acct = BacktestAccount(initial_cash=1_000_000, cost_config=CostConfig())
    pos = Position(code='SH.600000', volume=1000, open_price=9.0,
                   open_date='2024-01-02', market_value=9000.0)
    acct.positions['SH.600000'] = pos
    acct.snapshot('2024-01-02', prices={'SH.600000': 9.0})
    pos.market_value = 99999.0
    acct.snapshot('2024-01-03', prices={'SH.600000': 100.0})
    assert acct.snapshots[0].positions[0].market_value == 9000.0, \
        '第一个 snapshot 的 position 不应被后续 mutation 污染'
    assert acct.snapshots[1].positions[0].market_value == 99999.0
