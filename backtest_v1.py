"""
沪深 300 v1 策略离线回测系统

依赖: numpy / pandas / matplotlib / pytest
入口: python backtest_v1.py [--start ...] [--end ...] [--initial-cash ...] ...
"""

from __future__ import annotations
import argparse
import os
import sys
import glob
from datetime import datetime
import dataclasses
from dataclasses import dataclass
import types
import numpy as np
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


def _to_data_code(qmt_code: str) -> str:
    """Convert '600000.SH' → 'SH.600000'.  No-op for already-data-format ('SH.600000') or codes without a suffix."""
    if '.' not in qmt_code:
        return qmt_code
    a, b = qmt_code.split('.', 1)
    if b in ('SH', 'SZ'):  # QMT format NUM.EX
        return b + '.' + a
    return qmt_code  # already data format (EX.NUM)


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
        """获取行业成分股：所有加载的非指数股票，以 QMT 格式返回
        name 参数是 QMT 格式（如 '000300.SH'），用于指定要排除的指数代码
        """
        name_data_code = _to_data_code(name)  # Convert input from QMT to DataLoader format for lookup
        result = []
        for c in self.data_loader.list_stocks():
            if c == name_data_code:  # Skip the index itself
                continue
            if c.startswith('SH.') or c.startswith('SZ.'):
                ex, num = c.split('.', 1)
                result.append(num + '.' + ex)
            else:
                result.append(c)
        return result

    def get_instrumentdetail(self, code: str) -> dict:
        """获取股票详情（前一日 close/limit prices + 名字）。
        code 可以是 QMT 格式（'600000.SH'）或 DataLoader 格式（'SH.600000'）。
        """
        data_code = _to_data_code(code)
        if data_code not in self.data_loader.daily_df:
            return {}
        df = self.data_loader.daily_df[data_code]
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
            'm_strInstrumentName': self._stock_names.get(data_code, code),
        }

    # ------------------------------------------------------------------
    # 核心：partial-day bar + history data (Task 9)
    # ------------------------------------------------------------------

    def _partial_day_bar(self, code: str, day: pd.Timestamp, as_of: datetime, field: str):
        """构建截至 as_of（含）的当日部分 bar 聚合值。
        如果没有该日的 5min 数据则返回 None（调用方回退到纯历史数据）。
        as_of 时刻之后的 bar 严格不包含（防止未来数据泄漏）。
        """
        if code not in self.data_loader.m5_df:
            return None
        m5 = self.data_loader.m5_df[code]
        mask = (m5.index.normalize() == day) & (m5.index <= pd.Timestamp(as_of))
        bars = m5[mask]
        if len(bars) == 0:
            return None
        if field == 'open':
            return float(bars['open'].iloc[0])
        if field == 'high':
            return float(bars['high'].max())
        if field == 'low':
            return float(bars['low'].min())
        if field == 'close':
            return float(bars['close'].iloc[-1])
        if field == 'volume':
            return float(bars['volume'].sum())
        return None

    def get_history_data(self, N, period='1d', field='close',
                         dividend_type='front', skip_paused=True):
        """返回 dict[code, np.ndarray]，共 N 个元素，键为 QMT 格式。
        最后一个元素为当日 partial bar（由 5min 数据聚合，严格不含未来 bar）；
        如无 5min 数据则返回过去 N 日历史。
        """
        if period != '1d':
            raise NotImplementedError(f'period {period!r} not supported; only "1d" is available')
        result = {}
        cur_date = pd.Timestamp(self._bar_time.date())
        cur_time = self._bar_time

        codes = list(self._universe) if self._universe else self.data_loader.list_stocks()
        for code in codes:
            data_code = _to_data_code(code)
            if data_code not in self.data_loader.daily_df:
                continue
            df = self.data_loader.daily_df[data_code]
            past = df.loc[df.index < cur_date]
            col = field if field in past.columns else 'close'
            past_series = past[col]
            # 前复权：对历史数据应用调整因子（当日 partial bar 已是最新价，factor=1.0）
            if dividend_type == 'front':
                past_series = self.data_loader.adjusted(data_code, past_series)
            partial = self._partial_day_bar(data_code, cur_date, cur_time, field)
            if partial is None:
                # 无 5min 数据，只返回历史
                if len(past_series) < N:
                    continue
                arr = past_series.iloc[-N:].to_numpy(dtype=float)
            else:
                full = np.concatenate([past_series.to_numpy(dtype=float), [partial]])
                if len(full) < N:
                    continue
                arr = full[-N:]
            result[code] = arr  # KEY BY ORIGINAL (QMT) code
        return result

    def get_market_data_ex(self, fields, codes, period='1d', start_time=None,
                           end_time=None, count=None, dividend_type='front', fill_data=True):
        """兼容 v1 调用形态；返回 dict[code, pd.DataFrame]，键为 QMT 格式。"""
        result = {}
        cur_date = pd.Timestamp(self._bar_time.date())
        for code in codes:
            data_code = _to_data_code(code)
            if data_code not in self.data_loader.daily_df:
                continue
            df = self.data_loader.daily_df[data_code]
            past = df.loc[df.index < cur_date]
            partial_close = self._partial_day_bar(data_code, cur_date, self._bar_time, 'close')
            if partial_close is not None:
                row = pd.DataFrame({
                    'open':   [self._partial_day_bar(data_code, cur_date, self._bar_time, 'open')],
                    'high':   [self._partial_day_bar(data_code, cur_date, self._bar_time, 'high')],
                    'low':    [self._partial_day_bar(data_code, cur_date, self._bar_time, 'low')],
                    'close':  [partial_close],
                    'volume': [self._partial_day_bar(data_code, cur_date, self._bar_time, 'volume')],
                }, index=[cur_date])
                full = pd.concat([past, row])
            else:
                full = past
            sub = full.tail(count) if count else full
            result[code] = sub[list(fields)] if fields else sub  # KEY BY ORIGINAL (QMT) code
        return result

    def passorder(self, opType, orderType, account, code, prtype, price, volume, *args, **kwargs):
        """Convert v1's passorder call into a BacktestAccount.submit_order(Order).
        opType 23 = BUY, 24 = SELL.
        Reason is extracted from args[2] (the 备注 positional).
        """
        side = 'BUY' if opType == 23 else 'SELL' if opType == 24 else None
        if side is None:
            return
        # v1 的 reason 在 args 里第 3 个参数 ('备注')
        reason = ''
        if len(args) >= 3 and isinstance(args[2], str):
            reason = args[2]
        order = Order(
            bar_time=self._bar_time, code=code, side=side,
            volume=int(volume), reason=reason,
        )
        self.account.submit_order(order)

    def get_trade_detail_data(self, account, account_type, query):
        """Return mock account/position info for v1 compatibility.
        query='ACCOUNT' returns list with one MockAccountInfo (m_dBalance, m_dAvailable).
        query='POSITION' returns list of MockPositionInfo (one per held position).
        Account.positions is now keyed by QMT format; pass through as-is.
        """
        if query == 'ACCOUNT':
            obj = _MockAccountInfo(
                m_dBalance=self.account.cash + sum(p.market_value for p in self.account.positions.values()),
                m_dAvailable=self.account.cash,
            )
            return [obj]
        if query == 'POSITION':
            result = []
            for code, pos in self.account.positions.items():
                avail = self.account.available_volume(code)
                result.append(_MockPositionInfo(
                    m_strInstrumentID=code,  # already QMT format
                    m_nVolume=pos.volume,
                    m_nCanUseVolume=avail,
                    m_dOpenPrice=pos.open_price,
                    m_dMarketValue=pos.market_value,
                ))
            return result
        return []


@dataclass
class _MockAccountInfo:
    m_dBalance: float
    m_dAvailable: float


@dataclass
class _MockPositionInfo:
    m_strInstrumentID: str
    m_nVolume: int
    m_nCanUseVolume: int
    m_dOpenPrice: float
    m_dMarketValue: float


def load_v1_module(path: str, injected_globals: dict) -> types.ModuleType:
    """Load hs300_trend_strategy_single_file_v1.py with injected QMT globals.

    The v1 file may be gbk-encoded for QMT deployment, but locally it's utf-8.
    This loader handles both by trying gbk first, falling back to utf-8.

    Args:
        path: Path to the v1 strategy file
        injected_globals: dict of {name: callable} to inject (e.g., passorder, get_trade_detail_data, etc.)

    Returns:
        Loaded module with injected globals and v1's functions/classes
    """
    # Try gbk first (for QMT-deployed version), fall back to utf-8
    try:
        with open(path, 'r', encoding='gbk') as f:
            source = f.read()
    except (UnicodeDecodeError, LookupError):
        with open(path, 'r', encoding='utf-8') as f:
            source = f.read()

    mod = types.ModuleType('hs300_v1_loaded')
    mod.__file__ = path
    mod.__dict__.update(injected_globals)
    code = compile(source, path, 'exec')
    exec(code, mod.__dict__)
    return mod


class EventLoop:
    """Drives bar advancement for backtesting.

    Iterates over trading days × 5min bars, calling a handler per bar.
    Trading days are derived from a source stock's daily index (default SH.000300).
    """

    def __init__(self, data_loader, shim, account, config, handler,
                 trading_day_source='SH.000300'):
        self.data_loader = data_loader
        self.shim = shim
        self.account = account
        self.config = config
        self.handler = handler
        self.trading_day_source = trading_day_source
        self._global_bar_idx = 0

    def run(self):
        """Iterate trading days and 5min bars, calling handler per bar.
        After each bar: fill pending orders using next bar's close (or current bar if no next).
        After last bar of day: take snapshot using EOD daily closes.
        """
        start = pd.Timestamp(self.config.start_date)
        end = pd.Timestamp(self.config.end_date)
        source_df = self.data_loader.daily_df[self.trading_day_source]
        trading_days = source_df.loc[start:end].index.tolist()

        for day in trading_days:
            ym = day.strftime('%Y-%m')
            self.data_loader.ensure_month_loaded(ym)
            self.account.advance_day(day.strftime('%Y-%m-%d'))

            m5_idx_df = self.data_loader.m5_df.get(self.trading_day_source)
            if m5_idx_df is None:
                continue
            day_bars = m5_idx_df[m5_idx_df.index.normalize() == day]
            bar_list = list(day_bars.index)
            for i, bar_ts in enumerate(bar_list):
                self.shim.advance_to(bar_ts.to_pydatetime(), self._global_bar_idx)
                self.handler(self.shim)
                # fill：用下一根 bar 的 close（若没有下一根=当日末尾→当日收盘价）
                if self.account.pending_orders:
                    next_idx = i + 1
                    if next_idx < len(bar_list):
                        fill_bar_ts = bar_list[next_idx]
                    else:
                        fill_bar_ts = bar_ts  # 当日最后一根：用当前 bar close
                    self._fill_at(fill_bar_ts)
                self._global_bar_idx += 1

            # 收盘 snapshot
            close_prices = self._close_prices_at(day)
            self.account.snapshot(day.strftime('%Y-%m-%d'), close_prices)

    def _fill_at(self, bar_ts: pd.Timestamp):
        def price(code):
            data_code = _to_data_code(code)
            m5 = self.data_loader.m5_df.get(data_code)
            if m5 is None or bar_ts not in m5.index:
                return None
            return float(m5.loc[bar_ts, 'close'])
        def name(code):
            data_code = _to_data_code(code)
            return self.shim._stock_names.get(data_code, code)
        def limit_up(code):
            det = self.shim.get_instrumentdetail(code)  # already accepts QMT
            up = det.get('UpStopPrice')
            if up is None: return False
            cur = price(code)
            return cur is not None and cur >= up * 0.995

        self.account.fill_orders(
            fill_price_provider=price,
            stock_name_provider=name,
            is_limit_up_provider=limit_up,
            bar_time=bar_ts.to_pydatetime(),
        )

    def _close_prices_at(self, day: pd.Timestamp):
        prices = {}
        for data_code, df in self.data_loader.daily_df.items():
            if day in df.index:
                # Convert DataLoader format to QMT format for output dict keys
                if data_code.startswith('SH.') or data_code.startswith('SZ.'):
                    ex, num = data_code.split('.', 1)
                    qmt_code = num + '.' + ex
                else:
                    qmt_code = data_code
                prices[qmt_code] = float(df.loc[day, 'close'])
        return prices


class Reporter:
    def compute_metrics(self, snapshots, trades, periods):
        out = []
        for start, end in periods:
            in_period = [s for s in snapshots if start <= s.date <= end]
            if len(in_period) < 2:
                continue
            equity = np.array([s.total_equity for s in in_period], dtype=float)
            ret = equity[-1] / equity[0] - 1
            n_days = len(in_period)
            ann = (1 + ret) ** (252 / max(n_days, 1)) - 1 if n_days > 0 else 0.0
            # max drawdown
            peak = np.maximum.accumulate(equity)
            dd = (equity - peak) / peak
            max_dd = float(dd.min())
            # sharpe
            daily_ret = np.diff(equity) / equity[:-1]
            if daily_ret.std() > 0:
                sharpe = float(daily_ret.mean() / daily_ret.std() * np.sqrt(252))
            else:
                sharpe = 0.0
            # trade count + win rate（FIFO 配对）
            period_trades = [t for t in trades if start <= t.bar_time.strftime('%Y-%m-%d') <= end]
            buys_count = sum(1 for t in period_trades if t.side == 'BUY')
            win_rate = self._fifo_win_rate(period_trades)

            out.append({
                'period': f'{start} ~ {end}',
                'start_equity': float(equity[0]),
                'end_equity': float(equity[-1]),
                'return': float(ret),
                'ann_return': float(ann),
                'max_dd': max_dd,
                'sharpe': sharpe,
                'trades': buys_count,
                'win_rate': win_rate,
            })
        return out

    def _fifo_win_rate(self, trades):
        from collections import defaultdict, deque
        queues = defaultdict(deque)
        wins = 0
        total = 0
        for t in trades:
            if t.side == 'BUY':
                queues[t.code].append((t.price, t.volume))
            elif t.side == 'SELL':
                remaining = t.volume
                while remaining > 0 and queues[t.code]:
                    buy_price, buy_vol = queues[t.code][0]
                    matched = min(remaining, buy_vol)
                    total += 1
                    if t.price > buy_price:
                        wins += 1
                    remaining -= matched
                    if matched == buy_vol:
                        queues[t.code].popleft()
                    else:
                        queues[t.code][0] = (buy_price, buy_vol - matched)
        return wins / total if total > 0 else 0.0

    def write_all(self, output_dir, snapshots, trades, hs300_close, periods):
        os.makedirs(output_dir, exist_ok=True)
        self.write_metrics(os.path.join(output_dir, 'metrics.csv'), snapshots, trades, periods)
        self.write_trades(os.path.join(output_dir, 'trades.csv'), trades)
        self.write_snapshots(os.path.join(output_dir, 'daily_snapshot.csv'), snapshots)
        self.write_equity_png(os.path.join(output_dir, 'equity_curve.png'), snapshots, hs300_close)

    def write_metrics(self, path, snapshots, trades, periods):
        rows = self.compute_metrics(snapshots, trades, periods)
        df = pd.DataFrame(rows)
        df.to_csv(path, index=False, encoding='utf-8-sig')
        # 同时打印到控制台
        print(df.to_string(index=False))

    def write_trades(self, path, trades):
        rows = [
            {
                'bar_time': t.bar_time.strftime('%Y-%m-%d %H:%M:%S'),
                'code': t.code, 'name': t.name, 'side': t.side,
                'price': t.price, 'volume': t.volume, 'amount': t.amount,
                'commission': t.commission, 'stamp_tax': t.stamp_tax,
                'transfer_fee': t.transfer_fee, 'cash_after': t.cash_after,
                'reason': t.reason,
            }
            for t in trades
        ]
        pd.DataFrame(rows).to_csv(path, index=False, encoding='utf-8-sig')

    def write_snapshots(self, path, snapshots):
        rows = []
        for s in snapshots:
            pos_str = ';'.join(f'{p.code}:{p.volume}@{p.open_price:.2f}' for p in s.positions)
            rows.append({
                'date': s.date, 'cash': s.cash, 'total_equity': s.total_equity,
                'position_count': s.position_count, 'positions': pos_str,
            })
        pd.DataFrame(rows).to_csv(path, index=False, encoding='utf-8-sig')

    def write_equity_png(self, path, snapshots, hs300_close):
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        dates = pd.to_datetime([s.date for s in snapshots])
        equity = np.array([s.total_equity for s in snapshots])
        eq_norm = equity / equity[0]
        hs300_aligned = hs300_close.reindex(dates, method='ffill')
        hs300_norm = hs300_aligned / hs300_aligned.iloc[0]
        # 回撤
        peak = np.maximum.accumulate(equity)
        dd = (equity - peak) / peak
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 7), sharex=True,
                                       gridspec_kw={'height_ratios': [3, 1]})
        ax1.plot(dates, eq_norm, label='Strategy', color='blue')
        ax1.plot(dates, hs300_norm.values, label='HS300', color='gray', alpha=0.7)
        ax1.legend(); ax1.grid(alpha=0.3); ax1.set_title('Equity Curve')
        ax2.fill_between(dates, dd * 100, 0, color='red', alpha=0.4)
        ax2.set_ylabel('Drawdown %'); ax2.grid(alpha=0.3)
        fig.tight_layout()
        fig.savefig(path, dpi=100)
        plt.close(fig)


def _yearly_periods(start: str, end: str) -> list[tuple[str, str]]:
    """按自然年拆分 + 全期合计；首年若不足一年标 'YYYY(MM-MM)'"""
    s = datetime.strptime(start, '%Y-%m-%d')
    e = datetime.strptime(end, '%Y-%m-%d')
    out = []
    cur = s
    while cur.year <= e.year:
        y = cur.year
        y_start = max(cur, datetime(y, 1, 1)).strftime('%Y-%m-%d')
        y_end = min(datetime(y, 12, 31), e).strftime('%Y-%m-%d')
        out.append((y_start, y_end))
        cur = datetime(y + 1, 1, 1)
    out.append((start, end))  # 全期合计
    return out


def main(argv=None):
    cfg = BacktestConfig.from_cli(argv if argv is not None else sys.argv[1:])

    # 1. 数据
    loader = DataLoader(data_root=cfg.data_root)
    loader.load_daily()

    # 2. 账户 + shim
    cost = CostConfig(
        commission_rate=cfg.commission_rate,
        commission_min=cfg.commission_min,
        stamp_tax_rate=cfg.stamp_tax_rate,
        transfer_fee_rate=cfg.transfer_fee_rate,
        slippage_pct=cfg.slippage_pct,
    )
    account = BacktestAccount(initial_cash=cfg.initial_cash, cost_config=cost)
    shim = QMTShim(loader, account)

    # 3. 加载 v1，注入全局
    v1 = load_v1_module(
        'hs300_trend_strategy_single_file_v1.py',
        injected_globals={
            'passorder': shim.passorder,
            'get_trade_detail_data': shim.get_trade_detail_data,
            'get_sector': shim.get_sector,
            'get_instrumentdetail': shim.get_instrumentdetail,
            'timetag_to_datetime': timetag_to_datetime,
        },
    )
    # 回测时禁用历史回放跳过
    v1.SKIP_HISTORY_WARMUP = False

    # 4. v1.init(shim)
    v1.init(shim)

    # 5. EventLoop
    loop = EventLoop(loader, shim, account, cfg, v1.handlebar, trading_day_source='SH.000300')
    loop.run()

    # 6. 报告
    ts_tag = datetime.now().strftime('%Y%m%d_%H%M%S')
    out_dir = os.path.join(cfg.output_dir, f'{ts_tag}_{cfg.start_date}_{cfg.end_date}')
    hs300_close = loader.daily_df['SH.000300']['close']
    periods = _yearly_periods(cfg.start_date, cfg.end_date)
    Reporter().write_all(out_dir, account.snapshots, account.trades, hs300_close, periods)
    print(f'\n✓ 回测结果已落盘: {out_dir}')


if __name__ == '__main__':
    main()
