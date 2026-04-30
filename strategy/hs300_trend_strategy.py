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
    # 使用ContextInfo存储，保证跨bar持久化
    ContextInfo.positions = {}

    # 当日已处理标志（日线策略，每个交易日只执行一次交易逻辑）
    ContextInfo.last_trade_date = None


def handlebar(ContextInfo):
    """核心执行函数，每根K线调用一次"""
    # 只在最后一根K线执行（避免盘中反复计算）
    if not ContextInfo.is_last_bar():
        return

    # 获取当前日期
    current_date = timetag_to_datetime(ContextInfo.get_bar_timetag(ContextInfo.barpos), '%Y%m%d')

    # 日线策略：每个交易日只执行一次
    if ContextInfo.last_trade_date == current_date:
        return
    ContextInfo.last_trade_date = current_date

    # 1. 更新股票池（沪深300成分股）
    universe = ContextInfo.get_sector('000300.SH')
    if not universe:
        print(f"[{current_date}] 警告: 无法获取沪深300成分股")
        return
    ContextInfo.set_universe(universe)

    # 过滤ST股
    universe = _filter_st_stocks(universe, ContextInfo)

    # 2. 获取账户信息（实盘/模拟）
    account_id = ContextInfo.accountid if hasattr(ContextInfo, 'accountid') else ''
    account_type = 'STOCK'

    # 获取可用资金
    available_cash = ContextInfo.capital
    if account_id:
        acct_info = get_trade_detail_data(account_id, account_type, 'ACCOUNT')
        if acct_info:
            available_cash = acct_info[0].m_dAvailable

    # 3. 遍历现有持仓，检查止损/止盈
    positions_to_sell = []
    for stockcode, pos in list(ContextInfo.positions.items()):
        # 获取当前价格
        current_data = ContextInfo.get_market_data(['close'], [stockcode], period='1d', count=1)
        if current_data is None or stockcode not in current_data:
            continue
        current_price = current_data[stockcode]['close'].values[-1]

        # 获取20日均线
        hist_prices = ContextInfo.get_history_data(25, '1d', 'close', dividend_type='front', skip_paused=True)
        if stockcode not in hist_prices or len(hist_prices[stockcode]) < 20:
            continue
        prices_arr = np.array(hist_prices[stockcode])
        ma20 = np.mean(prices_arr[-20:])

        # 检查三个卖出条件
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
        _execute_sell(ContextInfo, account_id, account_type, stockcode, reason)
        if stockcode in ContextInfo.positions:
            del ContextInfo.positions[stockcode]

    # 4. 检查买入信号（未满仓时）
    current_holdings = len(ContextInfo.positions)
    if current_holdings >= MAX_POSITIONS:
        _log_status(ContextInfo, current_date)
        return

    # 获取可用资金（卖出后可能增加了）
    if account_id:
        acct_info = get_trade_detail_data(account_id, account_type, 'ACCOUNT')
        if acct_info:
            available_cash = acct_info[0].m_dAvailable

    for stockcode in universe:
        # 已持仓的不重复买入
        if stockcode in ContextInfo.positions:
            continue

        # 获取历史数据
        hist_prices = ContextInfo.get_history_data(70, '1d', 'close', dividend_type='front', skip_paused=True)
        hist_volumes = ContextInfo.get_history_data(25, '1d', 'volume', dividend_type='front', skip_paused=True)

        if stockcode not in hist_prices or len(hist_prices[stockcode]) < 70:
            continue
        if stockcode not in hist_volumes or len(hist_volumes[stockcode]) < 20:
            continue

        prices_arr = np.array(hist_prices[stockcode])
        volumes_arr = np.array(hist_volumes[stockcode])

        # 检查买入信号
        if check_buy_signal(prices_arr, volumes_arr):
            # 计算买入金额
            buy_amount = calculate_buy_amount(ContextInfo.capital, available_cash, MAX_POSITIONS)
            if buy_amount < 1000:  # 最小买入金额
                continue

            # 执行买入
            success = _execute_buy(ContextInfo, account_id, account_type, stockcode, buy_amount)
            if success:
                # 记录持仓
                current_price = prices_arr[-1]
                ContextInfo.positions[stockcode] = Position(
                    stockcode=stockcode,
                    buy_price=current_price,
                    buy_date=current_date,
                    volume=0  # QMT中通过get_trade_detail_data查询实际成交
                )
                available_cash -= buy_amount
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


def _execute_buy(ContextInfo, account_id, account_type, stockcode, amount):
    """执行买入"""
    try:
        passorder(
            23,  # 买入
            1102,  # 按金额
            account_id,
            stockcode,
            0,  # 最新价
            -1,
            amount,
            ContextInfo,
            'hs300_trend_strategy',
            1  # quickTrade=1，立即触发
        )
        print(f"买入信号: {stockcode}, 金额: {amount}")
        return True
    except Exception as e:
        print(f"买入失败 {stockcode}: {e}")
        return False


def _execute_sell(ContextInfo, account_id, account_type, stockcode, reason):
    """执行卖出"""
    try:
        passorder(
            24,  # 卖出
            1101,  # 按股数
            account_id,
            stockcode,
            0,  # 最新价
            -1,
            -1,  # 全仓卖出
            ContextInfo,
            'hs300_trend_strategy',
            1  # quickTrade=1
        )
        print(f"卖出信号: {stockcode}, 原因: {reason}")
    except Exception as e:
        print(f"卖出失败 {stockcode}: {e}")


def _log_status(ContextInfo, current_date):
    """输出当前持仓状态"""
    holdings = list(ContextInfo.positions.keys())
    log_msg = f"[{current_date}] 当前持仓({len(holdings)}只): {holdings}"
    print(log_msg)
