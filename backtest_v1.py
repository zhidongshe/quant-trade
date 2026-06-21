"""
沪深 300 v1 策略离线回测系统

依赖: numpy / pandas / matplotlib / pytest
入口: python backtest_v1.py [--start ...] [--end ...] [--initial-cash ...] ...
"""

from __future__ import annotations
import argparse
import os
import glob
from datetime import datetime
import dataclasses
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
        self._stock_names_buffer: dict[str, str] = {}

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
            if 'name' in raw.columns and len(raw) > 0:
                self._stock_names_buffer[code] = raw['name'].iloc[0]
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


@dataclass
class CostConfig:
    commission_rate: float = 0.0003
    commission_min: float = 5.0
    stamp_tax_rate: float = 0.0005
    transfer_fee_rate: float = 0.00001
    slippage_pct: float = 0.001


@dataclass
class Position:
    code: str
    volume: int
    open_price: float
    open_date: str
    market_value: float


@dataclass
class Order:
    bar_time: datetime
    code: str
    side: str           # 'BUY' | 'SELL'
    volume: int
    reason: str


@dataclass
class Trade:
    bar_time: datetime
    code: str
    name: str
    side: str
    price: float
    volume: int
    amount: float
    commission: float
    stamp_tax: float
    transfer_fee: float
    cash_after: float
    reason: str


@dataclass
class Snapshot:
    date: str
    cash: float
    total_equity: float
    position_count: int
    positions: list


class BacktestAccount:
    def __init__(self, initial_cash: float, cost_config: CostConfig):
        self.cash = initial_cash
        self.cost_config = cost_config
        self.positions: dict[str, Position] = {}
        self.pending_orders: list[Order] = []
        self.trades: list[Trade] = []
        self.snapshots: list[Snapshot] = []
        # T+1: {code: {buy_date: volume}}
        self.t1_locked: dict[str, dict[str, int]] = {}

    def total_equity(self, prices: dict[str, float]) -> float:
        mv = 0.0
        for code, pos in self.positions.items():
            px = prices.get(code, pos.market_value / pos.volume if pos.volume else 0.0)
            mv += px * pos.volume
        return self.cash + mv

    def snapshot(self, date: str, prices: dict[str, float] | None = None):
        prices = prices or {}
        snap = Snapshot(
            date=date,
            cash=self.cash,
            total_equity=self.total_equity(prices),
            position_count=len(self.positions),
            positions=[dataclasses.replace(p) for p in self.positions.values()],
        )
        self.snapshots.append(snap)

    def submit_order(self, order: Order):
        self.pending_orders.append(order)

    def available_volume(self, code: str) -> int:
        if code not in self.positions:
            return 0
        held = self.positions[code].volume
        locked = sum(self.t1_locked.get(code, {}).values())
        return max(held - locked, 0)

    def advance_day(self, new_date: str):
        """新交易日开始：解锁全部 T+1 持仓"""
        self.t1_locked.clear()

    def fill_orders(self, fill_price_provider, stock_name_provider, is_limit_up_provider, bar_time):
        for order in self.pending_orders:
            if order.volume <= 0:
                continue
            ref_price = fill_price_provider(order.code)
            if ref_price is None or ref_price <= 0:
                self._record_reject(order, 'NO_PRICE', bar_time, stock_name_provider)
                continue
            slip = self.cost_config.slippage_pct
            if order.side == 'BUY':
                if is_limit_up_provider(order.code):
                    self._record_reject(order, 'LIMIT_UP', bar_time, stock_name_provider)
                    continue
                fill_price = ref_price * (1 + slip)
                amount = fill_price * order.volume
                commission = max(amount * self.cost_config.commission_rate, self.cost_config.commission_min)
                transfer_fee = amount * self.cost_config.transfer_fee_rate if order.code.startswith('SH.') else 0.0
                total_out = amount + commission + transfer_fee
                if total_out > self.cash:
                    self._record_reject(order, 'CASH_SHORT', bar_time, stock_name_provider)
                    continue
                self._execute_buy(order, fill_price, amount, commission, 0.0, transfer_fee, bar_time, stock_name_provider)
            else:  # SELL
                avail = self.available_volume(order.code)
                if avail < order.volume:
                    self._record_reject(order, 'VOLUME_SHORT', bar_time, stock_name_provider)
                    continue
                fill_price = ref_price * (1 - slip)
                amount = fill_price * order.volume
                commission = max(amount * self.cost_config.commission_rate, self.cost_config.commission_min)
                stamp_tax = amount * self.cost_config.stamp_tax_rate
                transfer_fee = amount * self.cost_config.transfer_fee_rate if order.code.startswith('SH.') else 0.0
                self._execute_sell(order, fill_price, amount, commission, stamp_tax, transfer_fee, bar_time, stock_name_provider)
        self.pending_orders = []

    def _execute_buy(self, order, fill_price, amount, commission, stamp_tax, transfer_fee, bar_time, name_provider):
        self.cash -= amount + commission + transfer_fee
        if order.code in self.positions:
            old = self.positions[order.code]
            new_vol = old.volume + order.volume
            new_avg = (old.open_price * old.volume + fill_price * order.volume) / new_vol
            old.volume = new_vol
            old.open_price = new_avg
            old.market_value = fill_price * new_vol
        else:
            self.positions[order.code] = Position(
                code=order.code, volume=order.volume, open_price=fill_price,
                open_date=bar_time.strftime('%Y-%m-%d'),
                market_value=fill_price * order.volume,
            )
        # T+1 锁定
        d = bar_time.strftime('%Y-%m-%d')
        self.t1_locked.setdefault(order.code, {})
        self.t1_locked[order.code][d] = self.t1_locked[order.code].get(d, 0) + order.volume
        self._append_trade(order, fill_price, amount, commission, stamp_tax, transfer_fee, bar_time, name_provider)

    def _execute_sell(self, order, fill_price, amount, commission, stamp_tax, transfer_fee, bar_time, name_provider):
        self.cash += amount - commission - stamp_tax - transfer_fee
        pos = self.positions[order.code]
        pos.volume -= order.volume
        if pos.volume <= 0:
            del self.positions[order.code]
        else:
            pos.market_value = fill_price * pos.volume
        self._append_trade(order, fill_price, amount, commission, stamp_tax, transfer_fee, bar_time, name_provider)

    def _append_trade(self, order, fill_price, amount, commission, stamp_tax, transfer_fee, bar_time, name_provider):
        self.trades.append(Trade(
            bar_time=bar_time, code=order.code, name=name_provider(order.code),
            side=order.side, price=fill_price, volume=order.volume,
            amount=amount, commission=commission, stamp_tax=stamp_tax,
            transfer_fee=transfer_fee, cash_after=self.cash, reason=order.reason,
        ))

    def _record_reject(self, order, reason_tag, bar_time, name_provider):
        self.trades.append(Trade(
            bar_time=bar_time, code=order.code, name=name_provider(order.code),
            side=f'{order.side}_REJECTED', price=0.0, volume=order.volume,
            amount=0.0, commission=0.0, stamp_tax=0.0, transfer_fee=0.0,
            cash_after=self.cash, reason=f'{order.reason}|{reason_tag}',
        ))


def timetag_to_datetime(timetag, fmt):
    """将毫秒级时间戳转换为格式化字符串"""
    return datetime.fromtimestamp(timetag / 1000).strftime(fmt)


class QMTShim:
    """仿真 QMT ContextInfo，让 v1 策略不改代码直接跑"""

    def __init__(self, data_loader: DataLoader, account: BacktestAccount):
        self.data_loader = data_loader
        self.account = account

        # v1 用到的 ContextInfo 属性
        self.barpos = -1
        self.last_processed_barpos = -1
        self.accountid = ''
        self.capital = 0.0
        self.positions: dict = {}
        self.persisted_state: dict = {}
        self.last_trade_date = None
        self.rebalance_count = 0
        self.last_rebalance_date = None
        self.ranked_candidates = []
        self.realized_pnl = 0.0
        self.total_cost = 0.0
        self.trading_day_index = 0
        self.market_ok_streak = 0
        self.market_weak_streak = 0
        self.strategy_start_date = ''
        self.daily_sold_records = []
        self.daily_cost = 0.0

        self._universe: set[str] = set()
        self._bar_time: datetime | None = None
        self._bar_timetag_cache: dict[int, int] = {}

        # 从 DataLoader 读取股票名
        self._stock_names: dict[str, str] = getattr(data_loader, '_stock_names_buffer', {})

    def advance_to(self, bar_time: datetime, bar_idx_global: int):
        """推进到指定 bar 时刻；缓存 timetag"""
        self.barpos = bar_idx_global
        self._bar_time = bar_time
        self._bar_timetag_cache[bar_idx_global] = int(bar_time.timestamp() * 1000)

    def get_bar_timetag(self, barpos: int) -> int:
        """获取指定 barpos 的毫秒级时间戳"""
        return self._bar_timetag_cache[barpos]

    def is_last_bar(self) -> bool:
        """日级策略总是最后一根 bar"""
        return True

    def set_universe(self, codes):
        """设置交易宇宙"""
        self._universe = set(codes)

    def set_account(self, acct_id):
        """设置账户 ID"""
        self.accountid = str(acct_id)

    def get_sector(self, name: str):
        """获取行业成分股：所有加载的非指数股票"""
        return [c for c in self.data_loader.list_stocks() if c != 'SH.000300']

    def get_instrumentdetail(self, code: str) -> dict:
        """获取股票详情（前一日 close/limit prices + 名字）"""
        if code not in self.data_loader.daily_df:
            return {}
        df = self.data_loader.daily_df[code]
        if self._bar_time is None:
            return {}
        cur = pd.Timestamp(self._bar_time.date())
        prev_idx = df.index[df.index < cur]
        if len(prev_idx) == 0:
            return {}
        pre_close = df.loc[prev_idx[-1], 'close']
        return {
            'PreClose': pre_close,
            'UpStopPrice': round(pre_close * 1.1, 2),
            'DownStopPrice': round(pre_close * 0.9, 2),
            'InstrumentName': self._stock_names.get(code, code),
        }
