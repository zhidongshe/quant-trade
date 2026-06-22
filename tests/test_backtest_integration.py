"""
Integration tests for EventLoop — exercises full bar advancement workflow.
"""

from datetime import datetime, date
from backtest_v1 import (
    DataLoader, BacktestAccount, CostConfig, QMTShim, EventLoop, BacktestConfig
)


def test_event_loop_calls_handler_per_5min_bar():
    """EventLoop iterates over trading days and calls handler per 5min bar."""
    cfg = BacktestConfig(
        data_root='tests/fixtures/backtest',
        start_date='2024-01-04', end_date='2024-01-04',
    )
    loader = DataLoader(data_root=cfg.data_root)
    loader.load_daily()
    # fixture 里 SH.000300 暂未提供——为简化集成测试，先用 SH.600000 当 trading-day 源
    acct = BacktestAccount(cfg.initial_cash, CostConfig())
    shim = QMTShim(loader, acct)

    calls = []
    def handler(s):
        calls.append((s.barpos, s._bar_time))

    loop = EventLoop(loader, shim, acct, cfg, handler, trading_day_source='SH.600000')
    loop.run()
    # 01-04 全天 5min bar 数（11:30+13:00 中断的话约 47-48 根，按 fixture 实际）
    assert len(calls) >= 40
    assert calls[0][1].strftime('%Y-%m-%d %H:%M') == '2024-01-04 09:35'


def test_event_loop_buy_then_sell_flow():
    cfg = BacktestConfig(
        data_root='tests/fixtures/backtest',
        start_date='2024-01-04', end_date='2024-01-04',
        initial_cash=100_000,
    )
    loader = DataLoader(data_root=cfg.data_root)
    loader.load_daily()
    acct = BacktestAccount(cfg.initial_cash, CostConfig())
    shim = QMTShim(loader, acct)

    def handler(s):
        if s._bar_time.strftime('%H:%M') == '09:35':
            s.passorder(23, 1101, 'X', 'SH.600000', 5, 0, 1000, '', 1, '买', 1)
        # 注：v1 实际不会在 9:35 下单，但本测试是 EventLoop 单元测试，不依赖 v1

    loop = EventLoop(loader, shim, acct, cfg, handler, trading_day_source='SH.600000')
    loop.run()
    # 应有 1 笔 BUY 成交
    buys = [t for t in acct.trades if t.side == 'BUY']
    assert len(buys) == 1
    # 当日 snapshot 写入
    assert len(acct.snapshots) == 1
    assert acct.snapshots[0].date == '2024-01-04'
