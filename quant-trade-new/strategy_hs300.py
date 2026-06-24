# -*- coding: utf-8 -*-
"""沪深300多头趋势策略 — QMT 实盘/本地回测两用单文件版。

部署到 QMT 时改首行为 # -*- coding: gbk -*-，并修改 init() 里的 set_account。
本地回测时由 backtest/shim.py 注入 QMT 全局函数。
策略业务规则与 hs300_trend_strategy_single_file_v1.py 完全一致，仅整理结构。
"""

import numpy as np
import os
from datetime import datetime

# ════════════════════════════════════════════════════
# §A 配置常量
# ════════════════════════════════════════════════════

ACCOUNT_ID = '8890358835'  # 实盘部署时改成你的账号
ACCOUNT_TYPE = 'STOCK'
MAX_POSITIONS = 5
HARD_STOP_PCT = 0.05
PROFIT_THRESHOLD = 0.10
TRAILING_PULLBACK = 0.08
REBALANCE_INTERVAL = 10
INDEX_CODE = '000300.SH'

WEIGHTS = {'trend': 0.30, 'spread': 0.25, 'macd': 0.25, 'volume': 0.20}

COST = {
    'commission': 0.0001,
    'commission_min': 5.0,
    'stamp': 0.001,
    'transfer': 0.00001,
    'slippage': 0.0005,
}


# ════════════════════════════════════════════════════
# §C 指标计算（纯函数）
# ════════════════════════════════════════════════════

def sma(prices, period):
    """简单移动平均，长度不足时返回全 nan。与 v1 行为一致。"""
    prices = np.asarray(prices, dtype=float)
    if len(prices) < period:
        return np.full_like(prices, np.nan, dtype=float)
    result = np.full_like(prices, np.nan, dtype=float)
    cumsum = np.cumsum(np.insert(prices, 0, 0))
    result[period - 1:] = (cumsum[period:] - cumsum[:-period]) / period
    return result


def macd(prices, fast=12, slow=26, signal=9):
    """MACD (dif, dea, hist)。EMA 实现与 v1 一致。"""
    prices = np.asarray(prices, dtype=float)

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
    """四因子入场。逻辑字面复制 v1 行 87-115。"""
    prices = np.asarray(prices, dtype=float)
    volumes = np.asarray(volumes, dtype=float)

    if len(prices) < 70 or len(volumes) < 20:
        return False

    ma60 = sma(prices, 60)
    if np.isnan(ma60[-1]) or prices[-1] <= ma60[-1]:
        return False

    ma5 = sma(prices, 5)
    ma20 = sma(prices, 20)
    if np.isnan(ma5[-1]) or np.isnan(ma20[-1]) or ma5[-1] <= ma20[-1]:
        return False

    _, _, hist = macd(prices)
    if hist[-1] <= 0:
        return False
    if len(hist) >= 3 and hist[-1] <= hist[-2]:
        return False

    if len(prices) >= 2 and prices[-1] <= prices[-2] * 1.01:
        return False

    vol_ma20 = sma(volumes, 20)
    if np.isnan(vol_ma20[-1]) or volumes[-1] <= vol_ma20[-1]:
        return False

    return True


def score_factors(prices, volumes):
    """对满足四因子的票返回 4 维原始因子；不满足返回 None。
    逻辑字面复制 v1 行 118-144（v1 中函数名为 score_stock）。"""
    if not check_buy_signal(prices, volumes):
        return None

    prices = np.asarray(prices, dtype=float)
    volumes = np.asarray(volumes, dtype=float)
    price = prices[-1]

    ma60 = sma(prices, 60)
    trend_score = (price - ma60[-1]) / ma60[-1]

    ma5 = sma(prices, 5)
    ma20 = sma(prices, 20)
    ma_spread_score = (ma5[-1] - ma20[-1]) / ma20[-1]

    _, _, hist = macd(prices)
    macd_score = hist[-1] / ma20[-1]

    vol_ma20 = sma(volumes, 20)
    ratio = volumes[-1] / vol_ma20[-1] if vol_ma20[-1] > 0 else 1.0
    volume_score = float(np.log(max(ratio, 0.01)))

    return {
        'trend_score': float(trend_score),
        'ma_spread_score': float(ma_spread_score),
        'macd_score': float(macd_score),
        'volume_score': float(volume_score),
    }


# ════════════════════════════════════════════════════
# §D 持仓与风控（纯函数）
# ════════════════════════════════════════════════════

class Position:
    """简单持仓对象。v1 用法逐字保留。"""
    def __init__(self, stockcode, buy_price, buy_date, volume, buy_trading_day_idx=0):
        self.stockcode = stockcode
        self.buy_price = buy_price
        self.buy_date = buy_date
        self.volume = volume
        self.highest_price = buy_price
        self.buy_trading_day_idx = buy_trading_day_idx


def check_hard_stop(pos, current_price, hard_stop_pct=0.03):
    """硬止损。v1 行 159-162。注意：v1 默认参数 0.03，但 handlebar 传入 HARD_STOP_PCT=0.05。"""
    return bool(current_price <= pos.buy_price * (1 - hard_stop_pct))


def check_crash(prices):
    """单日暴跌 -7% 保护。v1 handlebar 行 439-444 内嵌。"""
    prices = np.asarray(prices, dtype=float)
    if len(prices) < 2:
        return False
    daily_change = (prices[-1] - prices[-2]) / prices[-2] if prices[-2] > 0 else 0
    return bool(daily_change <= -0.07)


def check_trend_break(current_price, ma20, hist):
    """跌破 MA20 + MACD 衰竭双确认。v1 handlebar 行 447-452 内嵌逻辑。"""
    hist = np.asarray(hist, dtype=float)
    macd_weakening = (hist[-1] <= 0) and (len(hist) >= 2) and (hist[-1] <= hist[-2])
    return bool((current_price <= ma20) and macd_weakening)


def check_trailing_stop(pos, current_price, profit_threshold=0.05, pullback_pct=0.05):
    """跟踪止盈。v1 行 171-183。"""
    if current_price > pos.highest_price:
        pos.highest_price = current_price
    max_profit_pct = (pos.highest_price - pos.buy_price) / pos.buy_price
    if max_profit_pct <= profit_threshold:
        return False
    return bool(current_price <= pos.highest_price * (1 - pullback_pct))


def position_size(total_assets, available_cash, max_positions=5):
    """每仓资金。v1 行 186-189。"""
    target_per_stock = total_assets / max_positions
    return min(target_per_stock, available_cash)


# ════════════════════════════════════════════════════
# §E 大盘择时（纯函数）
# ════════════════════════════════════════════════════

def check_market_trend(idx_prices):
    """大盘择时：close > MA20 且 MACD hist > 0 且当日跌幅 > -3%。
    v1 行 247-267 逐字保留（注意 v1 注释掉了 MACD 缩窄检查）。"""
    if idx_prices is None or len(idx_prices) < 20:
        return False

    idx_prices = np.asarray(idx_prices, dtype=float)

    if len(idx_prices) >= 2:
        daily_change = (idx_prices[-1] - idx_prices[-2]) / idx_prices[-2]
        if daily_change <= -0.03:
            return False

    ma20 = np.mean(idx_prices[-20:])
    _, _, hist = macd(idx_prices)

    # 2. MACD红柱缩窄保护：拒绝多头衰竭信号
    #if len(hist) >= 2 and hist[-1] <= hist[-2]:
    #    return False

    return bool(idx_prices[-1] > ma20 and hist[-1] > 0)


# ════════════════════════════════════════════════════
# §F 交易成本（纯函数 — 统一公式，替代 v1 中 4 处复制粘贴）
# ════════════════════════════════════════════════════

def trade_cost(side, amount):
    """成本 = 佣金（最低 5）+ 印花税（仅卖）+ 过户费 + 滑点。"""
    if side not in ('buy', 'sell'):
        raise ValueError(f"side must be 'buy' or 'sell', got {side!r}")
    commission = max(amount * COST['commission'], COST['commission_min'])
    stamp = amount * COST['stamp'] if side == 'sell' else 0.0
    transfer = amount * COST['transfer']
    slippage = amount * COST['slippage']
    return commission + stamp + transfer + slippage
