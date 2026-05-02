# -*- coding: utf-8 -*-
"""
HS300 Trend Strategy

Logic:
1. Universe: CSI 300 components, updated daily
2. Entry: Triple confirmation (above MA60 + MA5>MA20 + MACD>0 + volume spike)
3. Exit: 3% hard stop / break MA20 / trailing stop after 5% profit
4. Position: max 5 stocks, 20% each
"""
# NOTE: When loading into QMT, change encoding to GBK and add `# -*- coding: gbk -*-`

import numpy as np

# QMT环境路径处理
import sys
# 注意: 实际使用QMT时，需要将路径修改为QMT客户端所在机器上的实际路径
sys.path.insert(0, '/Users/shezhidong/Documents/代码库/quant-trade')
from strategy.indicators import check_buy_signal
from strategy.portfolio import Position, check_stop_loss, check_trend_break, check_trailing_stop, calculate_buy_amount


# 全局配置
MAX_POSITIONS = 5
HARD_STOP_PCT = 0.03
PROFIT_THRESHOLD = 0.05
TRAILING_PULLBACK_PCT = 0.05


def init(ContextInfo):
    """初始化函数，策略启动时执行一次"""
    # 实盘时填入资金账号，例如: ContextInfo.set_account('6000000223')
    ContextInfo.set_account('')
    ContextInfo.capital = 1000000  # 回测初始资金100万

    # 持仓状态字典: {stockcode: Position}
    ContextInfo.positions = {}

    # 当日已处理标志
    ContextInfo.last_trade_date = None

    # 在init中预设universe，消除第一个bar的数据延迟
    universe = ContextInfo.get_sector('000300.SH')
    if universe:
        ContextInfo.set_universe(universe)


def handlebar(ContextInfo):
    """核心执行函数，每根K线调用一次"""
    current_date = timetag_to_datetime(ContextInfo.get_bar_timetag(ContextInfo.barpos), '%Y%m%d')

    if ContextInfo.last_trade_date == current_date:
        return
    ContextInfo.last_trade_date = current_date

    holdings = list(ContextInfo.positions.keys())
    print("[{0}] ===== 持仓: {1}只 {2} =====".format(current_date, len(holdings), holdings))

    # 1. 更新股票池（沪深300成分股）
    universe = ContextInfo.get_sector('000300.SH')
    if not universe:
        print("[{0}] 警告: 无法获取沪深300成分股".format(current_date))
        return

    # 将持仓股票加入universe（提前设置，下一个bar就能获取数据）
    held_stocks = list(ContextInfo.positions.keys())
    full_universe = list(set(universe + held_stocks))
    ContextInfo.set_universe(full_universe)

    # 过滤ST股（只过滤买入池，不影响卖出）
    buy_universe = _filter_st_stocks(universe, ContextInfo)

    # 2. 获取账户信息（实盘/模拟）
    account_id = ContextInfo.accountid if hasattr(ContextInfo, 'accountid') else ''
    account_type = 'STOCK'

    available_cash = ContextInfo.capital
    if account_id:
        acct_info = get_trade_detail_data(account_id, account_type, 'ACCOUNT')
        if acct_info:
            available_cash = acct_info[0].m_dAvailable

    # 3. 遍历现有持仓，检查止损/止盈
    positions_to_sell = []
    if len(ContextInfo.positions) > 0:
        hist_prices = ContextInfo.get_history_data(25, '1d', 'close', dividend_type='front', skip_paused=True)

        for stockcode, pos in list(ContextInfo.positions.items()):
            if stockcode not in hist_prices or len(hist_prices[stockcode]) < 1:
                print("[{0}] {1} 跳过卖出: 无数据".format(current_date, stockcode))
                continue

            prices_list = hist_prices[stockcode]
            current_price = float(prices_list[-1])

            if current_price > pos.highest_price:
                pos.highest_price = current_price

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
                positions_to_sell.append((stockcode, sell_reason))

    # 执行卖出
    for stockcode, reason in positions_to_sell:
        _execute_sell(ContextInfo, account_id, account_type, stockcode, reason, current_date)
        if stockcode in ContextInfo.positions:
            del ContextInfo.positions[stockcode]

    # 4. 检查买入信号（未满仓时）
    current_holdings = len(ContextInfo.positions)
    if current_holdings >= MAX_POSITIONS:
        _log_status(ContextInfo, current_date)
        return

    if account_id:
        acct_info = get_trade_detail_data(account_id, account_type, 'ACCOUNT')
        if acct_info:
            available_cash = acct_info[0].m_dAvailable

    # 一次性获取所有universe的历史数据
    hist_prices = ContextInfo.get_history_data(70, '1d', 'close', dividend_type='front', skip_paused=True)
    hist_volumes = ContextInfo.get_history_data(25, '1d', 'volume', dividend_type='front', skip_paused=True)

    for stockcode in buy_universe:
        if stockcode in ContextInfo.positions:
            continue

        if stockcode not in hist_prices or len(hist_prices[stockcode]) < 70:
            continue
        if stockcode not in hist_volumes or len(hist_volumes[stockcode]) < 20:
            continue

        prices_arr = np.array(hist_prices[stockcode])
        volumes_arr = np.array(hist_volumes[stockcode])

        if check_buy_signal(prices_arr, volumes_arr):
            buy_amount = calculate_buy_amount(ContextInfo.capital, available_cash, MAX_POSITIONS)
            if buy_amount < 1000:
                continue

            current_price = prices_arr[-1]
            buy_volume = int(buy_amount / current_price / 100) * 100
            if buy_volume < 100:
                continue

            success = _execute_buy(ContextInfo, account_id, account_type, stockcode, buy_volume, current_price, current_date)
            if success:
                ContextInfo.positions[stockcode] = Position(
                    stockcode=stockcode,
                    buy_price=current_price,
                    buy_date=current_date,
                    volume=buy_volume
                )
                available_cash -= buy_volume * current_price
                current_holdings += 1

                if current_holdings >= MAX_POSITIONS:
                    break

    _log_status(ContextInfo, current_date)


def _filter_st_stocks(universe, ContextInfo):
    """过滤ST股票"""
    filtered = []
    for stockcode in universe:
        # 通过股票名称判断是否ST
        # QMT中可以通过 get_instrumentdetail 获取股票详细信息
        # 简化处理：检查代码对应的名称是否包含 'ST'
        try:
            detail = ContextInfo.get_instrumentdetail(stockcode)
            if detail and 'ST' in detail.get('m_strInstrumentName', ''):
                continue
        except:
            pass
        filtered.append(stockcode)
    return filtered


def _execute_buy(ContextInfo, account_id, account_type, stockcode, volume, price, trade_date):
    """执行买入（按股数下单）"""
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
        print("[{0}] 买入: {1}, 数量: {2}股, 价格: {3:.2f}".format(trade_date, stockcode, volume, price))
        return True
    except Exception as e:
        print("[{0}] 买入失败 {1}: {2}".format(trade_date, stockcode, e))
        return False


def _execute_sell(ContextInfo, account_id, account_type, stockcode, reason, trade_date):
    """执行卖出（按股数下单）"""
    try:
        sell_volume = 0
        if stockcode in ContextInfo.positions:
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
        print("[{0}] 卖出: {1}, 数量: {2}股, 原因: {3}".format(trade_date, stockcode, sell_volume, reason))
    except Exception as e:
        print("[{0}] 卖出失败 {1}: {2}".format(trade_date, stockcode, e))


def _log_status(ContextInfo, current_date):
    """输出当前持仓状态"""
    holdings = list(ContextInfo.positions.keys())
    print("[{0}] 当前持仓({1}只): {2}".format(current_date, len(holdings), holdings))
