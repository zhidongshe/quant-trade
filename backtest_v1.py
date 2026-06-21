"""
沪深 300 v1 策略离线回测系统

依赖: numpy / pandas / matplotlib / pytest
入口: python backtest_v1.py [--start ...] [--end ...] [--initial-cash ...] ...
"""

from __future__ import annotations
import argparse
import os
import glob
from dataclasses import dataclass
import pandas as pd


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


class DataLoader:
    def __init__(self, data_root: str = '300data'):
        self.data_root = data_root
        self.daily_df: dict[str, pd.DataFrame] = {}
        self.m5_df: dict[str, pd.DataFrame] = {}  # 后续 task 填
        self._loaded_months: set[str] = set()
        self.adj_factor: dict[str, pd.Series] = {}

    def load_daily(self):
        daily_dir = os.path.join(self.data_root, 'data_a')
        for path in glob.glob(os.path.join(daily_dir, '*_day.txt')):
            code = os.path.basename(path).replace('_day.txt', '')
            raw = pd.read_csv(path)
            raw['time_key'] = pd.to_datetime(raw['time_key'])
            df = raw.set_index('time_key')[['open', 'high', 'low', 'close', 'turnover']]
            df = df.rename(columns={'turnover': 'volume'})
            df = df.sort_index()
            self.daily_df[code] = df
        self.compute_adj_factors()

    def list_stocks(self) -> list[str]:
        return sorted(self.daily_df.keys())

    def ensure_month_loaded(self, year_month: str):
        """加载 year_month（'YYYY-MM'）；释放窗口外（仅保留 current + prev）。"""
        if year_month in self._loaded_months:
            return
        m5_dir = os.path.join(self.data_root, 'data_a_5m')
        pattern = os.path.join(m5_dir, '*_{0}.txt'.format(year_month))
        for path in glob.glob(pattern):
            fname = os.path.basename(path)
            code = fname.rsplit('_', 1)[0]  # 'SH.600000'
            raw = pd.read_csv(path)
            raw['time_key'] = pd.to_datetime(raw['time_key'])
            df = raw.set_index('time_key')[['open', 'high', 'low', 'close', 'turnover']]
            df = df.rename(columns={'turnover': 'volume'}).sort_index()
            if code in self.m5_df:
                self.m5_df[code] = pd.concat([self.m5_df[code], df]).sort_index()
            else:
                self.m5_df[code] = df
        self._loaded_months.add(year_month)
        self._evict_old_months(year_month)

    def _evict_old_months(self, current_ym: str):
        from datetime import datetime
        cur = datetime.strptime(current_ym, '%Y-%m')
        prev_year = cur.year if cur.month > 1 else cur.year - 1
        prev_month = cur.month - 1 if cur.month > 1 else 12
        keep = {current_ym, '{0:04d}-{1:02d}'.format(prev_year, prev_month)}
        for code in list(self.m5_df.keys()):
            df = self.m5_df[code]
            mask = df.index.strftime('%Y-%m').isin(keep)
            self.m5_df[code] = df[mask]
        self._loaded_months = {ym for ym in self._loaded_months if ym in keep}

    def compute_adj_factors(self, jump_threshold: float = 0.08):
        """前复权因子：以最后一日为基准（factor=1.0），向前回推。
        识别除权：相邻日 close 跳变 > jump_threshold（8%）且方向是下跌（送股/现金分红）。
        """
        for code, df in self.daily_df.items():
            closes = df['close']
            n = len(closes)
            factor = pd.Series(1.0, index=closes.index)
            cumulative = 1.0
            for i in range(n - 1, 0, -1):
                today_close = closes.iloc[i]
                prev_close = closes.iloc[i - 1]
                ratio = today_close / prev_close - 1
                if ratio < -jump_threshold:
                    # 疑似除权：用 today_close/prev_close 作为乘数（小于 1）
                    cumulative *= today_close / prev_close
                factor.iloc[i - 1] = cumulative
            self.adj_factor[code] = factor

    def adjusted(self, code: str, series: pd.Series) -> pd.Series:
        """对 series 应用前复权（series.index 必须能在 adj_factor 里找到）"""
        if code not in self.adj_factor:
            return series
        f = self.adj_factor[code].reindex(series.index, method='ffill').fillna(1.0)
        return series * f
