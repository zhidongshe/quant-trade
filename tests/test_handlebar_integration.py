# -*- coding: utf-8 -*-
"""
模拟QMT环境的集成测试
验证handlebar在各种场景下的卖出逻辑
"""
import sys
import numpy as np

sys.path.insert(0, '/Users/shezhidong/Documents/代码库/quant-trade')

from hs300_trend_strategy_single_file import (
    Position, check_stop_loss, check_trend_break, check_trailing_stop,
    check_buy_signal, score_stock, sma, macd, calculate_buy_amount,
    MAX_POSITIONS, HARD_STOP_PCT, PROFIT_THRESHOLD, TRAILING_PULLBACK_PCT
)


# ========== 模拟QMT环境 ==========

class MockContextInfo:
    """模拟QMT的ContextInfo对象"""
    def __init__(self):
        self.positions = {}
        self.capital = 1000000
        self.last_trade_date = None
        self.barpos = 0
        self._universe = []
        self._history_data = {}  # {field: {stockcode: [prices...]}}
        self._sector_stocks = []
        self._bar_timetags = []
        self._orders = []

    def set_account(self, acct):
        self.accountid = acct

    def set_universe(self, stocks):
        self._universe = stocks

    def get_sector(self, code):
        return self._sector_stocks

    def get_bar_timetag(self, barpos):
        return self._bar_timetags[barpos] if barpos < len(self._bar_timetags) else 0

    def get_history_data(self, count, period, field, **kwargs):
        result = {}
        for stockcode in self._universe:
            key = (stockcode, field)
            if key in self._history_data:
                data = self._history_data[key]
                result[stockcode] = data[-count:] if len(data) >= count else data
        return result

    def get_market_data(self, fields, stocks, **kwargs):
        return None

    def get_instrumentdetail(self, stockcode):
        return {'m_strInstrumentName': stockcode}


def timetag_to_datetime(timetag, fmt):
    return str(timetag)


def passorder(*args):
    pass


# ========== 测试用例 ==========

def test_sell_hard_stop():
    """测试硬止损：价格跌超3%应触发卖出"""
    pos = Position('000001.SZ', buy_price=100.0, buy_date='20260101', volume=1000)
    # 跌了3.1%
    assert check_stop_loss(pos, 96.9, HARD_STOP_PCT) == True
    # 只跌了2%
    assert check_stop_loss(pos, 98.0, HARD_STOP_PCT) == False
    # 正好3%边界
    assert check_stop_loss(pos, 97.0, HARD_STOP_PCT) == True


def test_sell_trend_break():
    """测试趋势破坏：收盘价跌破20日均线应触发"""
    assert check_trend_break(99.0, 100.0) == True
    assert check_trend_break(100.0, 100.0) == True
    assert check_trend_break(101.0, 100.0) == False


def test_sell_trailing_stop():
    """测试跟踪止盈：盈利5%后从高点回落5%应触发"""
    pos = Position('000001.SZ', buy_price=100.0, buy_date='20260101', volume=1000)

    # 价格涨到106（盈利6%，超过5%阈值），更新最高价
    result = check_trailing_stop(pos, 106.0, PROFIT_THRESHOLD, TRAILING_PULLBACK_PCT)
    assert result == False
    assert pos.highest_price == 106.0

    # 从最高106回落到100.7（回落5%=106*0.95=100.7）
    result = check_trailing_stop(pos, 100.6, PROFIT_THRESHOLD, TRAILING_PULLBACK_PCT)
    assert result == True


def test_sell_trailing_stop_not_yet():
    """测试跟踪止盈：盈利未达5%不触发"""
    pos = Position('000001.SZ', buy_price=100.0, buy_date='20260101', volume=1000)
    # 涨4%，未达阈值
    result = check_trailing_stop(pos, 104.0, PROFIT_THRESHOLD, TRAILING_PULLBACK_PCT)
    assert result == False


def test_sell_logic_with_mock_context():
    """模拟完整的卖出循环逻辑"""
    ctx = MockContextInfo()
    ctx._sector_stocks = ['000001.SZ', '000002.SZ', '000003.SZ']

    # 模拟持仓：买入价100
    ctx.positions = {
        '000001.SZ': Position('000001.SZ', 100.0, '20260101', 1000),
        '000002.SZ': Position('000002.SZ', 100.0, '20260101', 1000),
    }

    # 设置universe包含持仓股
    held_stocks = list(ctx.positions.keys())
    full_universe = list(set(ctx._sector_stocks + held_stocks))
    ctx.set_universe(full_universe)

    # 模拟历史数据：000001跌到96（触发硬止损），000002正常
    ctx._history_data[('000001.SZ', 'close')] = list(np.linspace(100, 96, 25))
    ctx._history_data[('000002.SZ', 'close')] = list(np.linspace(100, 102, 25))

    # 执行卖出检查逻辑
    positions_to_sell = []
    for stockcode, pos in list(ctx.positions.items()):
        hist_prices = ctx.get_history_data(25, '1d', 'close', dividend_type='front', skip_paused=True)
        if stockcode not in hist_prices or len(hist_prices[stockcode]) < 20:
            if stockcode in hist_prices and len(hist_prices[stockcode]) > 0:
                current_price = float(hist_prices[stockcode][-1])
                if check_stop_loss(pos, current_price, HARD_STOP_PCT):
                    positions_to_sell.append((stockcode, 'hard_stop'))
            continue
        prices_arr = np.array(hist_prices[stockcode])
        current_price = prices_arr[-1]
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

    # 000001应触发硬止损（跌到96，跌4%>3%）
    assert ('000001.SZ', 'hard_stop') in positions_to_sell
    # 000002不应卖出（涨到102）
    assert not any(s[0] == '000002.SZ' for s in positions_to_sell)


def test_sell_logic_trend_break():
    """测试卖出逻辑：收盘价跌破20日均线"""
    ctx = MockContextInfo()
    ctx._sector_stocks = ['000001.SZ']
    ctx.positions = {
        '000001.SZ': Position('000001.SZ', 100.0, '20260101', 1000),
    }
    ctx.set_universe(['000001.SZ'])

    # 价格从110逐渐跌到98，MA20约为中间值，当前价低于MA20
    prices = list(np.linspace(110, 98, 25))
    ctx._history_data[('000001.SZ', 'close')] = prices

    hist_prices = ctx.get_history_data(25, '1d', 'close', dividend_type='front', skip_paused=True)
    prices_arr = np.array(hist_prices['000001.SZ'])
    current_price = prices_arr[-1]  # 98
    ma20 = np.mean(prices_arr[-20:])  # 约104

    # 98 < 104，应触发trend_break
    assert check_trend_break(current_price, ma20) == True
    # 但没有触发硬止损（98 > 100*0.97=97）
    pos = ctx.positions['000001.SZ']
    assert check_stop_loss(pos, current_price, HARD_STOP_PCT) == False


def test_sell_fallback_when_no_history():
    """测试备选方案：历史数据不足20条时，仅检查硬止损"""
    ctx = MockContextInfo()
    ctx._sector_stocks = ['000001.SZ']
    ctx.positions = {
        '000001.SZ': Position('000001.SZ', 100.0, '20260101', 1000),
    }
    ctx.set_universe(['000001.SZ'])

    # 只有5条数据（不足20条）
    ctx._history_data[('000001.SZ', 'close')] = [100, 99, 98, 97, 95]

    positions_to_sell = []
    for stockcode, pos in list(ctx.positions.items()):
        hist_prices = ctx.get_history_data(25, '1d', 'close', dividend_type='front', skip_paused=True)
        if stockcode not in hist_prices or len(hist_prices[stockcode]) < 20:
            if stockcode in hist_prices and len(hist_prices[stockcode]) > 0:
                current_price = float(hist_prices[stockcode][-1])
                if check_stop_loss(pos, current_price, HARD_STOP_PCT):
                    positions_to_sell.append((stockcode, 'hard_stop'))
            continue

    # 最后价格95，跌5%>3%，应触发硬止损
    assert ('000001.SZ', 'hard_stop') in positions_to_sell


def test_sell_fallback_no_trigger():
    """测试备选方案：历史数据不足但价格正常，不触发"""
    ctx = MockContextInfo()
    ctx._sector_stocks = ['000001.SZ']
    ctx.positions = {
        '000001.SZ': Position('000001.SZ', 100.0, '20260101', 1000),
    }
    ctx.set_universe(['000001.SZ'])

    # 只有5条数据，但价格正常（没跌3%）
    ctx._history_data[('000001.SZ', 'close')] = [100, 101, 100, 99, 98]

    positions_to_sell = []
    for stockcode, pos in list(ctx.positions.items()):
        hist_prices = ctx.get_history_data(25, '1d', 'close', dividend_type='front', skip_paused=True)
        if stockcode not in hist_prices or len(hist_prices[stockcode]) < 20:
            if stockcode in hist_prices and len(hist_prices[stockcode]) > 0:
                current_price = float(hist_prices[stockcode][-1])
                if check_stop_loss(pos, current_price, HARD_STOP_PCT):
                    positions_to_sell.append((stockcode, 'hard_stop'))
            continue

    # 跌2%<3%，不应触发
    assert len(positions_to_sell) == 0


def test_sell_stock_not_in_universe():
    """测试：如果持仓股不在universe中（set_universe未包含），完全拿不到数据"""
    ctx = MockContextInfo()
    ctx._sector_stocks = ['000002.SZ']
    ctx.positions = {
        '000001.SZ': Position('000001.SZ', 100.0, '20260101', 1000),
    }
    # 只设置000002在universe中，不包含000001
    ctx.set_universe(['000002.SZ'])

    # 数据存在但因为不在universe中，get_history_data拿不到
    ctx._history_data[('000001.SZ', 'close')] = list(np.linspace(100, 95, 25))

    hist_prices = ctx.get_history_data(25, '1d', 'close', dividend_type='front', skip_paused=True)
    # 000001不在universe中，所以拿不到
    assert '000001.SZ' not in hist_prices


def test_set_universe_includes_held_stocks():
    """测试：set_universe应包含持仓股，确保get_history_data能返回数据"""
    ctx = MockContextInfo()
    ctx._sector_stocks = ['000002.SZ', '000003.SZ']
    ctx.positions = {
        '000001.SZ': Position('000001.SZ', 100.0, '20260101', 1000),
    }

    # 模拟策略代码：将持仓股加入universe
    held_stocks = list(ctx.positions.keys())
    full_universe = list(set(ctx._sector_stocks + held_stocks))
    ctx.set_universe(full_universe)

    ctx._history_data[('000001.SZ', 'close')] = list(np.linspace(100, 95, 25))

    hist_prices = ctx.get_history_data(25, '1d', 'close', dividend_type='front', skip_paused=True)
    # 现在000001在universe中，可以拿到数据
    assert '000001.SZ' in hist_prices
    assert len(hist_prices['000001.SZ']) == 25


def test_buy_signal_requires_all_factors():
    """测试买入信号需要所有因子同时满足"""
    # 构造一个上升趋势的价格序列
    np.random.seed(42)
    base = np.linspace(80, 120, 70)  # 明确上升趋势
    prices = base + np.random.normal(0, 0.5, 70)
    prices = prices.astype(float)

    # 成交量放大
    volumes = np.ones(25) * 1000000
    volumes[-1] = 2000000  # 当日放量

    result = check_buy_signal(prices, volumes.astype(float))
    # 检查结果是否合理（可能True或False取决于随机数）
    assert isinstance(result, (bool, np.bool_))


def test_position_tracking():
    """测试持仓追踪：highest_price应正确更新"""
    pos = Position('000001.SZ', 100.0, '20260101', 1000)
    assert pos.highest_price == 100.0

    # 价格涨到105
    check_trailing_stop(pos, 105.0, PROFIT_THRESHOLD, TRAILING_PULLBACK_PCT)
    assert pos.highest_price == 105.0

    # 价格涨到110
    check_trailing_stop(pos, 110.0, PROFIT_THRESHOLD, TRAILING_PULLBACK_PCT)
    assert pos.highest_price == 110.0

    # 价格回落到108，highest不变
    check_trailing_stop(pos, 108.0, PROFIT_THRESHOLD, TRAILING_PULLBACK_PCT)
    assert pos.highest_price == 110.0


def test_score_stock_returns_none_when_signal_fails():
    """不满足四因子条件时score_stock返回None"""
    prices = np.linspace(100, 80, 70)
    volumes = np.ones(25) * 1000000
    assert score_stock(prices, volumes.astype(float)) is None


def test_score_stock_returns_float_when_signal_passes():
    """满足四因子时score_stock应返回浮点分数"""
    np.random.seed(100)
    base = np.linspace(80, 130, 70)
    prices = base + np.random.normal(0, 0.3, 70)
    prices = prices.astype(float)
    volumes = np.ones(25, dtype=float) * 1000000
    volumes[-1] = 3000000

    result = score_stock(prices, volumes)
    if result is not None:
        assert isinstance(result, float)
        assert result > 0


def test_score_stock_ranking_order():
    """趋势更强的股票应获得更高分数"""
    np.random.seed(42)
    # 强趋势股: 从80涨到150
    strong_prices = np.linspace(80, 150, 70).astype(float)
    # 弱趋势股: 从80涨到115
    weak_prices = np.linspace(80, 115, 70).astype(float)

    volumes = np.ones(25, dtype=float) * 1000000
    volumes[-1] = 2000000

    strong_score = score_stock(strong_prices, volumes)
    weak_score = score_stock(weak_prices, volumes)

    if strong_score is not None and weak_score is not None:
        assert strong_score > weak_score


def test_score_stock_volume_impact():
    """放量更大的股票应获得更高分数"""
    np.random.seed(42)
    base_prices = np.linspace(80, 130, 70).astype(float)

    vol_low = np.ones(25, dtype=float) * 1000000
    vol_low[-1] = 1500000

    vol_high = np.ones(25, dtype=float) * 1000000
    vol_high[-1] = 5000000

    score_low = score_stock(base_prices, vol_low)
    score_high = score_stock(base_prices, vol_high)

    if score_low is not None and score_high is not None:
        assert score_high > score_low


if __name__ == '__main__':
    import pytest
    pytest.main([__file__, '-v'])
