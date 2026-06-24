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


# ════════════════════════════════════════════════════
# §B 日志（环境无关）
# ════════════════════════════════════════════════════

_LOG_FILE_PATH = None


def _init_log(ctx=None):
    global _LOG_FILE_PATH
    log_dir = getattr(ctx, 'log_dir', r'c:') if ctx else r'c:'
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    _LOG_FILE_PATH = os.path.join(log_dir, '量化日志_{0}.log'.format(ts))


def _log(msg, ctx=None):
    """同时输出到终端和日志文件，带时间戳。
    回测时 ctx.log_dir 指向 tmp_path/logs；实盘默认 c:\\（macOS 写入失败被 try/except 吞掉）。
    """
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = '{0} {1}'.format(timestamp, msg)
    print(line)
    if _LOG_FILE_PATH is None:
        _init_log(ctx)
    try:
        with open(_LOG_FILE_PATH, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass


# ════════════════════════════════════════════════════
# §G QMT 接口适配（与 QMT/Shim 交互的桥梁层）
# ════════════════════════════════════════════════════

def _normalize_code(code):
    """将 QMT 返回的股票代码标准化为带市场后缀的格式。
    v1 行 232-244 字面保留。'601689' → '601689.SH'。
    """
    if '.' in code:
        return code
    digits = code.strip()
    if digits.startswith(('6', '9')):
        return digits + '.SH'
    elif digits.startswith(('0', '3')):
        return digits + '.SZ'
    return code


def _filter_buyable(universe, ctx):
    """过滤 688 科创板 + ST 股。v1 行 377-378（688）+ 行 777-790（ST）合并。
    获取 get_instrumentdetail 异常时保留（fail-open），与 v1 行为一致。
    """
    filtered = []
    fail_count = 0
    for code in universe:
        if code.startswith('688'):
            continue
        try:
            detail = ctx.get_instrumentdetail(code)
            if detail and 'ST' in detail.get('m_strInstrumentName', ''):
                continue
        except Exception:
            fail_count += 1
        filtered.append(code)
    if fail_count > 0:
        _log("[filter] ST过滤异常: {0}只详情失败，已保留".format(fail_count), ctx)
    return filtered


def _sync_positions(ctx, current_date):
    """从 QMT 实际持仓同步到 ContextInfo.positions，防止两边脱节。v1 行 270-312。"""
    account_id = getattr(ctx, 'accountid', '')
    if not account_id:
        return
    try:
        position_list = get_trade_detail_data(account_id, ACCOUNT_TYPE, 'POSITION')
        if not position_list:
            return

        qmt_holdings = {}
        for p in position_list:
            raw_code = p.m_strInstrumentID
            code = _normalize_code(raw_code)
            vol = int(p.m_nVolume) if hasattr(p, 'm_nVolume') else int(p.m_nCanUseVolume)
            if vol > 0:
                qmt_holdings[code] = {
                    'volume': vol,
                    'cost_price': p.m_dOpenPrice if hasattr(p, 'm_dOpenPrice') else 0.0,
                }

        # QMT 有但我们没记录的 → 补录
        for code, info in qmt_holdings.items():
            if code not in ctx.positions:
                ctx.positions[code] = Position(
                    stockcode=code,
                    buy_price=info['cost_price'] if info['cost_price'] > 0 else 1.0,
                    buy_date=current_date,
                    volume=info['volume'],
                )
                _log("[{0}] 同步持仓: {1}, 数量{2}股".format(current_date, code, info['volume']), ctx)

        # 同步已有持仓 volume；清除 QMT 已不持有的
        for code in list(ctx.positions.keys()):
            if code in qmt_holdings:
                ctx.positions[code].volume = qmt_holdings[code]['volume']
            else:
                _log("[{0}] 清除失效持仓: {1}".format(current_date, code), ctx)
                del ctx.positions[code]

    except Exception as e:
        _log("[{0}] 持仓同步异常: {1}".format(current_date, e), ctx)


def _get_account(ctx):
    """返回 (total_assets, available_cash)。
    先尝试 get_trade_detail_data，失败时回退到 ctx.capital + realized_pnl。
    v1 行 524-531 + 行 661-670 散落多处合并为单函数。
    """
    account_id = getattr(ctx, 'accountid', '')
    if account_id:
        try:
            acct_info = get_trade_detail_data(account_id, ACCOUNT_TYPE, 'ACCOUNT')
            if acct_info:
                return acct_info[0].m_dBalance, acct_info[0].m_dAvailable
        except Exception:
            pass
    # Fallback：用 capital + realized_pnl 估算
    realized = getattr(ctx, 'realized_pnl', 0.0)
    return ctx.capital + realized, ctx.capital + realized


def _execute_buy(ctx, code, volume, price, current_date, score=None):
    """v1 行 793-817 字面保留，仅 trade_cost 替换为统一函数。"""
    try:
        account_id = getattr(ctx, 'accountid', '')
        passorder(23, 1101, account_id, code, 5, -1.0, float(volume), ctx)
        amount = volume * price
        cost = trade_cost('buy', amount)
        ctx.daily_cost = getattr(ctx, 'daily_cost', 0.0) + cost
        score_str = " | 评分: {0:.4f}".format(score) if score is not None else ""
        _log("[{0}] >> 买入: {1} | {2}股 x {3:.2f}元 = {4:.0f}元 | 成本: {5:.2f}元{6}".format(
            current_date, code, volume, price, amount, cost, score_str), ctx)
        return True, cost
    except Exception as e:
        _log("[{0}] !! 买入失败: {1} | {2}".format(current_date, code, e), ctx)
        return False, 0.0


def _execute_sell(ctx, code, reason, current_date):
    """v1 行 820-882。
    修 bug：v1 先下 passorder 再读 pos 信息（pos 可能已被上层 del），导致日志走 fallback。
    新版：**先**抓 pos 信息生成日志内容，**再**下 passorder，保证 buy_date/pnl 可见。
    """
    try:
        sell_volume = 0
        account_id = getattr(ctx, 'accountid', '')

        # 优先从 QMT 实际持仓获取可卖数量
        if account_id:
            try:
                position_list = get_trade_detail_data(account_id, ACCOUNT_TYPE, 'POSITION')
                if position_list:
                    for p in position_list:
                        if p.m_strInstrumentID == code:
                            sell_volume = (int(p.m_nCanUseVolume)
                                           if hasattr(p, 'm_nCanUseVolume')
                                           else int(p.m_nVolume))
                            break
            except Exception:
                pass

        # 回退到本地记录
        if sell_volume <= 0 and code in ctx.positions:
            sell_volume = ctx.positions[code].volume

        if sell_volume <= 0:
            pos = ctx.positions.get(code)
            if pos:
                sell_volume = int(200000 / pos.buy_price / 100) * 100
        if sell_volume <= 0:
            sell_volume = 100

        # **修 bug**：先抓 pos 信息，生成日志内容 —— 然后才下单
        reason_map = {
            'hard_stop': '硬止损', 'trend_break': '破MA20',
            'trailing_stop': '跟踪止盈', 'rebalance': '换仓调出',
            'crash_protection': '暴跌保护', 'macd_weak': 'MACD衰竭',
            'market_weak': '大盘弱势清仓',
        }
        reason_cn = reason_map.get(reason, reason)
        pos = ctx.positions.get(code)
        pnl_pct = 0.0
        buy_date = ''
        if pos:
            buy_date = pos.buy_date
            try:
                hist = ctx.get_history_data(1, '1d', 'close')
                if code in hist and len(hist[code]) > 0:
                    cur = float(hist[code][-1])
                    pnl_pct = (cur - pos.buy_price) / pos.buy_price * 100
            except Exception:
                pass

        # 下单（pos 信息已抓取，无论此后 pos 被谁 del 日志都不受影响）
        passorder(24, 1101, account_id, code, 5, -1.0, float(sell_volume), ctx)

        if buy_date:
            _log("[{0}] << 卖出: {1} | {2}股 | 原因: {3} | 持仓自: {4} | 盈亏: {5:+.2f}%".format(
                current_date, code, sell_volume, reason_cn, buy_date, pnl_pct), ctx)
        else:
            _log("[{0}] << 卖出: {1} | {2}股 | 原因: {3}".format(
                current_date, code, sell_volume, reason_cn), ctx)
    except Exception as e:
        _log("[{0}] !! 卖出失败: {1} | {2}".format(current_date, code, e), ctx)
