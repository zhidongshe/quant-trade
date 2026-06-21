from backtest_v1 import BacktestConfig

def test_default_values():
    cfg = BacktestConfig()
    assert cfg.data_root == '300data'
    assert cfg.start_date == '2019-09-01'
    assert cfg.end_date == '2025-12-31'
    assert cfg.initial_cash == 1_000_000
    assert cfg.commission_rate == 0.0003

def test_from_cli_overrides():
    cfg = BacktestConfig.from_cli(['--start', '2020-01-01', '--initial-cash', '3000000', '--slippage', '0.0005'])
    assert cfg.start_date == '2020-01-01'
    assert cfg.initial_cash == 3_000_000
    assert cfg.slippage_pct == 0.0005
