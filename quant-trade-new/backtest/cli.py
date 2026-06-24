"""CLI 入口与配置合并。"""
import argparse
import yaml
from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class RunConfig:
    start_date: date
    end_date: date
    initial_capital: float
    data_root: str
    results_dir: str
    commission_rate: float
    commission_min: float
    stamp_rate: float
    transfer_rate: float
    slippage_rate: float
    max_positions: int
    rebalance_interval: int
    warmup_days: int


def _parse_date(v):
    if v is None:
        return None
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v))


def load_config(config_path: str | None, cli_overrides: dict) -> RunConfig:
    raw: dict = {}
    if config_path:
        with open(config_path) as f:
            raw = yaml.safe_load(f) or {}
    raw.update({k: v for k, v in cli_overrides.items() if v is not None})

    start = _parse_date(raw.get('start_date'))
    end = _parse_date(raw.get('end_date'))
    if start is None:
        raise ValueError("start_date 必须通过 CLI 或 config 提供")
    if end is None:
        raise ValueError("end_date 必须通过 CLI 或 config 提供")
    if end < start:
        raise ValueError(f"end_date {end} 必须 >= start_date {start}")

    return RunConfig(
        start_date=start, end_date=end,
        initial_capital=float(raw.get('initial_capital', 500000.0)),
        data_root=str(raw.get('data_root', '../300data/data_a')),
        results_dir=str(raw.get('results_dir', 'results')),
        commission_rate=float(raw.get('commission_rate', 0.0001)),
        commission_min=float(raw.get('commission_min', 5.0)),
        stamp_rate=float(raw.get('stamp_rate', 0.001)),
        transfer_rate=float(raw.get('transfer_rate', 0.00001)),
        slippage_rate=float(raw.get('slippage_rate', 0.0005)),
        max_positions=int(raw.get('max_positions', 5)),
        rebalance_interval=int(raw.get('rebalance_interval', 10)),
        warmup_days=int(raw.get('warmup_days', 120)),
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog='backtest')
    p.add_argument('--config', default='configs/default.yaml')
    p.add_argument('--start', type=date.fromisoformat, dest='start')
    p.add_argument('--end', type=date.fromisoformat, dest='end')
    p.add_argument('--capital', type=float, dest='capital')
    p.add_argument('--data-root', dest='data_root')
    p.add_argument('--results-dir', dest='results_dir')
    return p.parse_args(argv)


def build_run_id(start: date, end: date, now: datetime) -> str:
    return f"{start.strftime('%Y%m%d')}-{end.strftime('%Y%m%d')}_{now.strftime('%Y%m%d-%H%M%S')}"


def main():
    ns = parse_args(None)
    overrides = {
        'start_date': ns.start, 'end_date': ns.end,
        'initial_capital': ns.capital,
        'data_root': ns.data_root, 'results_dir': ns.results_dir,
    }
    cfg = load_config(ns.config, overrides)
    print(cfg)


if __name__ == '__main__':
    main()
