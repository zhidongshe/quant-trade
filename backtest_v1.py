"""
沪深 300 v1 策略离线回测系统

依赖: numpy / pandas / matplotlib / pytest
入口: python backtest_v1.py [--start ...] [--end ...] [--initial-cash ...] ...
"""

from __future__ import annotations
import argparse
from dataclasses import dataclass


@dataclass
class BacktestConfig:
    data_root: str = '300data'
    start_date: str = '2019-09-01'
    end_date: str = '2025-12-31'
    initial_cash: float = 1_000_000
    commission_rate: float = 0.0003
    commission_min: float = 5.0
    stamp_tax_rate: float = 0.0005
    transfer_fee_rate: float = 0.00001
    slippage_pct: float = 0.001
    output_dir: str = 'backtest_results'
    verbose: bool = False

    @classmethod
    def from_cli(cls, argv):
        p = argparse.ArgumentParser()
        p.add_argument('--data-root', default=cls.data_root)
        p.add_argument('--start', dest='start_date', default=cls.start_date)
        p.add_argument('--end', dest='end_date', default=cls.end_date)
        p.add_argument('--initial-cash', type=float, default=cls.initial_cash)
        p.add_argument('--commission-rate', type=float, default=cls.commission_rate)
        p.add_argument('--commission-min', type=float, default=cls.commission_min)
        p.add_argument('--stamp-tax-rate', type=float, default=cls.stamp_tax_rate)
        p.add_argument('--transfer-fee-rate', type=float, default=cls.transfer_fee_rate)
        p.add_argument('--slippage', dest='slippage_pct', type=float, default=cls.slippage_pct)
        p.add_argument('--output-dir', default=cls.output_dir)
        p.add_argument('--verbose', action='store_true', default=cls.verbose)
        ns = p.parse_args(argv)
        return cls(**vars(ns))
