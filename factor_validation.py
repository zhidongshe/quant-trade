# -*- coding: gbk -*-
"""
四因子有效性验证（纯选股，无风控、无换仓、无止损止盈）

逻辑：
1. 每天收盘前，遍历沪深300成分股
2. 选出满足四因子的股票，按 score_stock 打分排序
3. 取前 MAX_DAILY_POSITIONS 只，等权重买入
4. 第二天开盘前（或收盘前）全部卖出
5. 统计每日盈亏、胜率、累计收益

目的：剥离风控和换仓干扰，单独验证选股因子本身是否有 alpha。
"""

import numpy as np

# ==================== 指标计算模块 ====================

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

    vol_ma20 = sma(volumes.astype(float), 20)
    if np.isnan(vol_ma20[-1]) or volumes[-1] <= vol_ma20[-1]:
        return False

    return True


def score_stock(prices, volumes):
    """对满足四因子条件的股票打分，返回加权总分；不满足条件返回None"""
    if not check_buy_signal(prices, volumes):
        return None

    price = prices[-1]

    ma60 = sma(prices, 60)
    trend_score = (price - ma60[-1]) / ma60[-1]

    ma5 = sma(prices, 5)
    ma20 = sma(prices, 20)
    ma_spread_score = (ma5[-1] - ma20[-1]) / ma20[-1]

    dif, dea, hist = macd(prices)
    macd_score = hist[-1] / price

    vol_ma20 = sma(volumes.astype(float), 20)
    volume_score = volumes[-1] / vol_ma20[-1] - 1.0

    total = (trend_score * 0.30
             + ma_spread_score * 0.25
             + macd_score * 0.25
             + volume_score * 0.20)
    return total


# ==================== 全局配置 ====================

MAX_DAILY_POSITIONS = 5   # 每天最多买入几只（等权重）
TARGET_PER_STOCK = 20000  # 每只目标金额（元），等权重


# ==================== 日志模块 ====================

_LOG_FILE_PATH = None

def _init_log():
    global _LOG_FILE_PATH
    from datetime import datetime
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    _LOG_FILE_PATH = r'c:\因子验证日志_{0}.log'.format(ts)

def _log(msg):
    from datetime import datetime
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = '{0} {1}'.format(timestamp, msg)
    print(line)
    if _LOG_FILE_PATH is None:
        _init_log()
    try:
        with open(_LOG_FILE_PATH, 'a', encoding='gbk') as f:
            f.write(line + '\n')
    except Exception:
        pass

_init_log()


# ==================== 交易执行模块 ====================

def _execute_buy(ContextInfo, account_id, account_type, stockcode, volume, price, trade_date):
    try:
        passorder(
            23, 1101, account_id, stockcode, 5, -1.0,
            float(volume), ContextInfo
        )
        amount = volume * price
        commission = max(amount * 0.0001, 5.0)
        _log("[{0}] >> 买入: {1} | {2}股 x {3:.2f}元 = {4:.0f}元 | 佣金: {5:.2f}元".format(
            trade_date, stockcode, volume, price, amount, commission))
        return True
    except Exception as e:
        _log("[{0}] !! 买入失败: {1} | {2}".format(trade_date, stockcode, e))
        return False


def _execute_sell(ContextInfo, account_id, account_type, stockcode, volume, price, trade_date):
    try:
        passorder(
            24, 1101, account_id, stockcode, 5, -1.0,
            float(volume), ContextInfo
        )
        amount = volume * price
        commission = max(amount * 0.0001, 5.0)
        stamp_tax = amount * 0.001
        _log("[{0}] << 卖出: {1} | {2}股 x {3:.2f}元 = {4:.0f}元 | 佣金: {5:.2f}元 | 印花税: {6:.2f}元".format(
            trade_date, stockcode, volume, price, amount, commission, stamp_tax))
    except Exception as e:
        _log("[{0}] !! 卖出失败: {1} | {2}".format(trade_date, stockcode, e))


# ==================== QMT策略主函数 ====================

def init(ContextInfo):
    ContextInfo.set_account('8890358835')
    ContextInfo.capital = 100000
    ContextInfo.accountid = '8890358835'

    # 昨日买入的持仓记录: {stockcode: {'volume': int, 'buy_price': float}}
    ContextInfo.prev_positions = {}

    # 统计指标
    ContextInfo.total_pnl = 0.0          # 累计盈亏（不含成本）
    ContextInfo.total_cost = 0.0         # 累计交易成本
    ContextInfo.trade_count = 0          # 买入次数
    ContextInfo.win_count = 0            # 盈利次数
    ContextInfo.lose_count = 0           # 亏损次数
    ContextInfo.day_count = 0            # 交易天数
    ContextInfo.max_drawdown = 0.0       # 最大回撤（基于累计盈亏）
    ContextInfo.peak_pnl = 0.0           # 累计盈亏峰值

    universe = ContextInfo.get_sector('000300.SH')
    if universe:
        ContextInfo.set_universe(universe)


def handlebar(ContextInfo):
    current_date = timetag_to_datetime(ContextInfo.get_bar_timetag(ContextInfo.barpos), '%Y%m%d')

    account_id = ContextInfo.accountid if hasattr(ContextInfo, 'accountid') else ''
    account_type = 'STOCK'

    # 1. 卖出昨天买入的所有持仓
    day_sell_pnl = 0.0
    day_sell_count = 0
    for stockcode, pos in list(ContextInfo.prev_positions.items()):
        hist = ContextInfo.get_history_data(1, '1d', 'close', dividend_type='front', skip_paused=True)
        if stockcode in hist and len(hist[stockcode]) > 0:
            sell_price = float(hist[stockcode][-1])
            pnl = (sell_price - pos['buy_price']) * pos['volume']
            day_sell_pnl += pnl
            day_sell_count += 1
            if pnl > 0:
                ContextInfo.win_count += 1
            else:
                ContextInfo.lose_count += 1

            # 记录当日卖出成本
            amount = pos['volume'] * sell_price
            commission = max(amount * 0.0001, 5.0)
            stamp_tax = amount * 0.001
            ContextInfo.total_cost += commission + stamp_tax

            _execute_sell(ContextInfo, account_id, account_type, stockcode, pos['volume'], sell_price, current_date)
        del ContextInfo.prev_positions[stockcode]

    ContextInfo.total_pnl += day_sell_pnl
    ContextInfo.day_count += 1

    # 更新最大回撤
    if ContextInfo.total_pnl > ContextInfo.peak_pnl:
        ContextInfo.peak_pnl = ContextInfo.total_pnl
    drawdown = ContextInfo.peak_pnl - ContextInfo.total_pnl
    if drawdown > ContextInfo.max_drawdown:
        ContextInfo.max_drawdown = drawdown

    # 2. 选股：获取全市场数据，筛选四因子+打分
    universe = ContextInfo.get_sector('000300.SH')
    if not universe:
        _log("[{0}] 警告: 无法获取沪深300成分股".format(current_date))
        return

    ContextInfo.set_universe(universe)

    hist_prices = ContextInfo.get_history_data(70, '1d', 'close', dividend_type='front', skip_paused=True)
    hist_volumes = ContextInfo.get_history_data(25, '1d', 'volume', dividend_type='front', skip_paused=True)

    candidates = []
    for stockcode in universe:
        if stockcode not in hist_prices or len(hist_prices[stockcode]) < 70:
            continue
        if stockcode not in hist_volumes or len(hist_volumes[stockcode]) < 20:
            continue
        prices_arr = np.array(hist_prices[stockcode])
        volumes_arr = np.array(hist_volumes[stockcode])
        s = score_stock(prices_arr, volumes_arr)
        if s is not None:
            current_price = float(prices_arr[-1])
            candidates.append((stockcode, s, current_price))

    candidates.sort(key=lambda x: x[1], reverse=True)
    selected = candidates[:MAX_DAILY_POSITIONS]

    # 3. 等权重买入 today's selected
    if len(selected) > 0:
        per_stock_target = TARGET_PER_STOCK  # 固定金额，不考虑实际资金变化
        for stockcode, score, current_price in selected:
            buy_volume = int(per_stock_target / current_price / 100) * 100
            if buy_volume < 100:
                continue

            success = _execute_buy(ContextInfo, account_id, account_type, stockcode, buy_volume, current_price, current_date)
            if success:
                ContextInfo.prev_positions[stockcode] = {
                    'volume': buy_volume,
                    'buy_price': current_price
                }
                ContextInfo.trade_count += 1

    # 4. 打印当日统计
    win_rate = (ContextInfo.win_count / ContextInfo.trade_count * 100) if ContextInfo.trade_count > 0 else 0
    _log("[{0}] ===== 日终统计 =====".format(current_date))
    _log("[{0}] 候选池: {1}只 | 今日买入: {2}只 | 今日卖出: {3}只 | 卖出盈亏: {4:+.0f}元".format(
        current_date, len(candidates), len(selected), day_sell_count, day_sell_pnl))
    _log("[{0}] 累计盈亏: {1:+.0f}元 | 累计成本: {2:.0f}元 | 净收益: {3:+.0f}元 | 最大回撤: {4:.0f}元 | 胜率: {5:.1f}% ({6}胜/{7}负)".format(
        current_date, ContextInfo.total_pnl, ContextInfo.total_cost,
        ContextInfo.total_pnl - ContextInfo.total_cost, ContextInfo.max_drawdown,
        win_rate, ContextInfo.win_count, ContextInfo.lose_count))
