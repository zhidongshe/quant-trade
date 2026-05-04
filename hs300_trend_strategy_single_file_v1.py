# -*- coding: utf-8 -*-
"""
沪深300多头趋势策略（单文件版）

策略逻辑:
1. 股票池: 沪深300成分股，每日更新
2. 入场: 三因子共振 (60日线上 + 5日>20日 + MACD>0 + 放量)
3. 卖出: 3%硬止损 / 跌破20日线 / 盈利5%后跟踪止盈(回落5%)
4. 仓位: 最多5只，每只20%

使用方法:
1. 在QMT中新建Python模型
2. 将此文件全部内容复制粘贴到策略编辑器
3. 修改 ContextInfo.set_account('你的资金账号')
4. 设置回测参数后运行
"""

import numpy as np
import os
from datetime import datetime

# ==================== 日志模块 ====================

_LOG_FILE_PATH = None


def _init_log():
    """初始化日志文件路径，文件名带时间戳"""
    global _LOG_FILE_PATH
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    _LOG_FILE_PATH = r'c:\量化日志_{0}.log'.format(ts)


def _log(msg):
    """同时输出到终端和日志文件，带时间戳"""
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
    # MACD红柱必须相比昨日扩大，拒绝缩窄（多头衰竭）信号
    if len(hist) >= 3 and hist[-1] <= hist[-2]:
        return False

    # 只买上涨日，拒绝放量下跌；且涨幅至少1%，过滤高开低走勉强红盘
    if len(prices) >= 2 and prices[-1] <= prices[-2] * 1.01:
        return False

    vol_ma20 = sma(volumes.astype(float), 20)
    if np.isnan(vol_ma20[-1]) or volumes[-1] <= vol_ma20[-1]:
        return False

    return True


def score_stock(prices, volumes):
    """对满足四因子条件的股票返回原始因子字典；不满足条件返回None"""
    if not check_buy_signal(prices, volumes):
        return None

    price = prices[-1]

    ma60 = sma(prices, 60)
    trend_score = (price - ma60[-1]) / ma60[-1]

    ma5 = sma(prices, 5)
    ma20 = sma(prices, 20)
    ma_spread_score = (ma5[-1] - ma20[-1]) / ma20[-1]

    dif, dea, hist = macd(prices)
    macd_score = hist[-1] / ma20[-1]  # 使用MA20做量纲对齐，而非price

    vol_ma20 = sma(volumes.astype(float), 20)
    ratio = volumes[-1] / vol_ma20[-1] if vol_ma20[-1] > 0 else 1.0
    volume_score = np.log(max(ratio, 0.01))  # 限制最小比值0.01，防止无量跌停时负无穷

    return {
        'trend_score': trend_score,
        'ma_spread_score': ma_spread_score,
        'macd_score': macd_score,
        'volume_score': volume_score,
    }


# ==================== 持仓管理模块 ====================

class Position:
    def __init__(self, stockcode, buy_price, buy_date, volume, buy_trading_day_idx=0):
        self.stockcode = stockcode
        self.buy_price = buy_price
        self.buy_date = buy_date
        self.volume = volume
        self.highest_price = buy_price
        self.buy_trading_day_idx = buy_trading_day_idx


def check_stop_loss(pos, current_price, hard_stop_pct=0.03):
    if current_price <= pos.buy_price * (1 - hard_stop_pct):
        return True
    return False


def check_trend_break(current_price, ma20):
    if current_price <= ma20:
        return True
    return False


def check_trailing_stop(pos, current_price, profit_threshold=0.05, pullback_pct=0.05):
    if current_price > pos.highest_price:
        pos.highest_price = current_price

    max_profit_pct = (pos.highest_price - pos.buy_price) / pos.buy_price

    if max_profit_pct <= profit_threshold:
        return False

    if current_price <= pos.highest_price * (1 - pullback_pct):
        return True

    return False


def calculate_buy_amount(total_capital, available_cash, max_positions=5):
    target_per_stock = total_capital / max_positions
    amount = min(target_per_stock, available_cash)
    return int(amount // 100 * 100)


# ==================== 全局配置 ====================

MAX_POSITIONS = 5
HARD_STOP_PCT = 0.05
PROFIT_THRESHOLD = 0.10
TRAILING_PULLBACK_PCT = 0.08
REBALANCE_INTERVAL = 10  # 每10个交易日换仓（约2周）
MIN_HOLD_DAYS = 3       # 最低持有3个交易日


# ==================== QMT策略主函数 ====================

def init(ContextInfo):
    ContextInfo.set_account('8890358835')
    # 尝试从QMT账户读取实际初始资金，失败则回退到默认值
    try:
        acct_info = get_trade_detail_data('8890358835', 'STOCK', 'ACCOUNT')
        if acct_info:
            ContextInfo.capital = acct_info[0].m_dBalance
        else:
            ContextInfo.capital = 100000
    except Exception:
        ContextInfo.capital = 100000

    ContextInfo.positions = {}
    ContextInfo.last_trade_date = None
    ContextInfo.accountid = '8890358835'

    ContextInfo.rebalance_count = 0
    ContextInfo.last_rebalance_date = None
    ContextInfo.ranked_candidates = []
    ContextInfo.realized_pnl = 0.0  # 累计已实现盈亏（用于回测时估算总资产）
    ContextInfo.total_cost = 0.0    # 累计交易成本
    ContextInfo.trading_day_index = 0  # 交易日计数器（用于最低持有期）
    ContextInfo.market_ok_streak = 0   # 大盘连续OK天数，≥2才允许买入
    ContextInfo.market_weak_streak = 0 # 大盘连续弱天数，≥2则清仓非强势股

    universe = ContextInfo.get_sector('000300.SH')
    if universe:
        # 把指数加入 universe，以便 get_history_data 获取大盘数据
        ContextInfo.set_universe(list(universe) + ['000300.SH'])


def _normalize_stock_code(code):
    """将QMT返回的股票代码标准化为带市场后缀的格式
    QMT的get_trade_detail_data返回的m_strInstrumentID可能不带后缀(如'601689'),
    而set_universe/get_history_data需要带后缀(如'601689.SH')
    """
    if '.' in code:
        return code
    digits = code.strip()
    if digits.startswith(('6', '9')):
        return digits + '.SH'
    elif digits.startswith(('0', '3')):
        return digits + '.SZ'
    return code


def _check_market_trend(idx_prices):
    """判断大盘是否在上升趋势：沪深300 close > MA20 且 MACD hist > 0
    idx_prices: 指数近25日收盘价数组（numpy array 或 list）
    """
    if idx_prices is None or len(idx_prices) < 20:
        return False
    ma20 = np.mean(idx_prices[-20:])
    dif, dea, hist = macd(np.array(idx_prices, dtype=float))
    return idx_prices[-1] > ma20 and hist[-1] > 0


def _sync_positions(ContextInfo, account_id, account_type, current_date):
    """从QMT实际持仓同步到ContextInfo.positions，防止两边脱节"""
    if not account_id:
        return
    try:
        position_list = get_trade_detail_data(account_id, account_type, 'POSITION')
        if not position_list:
            return

        qmt_holdings = {}
        for p in position_list:
            raw_code = p.m_strInstrumentID
            code = _normalize_stock_code(raw_code)
            #if code != raw_code:
            #_log("[{0}] 代码标准化: {1} → {2}".format(current_date, raw_code, code))
            vol = int(p.m_nVolume) if hasattr(p, 'm_nVolume') else int(p.m_nCanUseVolume)
            if vol > 0:
                qmt_holdings[code] = {
                    'volume': vol,
                    'cost_price': p.m_dOpenPrice if hasattr(p, 'm_dOpenPrice') else 0.0,
                }

        # QMT有但我们没记录的 → 补录
        for code, info in qmt_holdings.items():
            if code not in ContextInfo.positions:
                ContextInfo.positions[code] = Position(
                    stockcode=code,
                    buy_price=info['cost_price'] if info['cost_price'] > 0 else 1.0,
                    buy_date=current_date,
                    volume=info['volume']
                )
                _log("[{0}] 同步持仓: {1}, 数量{2}股".format(current_date, code, info['volume']))

        # 同步已有持仓的volume，但不覆盖buy_price（保持前复权基准）
        for code in list(ContextInfo.positions.keys()):
            if code in qmt_holdings:
                ContextInfo.positions[code].volume = qmt_holdings[code]['volume']
            else:
                _log("[{0}] 清除失效持仓: {1}".format(current_date, code))
                del ContextInfo.positions[code]

    except Exception as e:
        _log("[{0}] 持仓同步异常: {1}".format(current_date, e))


def handlebar(ContextInfo):
    current_date = timetag_to_datetime(ContextInfo.get_bar_timetag(ContextInfo.barpos), '%Y%m%d')

    if ContextInfo.last_trade_date == current_date:
        return
    ContextInfo.last_trade_date = current_date
    # 把前一天交易成本累加到累计值，再清空当日记录
    ContextInfo.total_cost = getattr(ContextInfo, 'total_cost', 0.0) + getattr(ContextInfo, 'daily_cost', 0.0)
    ContextInfo.daily_sold_records = []
    ContextInfo.daily_cost = 0.0

    # 从QMT实际持仓同步，防止positions字典和QMT脱节
    account_id = ContextInfo.accountid if hasattr(ContextInfo, 'accountid') else ''
    _sync_positions(ContextInfo, account_id, 'STOCK', current_date)

    # 交易日计数 + 换仓日判断提前（卖出逻辑需要）
    ContextInfo.trading_day_index = getattr(ContextInfo, 'trading_day_index', 0) + 1
    ContextInfo.rebalance_count = getattr(ContextInfo, 'rebalance_count', 0) + 1
    is_rebalance_day = (ContextInfo.rebalance_count >= REBALANCE_INTERVAL)

    holdings = list(ContextInfo.positions.keys())

    # 1. 更新股票池
    universe = ContextInfo.get_sector('000300.SH')
    if not universe:
        _log("[{0}] 警告: 无法获取沪深300成分股".format(current_date))
        return

    # 只在持仓股有变化（买入新股或成分股调整导致持仓股不在 universe 中）时才调用 set_universe
    # 避免每天重复调用导致 get_history_data 隔天为空
    # 始终保留指数 '000300.SH' 在 universe 中，以便获取大盘历史数据
    held_stocks = list(ContextInfo.positions.keys())
    missing = [code for code in held_stocks if code not in universe]
    if missing:
        full_universe = list(set(universe + held_stocks + ['000300.SH']))
        ContextInfo.set_universe(full_universe)
        _log("[{0}] set_universe: 补充{1}只持仓股进 universe".format(current_date, len(missing)))

    # 过滤ST股（只过滤买入池，不影响卖出），并排除指数本身
    buy_universe = [code for code in _filter_st_stocks(universe, ContextInfo) if code != '000300.SH']

    # 2. 获取账户信息
    account_type = 'STOCK'

    available_cash = ContextInfo.capital
    if account_id:
        acct_info = get_trade_detail_data(account_id, account_type, 'ACCOUNT')
        if acct_info:
            available_cash = acct_info[0].m_dAvailable

    # 3. 遍历现有持仓，检查止损/止盈
    positions_to_sell = []
    hist_prices = ContextInfo.get_history_data(70, '1d', 'close', dividend_type='front', skip_paused=True)

    # 大盘择时（基于 get_history_data 获取的指数数据）
    idx_prices = None
    if '000300.SH' in hist_prices and len(hist_prices['000300.SH']) >= 70:
        idx_prices = np.array(hist_prices['000300.SH'], dtype=float)
    market_ok = _check_market_trend(idx_prices)
    if market_ok:
        ContextInfo.market_ok_streak = getattr(ContextInfo, 'market_ok_streak', 0) + 1
        ContextInfo.market_weak_streak = 0
    else:
        ContextInfo.market_ok_streak = 0
        ContextInfo.market_weak_streak = getattr(ContextInfo, 'market_weak_streak', 0) + 1
    market_str = "大盘OK({0}天)".format(ContextInfo.market_ok_streak) if market_ok else "大盘弱({0}天)".format(ContextInfo.market_weak_streak)
    _log("[{0}] ===== 日期: {0} | 持仓: {1}只 | {2} | 距下次换仓: {3}个交易日 =====".format(
        current_date, len(holdings), market_str,
        REBALANCE_INTERVAL - ContextInfo.rebalance_count
    ))

    if len(ContextInfo.positions) > 0:
        for stockcode, pos in list(ContextInfo.positions.items()):
            if stockcode not in hist_prices or len(hist_prices[stockcode]) < 1:
                _log("[{0}] {1} 跳过卖出: 无数据".format(current_date, stockcode))
                continue

            prices_list = hist_prices[stockcode]
            current_price = float(prices_list[-1])

            # 更新highest_price用于跟踪止盈
            if current_price > pos.highest_price:
                pos.highest_price = current_price

            # 数据不足20条时，只能检查硬止损
            if len(prices_list) < 20:
                if check_stop_loss(pos, current_price, HARD_STOP_PCT):
                    positions_to_sell.append((stockcode, 'hard_stop'))
                continue

            prices_arr = np.array(prices_list)
            ma20 = np.mean(prices_arr[-20:])

            # 计算MACD用于动能衰竭判断
            dif, dea, hist = macd(prices_arr)

            # 计算持有交易日数
            hold_days = ContextInfo.trading_day_index - getattr(pos, 'buy_trading_day_idx', 0)

            should_sell = False
            sell_reason = ''

            # 硬止损始终检查（无论是否最低持有期）
            if check_stop_loss(pos, current_price, HARD_STOP_PCT):
                should_sell = True
                sell_reason = 'hard_stop'
            # 单日暴跌保护：防止次日暴跌无法出逃
            elif len(prices_list) >= 2:
                prev_price = float(prices_list[-2])
                daily_change = (current_price - prev_price) / prev_price if prev_price > 0 else 0
                if daily_change <= -0.07:
                    should_sell = True
                    sell_reason = 'crash_protection'

            # 取消最低持有期限制，买入次日即可检查全部卖出条件（趋势/MACD/止盈）
            macd_weakening = (hist[-1] <= 0) and (len(hist) >= 2) and (hist[-1] <= hist[-2])
            if not should_sell:
                # 趋势破坏：跌破MA20 且 MACD动能衰竭（双确认）
                if check_trend_break(current_price, ma20) and macd_weakening:
                    should_sell = True
                    sell_reason = 'trend_break'
                elif check_trailing_stop(pos, current_price, PROFIT_THRESHOLD, TRAILING_PULLBACK_PCT):
                    should_sell = True
                    sell_reason = 'trailing_stop'

            if should_sell:
                pnl_pct = (current_price - pos.buy_price) / pos.buy_price * 100
                _log("[{0}] 触发卖出: {1} | 原因: {2} | 持有{3}天 | 买入价: {4:.2f} | 现价: {5:.2f} | 盈亏: {6:+.2f}%".format(
                    current_date, stockcode, sell_reason, hold_days, pos.buy_price, current_price, pnl_pct))
                positions_to_sell.append((stockcode, sell_reason))

    # 大盘连续2天弱，清仓非强势股（保留已进入跟踪止盈区间的股票）
    if ContextInfo.market_weak_streak >= 2:
        already_marked = {s for s, _ in positions_to_sell}
        for stockcode, pos in list(ContextInfo.positions.items()):
            if stockcode in already_marked:
                continue
            max_profit_pct = (pos.highest_price - pos.buy_price) / pos.buy_price
            if max_profit_pct <= PROFIT_THRESHOLD:
                positions_to_sell.append((stockcode, 'market_weak'))
                _log("[{0}] 大盘连续弱{1}天，清仓: {2} | 最高盈利{3:+.2f}%，未达强势股标准".format(
                    current_date, ContextInfo.market_weak_streak, stockcode, max_profit_pct * 100))

    # 执行卖出，并记录当日已卖出股票（当天不再买回）
    sold_today = set()
    for stockcode, reason in positions_to_sell:
        if stockcode in ContextInfo.positions:
            pos = ContextInfo.positions[stockcode]
            sell_price = pos.buy_price
            if stockcode in hist_prices and len(hist_prices[stockcode]) > 0:
                sell_price = float(hist_prices[stockcode][-1])
                realized = (sell_price - pos.buy_price) * pos.volume
                ContextInfo.realized_pnl = getattr(ContextInfo, 'realized_pnl', 0.0) + realized
            # 记录当日卖出
            ContextInfo.daily_sold_records.append({
                'stockcode': stockcode,
                'volume': pos.volume,
                'buy_price': pos.buy_price,
                'sell_price': sell_price,
                'reason': reason,
                'buy_date': pos.buy_date,
            })
            # 计算卖出交易成本（佣金+印花税+过户费+滑点）
            amount = pos.volume * sell_price
            commission = max(amount * 0.0001, 5.0)
            stamp_tax = amount * 0.001
            transfer_fee = amount * 0.00001
            slippage = amount * 0.0005
            total_cost = commission + stamp_tax + transfer_fee + slippage
            ContextInfo.daily_cost = getattr(ContextInfo, 'daily_cost', 0.0) + total_cost
        _execute_sell(ContextInfo, account_id, account_type, stockcode, reason, current_date)
        if stockcode in ContextInfo.positions:
            del ContextInfo.positions[stockcode]
        sold_today.add(stockcode)

    # 4. 换仓/补仓逻辑
    # 大盘弱势时禁止买入（但允许卖出）
    if not market_ok:
        _log("[{0}] 大盘环境不满足上升趋势，今日禁止买入".format(current_date))

    if account_id:
        acct_info = get_trade_detail_data(account_id, account_type, 'ACCOUNT')
        if acct_info:
            available_cash = acct_info[0].m_dAvailable

    # 一次性获取所有需要的历史数据
    hist_prices = ContextInfo.get_history_data(70, '1d', 'close', dividend_type='front', skip_paused=True)
    hist_volumes = ContextInfo.get_history_data(70, '1d', 'volume', dividend_type='front', skip_paused=True)

    got_prices = len(hist_prices) if hist_prices else 0
    got_volumes = len(hist_volumes) if hist_volumes else 0
    #_log("[{0}] 数据获取: close={1}只, volume={2}只".format(current_date, got_prices, got_volumes))

    # 每天对所有候选股打分（不管是不是换仓日）
    candidates = []
    for stockcode in buy_universe:
        if stockcode not in hist_prices or len(hist_prices[stockcode]) < 70:
            continue
        if stockcode not in hist_volumes or len(hist_volumes[stockcode]) < 20:
            continue
        prices_arr = np.array(hist_prices[stockcode])
        volumes_arr = np.array(hist_volumes[stockcode])
        factors = score_stock(prices_arr, volumes_arr)
        if factors is not None:
            candidates.append((stockcode, factors))

    # 截面标准化（Z-Score），消除量纲差异；候选股过少时跳过标准化，避免std不稳定
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
            total = (f['trend_score'] * 0.30
                     + f['ma_spread_score'] * 0.25
                     + f['macd_score'] * 0.25
                     + f['volume_score'] * 0.20)
            scored.append((stockcode, total))

    scored.sort(key=lambda x: x[1], reverse=True)
    ContextInfo.ranked_candidates = (current_date, scored)

    if is_rebalance_day:
        ContextInfo.rebalance_count = 0
        ContextInfo.last_rebalance_date = current_date

        top_n = scored[:MAX_POSITIONS]
        top_codes = [x[0] for x in top_n]

        _log("[{0}] ====== 换仓日 ======".format(current_date))
        _log("[{0}] 打分候选: {1}只通过四因子".format(current_date, len(scored)))
        if len(scored) > 0:
            _log("[{0}] Top{1}排名: {2}".format(
                current_date, MAX_POSITIONS,
                " | ".join(["{0}({1:.4f})".format(c, s) for c, s in top_n])
            ))
            if len(scored) > MAX_POSITIONS:
                _log("[{0}] 候补: {1}".format(
                    current_date,
                    " | ".join(["{0}({1:.4f})".format(c, s) for c, s in scored[MAX_POSITIONS:MAX_POSITIONS+5]])
                ))

        old_holdings = set(ContextInfo.positions.keys())
        new_holdings = set(top_codes)

        # 盈利保护：盈利>10%的持仓不因换仓而强制卖出
        to_sell = set()
        for stockcode in old_holdings - new_holdings:
            pos = ContextInfo.positions[stockcode]
            if stockcode in hist_prices and len(hist_prices[stockcode]) > 0:
                cur_price = float(hist_prices[stockcode][-1])
                profit_pct = (cur_price - pos.buy_price) / pos.buy_price
                if profit_pct > PROFIT_THRESHOLD:
                    continue
            to_sell.add(stockcode)

        to_buy = new_holdings - old_holdings
        to_keep = old_holdings & new_holdings
        if to_keep:
            _log("[{0}] 继续持有: {1}".format(current_date, list(to_keep)))
        if to_sell:
            _log("[{0}] 换仓卖出: {1}".format(current_date, list(to_sell)))
        if to_buy:
            _log("[{0}] 换仓买入: {1}".format(current_date, list(to_buy)))

        # 卖出不在新Top N中的持仓（盈利超过阈值的保留）
        for stockcode in list(ContextInfo.positions.keys()):
            if stockcode not in top_codes:
                pos = ContextInfo.positions[stockcode]
                sell_price = pos.buy_price
                if stockcode in hist_prices and len(hist_prices[stockcode]) > 0:
                    sell_price = float(hist_prices[stockcode][-1])
                    profit_pct = (sell_price - pos.buy_price) / pos.buy_price
                    if profit_pct > PROFIT_THRESHOLD:
                        _log("[{0}] 换仓保留: {1} | 盈利{2:+.2f}%，不强制卖出".format(
                            current_date, stockcode, profit_pct * 100))
                        continue
                    realized = (sell_price - pos.buy_price) * pos.volume
                    ContextInfo.realized_pnl = getattr(ContextInfo, 'realized_pnl', 0.0) + realized
                # 记录当日卖出
                ContextInfo.daily_sold_records.append({
                    'stockcode': stockcode,
                    'volume': pos.volume,
                    'buy_price': pos.buy_price,
                    'sell_price': sell_price,
                    'reason': 'rebalance',
                    'buy_date': pos.buy_date,
                })
                # 计算卖出交易成本（佣金+印花税+过户费+滑点）
                amount = pos.volume * sell_price
                commission = max(amount * 0.0001, 5.0)
                stamp_tax = amount * 0.001
                transfer_fee = amount * 0.00001
                slippage = amount * 0.0005
                total_cost = commission + stamp_tax + transfer_fee + slippage
                ContextInfo.daily_cost = getattr(ContextInfo, 'daily_cost', 0.0) + total_cost
                _execute_sell(ContextInfo, account_id, account_type, stockcode, 'rebalance', current_date)
                if stockcode in ContextInfo.positions:
                    del ContextInfo.positions[stockcode]
                sold_today.add(stockcode)

        # 买入新Top N中未持仓的（大盘连续2天OK才买）
        if ContextInfo.market_ok_streak >= 2:
            current_holdings = len(ContextInfo.positions)
            for stockcode, s in top_n:
                if current_holdings >= MAX_POSITIONS:
                    break
                if stockcode in ContextInfo.positions:
                    continue
                if stockcode in sold_today:
                    continue
                if stockcode not in hist_prices:
                    continue

                prices_arr = np.array(hist_prices[stockcode])
                current_price = float(prices_arr[-1])
                buy_amount = calculate_buy_amount(ContextInfo.capital, available_cash, MAX_POSITIONS)
                if buy_amount < 1000:
                    continue
                buy_volume = int(buy_amount / current_price / 100) * 100
                if buy_volume < 100:
                    _log("[{0}] 买入跳过: {1} | 价格{2:.2f}元过高，资金不足以买1手".format(
                        current_date, stockcode, current_price))
                    continue

                success = _execute_buy(ContextInfo, account_id, account_type, stockcode, buy_volume, current_price, current_date, score=s)
                if success:
                    ContextInfo.positions[stockcode] = Position(
                        stockcode=stockcode,
                        buy_price=current_price,
                        buy_date=current_date,
                        volume=buy_volume,
                        buy_trading_day_idx=ContextInfo.trading_day_index
                    )
                    available_cash -= buy_volume * current_price
                    current_holdings += 1
        else:
            _log("[{0}] 大盘弱势，换仓日跳过买入".format(current_date))

    else:
        # 非换仓日：大盘连续2天OK才补仓
        if ContextInfo.market_ok_streak >= 2:
            current_holdings = len(ContextInfo.positions)
            cached = getattr(ContextInfo, 'ranked_candidates', (None, []))
            cand_date, candidates = cached
            if cand_date == current_date and current_holdings < MAX_POSITIONS and len(candidates) > 0:
                for stockcode, s in candidates:
                    if current_holdings >= MAX_POSITIONS:
                        break
                    if stockcode in ContextInfo.positions:
                        continue
                    if stockcode in sold_today:
                        continue
                    if stockcode not in hist_prices or len(hist_prices[stockcode]) < 70:
                        continue
                    if stockcode not in hist_volumes or len(hist_volumes[stockcode]) < 20:
                        continue

                    prices_arr = np.array(hist_prices[stockcode])
                    volumes_arr = np.array(hist_volumes[stockcode])
                    if not check_buy_signal(prices_arr, volumes_arr):
                        continue

                    current_price = float(prices_arr[-1])
                    buy_amount = calculate_buy_amount(ContextInfo.capital, available_cash, MAX_POSITIONS)
                    if buy_amount < 1000:
                        continue
                    buy_volume = int(buy_amount / current_price / 100) * 100
                    if buy_volume < 100:
                        _log("[{0}] 补仓跳过: {1} | 价格{2:.2f}元过高，资金不足以买1手".format(
                            current_date, stockcode, current_price))
                        continue

                    success = _execute_buy(ContextInfo, account_id, account_type, stockcode, buy_volume, current_price, current_date, score=s)
                    if success:
                        ContextInfo.positions[stockcode] = Position(
                            stockcode=stockcode,
                            buy_price=current_price,
                            buy_date=current_date,
                            volume=buy_volume,
                            buy_trading_day_idx=ContextInfo.trading_day_index
                        )
                        available_cash -= buy_volume * current_price
                        current_holdings += 1
        else:
            _log("[{0}] 大盘弱势，非换仓日跳过补仓".format(current_date))

    _log_status(ContextInfo, current_date)


def _filter_st_stocks(universe, ContextInfo):
    filtered = []
    fail_count = 0
    for stockcode in universe:
        try:
            detail = ContextInfo.get_instrumentdetail(stockcode)
            if detail and 'ST' in detail.get('m_strInstrumentName', ''):
                continue
        except Exception:
            fail_count += 1
        filtered.append(stockcode)
    if fail_count > 0:
        _log("[filter] ST过滤异常: {0}只股票详情获取失败，已保留".format(fail_count))
    return filtered


def _execute_buy(ContextInfo, account_id, account_type, stockcode, volume, price, trade_date, score=None):
    try:
        passorder(
            23,  # 买入
            1101,  # 按股数
            account_id,
            stockcode,
            5,  # 最新价
            -1.0,
            float(volume),
            ContextInfo
        )
        amount = volume * price
        commission = max(amount * 0.0001, 5.0)
        transfer_fee = amount * 0.00001
        slippage = amount * 0.0005
        total_cost = commission + transfer_fee + slippage
        ContextInfo.daily_cost = getattr(ContextInfo, 'daily_cost', 0.0) + total_cost
        score_str = " | 评分: {0:.4f}".format(score) if score is not None else ""
        _log("[{0}] >> 买入: {1} | {2}股 x {3:.2f}元 = {4:.0f}元 | 交易成本: {5:.2f}元{6}".format(
            trade_date, stockcode, volume, price, amount, total_cost, score_str))
        return True
    except Exception as e:
        _log("[{0}] !! 买入失败: {1} | {2}".format(trade_date, stockcode, e))
        return False


def _execute_sell(ContextInfo, account_id, account_type, stockcode, reason, trade_date):
    try:
        sell_volume = 0

        # 优先从QMT实际持仓获取可卖数量
        if account_id:
            try:
                position_list = get_trade_detail_data(account_id, account_type, 'POSITION')
                if position_list:
                    for p in position_list:
                        if p.m_strInstrumentID == stockcode:
                            sell_volume = int(p.m_nCanUseVolume) if hasattr(p, 'm_nCanUseVolume') else int(p.m_nVolume)
                            break
            except:
                pass

        # 回退到我们自己记录的数量
        if sell_volume <= 0 and stockcode in ContextInfo.positions:
            sell_volume = ContextInfo.positions[stockcode].volume

        if sell_volume <= 0:
            pos = ContextInfo.positions.get(stockcode)
            if pos:
                sell_volume = int(200000 / pos.buy_price / 100) * 100

        if sell_volume <= 0:
            sell_volume = 100

        passorder(
            24,  # 卖出
            1101,  # 按股数
            account_id,
            stockcode,
            5,  # 最新价
            -1.0,
            float(sell_volume),
            ContextInfo
        )

        reason_map = {
            'hard_stop': '硬止损',
            'trend_break': '破MA20',
            'trailing_stop': '跟踪止盈',
            'rebalance': '换仓调出',
            'crash_protection': '暴跌保护',
            'macd_weak': 'MACD衰竭',
            'market_weak': '大盘弱势清仓',
        }
        reason_cn = reason_map.get(reason, reason)
        pos = ContextInfo.positions.get(stockcode)
        if pos:
            pnl_pct = 0
            hist_prices_data = ContextInfo.get_history_data(1, '1d', 'close', dividend_type='front', skip_paused=True)
            if stockcode in hist_prices_data and len(hist_prices_data[stockcode]) > 0:
                current_price = float(hist_prices_data[stockcode][-1])
                pnl_pct = (current_price - pos.buy_price) / pos.buy_price * 100
            _log("[{0}] << 卖出: {1} | {2}股 | 原因: {3} | 持仓自: {4} | 盈亏: {5:+.2f}%".format(
                trade_date, stockcode, sell_volume, reason_cn, pos.buy_date, pnl_pct))
        else:
            _log("[{0}] << 卖出: {1} | {2}股 | 原因: {3}".format(
                trade_date, stockcode, sell_volume, reason_cn))
    except Exception as e:
        _log("[{0}] !! 卖出失败: {1} | {2}".format(trade_date, stockcode, e))


def _log_status(ContextInfo, current_date):
    holdings = list(ContextInfo.positions.keys())
    sold_records = getattr(ContextInfo, 'daily_sold_records', [])

    # 既无持仓也无卖出 → 空仓
    if len(holdings) == 0 and len(sold_records) == 0:
        total_assets = None
        account_id = getattr(ContextInfo, 'accountid', '')
        if account_id:
            try:
                acct_info = get_trade_detail_data(account_id, 'STOCK', 'ACCOUNT')
                if acct_info:
                    total_assets = acct_info[0].m_dBalance
            except Exception:
                pass
        if total_assets is None:
            realized_pnl = getattr(ContextInfo, 'realized_pnl', 0)
            total_assets = ContextInfo.capital + realized_pnl
        total_profit = total_assets - ContextInfo.capital
        _log("[{0}] 当前持仓: 空仓 | 总资产: {1:.0f}元 | 总盈亏: {2:+.0f}元".format(
            current_date, total_assets, total_profit))
        return

    # 获取最近2天收盘价，用于计算今日盈亏
    hist = ContextInfo.get_history_data(2, '1d', 'close', dividend_type='front', skip_paused=True)

    total_value = 0       # 持仓总市值
    total_pnl = 0         # 持仓总盈亏（含已卖出，仅用于展示）
    unrealized_pnl = 0    # 当前持仓未实现盈亏（用于总资产计算，避免与 realized_pnl 重复）
    total_today_pnl = 0   # 今日持仓盈亏（含已卖出）
    total_cost = 0        # 持仓总成本（含已卖出）

    # 1. 打印当前持仓
    if len(holdings) > 0:
        _log("[{0}] 当前持仓({1}只):".format(current_date, len(holdings)))
        for code in holdings:
            pos = ContextInfo.positions[code]
            if code in hist and len(hist[code]) >= 1:
                cur = float(hist[code][-1])
                value = cur * pos.volume                 # 持仓市值
                pnl = (cur - pos.buy_price) * pos.volume  # 持仓盈亏
                cost = pos.buy_price * pos.volume         # 持仓成本

                # 今日盈亏：今天买入的用买入价算；之前买入的用昨日收盘价算
                if len(hist[code]) >= 2 and pos.buy_date != current_date:
                    prev = float(hist[code][-2])
                    today_pnl = (cur - prev) * pos.volume
                    today_pnl_pct = ((cur - prev) / prev * 100) if prev > 0 else 0
                elif pos.buy_date == current_date:
                    today_pnl = (cur - pos.buy_price) * pos.volume
                    today_pnl_pct = ((cur - pos.buy_price) / pos.buy_price * 100) if pos.buy_price > 0 else 0
                else:
                    today_pnl = None
                    today_pnl_pct = None

                pnl_pct = ((cur - pos.buy_price) / pos.buy_price * 100) if pos.buy_price > 0 else 0

                if today_pnl is not None:
                    total_today_pnl += today_pnl
                    _log("  {0}: {1}股 | 成本{2:.2f} | 现价{3:.2f} | 市值{4:.0f}元 | 持仓盈亏{5:+.0f}元({6:+.2f}%) | 今日盈亏{7:+.0f}元({8:+.2f}%)".format(
                        code, pos.volume, pos.buy_price, cur, value, pnl, pnl_pct, today_pnl, today_pnl_pct))
                else:
                    _log("  {0}: {1}股 | 成本{2:.2f} | 现价{3:.2f} | 市值{4:.0f}元 | 持仓盈亏{5:+.0f}元({6:+.2f}%) | 今日盈亏: 无数据".format(
                        code, pos.volume, pos.buy_price, cur, value, pnl, pnl_pct))

                total_value += value
                total_pnl += pnl
                unrealized_pnl += pnl
                total_cost += cost
            else:
                _log("  {0}: 无行情数据".format(code))

    # 2. 打印今日卖出，并汇总盈亏
    if len(sold_records) > 0:
        _log("[{0}] 今日卖出({1}只):".format(current_date, len(sold_records)))
        for rec in sold_records:
            code = rec['stockcode']
            volume = rec['volume']
            buy_price = rec['buy_price']
            sell_price = rec['sell_price']
            reason = rec['reason']
            buy_date = rec['buy_date']

            pnl = (sell_price - buy_price) * volume
            pnl_pct = ((sell_price - buy_price) / buy_price * 100) if buy_price > 0 else 0

            # 今日盈亏
            if buy_date == current_date:
                today_pnl = pnl
                today_pnl_pct = pnl_pct
            elif code in hist and len(hist[code]) >= 2:
                prev = float(hist[code][-2])
                today_pnl = (sell_price - prev) * volume
                today_pnl_pct = ((sell_price - prev) / prev * 100) if prev > 0 else 0
            else:
                today_pnl = None
                today_pnl_pct = None

            if today_pnl is not None:
                total_today_pnl += today_pnl
                _log("  {0}: {1}股 | 成本{2:.2f} | 卖出价{3:.2f} | 持仓盈亏{4:+.0f}元({5:+.2f}%) | 今日盈亏{6:+.0f}元({7:+.2f}%) | 原因: {8}".format(
                    code, volume, buy_price, sell_price, pnl, pnl_pct, today_pnl, today_pnl_pct, reason))
            else:
                _log("  {0}: {1}股 | 成本{2:.2f} | 卖出价{3:.2f} | 持仓盈亏{4:+.0f}元({5:+.2f}%) | 今日盈亏: 无数据 | 原因: {6}".format(
                    code, volume, buy_price, sell_price, pnl, pnl_pct, reason))

            total_pnl += pnl
            total_cost += buy_price * volume

    # 3. 汇总
    total_assets = None
    account_id = getattr(ContextInfo, 'accountid', '')
    if account_id:
        try:
            acct_info = get_trade_detail_data(account_id, 'STOCK', 'ACCOUNT')
            if acct_info:
                total_assets = acct_info[0].m_dBalance
        except Exception:
            pass
    if total_assets is None:
        realized_pnl = getattr(ContextInfo, 'realized_pnl', 0)
        total_assets = ContextInfo.capital + realized_pnl + unrealized_pnl

    total_profit = total_assets - ContextInfo.capital
    total_profit_pct = (total_profit / ContextInfo.capital * 100) if ContextInfo.capital > 0 else 0
    total_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0
    yesterday_value = total_value - total_today_pnl
    total_today_pnl_pct = (total_today_pnl / yesterday_value * 100) if yesterday_value > 0 else 0

    # 资金余额
    cash_balance = None
    if account_id:
        try:
            acct_info = get_trade_detail_data(account_id, 'STOCK', 'ACCOUNT')
            if acct_info:
                cash_balance = acct_info[0].m_dAvailable
        except Exception:
            pass
    if cash_balance is None:
        cash_balance = total_assets - total_value

    daily_cost = getattr(ContextInfo, 'daily_cost', 0.0)
    total_cost_acc = getattr(ContextInfo, 'total_cost', 0.0) + daily_cost

    _log("[{0}] ====== 总资产: {1:.0f}元 | 总盈亏: {2:+.0f}元({3:+.2f}%) | 持仓总市值: {4:.0f}元 | 持仓总盈亏: {5:+.0f}元({6:+.2f}%) | 今日持仓盈亏: {7:+.0f}元({8:+.2f}%) | 资金余额: {9:.0f}元 | 当日交易成本: {10:.2f}元 | 累计交易成本: {11:.2f}元".format(
        current_date, total_assets, total_profit, total_profit_pct, total_value, total_pnl, total_pnl_pct, total_today_pnl, total_today_pnl_pct, cash_balance, daily_cost, total_cost_acc))
    _log("================================================")