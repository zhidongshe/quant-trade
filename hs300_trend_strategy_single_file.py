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


# ==================== 持仓管理模块 ====================

class Position:
    def __init__(self, stockcode, buy_price, buy_date, volume):
        self.stockcode = stockcode
        self.buy_price = buy_price
        self.buy_date = buy_date
        self.volume = volume
        self.highest_price = buy_price


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
HARD_STOP_PCT = 0.03
PROFIT_THRESHOLD = 0.05
TRAILING_PULLBACK_PCT = 0.05
REBALANCE_INTERVAL = 10  # 每10个交易日换仓（约两周）


# ==================== QMT策略主函数 ====================

def init(ContextInfo):
    ContextInfo.set_account('8890358835')
    ContextInfo.capital = 1000000

    ContextInfo.positions = {}
    ContextInfo.last_trade_date = None
    ContextInfo.accountid = '8890358835'

    ContextInfo.rebalance_count = 0
    ContextInfo.last_rebalance_date = None
    ContextInfo.ranked_candidates = []

    universe = ContextInfo.get_sector('000300.SH')
    if universe:
        ContextInfo.set_universe(universe)


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
            if code != raw_code:
                _log("[{0}] 代码标准化: {1} → {2}".format(current_date, raw_code, code))
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

        # 我们有但QMT已经没有的 → 清除
        for code in list(ContextInfo.positions.keys()):
            if code not in qmt_holdings:
                _log("[{0}] 清除失效持仓: {1}".format(current_date, code))
                del ContextInfo.positions[code]

    except Exception as e:
        _log("[{0}] 持仓同步异常: {1}".format(current_date, e))


def handlebar(ContextInfo):
    current_date = timetag_to_datetime(ContextInfo.get_bar_timetag(ContextInfo.barpos), '%Y%m%d')

    if ContextInfo.last_trade_date == current_date:
        return
    ContextInfo.last_trade_date = current_date

    # 从QMT实际持仓同步，防止positions字典和QMT脱节
    account_id = ContextInfo.accountid if hasattr(ContextInfo, 'accountid') else ''
    _sync_positions(ContextInfo, account_id, 'STOCK', current_date)

    holdings = list(ContextInfo.positions.keys())
    _log("[{0}] ===== 日期: {0} | 持仓: {1}只 | 距下次换仓: {2}个交易日 =====".format(
        current_date, len(holdings),
        REBALANCE_INTERVAL - getattr(ContextInfo, 'rebalance_count', 0)
    ))

    # 1. 更新股票池
    universe = ContextInfo.get_sector('000300.SH')
    if not universe:
        _log("[{0}] 警告: 无法获取沪深300成分股".format(current_date))
        return

    # 将持仓股票加入universe（提前设置，下一个bar就能获取数据）
    held_stocks = list(ContextInfo.positions.keys())
    full_universe = list(set(universe + held_stocks))
    ContextInfo.set_universe(full_universe)

    # 过滤ST股（只过滤买入池，不影响卖出）
    buy_universe = _filter_st_stocks(universe, ContextInfo)

    # 2. 获取账户信息
    account_type = 'STOCK'

    available_cash = ContextInfo.capital
    if account_id:
        acct_info = get_trade_detail_data(account_id, account_type, 'ACCOUNT')
        if acct_info:
            available_cash = acct_info[0].m_dAvailable

    # 3. 遍历现有持仓，检查止损/止盈
    # 用get_history_data获取所有universe内股票的收盘价（一次调用拿全部）
    positions_to_sell = []
    if len(ContextInfo.positions) > 0:
        hist_prices = ContextInfo.get_history_data(25, '1d', 'close', dividend_type='front', skip_paused=True)

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

            should_sell = False
            sell_reason = ''

            if check_stop_loss(pos, current_price, HARD_STOP_PCT):
                should_sell = True
                sell_reason = 'hard_stop'
            elif check_trend_break(current_price, ma20):
                should_sell = True
                sell_reason = 'trend_break'
            elif check_trailing_stop(pos, current_price, PROFIT_THRESHOLD, TRAILING_PULLBACK_PCT):
                should_sell = True
                sell_reason = 'trailing_stop'

            if should_sell:
                pnl_pct = (current_price - pos.buy_price) / pos.buy_price * 100
                _log("[{0}] 触发卖出: {1} | 原因: {2} | 买入价: {3:.2f} | 现价: {4:.2f} | 盈亏: {5:+.2f}%".format(
                    current_date, stockcode, sell_reason, pos.buy_price, current_price, pnl_pct))
                positions_to_sell.append((stockcode, sell_reason))

    # 执行卖出
    for stockcode, reason in positions_to_sell:
        _execute_sell(ContextInfo, account_id, account_type, stockcode, reason, current_date)
        if stockcode in ContextInfo.positions:
            del ContextInfo.positions[stockcode]

    # 4. 换仓/补仓逻辑
    ContextInfo.rebalance_count = getattr(ContextInfo, 'rebalance_count', 0) + 1
    is_rebalance_day = (ContextInfo.rebalance_count >= REBALANCE_INTERVAL)

    if account_id:
        acct_info = get_trade_detail_data(account_id, account_type, 'ACCOUNT')
        if acct_info:
            available_cash = acct_info[0].m_dAvailable

    # 一次性获取所有universe的历史数据
    hist_prices = ContextInfo.get_history_data(70, '1d', 'close', dividend_type='front', skip_paused=True)
    hist_volumes = ContextInfo.get_history_data(25, '1d', 'volume', dividend_type='front', skip_paused=True)

    if is_rebalance_day:
        ContextInfo.rebalance_count = 0
        ContextInfo.last_rebalance_date = current_date

        # 对所有候选股打分
        scored = []
        for stockcode in buy_universe:
            if stockcode not in hist_prices or len(hist_prices[stockcode]) < 70:
                continue
            if stockcode not in hist_volumes or len(hist_volumes[stockcode]) < 20:
                continue
            prices_arr = np.array(hist_prices[stockcode])
            volumes_arr = np.array(hist_volumes[stockcode])
            s = score_stock(prices_arr, volumes_arr)
            if s is not None:
                scored.append((stockcode, s))

        scored.sort(key=lambda x: x[1], reverse=True)
        top_n = scored[:MAX_POSITIONS]
        top_codes = [x[0] for x in top_n]
        ContextInfo.ranked_candidates = scored

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
        to_sell = old_holdings - new_holdings
        to_buy = new_holdings - old_holdings
        to_keep = old_holdings & new_holdings
        if to_keep:
            _log("[{0}] 继续持有: {1}".format(current_date, list(to_keep)))
        if to_sell:
            _log("[{0}] 换仓卖出: {1}".format(current_date, list(to_sell)))
        if to_buy:
            _log("[{0}] 换仓买入: {1}".format(current_date, list(to_buy)))

        # 卖出不在新Top N中的持仓
        for stockcode in list(ContextInfo.positions.keys()):
            if stockcode not in top_codes:
                _execute_sell(ContextInfo, account_id, account_type, stockcode, 'rebalance', current_date)
                if stockcode in ContextInfo.positions:
                    del ContextInfo.positions[stockcode]

        # 买入新Top N中未持仓的
        current_holdings = len(ContextInfo.positions)
        for stockcode, s in top_n:
            if current_holdings >= MAX_POSITIONS:
                break
            if stockcode in ContextInfo.positions:
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
                continue

            success = _execute_buy(ContextInfo, account_id, account_type, stockcode, buy_volume, current_price, current_date, score=s)
            if success:
                ContextInfo.positions[stockcode] = Position(
                    stockcode=stockcode,
                    buy_price=current_price,
                    buy_date=current_date,
                    volume=buy_volume
                )
                available_cash -= buy_volume * current_price
                current_holdings += 1

    else:
        # 非换仓日：如果止损导致有空仓位，从缓存排名中补仓
        current_holdings = len(ContextInfo.positions)
        candidates = getattr(ContextInfo, 'ranked_candidates', [])
        if current_holdings < MAX_POSITIONS and len(candidates) > 0:
            for stockcode, s in candidates:
                if current_holdings >= MAX_POSITIONS:
                    break
                if stockcode in ContextInfo.positions:
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
                    continue

                success = _execute_buy(ContextInfo, account_id, account_type, stockcode, buy_volume, current_price, current_date, score=s)
                if success:
                    ContextInfo.positions[stockcode] = Position(
                        stockcode=stockcode,
                        buy_price=current_price,
                        buy_date=current_date,
                        volume=buy_volume
                    )
                    available_cash -= buy_volume * current_price
                    current_holdings += 1

    _log_status(ContextInfo, current_date)


def _filter_st_stocks(universe, ContextInfo):
    filtered = []
    for stockcode in universe:
        try:
            detail = ContextInfo.get_instrumentdetail(stockcode)
            if detail and 'ST' in detail.get('m_strInstrumentName', ''):
                continue
        except:
            pass
        filtered.append(stockcode)
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
        score_str = " | 评分: {0:.4f}".format(score) if score is not None else ""
        _log("[{0}] >> 买入: {1} | {2}股 x {3:.2f}元 = {4:.0f}元{5}".format(
            trade_date, stockcode, volume, price, amount, score_str))
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
    if len(holdings) == 0:
        _log("[{0}] 当前持仓: 空仓".format(current_date))
        return

    # 尝试获取最新价格计算浮动盈亏
    lines = []
    total_pnl = 0
    total_value = 0
    hist = ContextInfo.get_history_data(1, '1d', 'close', dividend_type='front', skip_paused=True)
    for code in holdings:
        pos = ContextInfo.positions[code]
        if code in hist and len(hist[code]) > 0:
            cur = float(hist[code][-1])
            pnl = (cur - pos.buy_price) / pos.buy_price * 100
            value = cur * pos.volume
            total_pnl += (cur - pos.buy_price) * pos.volume
            total_value += value
            lines.append("  {0}: {1}股 | 成本{2:.2f} | 现价{3:.2f} | {4:+.2f}%".format(
                code, pos.volume, pos.buy_price, cur, pnl))
        else:
            lines.append("  {0}: {1}股 | 成本{2:.2f} | 现价: 无数据".format(
                code, pos.volume, pos.buy_price))

    _log("[{0}] 当前持仓({1}只):".format(current_date, len(holdings)))
    for line in lines:
        _log(line)
    if total_value > 0:
        _log("[{0}] 持仓总市值: {1:.0f}元 | 浮动盈亏: {2:+.0f}元".format(
            current_date, total_value, total_pnl))
