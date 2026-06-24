from datetime import date, datetime
from backtest.cli import load_config, parse_args, build_run_id


def test_load_default_config():
    cli_overrides = {'start_date': date(2020, 1, 1), 'end_date': date(2021, 12, 31)}
    cfg = load_config('configs/default.yaml', cli_overrides)
    assert cfg.initial_capital == 500000.0
    assert cfg.commission_rate == 0.0001
    assert cfg.max_positions == 5
    assert cfg.warmup_days == 120


def test_cli_overrides_config():
    cli_overrides = {'start_date': date(2020, 1, 1), 'end_date': date(2021, 12, 31),
                     'initial_capital': 1000000.0}
    cfg = load_config('configs/default.yaml', cli_overrides)
    assert cfg.start_date == date(2020, 1, 1)
    assert cfg.end_date == date(2021, 12, 31)
    assert cfg.initial_capital == 1000000.0  # CLI 覆盖 config


def test_missing_dates_raises():
    import pytest
    with pytest.raises(ValueError, match="start_date"):
        load_config('configs/default.yaml', {})  # 默认 config 里 start/end 都是 null


def test_parse_args_basic():
    ns = parse_args(['--start', '2020-01-01', '--end', '2021-12-31',
                     '--capital', '500000'])
    assert ns.start == date(2020, 1, 1)
    assert ns.end == date(2021, 12, 31)
    assert ns.capital == 500000.0


def test_build_run_id_format():
    now = datetime(2026, 6, 24, 20, 30, 15)
    rid = build_run_id(date(2020, 1, 1), date(2021, 12, 31), now)
    assert rid == "20200101-20211231_20260624-203015"
