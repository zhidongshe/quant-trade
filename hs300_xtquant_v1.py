# -*- coding: utf-8 -*-
"""
沪深300多头趋势策略 (xtquant/MiniQMT 版)

从 hs300_online_fafav1test.py (QMT passorder 版) 迁移而来。
核心改进:
  1. passorder → xt_trader.order_stock (有返回值,可查状态)
  2. "发了就忘" → 成交确认机制 (下单后查 order 状态再变更持仓)
  3. bar 驱动 → 定时调度 (每个交易日 14:55 执行)
  4. 黑盒调试 → 本地 Python,可断点

策略逻辑与原版完全一致:
  1. 股票池: 沪深300成分股
  2. 入场: 三因子共振 (60日线上 + 5日>20日 + MACD>0 + 放量)
  3. 卖出: 5%硬止损 / 跌破20日线+MACD衰竭 / 盈利10%后跟踪止盈(回落8%)
  4. 仓位: 最多5只,每只20%

使用方法:
  1. 启动 miniQMT 并登录极简模式
  2. 修改下方 ACCOUNT_ID 和 QMT_PATH
  3. python hs300_xtquant_v1.py          # 跑一次(调试用)
  4. python hs300_xtquant_v1.py --daemon  # 守护模式(每天14:55自动执行)
"""

import os
import sys
import json
import time
import argparse
import numpy as np
from datetime import datetime, timedelta

from xtquant_live.config import load_live_config
from xtquant_live.guards import guard_can_continue_cycle, guard_can_open_new_positions
from xtquant_live.reconcile import classify_buy_outcome, classify_sell_outcome
from xtquant_live.state_paths import build_log_file_path, build_state_file_path

# 当前时间函数(实盘用datetime.now,回测由外部注入)
_now = datetime.now

def set_now_fn(fn):
    """供回测注入自定义时间函数,实盘不需要调用"""
    global _now
    _now = fn

# ==================== 全局配置 ====================

LIVE_CONFIG = load_live_config()
ACCOUNT_ID = LIVE_CONFIG.account_id
QMT_PATH = LIVE_CONFIG.qmt_path

MAX_POSITIONS = 5
HARD_STOP_PCT = 0.05
PROFIT_THRESHOLD = 0.10
TRAILING_PULLBACK_PCT = 0.08
REBALANCE_INTERVAL = 30  # 每30个交易日换仓(约1.5个月,匹配波段周期)
MIN_HOLD_DAYS = 3

# 下单后等成交确认的轮询参数
ORDER_CONFIRM_TIMEOUT = 10   # 等成交的最长秒数
ORDER_CONFIRM_POLL = 0.5      # 轮询间隔秒数

# 守护模式的调度时间
SCHEDULE_TIME = LIVE_CONFIG.schedule_time       # 每天14:55执行

# 卖单价格类型: 0=限价(需price) 5=最新价 6=买一价
# crash_protection 时用5(最新价,跌停时买一为空也能成交)
SELL_PRICE_TYPE_DEFAULT = 6   # 买一价,秒成交
SELL_PRICE_TYPE_CRASH = 5     # 暴跌保护时用最新价

# ==================== 日志模块 ====================

_LOG_FILE_PATH = None

def _init_log():
    global _LOG_FILE_PATH
    ts = _now().strftime('%Y%m%d_%H%M%S')
    _LOG_FILE_PATH = build_log_file_path(LIVE_CONFIG, ts)

def _log(msg):
    timestamp = _now().strftime('%Y-%m-%d %H:%M:%S')
    line = '{0} {1}'.format(timestamp, msg)
    print(line)
    if _LOG_FILE_PATH is None:
        _init_log()
    try:
        with open(_LOG_FILE_PATH, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass

# ==================== 状态持久化 ====================

_STATE_FILE_PATH = build_state_file_path(LIVE_CONFIG)

def _load_state():
    if not os.path.exists(_STATE_FILE_PATH):
        return {}
    try:
        with open(_STATE_FILE_PATH, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            if not content:
                return {}
            data = json.loads(content)
            return data if isinstance(data, dict) else {}
    except Exception as e:
        _log('状态文件读取失败: {0}'.format(e))
        return {}

def _save_state(state):
    tmp_path = _STATE_FILE_PATH + '.tmp'
    try:
        data_str = json.dumps(state, ensure_ascii=False)
    except Exception as e:
        _log('状态文件序列化失败: {0}'.format(e))
        return False
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            f.write(data_str)
            f.flush()
            os.fsync(f.fileno())
    except Exception as e:
        _log('状态文件 tmp 写入失败: {0}'.format(e))
        return False
    for attempt in range(3):
        try:
            os.replace(tmp_path, _STATE_FILE_PATH)
            return True
        except OSError:
            if attempt < 2:
                time.sleep(0.05 * (attempt + 1))
    try:
        with open(_STATE_FILE_PATH, 'w', encoding='utf-8') as f:
            f.write(data_str)
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        return True
    except Exception as e:
        _log('状态文件写入失败: {0}'.format(e))
        return False

# ==================== 指标计算 (与原版完全一致) ====================

def sma(prices, period):
    if len(prices) < period:
        return np.full_like(prices, np.nan, dtype=float)
    result = np.full_like(prices, np.nan, dtype=float)
    cumsum = np.cumsum(np.insert(prices, 0, 0))
    result[period - 1:] = (cumsum[period:] - cumsum[:-period]) / period
    return result

def macd(prices, fast=12, slow=26, signal=9):
    def _ema(data, period):
        alpha = 2.0 / (period + 1)
        result = np.zeros_like(data, dtype=float)
        result[0] = data[0]
        for i in range(1, len(data)):
            result[i] = alpha * data[i] + (1 - alpha) * result[i - 1]
        return result
    ema_fast = _ema(prices, fast)
    ema_slow = _ema(prices, slow)
    dif = ema_fast - ema_slow
    dea = _ema(dif, signal)
    hist = dif - dea
    return dif, dea, hist

def check_buy_signal(prices, volumes):
    if len(prices) < 70 or len(volumes) < 20:
        return False
    ma60 = sma(prices, 60)
    if np.isnan(ma60[-1]) or prices[-1] <= ma60[-1]:
        return False
    ma5 = sma(prices, 5)
    ma20 = sma(prices, 20)
    if np.isnan(ma5[-1]) or np.isnan(ma20[-1]) or ma5[-1] <= ma20[-1]:
        return False
    dif, dea, hist = macd(prices)
    if hist[-1] <= 0:
        return False
    if len(hist) >= 3 and hist[-1] <= hist[-2]:
        return False
    if len(prices) >= 2 and prices[-1] <= prices[-2] * 1.01:
        return False
    vol_ma20 = sma(volumes.astype(float), 20)
    if np.isnan(vol_ma20[-1]) or volumes[-1] <= vol_ma20[-1]:
        return False
    return True

def score_stock(prices, volumes):
    if not check_buy_signal(prices, volumes):
        return None
    price = prices[-1]
    ma60 = sma(prices, 60)
    trend_score = (price - ma60[-1]) / ma60[-1]
    ma5 = sma(prices, 5)
    ma20 = sma(prices, 20)
    ma_spread_score = (ma5[-1] - ma20[-1]) / ma20[-1]
    dif, dea, hist = macd(prices)
    macd_score = hist[-1] / ma20[-1]
    vol_ma20 = sma(volumes.astype(float), 20)
    ratio = volumes[-1] / vol_ma20[-1] if vol_ma20[-1] > 0 else 1.0
    volume_score = np.log(max(ratio, 0.01))
    return {
        'trend_score': trend_score,
        'ma_spread_score': ma_spread_score,
        'macd_score': macd_score,
        'volume_score': volume_score,
    }

# ==================== 持仓管理 (与原版一致) ====================

class Position:
    def __init__(self, stockcode, buy_price, buy_date, volume, buy_trading_day_idx=0):
        self.stockcode = stockcode
        self.buy_price = buy_price
        self.buy_date = buy_date
        self.volume = volume
        self.highest_price = buy_price
        self.buy_trading_day_idx = buy_trading_day_idx

def check_stop_loss(pos, current_price):
    return current_price <= pos.buy_price * (1 - HARD_STOP_PCT)

def check_trend_break(current_price, ma20):
    return current_price <= ma20

def check_trailing_stop(pos, current_price):
    if current_price > pos.highest_price:
        pos.highest_price = current_price
    max_profit_pct = (pos.highest_price - pos.buy_price) / pos.buy_price
    if max_profit_pct <= PROFIT_THRESHOLD:
        return False
    return current_price <= pos.highest_price * (1 - TRAILING_PULLBACK_PCT)

def calculate_buy_amount(total_assets, available_cash):
    target_per_stock = total_assets / MAX_POSITIONS
    return min(target_per_stock, available_cash)

# ==================== xtquant 交易层 (替代 passorder) ====================

from xtquant.xttrader import XtQuantTrader
from xtquant.xttype import StockAccount
from xtquant import xtdata
from xtquant import xtconstant

class Trader:
    """封装 xtquant 交易接口,替代原版的 passorder + get_trade_detail_data"""

    def __init__(self, path, account_id):
        self.path = path
        self.account_id = account_id
        self.session_id = int(time.time())
        self.xt_trader = None
        self.account = None
        self._connected = False

    def connect(self):
        """连接 miniQMT 终端"""
        self.xt_trader = XtQuantTrader(self.path, self.session_id)
        self.xt_trader.start()
        result = self.xt_trader.connect()
        if result != 0:
            _log('连接 miniQMT 失败,错误码: {0}'.format(result))
            return False
        self.account = StockAccount(self.account_id, 'STOCK')
        sub_result = self.xt_trader.subscribe(self.account)
        if sub_result != 0:
            _log('账户订阅失败,错误码: {0}'.format(sub_result))
            return False
        self._connected = True
        _log('miniQMT 连接成功,账号: {0}'.format(self.account_id))
        return True

    def disconnect(self):
        if self.xt_trader:
            self.xt_trader.stop()
            self._connected = False
            _log('miniQMT 已断开')

    @property
    def connected(self):
        return self._connected

    # ---- 查询接口 ----

    def get_asset(self):
        """查账户资产,返回 (总资产, 可用现金, 持仓市值, 冻结资金) 或 None"""
        if not self._connected:
            return None
        try:
            asset = self.xt_trader.query_stock_asset(self.account)
            if asset:
                return (float(asset.total_asset), float(asset.cash),
                        float(asset.market_value), float(asset.frozen_cash))
        except Exception as e:
            _log('查资产异常: {0}'.format(e))
        return None

    def get_positions(self):
        """查持仓,返回 {code: {volume, can_use, open_price, market_value}} 或 None"""
        if not self._connected:
            return None
        try:
            positions = self.xt_trader.query_stock_positions(self.account)
            result = {}
            if positions:
                for p in positions:
                    code = p.stock_code
                    vol = int(p.volume)
                    if vol > 0:
                        result[code] = {
                            'volume': vol,
                            'can_use': int(p.can_use_volume),
                            'open_price': float(p.open_price),
                            'market_value': float(getattr(p, 'market_value', 0)),
                        }
            return result
        except Exception as e:
            _log('查持仓异常: {0}'.format(e))
        return None

    def get_orders(self):
        """查当日委托,返回列表"""
        if not self._connected:
            return []
        try:
            return self.xt_trader.query_stock_orders(self.account) or []
        except Exception as e:
            _log('查委托异常: {0}'.format(e))
            return []

    def get_trades(self):
        """查当日成交,返回列表"""
        if not self._connected:
            return []
        try:
            return self.xt_trader.query_stock_trades(self.account) or []
        except Exception as e:
            _log('查成交异常: {0}'.format(e))
            return []

    # ---- 下单接口 ----

    def buy(self, stockcode, volume, price=None, price_type=5):
        """买入下单
        price_type: 5=最新价 6=买一价(卖单用) 11=限价(需price)
        返回 (success, order_id)
        """
        if not self._connected:
            return False, None
        try:
            order_id = self.xt_trader.order_stock(
                self.account,
                stockcode,
                xtconstant.STOCK_BUY,
                volume,
                price_type,
                price if price else -1.0,
                'hs300_xt',
                ''
            )
            _log('[buy] {0} {1}股 price_type={2} order_id={3}'.format(
                stockcode, volume, price_type, order_id))
            return True, order_id
        except Exception as e:
            _log('!! 买入失败: {0} | {1}'.format(stockcode, e))
            return False, None

    def sell(self, stockcode, volume, price=None, price_type=6):
        """卖出下单
        price_type: 6=买一价(默认,秒成交) 5=最新价(暴跌时用)
        返回 (success, order_id)
        """
        if not self._connected:
            return False, None
        try:
            order_id = self.xt_trader.order_stock(
                self.account,
                stockcode,
                xtconstant.STOCK_SELL,
                volume,
                price_type,
                price if price else -1.0,
                'hs300_xt',
                ''
            )
            _log('[sell] {0} {1}股 price_type={2} order_id={3}'.format(
                stockcode, volume, price_type, order_id))
            return True, order_id
        except Exception as e:
            _log('!! 卖出失败: {0} | {1}'.format(stockcode, e))
            return False, None

    def wait_order_filled(self, order_id, timeout=ORDER_CONFIRM_TIMEOUT):
        """等某笔订单成交确认,返回 True=已成交 False=超时/未成交"""
        if not order_id:
            return False
        deadline = time.time() + timeout
        while time.time() < deadline:
            orders = self.get_orders()
            for o in orders:
                if str(getattr(o, 'order_id', '')) == str(order_id):
                    status = getattr(o, 'status', -1)
                    # xtconstant: ORDER_ACCEPTED=48 ORDER_FILLED=50 ORDER_CANCELED=52
                    if status == 50:  # 已成交
                        return True
                    if status == 52:  # 已撤单/废单
                        _log('订单 {0} 状态={1}(已撤/废单)'.format(order_id, status))
                        return False
            time.sleep(ORDER_CONFIRM_POLL)
        _log('订单 {0} 等成交超时{1}s'.format(order_id, timeout))
        return False

    # ---- 行情接口 ----

    @staticmethod
    def get_sector(sector_code):
        """获取板块成分股,替代 QMT 的 get_sector"""
        try:
            return xtdata.get_stock_list_in_sector(sector_code)
        except Exception as e:
            _log('获取板块 {0} 失败: {1}'.format(sector_code, e))
            return []

    @staticmethod
    def get_history_data(stockcodes, count, period='1d', field='close'):
        """获取历史数据,替代 QMT 的 get_history_data
        返回 {code: np.array(prices)} 或 {}
        """
        if isinstance(stockcodes, str):
            stockcodes = [stockcodes]

        result = {}
        for code in stockcodes:
            try:
                # 确保本地有数据
                xtdata.download_history_data(code, period, '', '')
                data = xtdata.get_local_data([], [code], period=period, count=count)
                if code in data and len(data[code]) > 0:
                    df = data[code]
                    if field in df.columns:
                        result[code] = np.array(df[field].values, dtype=float)
                    elif hasattr(df, field):
                        result[code] = np.array(getattr(df, field).values, dtype=float)
            except Exception as e:
                pass  # 静默跳过,个别股票数据缺失不影响整体
        return result

    @staticmethod
    def get_history_data_multi(stockcodes, count, period='1d'):
        """一次性获取多只股票的 close 和 volume,减少调用次数"""
        closes = {}
        volumes = {}
        for code in stockcodes:
            try:
                xtdata.download_history_data(code, period, '', '')
                data = xtdata.get_local_data([], [code], period=period, count=count)
                if code in data and len(data[code]) > 0:
                    df = data[code]
                    if 'close' in df.columns:
                        closes[code] = np.array(df['close'].values, dtype=float)
                    if 'volume' in df.columns:
                        volumes[code] = np.array(df['volume'].values, dtype=float)
            except Exception:
                pass
        return closes, volumes

    @staticmethod
    def get_instrument_detail(code):
        """获取合约信息,替代 QMT 的 get_instrumentdetail"""
        try:
            return xtdata.get_instrument_detail(code)
        except Exception:
            return None

# ==================== 策略主体 ====================

class Strategy:
    """策略状态容器,替代原版的 ContextInfo"""

    def __init__(self, trader):
        self.trader = trader
        self.positions = {}
        self.capital = 100000
        self.trading_day_index = 0
        self.rebalance_count = 0
        self.last_rebalance_date = None
        self.market_ok_streak = 0
        self.market_weak_streak = 0
        self.ranked_candidates = []
        self.daily_sold_records = []
        self.state = _load_state()
        self.state.setdefault('pending_orders', {})
        self.state.setdefault('manual_review_flags', [])

        # 从持久化恢复
        self.trading_day_index = int(self.state.get('trading_day_index', 0))
        self.rebalance_count = int(self.state.get('rebalance_count', 0))
        self.market_ok_streak = int(self.state.get('market_ok_streak', 0))
        self.market_weak_streak = int(self.state.get('market_weak_streak', 0))
        self.last_trade_date = self.state.get('last_processed_trade_date')

        # 读初始资金
        asset = self.trader.get_asset()
        if asset:
            self.capital = asset[0]

        # 恢复持仓
        self._sync_positions()

    def _sync_positions(self):
        """从 broker 同步持仓"""
        broker_pos = self.trader.get_positions()
        if broker_pos is None:
            return

        meta_all = self.state.get('positions_meta', {})

        # broker 有但我们没记录的 → 补录
        for code, info in broker_pos.items():
            if code not in self.positions:
                m = meta_all.get(code, {})
                fallback_buy = info['open_price'] if info['open_price'] > 0 else 1.0
                pos = Position(
                    stockcode=code,
                    buy_price=float(m.get('buy_price', fallback_buy)),
                    buy_date=m.get('buy_date', _now().strftime('%Y%m%d')),
                    volume=info['volume'],
                    buy_trading_day_idx=int(m.get('buy_trading_day_idx', 0)),
                )
                if 'highest_price' in m:
                    pos.highest_price = max(float(m['highest_price']), pos.buy_price)
                self.positions[code] = pos
                _log('同步持仓: {0} {1}股 | buy_date={2} highest={3:.2f}'.format(
                    code, info['volume'], pos.buy_date, pos.highest_price))

        # broker 没有但我们记录的 → 清除
        for code in list(self.positions.keys()):
            if code not in broker_pos:
                _log('清除失效持仓: {0}'.format(code))
                del self.positions[code]

    def _record_pending_order(self, side, stockcode, volume, order_id, current_date):
        key = '{0}:{1}'.format(side, stockcode)
        self.state.setdefault('pending_orders', {})[key] = {
            'side': side,
            'stockcode': stockcode,
            'volume': int(volume),
            'order_id': str(order_id),
            'trade_date': current_date,
        }

    def _clear_pending_order(self, side, stockcode):
        key = '{0}:{1}'.format(side, stockcode)
        self.state.setdefault('pending_orders', {}).pop(key, None)

    def _confirm_buy_and_sync(self, stockcode, requested_volume, order_id, current_date):
        before_positions = self.trader.get_positions() or {}
        filled = self.trader.wait_order_filled(order_id, timeout=ORDER_CONFIRM_TIMEOUT)
        after_positions = self.trader.get_positions() or {}
        outcome = classify_buy_outcome(stockcode, requested_volume, before_positions, after_positions)
        self._sync_positions()
        if filled or outcome in ('filled', 'partial'):
            self._clear_pending_order('buy', stockcode)
            return True, outcome
        self.state.setdefault('manual_review_flags', []).append({
            'side': 'buy',
            'stockcode': stockcode,
            'order_id': str(order_id),
            'trade_date': current_date,
            'outcome': outcome,
        })
        return False, outcome

    def _confirm_sell_and_sync(self, stockcode, requested_volume, order_id, current_date):
        before_positions = self.trader.get_positions() or {}
        filled = self.trader.wait_order_filled(order_id, timeout=ORDER_CONFIRM_TIMEOUT)
        after_positions = self.trader.get_positions() or {}
        outcome = classify_sell_outcome(stockcode, requested_volume, before_positions, after_positions)
        self._sync_positions()
        if filled or outcome in ('filled', 'partial'):
            self._clear_pending_order('sell', stockcode)
            return True, outcome
        self.state.setdefault('manual_review_flags', []).append({
            'side': 'sell',
            'stockcode': stockcode,
            'order_id': str(order_id),
            'trade_date': current_date,
            'outcome': outcome,
        })
        return False, outcome

    def _can_continue_cycle(self):
        allowed, reason = guard_can_continue_cycle(self.trader.get_asset(), self.trader.get_positions())
        self.state['cycle_guard_reason'] = reason
        return allowed

    def _can_open_new_positions(self, history_ok):
        allowed, reason = guard_can_open_new_positions(self.trader.get_asset(), self.trader.get_positions(), history_ok)
        self.state['buy_block_reason'] = reason
        return allowed

    def _check_market_trend(self, idx_prices):
        """判断大盘是否在上升趋势"""
        if idx_prices is None or len(idx_prices) < 20:
            return False
        if len(idx_prices) >= 2:
            daily_change = (idx_prices[-1] - idx_prices[-2]) / idx_prices[-2]
            if daily_change <= -0.03:
                return False
        ma20 = np.mean(idx_prices[-20:])
        dif, dea, hist = macd(np.array(idx_prices, dtype=float))
        return idx_prices[-1] > ma20 and hist[-1] > 0

    def _filter_st_stocks(self, universe):
        """过滤ST股"""
        filtered = []
        for code in universe:
            try:
                detail = self.trader.get_instrument_detail(code)
                if detail and 'ST' in detail.get('InstrumentName', ''):
                    continue
            except Exception:
                pass
            filtered.append(code)
        return filtered

    def _is_limit_up_today(self, code, hist_prices):
        """检查是否当天涨停(涨幅>9%视为涨停,过滤掉买不进的票)"""
        if code not in hist_prices or len(hist_prices[code]) < 2:
            return False
        prices = hist_prices[code]
        today_close = float(prices[-1])
        yesterday_close = float(prices[-2])
        if yesterday_close <= 0:
            return False
        return today_close > yesterday_close * 1.09

    @staticmethod
    def _only_mainboard(universe):
        """只保留主板股票(600和000开头)"""
        return [c for c in universe if c.startswith('600') or c.startswith('000')]

    def run_once(self):
        """执行一次策略(相当于原版的 handlebar)"""
        self._crash_day = False  # 重置暴跌标志
        current_date = _now().strftime('%Y%m%d')
        current_time = _now().strftime('%H:%M:%S')

        _log('[{0}] {1} 策略启动'.format(current_date, current_time))

        # 幂等: 同一天只执行一次
        if self.last_trade_date == current_date:
            _log('[{0}] 跳过已处理的交易日'.format(current_date))
            return

        # 更新 broker 持仓
        self._sync_positions()
        if not self._can_continue_cycle():
            _log('[{0}] 关键查询失败，终止本轮执行'.format(current_date))
            self._save_and_exit(current_date)
            return

        # 交易日计数 + 换仓日判断
        self.trading_day_index += 1
        self.rebalance_count += 1
        is_rebalance_day = (self.rebalance_count >= REBALANCE_INTERVAL)
        holdings = list(self.positions.keys())

        # 1. 更新股票池
        universe = self.trader.get_sector('沪深300')
        if not universe:
            _log('[{0}] 警告: 无法获取沪深300成分股'.format(current_date))
            self._save_and_exit(current_date)
            return

        # 过滤: 只排除创业板(300/301)和科创板(688) + ST
        buy_universe = [c for c in self._filter_st_stocks(universe)
                        if c != '000300.SH'
                        and not c.startswith('688')
                        and not c.startswith('300')
                        and not c.startswith('301')]

        # 2. 获取历史数据(一次性获取 close + volume)
        all_codes = list(set(buy_universe + holdings + ['000300.SH']))
        hist_prices, hist_volumes = self.trader.get_history_data_multi(all_codes, 70, '1d')

        # 大盘择时
        idx_prices = None
        if '000300.SH' in hist_prices and len(hist_prices['000300.SH']) >= 70:
            idx_prices = hist_prices['000300.SH']
        market_ok = self._check_market_trend(idx_prices)
        if market_ok:
            self.market_ok_streak += 1
            self.market_weak_streak = 0
        else:
            self.market_ok_streak = 0
            self.market_weak_streak += 1

        market_str = "大盘OK({0}天)".format(self.market_ok_streak) if market_ok else "大盘弱({0}天)".format(self.market_weak_streak)
        _log('[{0}] ===== 日期: {0} | 开盘持仓: {1}只 | {2} | 距下次换仓: {3}天 ====='.format(
            current_date, len(holdings), market_str,
            REBALANCE_INTERVAL - self.rebalance_count))

        # 3. 检查止损/止盈
        positions_to_sell = []
        for stockcode, pos in list(self.positions.items()):
            if stockcode not in hist_prices or len(hist_prices[stockcode]) < 1:
                continue
            prices_list = hist_prices[stockcode]
            current_price = float(prices_list[-1])
            if current_price > pos.highest_price:
                pos.highest_price = current_price

            if len(prices_list) < 20:
                if check_stop_loss(pos, current_price):
                    positions_to_sell.append((stockcode, 'hard_stop'))
                continue

            prices_arr = np.array(prices_list)
            ma20 = np.mean(prices_arr[-20:])
            dif, dea, hist = macd(prices_arr)
            hold_days = self.trading_day_index - pos.buy_trading_day_idx

            should_sell = False
            sell_reason = ''

            if check_stop_loss(pos, current_price):
                should_sell = True
                sell_reason = 'hard_stop'
            elif len(prices_list) >= 2:
                prev_price = float(prices_list[-2])
                daily_change = (current_price - prev_price) / prev_price if prev_price > 0 else 0
                if daily_change <= -0.07:
                    should_sell = True
                    sell_reason = 'crash_protection'

            macd_weakening = (hist[-1] <= 0) and (len(hist) >= 2) and (hist[-1] <= hist[-2])
            if not should_sell:
                if check_trend_break(current_price, ma20) and macd_weakening:
                    should_sell = True
                    sell_reason = 'trend_break'
                elif check_trailing_stop(pos, current_price):
                    should_sell = True
                    sell_reason = 'trailing_stop'

            if should_sell:
                pnl_pct = (current_price - pos.buy_price) / pos.buy_price * 100
                _log('[{0}] 触发卖出: {1} | 原因: {2} | 持有{3}天 | 买价: {4:.2f} | 现价: {5:.2f} | 盈亏: {6:+.2f}%'.format(
                    current_date, stockcode, sell_reason, hold_days, pos.buy_price, current_price, pnl_pct))
                positions_to_sell.append((stockcode, sell_reason))

        # 大盘连续弱2天,清仓非强势股
        if self.market_weak_streak >= 2:
            already_marked = {s for s, _ in positions_to_sell}
            for stockcode, pos in list(self.positions.items()):
                if stockcode in already_marked:
                    continue
                max_profit_pct = (pos.highest_price - pos.buy_price) / pos.buy_price
                if max_profit_pct <= PROFIT_THRESHOLD:
                    positions_to_sell.append((stockcode, 'market_weak'))
                    _log('[{0}] 大盘连续弱{1}天,清仓: {2} | 最高盈利{3:+.2f}%'.format(
                        current_date, self.market_weak_streak, stockcode, max_profit_pct * 100))

        # 4. 执行卖出 (带成交确认)
        # 当日已卖清单: 仅在同一天生效, 跨日清空
        # (防止卖出过的股票永远进黑名单导致策略瘫痪)
        if self.state.get('sold_today_date') == current_date:
            sold_today = set(self.state.get('sold_today_set', []))
        else:
            sold_today = set()
            self.state['sold_today_set'] = []
            self.state['sold_today_date'] = current_date
        for stockcode, reason in positions_to_sell:
            if stockcode in sold_today:
                _log('[{0}] 跳过重复卖出: {1}'.format(current_date, stockcode))
                continue

            pos = self.positions.get(stockcode)
            if pos is None:
                continue

            # 卖出价类型: crash_protection 用最新价(跌停时买一为空)
            price_type = SELL_PRICE_TYPE_CRASH if reason == 'crash_protection' else SELL_PRICE_TYPE_DEFAULT

            success, order_id = self.trader.sell(stockcode, pos.volume, price_type=price_type)
            if not success:
                _log('[{0}] !! 卖出被拒: {1} | order_id={2} | 保留持仓'.format(
                    current_date, stockcode, order_id))
                continue

            self._record_pending_order('sell', stockcode, pos.volume, order_id, current_date)
            confirmed, outcome = self._confirm_sell_and_sync(stockcode, pos.volume, order_id, current_date)
            if confirmed and stockcode not in self.positions:
                sell_price = float(hist_prices[stockcode][-1]) if stockcode in hist_prices else pos.buy_price
                realized = (sell_price - pos.buy_price) * pos.volume
                _log('[{0}] << 卖出确认: {1} | {2}股 | 原因: {3} | 盈亏: {4:+.0f}元 | {5}'.format(
                    current_date, stockcode, pos.volume, reason, realized, outcome))
                self.daily_sold_records.append({
                    'stockcode': stockcode, 'volume': pos.volume,
                    'buy_price': pos.buy_price, 'sell_price': sell_price,
                    'reason': reason, 'buy_date': pos.buy_date,
                })
                sold_today.add(stockcode)
                if reason == 'crash_protection':
                    self._crash_day = True
            else:
                _log('[{0}] !! 卖出待人工检查: {1} | order_id={2} | {3}'.format(
                    current_date, stockcode, order_id, outcome))

        # 5. 打分(过滤涨停票)
        candidates = []
        limit_up_count = 0
        for stockcode in buy_universe:
            if stockcode not in hist_prices or len(hist_prices[stockcode]) < 70:
                continue
            if stockcode not in hist_volumes or len(hist_volumes[stockcode]) < 20:
                continue
            # 过滤当天涨停的票(买不进,浪费slot)
            if self._is_limit_up_today(stockcode, hist_prices):
                limit_up_count += 1
                continue
            factors = score_stock(np.array(hist_prices[stockcode]), np.array(hist_volumes[stockcode]))
            if factors is not None:
                candidates.append((stockcode, factors))

        if limit_up_count > 0:
            _log('[{0}] 涨停过滤: {1}只涨停票跳过'.format(current_date, limit_up_count))

        scored = []
        if candidates:
            do_normalize = len(candidates) >= 5
            if do_normalize:
                for key in ('trend_score', 'ma_spread_score', 'macd_score', 'volume_score'):
                    values = np.array([f[key] for _, f in candidates], dtype=float)
                    mean = np.mean(values)
                    std = np.std(values)
                    if std > 1e-12:
                        for _, f in candidates:
                            f[key] = (f[key] - mean) / std
                    else:
                        for _, f in candidates:
                            f[key] = 0.0
            for stockcode, f in candidates:
                total = (f['trend_score'] * 0.30 + f['ma_spread_score'] * 0.25 +
                         f['macd_score'] * 0.25 + f['volume_score'] * 0.20)
                scored.append((stockcode, total))

        scored.sort(key=lambda x: x[1], reverse=True)
        self.ranked_candidates = (current_date, scored)

        # 6. 换仓/补仓
        if is_rebalance_day:
            self.rebalance_count = 0
            self.last_rebalance_date = current_date
            self._do_rebalance(scored, hist_prices, sold_today, market_ok, current_date)
        else:
            self._do_replenish(scored, hist_prices, hist_volumes, sold_today, market_ok, current_date)

        # 7. 持久化
        self.last_trade_date = current_date
        self._persist(current_date, sold_today)
        _log('[{0}] 策略执行完毕'.format(current_date))

    def _do_rebalance(self, scored, hist_prices, sold_today, market_ok, current_date):
        """换仓日逻辑"""
        top_n = scored[:MAX_POSITIONS]
        top_codes = [x[0] for x in top_n]

        _log('[{0}] ====== 换仓日 ======'.format(current_date))
        _log('[{0}] 候选: {1}只 | Top{2}: {3}'.format(
            current_date, len(scored), MAX_POSITIONS,
            " | ".join(["{0}({1:.4f})".format(c, s) for c, s in top_n])))

        # 换仓卖出: 不在TopN的持仓(盈利保护+最低持有保护)
        for stockcode in list(self.positions.keys()):
            if stockcode in top_codes:
                continue
            if stockcode in sold_today:
                continue
            pos = self.positions[stockcode]
            hold_days = self.trading_day_index - pos.buy_trading_day_idx
            if hold_days < MIN_HOLD_DAYS:
                _log('[{0}] 换仓保留: {1} | 持有仅{2}天'.format(current_date, stockcode, hold_days))
                continue
            if stockcode in hist_prices and len(hist_prices[stockcode]) > 0:
                cur_price = float(hist_prices[stockcode][-1])
                profit_pct = (cur_price - pos.buy_price) / pos.buy_price
                if profit_pct > PROFIT_THRESHOLD:
                    _log('[{0}] 换仓保留: {1} | 盈利{2:+.2f}%'.format(current_date, stockcode, profit_pct * 100))
                    continue

            success, order_id = self.trader.sell(stockcode, pos.volume)
            if not success:
                _log('[{0}] !! 换仓卖出被拒: {1}'.format(current_date, stockcode))
                continue
            self._record_pending_order('sell', stockcode, pos.volume, order_id, current_date)
            confirmed, outcome = self._confirm_sell_and_sync(stockcode, pos.volume, order_id, current_date)
            if confirmed and stockcode not in self.positions:
                _log('[{0}] 换仓卖出确认: {1} | {2}'.format(current_date, stockcode, outcome))
                sold_today.add(stockcode)
            else:
                _log('[{0}] !! 换仓卖出待人工检查: {1} | order_id={2} | {3}'.format(
                    current_date, stockcode, order_id, outcome))

        # 换仓买入
        can_open_new = self._can_open_new_positions(history_ok=bool(hist_prices))
        if self.market_ok_streak >= 2 and market_ok and not self._crash_day and can_open_new:
            asset = self.trader.get_asset()
            if asset:
                total_assets, available_cash = asset[0], asset[1]
                current_holdings = len(self.positions)
                for stockcode, s in top_n:
                    if current_holdings >= MAX_POSITIONS:
                        break
                    if stockcode in self.positions or stockcode in sold_today:
                        continue
                    if stockcode not in hist_prices:
                        continue
                    current_price = float(hist_prices[stockcode][-1])
                    buy_amount = calculate_buy_amount(total_assets, available_cash)
                    if buy_amount < 1000:
                        continue
                    buy_volume = int(buy_amount / current_price / 100) * 100
                    if buy_volume < 100:
                        continue
                    success, order_id = self.trader.buy(stockcode, buy_volume)
                    if success:
                        self._record_pending_order('buy', stockcode, buy_volume, order_id, current_date)
                        confirmed, outcome = self._confirm_buy_and_sync(stockcode, buy_volume, order_id, current_date)
                        if confirmed and stockcode in self.positions:
                            available_cash -= buy_volume * current_price
                            current_holdings += 1
                            _log('[{0}] >> 买入确认: {1} | {2}股 @ {3:.2f} | {4}'.format(
                                current_date, stockcode, buy_volume, current_price, outcome))
                        else:
                            _log('[{0}] !! 买入待人工检查: {1} | order_id={2} | {3}'.format(
                                current_date, stockcode, order_id, outcome))
        else:
            _log('[{0}] 大盘弱势,换仓日跳过买入'.format(current_date))

    def _do_replenish(self, scored, hist_prices, hist_volumes, sold_today, market_ok, current_date):
        """非换仓日补仓"""
        if not (self.market_ok_streak >= 2 and market_ok) or self._crash_day:
            _log('[{0}] 大盘弱势或暴跌日,非换仓日跳过补仓'.format(current_date))
            return
        if not self._can_open_new_positions(history_ok=bool(hist_prices)):
            _log('[{0}] 禁止新开仓: {1}'.format(current_date, self.state.get('buy_block_reason', 'unknown')))
            return

        asset = self.trader.get_asset()
        if not asset:
            return
        total_assets, available_cash = asset[0], asset[1]
        current_holdings = len(self.positions)

        for stockcode, s in scored:
            if current_holdings >= MAX_POSITIONS:
                break
            if stockcode in self.positions or stockcode in sold_today:
                continue
            if stockcode not in hist_prices or len(hist_prices[stockcode]) < 70:
                continue
            if stockcode not in hist_volumes or len(hist_volumes[stockcode]) < 20:
                continue
            if not check_buy_signal(np.array(hist_prices[stockcode]), np.array(hist_volumes[stockcode])):
                continue
            current_price = float(hist_prices[stockcode][-1])
            buy_amount = calculate_buy_amount(total_assets, available_cash)
            if buy_amount < 1000:
                continue
            buy_volume = int(buy_amount / current_price / 100) * 100
            if buy_volume < 100:
                continue
            success, order_id = self.trader.buy(stockcode, buy_volume)
            if success:
                self._record_pending_order('buy', stockcode, buy_volume, order_id, current_date)
                confirmed, outcome = self._confirm_buy_and_sync(stockcode, buy_volume, order_id, current_date)
                if confirmed and stockcode in self.positions:
                    available_cash -= buy_volume * current_price
                    current_holdings += 1
                    _log('[{0}] >> 补仓确认: {1} | {2}股 @ {3:.2f} | {4}'.format(
                        current_date, stockcode, buy_volume, current_price, outcome))
                else:
                    _log('[{0}] !! 补仓待人工检查: {1} | order_id={2} | {3}'.format(
                        current_date, stockcode, order_id, outcome))

    def _persist(self, current_date, sold_today):
        """持久化状态"""
        self.state['last_processed_trade_date'] = current_date
        self.state['rebalance_count'] = self.rebalance_count
        self.state['trading_day_index'] = self.trading_day_index
        self.state['market_ok_streak'] = self.market_ok_streak
        self.state['market_weak_streak'] = self.market_weak_streak
        self.state['sold_today_date'] = current_date
        self.state['sold_today_set'] = sorted(sold_today)
        self.state['positions_meta'] = {
            code: {
                'buy_price': pos.buy_price,
                'buy_date': pos.buy_date,
                'highest_price': pos.highest_price,
                'buy_trading_day_idx': pos.buy_trading_day_idx,
                'volume': pos.volume,
            }
            for code, pos in self.positions.items()
        }
        if _save_state(self.state):
            _log('[{0}] 状态已持久化'.format(current_date))

    def _save_and_exit(self, current_date):
        """异常退出时也要持久化 last_date"""
        self.state['last_processed_trade_date'] = current_date
        _save_state(self.state)

# ==================== 主入口 ====================

def run_once():
    """执行一次策略"""
    _init_log()
    _log('=' * 60)
    _log('hs300 xtquant 策略 - 单次执行')
    _log('=' * 60)

    trader = Trader(QMT_PATH, ACCOUNT_ID)
    if not trader.connect():
        _log('连接失败,退出')
        return

    try:
        strategy = Strategy(trader)
        strategy.run_once()
    except Exception as e:
        _log('策略执行异常: {0}'.format(e))
        import traceback
        _log(traceback.format_exc())
    finally:
        trader.disconnect()

def run_daemon():
    """守护模式: 每个交易日 14:55 自动执行"""
    _init_log()
    _log('=' * 60)
    _log('hs300 xtquant 策略 - 守护模式')
    _log('调度时间: 每个交易日 {0}'.format(SCHEDULE_TIME))
    _log('=' * 60)

    while True:
        now = _now()
        # 周末不执行
        if now.weekday() >= 5:
            _log('周末,休眠到周一')
            next_monday = now + timedelta(days=7 - now.weekday())
            next_time = next_monday.replace(hour=9, minute=0, second=0, microsecond=0)
            sleep_sec = (next_time - now).total_seconds()
            time.sleep(min(sleep_sec, 3600))  # 最多睡1小时,避免漂移
            continue

        # 检查是否到了调度时间
        target_time = now.replace(hour=int(SCHEDULE_TIME[:2]), minute=int(SCHEDULE_TIME[3:]),
                                  second=0, microsecond=0)
        if now >= target_time:
            # 执行策略
            run_once()
            # 执行完睡到明天
            _log('执行完毕,休眠到明天')
            time.sleep(3600)
        else:
            # 还没到时间,睡到调度时间前60秒
            sleep_sec = (target_time - now).total_seconds() - 60
            if sleep_sec > 0:
                _log('等待 {0:.0f}s 到 {1}'.format(sleep_sec, SCHEDULE_TIME))
                time.sleep(min(sleep_sec, 3600))
            else:
                time.sleep(30)

def main():
    parser = argparse.ArgumentParser(description='沪深300 xtquant 策略')
    parser.add_argument('--daemon', action='store_true', help='守护模式')
    args = parser.parse_args()

    if args.daemon:
        run_daemon()
    else:
        run_once()

if __name__ == '__main__':
    main()
