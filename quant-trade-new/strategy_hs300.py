# -*- coding: utf-8 -*-
"""沪深300多头趋势策略 — QMT 实盘/本地回测两用单文件版。

部署到 QMT 时改首行为 # -*- coding: gbk -*-，并修改 init() 里的 set_account。
本地回测时由 backtest/shim.py 注入 QMT 全局函数。
策略业务规则与 hs300_trend_strategy_single_file_v1.py 完全一致，仅整理结构。
"""

import numpy as np
import os
import time
from datetime import datetime

# ════════════════════════════════════════════════════
# §A 配置常量
# ════════════════════════════════════════════════════

# 实盘部署前必须改下面这行为你自己的资金账号；保留默认值会触发 init 警告
DEFAULT_DEV_ACCOUNT_ID = '8890358835'
ACCOUNT_ID = '8890358835'  # ← 改成你的实盘账号
ACCOUNT_TYPE = 'STOCK'
MAX_POSITIONS = 5
HARD_STOP_PCT = 0.05
PROFIT_THRESHOLD = 0.10
TRAILING_PULLBACK = 0.08
REBALANCE_INTERVAL = 10
INDEX_CODE = '000300.SH'

# 卖单走对手价(prType=11)能秒成交,但 broker 通过成交回报更新 m_dAvailable 是异步的,
# 实盘下需要轮询等回报到位再算可用现金,否则同 bar 内卖→买会把现金严重低估。
WAIT_FILL_TIMEOUT = 10  # 等待成交回报的最长秒数
WAIT_FILL_POLL = 0.5    # 轮询 broker 的间隔秒数

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
    log_dir = getattr(ctx, 'log_dir', 'c:\\') if ctx else 'c:\\'
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


def _get_account(ctx, force_internal=False):
    """返回 (total_assets, available_cash)。

    优先采用 QMT broker（m_dBalance / m_dAvailable）；接口不可用或 force_internal=True 时
    回落到内部账本估算 capital + realized_pnl - position_cost_basis - total_cost。

    force_internal=True 的使用场景：调用方知道 broker m_dAvailable 还没同步本 bar 的卖/买
    （例如卖单回报未到或 QMT 回测下 broker 给的是 pre-bar 快照），此时强制走内部账本，
    避免买入循环把现金严重低估。
    """
    account_id = getattr(ctx, 'accountid', '')
    if not force_internal and account_id:
        try:
            acct_info = get_trade_detail_data(account_id, ACCOUNT_TYPE, 'ACCOUNT')
            if acct_info:
                return acct_info[0].m_dBalance, acct_info[0].m_dAvailable
        except Exception:
            pass

    # 内部账本估算
    realized = getattr(ctx, 'realized_pnl', 0.0)
    total_cost_acc = getattr(ctx, 'total_cost', 0.0) + getattr(ctx, 'daily_cost', 0.0)
    position_cost_basis = sum(p.buy_price * p.volume for p in ctx.positions.values())
    cash = ctx.capital + realized - position_cost_basis - total_cost_acc
    # 持仓市值用最新可得价（无 hist 时退回买入价，结果略偏低但不影响 cash 估算）
    position_value = position_cost_basis
    return cash + position_value, cash


def _wait_for_sell_settlement(ctx, n_new_sells, current_date):
    """卖单 passorder 后,轮询 broker m_dAvailable,等成交回报把现金提上来。

    n_new_sells: 本 bar 内新发起的卖单数;为 0 直接返回 True。
    回测模式（ctx.do_back_test=True，本地 Shim 同步成交 / QMT 回测）或 account_id 缺失
    也直接返回 True —— 此时调用方无需轮询，broker 立刻准（Shim）或反正会走内部估算（QMT 回测）。

    返回 True 表示 broker 已同步,调用方可信用 m_dAvailable；
    False 表示超时,调用方应让 _get_account 走 force_internal=True 回落内部账本。
    """
    if n_new_sells <= 0:
        return True
    account_id = getattr(ctx, 'accountid', '')
    if not account_id:
        return True
    is_backtest = getattr(ctx, 'do_back_test', False)
    if is_backtest:
        return True

    # 内部账本算出的"卖出回款应到位后"的现金底线
    realized = getattr(ctx, 'realized_pnl', 0.0)
    total_cost_acc = getattr(ctx, 'total_cost', 0.0) + getattr(ctx, 'daily_cost', 0.0)
    position_cost_basis = sum(p.buy_price * p.volume for p in ctx.positions.values())
    expected_floor = ctx.capital + realized - position_cost_basis - total_cost_acc
    target = expected_floor * 0.95  # 5% 余量避开手续费/滑点偏差

    deadline = time.time() + WAIT_FILL_TIMEOUT
    last_avail = None
    while time.time() < deadline:
        try:
            acct_info = get_trade_detail_data(account_id, ACCOUNT_TYPE, 'ACCOUNT')
            if acct_info:
                last_avail = acct_info[0].m_dAvailable
                if last_avail >= target:
                    _log("[{0}] 卖单成交回报到位({1}笔): m_dAvailable={2:.0f}元 (期望底线{3:.0f})".format(
                        current_date, n_new_sells, last_avail, target), ctx)
                    return True
        except Exception:
            pass
        time.sleep(WAIT_FILL_POLL)
    _log("[{0}] 等成交回报超时{1}s({2}笔卖单): m_dAvailable={3} (期望底线{4:.0f}),回落内部账本估算".format(
        current_date, WAIT_FILL_TIMEOUT, n_new_sells,
        '?' if last_avail is None else "{0:.0f}".format(last_avail), target), ctx)
    return False


def _execute_buy(ctx, code, volume, price, current_date, score=None):
    """v1 行 793-817 字面保留，仅 trade_cost 替换为统一函数。"""
    try:
        account_id = getattr(ctx, 'accountid', '')
        passorder(23, 1101, account_id, code, 5, -1.0, float(volume), ctx)
        amount = volume * price
        cost = trade_cost('buy', amount)
        ctx.daily_cost = getattr(ctx, 'daily_cost', 0.0) + cost
        score_str = " | 评分: {0:.4f}".format(score) if score is not None else ""
        _log("[{0}] >> 买入: {1} | {2}股 x {3:.2f}元 = {4:.0f}元 | 交易费用: {5:.2f}元{6}".format(
            current_date, code, volume, price, amount, cost, score_str), ctx)
        return True, cost
    except Exception as e:
        _log("[{0}] !! 买入失败: {1} | {2}".format(current_date, code, e), ctx)
        return False, 0.0


def _execute_sell(ctx, code, reason, current_date):
    """v1 行 820-882。
    修 bug：v1 先下 passorder 再读 pos 信息（pos 可能已被上层 del），导致日志走 fallback。
    新版：**先**抓 pos 信息生成日志内容，**再**下 passorder，保证 buy_date/pnl 可见。
    返回 True 表示卖出成交，False 表示拒单/失败；上层据此决定是否 del ctx.positions。
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
        buy_price = None
        cur_for_pnl = None
        hold_volume = 0
        if pos:
            buy_date = pos.buy_date
            buy_price = pos.buy_price
            hold_volume = pos.volume
            try:
                hist = ctx.get_history_data(1, '1d', 'close', dividend_type=1)
                if code in hist and len(hist[code]) > 0:
                    cur_for_pnl = float(hist[code][-1])
                    pnl_pct = (cur_for_pnl - pos.buy_price) / pos.buy_price * 100
            except Exception:
                pass

        # 下单（pos 信息已抓取，无论此后 pos 被谁 del 日志都不受影响）
        # prType=11 对手价：卖单按当前买一价挂出，HS300 深度盘下几乎秒成交，
        # 让 broker 的 m_dAvailable 尽快反映回款（避免同 bar 内卖→买的现金低估）。
        passorder(24, 1101, account_id, code, 11, -1.0, float(sell_volume), ctx)

        # 确认成交后才累计 realized_pnl，防止拒单（LIMIT_DOWN / QMT 异常）产生幻象盈亏
        if buy_price is not None and cur_for_pnl is not None and hold_volume > 0:
            fill_confirmed = True
            try:
                pos_list = get_trade_detail_data(account_id, ACCOUNT_TYPE, 'POSITION')
                if pos_list:
                    still_holds = any(
                        p.m_strInstrumentID == code and getattr(p, 'm_nVolume', 0) >= hold_volume
                        for p in pos_list
                    )
                    if still_holds:
                        fill_confirmed = False
            except Exception:
                # 查询失败时保守假设成交（保留 v1 在无法查询时的行为）
                pass
            if fill_confirmed:
                realized = (cur_for_pnl - buy_price) * hold_volume
                ctx.realized_pnl = getattr(ctx, 'realized_pnl', 0.0) + realized

        if buy_date:
            _log("[{0}] << 卖出: {1} | {2}股 | 原因: {3} | 持仓自: {4} | 盈亏: {5:+.2f}%".format(
                current_date, code, sell_volume, reason_cn, buy_date, pnl_pct), ctx)
        else:
            _log("[{0}] << 卖出: {1} | {2}股 | 原因: {3}".format(
                current_date, code, sell_volume, reason_cn), ctx)
        return True
    except Exception as e:
        _log("[{0}] !! 卖出失败: {1} | {2}".format(current_date, code, e), ctx)
        return False


# ════════════════════════════════════════════════════
# §H 主控（init + handlebar + 10 个私有 helper）
# ════════════════════════════════════════════════════

def init(ContextInfo):
    """v1 行 194-229，但删除 SKIP_HISTORY_WARMUP 相关日志逻辑。"""
    ContextInfo.set_account(ACCOUNT_ID)
    if ACCOUNT_ID == DEFAULT_DEV_ACCOUNT_ID:
        _log("⚠️ 警告: ACCOUNT_ID 仍是默认开发账号 '{0}'，实盘部署前请修改为你自己的账号！".format(
            DEFAULT_DEV_ACCOUNT_ID), ContextInfo)
    try:
        acct_info = get_trade_detail_data(ACCOUNT_ID, ACCOUNT_TYPE, 'ACCOUNT')
        if acct_info:
            ContextInfo.capital = acct_info[0].m_dBalance
        else:
            ContextInfo.capital = 100000
    except Exception:
        ContextInfo.capital = 100000

    ContextInfo.positions = {}
    ContextInfo.last_trade_date = None
    ContextInfo.accountid = ACCOUNT_ID
    ContextInfo.rebalance_count = 0
    ContextInfo.last_rebalance_date = None
    ContextInfo.realized_pnl = 0.0
    ContextInfo.total_cost = 0.0
    ContextInfo.trading_day_index = 0
    ContextInfo.market_ok_streak = 1
    ContextInfo.market_weak_streak = 0
    ContextInfo.strategy_start_date = datetime.now().strftime('%Y%m%d')
    ContextInfo.daily_cost = 0.0
    ContextInfo.daily_sold_records = []

    universe = ContextInfo.get_sector(INDEX_CODE)
    if universe:
        ContextInfo.set_universe(list(universe) + [INDEX_CODE])


def _is_actionable_bar(ctx):
    """时间闸 + 幂等 + start_date 过滤。"""
    current_date = timetag_to_datetime(ctx.get_bar_timetag(ctx.barpos), '%Y%m%d')
    current_time = timetag_to_datetime(ctx.get_bar_timetag(ctx.barpos), '%H:%M:%S')
    _log("[bar] barpos={0} date={1} time={2}".format(ctx.barpos, current_date, current_time), ctx)

    # QMT 回测模式 do_back_test=True 时不过滤历史 bar（QMT 回测就是要处理历史 bar）
    # 实盘模式 do_back_test=False（默认），过滤启动时的历史回放
    is_backtest = getattr(ctx, 'do_back_test', False)
    if not is_backtest and current_date < ctx.strategy_start_date:
        return False

    # 时间闸：分钟模式有效；日线模式 current_time='00:00:00' 自然通过
    if current_time != '00:00:00' and current_time < '14:50:00':
        return False

    # barpos 幂等
    last_bar = getattr(ctx, 'last_processed_barpos', -1)
    if ctx.barpos <= last_bar:
        return False
    ctx.last_processed_barpos = ctx.barpos

    # same-day 幂等
    if ctx.last_trade_date == current_date:
        return False
    ctx.last_trade_date = current_date

    return True


def _daily_setup(ctx):
    """每日起始：累计成本结算 + 计数器。"""
    ctx.total_cost = getattr(ctx, 'total_cost', 0.0) + getattr(ctx, 'daily_cost', 0.0)
    ctx.daily_sold_records = []
    ctx.daily_cost = 0.0
    ctx.trading_day_index = getattr(ctx, 'trading_day_index', 0) + 1
    ctx.rebalance_count = getattr(ctx, 'rebalance_count', 0) + 1


def _fetch_data(ctx):
    """一次拿齐 close + volume + 指数。替代 v1 中 3 次 get_history_data。"""
    hist_close = ctx.get_history_data(70, '1d', 'close', dividend_type=1, skip_paused=True)
    hist_volume = ctx.get_history_data(70, '1d', 'volume', dividend_type=1, skip_paused=True)
    idx_prices = None
    if INDEX_CODE in hist_close and len(hist_close[INDEX_CODE]) >= 70:
        idx_prices = np.array(hist_close[INDEX_CODE], dtype=float)
    return hist_close, hist_volume, idx_prices


def _update_market_streak(ctx, idx_prices):
    """v1 行 390-401。"""
    market_ok = check_market_trend(idx_prices)
    if market_ok:
        ctx.market_ok_streak = getattr(ctx, 'market_ok_streak', 0) + 1
        ctx.market_weak_streak = 0
    else:
        ctx.market_ok_streak = 0
        ctx.market_weak_streak = getattr(ctx, 'market_weak_streak', 0) + 1
    return market_ok


def _is_rebalance_day(ctx):
    return ctx.rebalance_count >= REBALANCE_INTERVAL


def _evaluate_and_execute_sells(ctx, hist_close, current_date):
    """v1 行 403-505 字面保留。返回 (当日已卖出的 set, 实际成交的卖单笔数)。"""
    positions_to_sell = []

    for code, pos in list(ctx.positions.items()):
        if code not in hist_close or len(hist_close[code]) < 1:
            _log("[{0}] {1} 跳过卖出: 无数据".format(current_date, code), ctx)
            continue
        prices_list = hist_close[code]
        current_price = float(prices_list[-1])

        if current_price > pos.highest_price:
            pos.highest_price = current_price

        if len(prices_list) < 20:
            if check_hard_stop(pos, current_price, HARD_STOP_PCT):
                positions_to_sell.append((code, 'hard_stop'))
            continue

        prices_arr = np.array(prices_list, dtype=float)
        ma20 = np.mean(prices_arr[-20:])
        _, _, hist = macd(prices_arr)

        should_sell = False
        sell_reason = ''

        if check_hard_stop(pos, current_price, HARD_STOP_PCT):
            should_sell = True
            sell_reason = 'hard_stop'
        elif check_crash(prices_arr):
            should_sell = True
            sell_reason = 'crash_protection'

        if not should_sell:
            if check_trend_break(current_price, ma20, hist):
                should_sell = True
                sell_reason = 'trend_break'
            elif check_trailing_stop(pos, current_price, PROFIT_THRESHOLD, TRAILING_PULLBACK):
                should_sell = True
                sell_reason = 'trailing_stop'

        if should_sell:
            pnl_pct = (current_price - pos.buy_price) / pos.buy_price * 100
            _log("[{0}] 触发卖出: {1} | 原因: {2} | 买入价: {3:.2f} | 现价: {4:.2f} | 盈亏: {5:+.2f}%".format(
                current_date, code, sell_reason, pos.buy_price, current_price, pnl_pct), ctx)
            positions_to_sell.append((code, sell_reason))

    # 大盘弱势清仓豁免（保留盈利 >10% 的强势股）
    if ctx.market_weak_streak >= 2:
        already = {s for s, _ in positions_to_sell}
        for code, pos in list(ctx.positions.items()):
            if code in already:
                continue
            max_profit = (pos.highest_price - pos.buy_price) / pos.buy_price
            if max_profit <= PROFIT_THRESHOLD:
                positions_to_sell.append((code, 'market_weak'))

    # 执行卖出
    sold_today = set()
    n_new_sells = 0
    for code, reason in positions_to_sell:
        if code in ctx.positions:
            pos = ctx.positions[code]
            sell_price = pos.buy_price
            if code in hist_close and len(hist_close[code]) > 0:
                sell_price = float(hist_close[code][-1])
            # 注：daily_cost 和 daily_sold_records 仅用于策略侧日志展示；
            # Account 是成本与已实现盈亏的权威源；realized_pnl 在 _execute_sell 确认成交后更新
            ctx.daily_sold_records.append({
                'stockcode': code, 'volume': pos.volume,
                'buy_price': pos.buy_price, 'sell_price': sell_price,
                'reason': reason, 'buy_date': pos.buy_date,
            })
            ctx.daily_cost = getattr(ctx, 'daily_cost', 0.0) + trade_cost('sell', pos.volume * sell_price)
        sell_ok = _execute_sell(ctx, code, reason, current_date)
        if sell_ok:
            n_new_sells += 1
            if code in ctx.positions:
                del ctx.positions[code]
        sold_today.add(code)

    return sold_today, n_new_sells


def _score_universe(ctx, buy_universe, hist_close, hist_volume):
    """打分 + Z-score 归一 + 加权。返回排序后的 list[(code, score)]."""
    candidates = []
    for code in buy_universe:
        if code not in hist_close or len(hist_close[code]) < 70:
            continue
        if code not in hist_volume or len(hist_volume[code]) < 20:
            continue
        prices_arr = np.array(hist_close[code], dtype=float)
        volumes_arr = np.array(hist_volume[code], dtype=float)
        f = score_factors(prices_arr, volumes_arr)
        if f is not None:
            candidates.append((code, f))

    scored = []
    if candidates:
        if len(candidates) >= 5:
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
        for code, f in candidates:
            total = (f['trend_score'] * WEIGHTS['trend']
                     + f['ma_spread_score'] * WEIGHTS['spread']
                     + f['macd_score'] * WEIGHTS['macd']
                     + f['volume_score'] * WEIGHTS['volume'])
            scored.append((code, total))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def _do_rebalance(ctx, hist_close, hist_volume, sold_today, scored,
                  total_assets, available_cash, current_date):
    """换仓日。v1 行 581-716。"""
    ctx.rebalance_count = 0
    ctx.last_rebalance_date = current_date
    top_n = scored[:MAX_POSITIONS]
    top_codes = [x[0] for x in top_n]

    _log("[{0}] ====== 换仓日 ====== Top{1}".format(current_date, MAX_POSITIONS), ctx)

    # 卖出非 Top N 中且盈利 ≤10% 的（盈利 >10% 保留）
    n_rebalance_sells = 0
    for code in list(ctx.positions.keys()):
        if code in top_codes:
            continue
        pos = ctx.positions[code]
        sell_price = pos.buy_price
        if code in hist_close and len(hist_close[code]) > 0:
            sell_price = float(hist_close[code][-1])
            profit = (sell_price - pos.buy_price) / pos.buy_price
            if profit > PROFIT_THRESHOLD:
                _log("[{0}] 换仓保留: {1} | 盈利{2:+.2f}%".format(current_date, code, profit * 100), ctx)
                continue

        # 注：daily_cost 和 daily_sold_records 仅用于策略侧日志展示；
        # Account 是成本与已实现盈亏的权威源；realized_pnl 在 _execute_sell 确认成交后更新
        ctx.daily_sold_records.append({
            'stockcode': code, 'volume': pos.volume,
            'buy_price': pos.buy_price, 'sell_price': sell_price,
            'reason': 'rebalance', 'buy_date': pos.buy_date,
        })
        ctx.daily_cost = getattr(ctx, 'daily_cost', 0.0) + trade_cost('sell', pos.volume * sell_price)
        sell_ok = _execute_sell(ctx, code, 'rebalance', current_date)
        if sell_ok:
            n_rebalance_sells += 1
            if code in ctx.positions:
                del ctx.positions[code]
        sold_today.add(code)

    # 卖出后重新拿资金；实盘下先等 broker 回报，超时回落内部账本
    rebalance_sells_synced = _wait_for_sell_settlement(ctx, n_rebalance_sells, current_date)
    total_assets, available_cash = _get_account(ctx, force_internal=not rebalance_sells_synced)

    # 买入 Top N（大盘连续 2 天 OK 才买）
    if ctx.market_ok_streak >= 2:
        current_holdings = len(ctx.positions)
        for code, s in top_n:
            if current_holdings >= MAX_POSITIONS:
                break
            if code in ctx.positions or code in sold_today:
                continue
            if code not in hist_close:
                continue
            prices_arr = np.array(hist_close[code], dtype=float)
            current_price = float(prices_arr[-1])
            buy_amount = position_size(total_assets, available_cash, MAX_POSITIONS)
            if buy_amount < 1000:
                continue
            buy_volume = int(buy_amount / current_price / 100) * 100
            if buy_volume < 100:
                continue
            success, cost = _execute_buy(ctx, code, buy_volume, current_price, current_date, score=s)
            if success:
                ctx.positions[code] = Position(
                    stockcode=code, buy_price=current_price, buy_date=current_date,
                    volume=buy_volume, buy_trading_day_idx=ctx.trading_day_index,
                )
                # 手动扣减 available_cash，本 bar 不再读 broker —— broker 扣冻同样异步,
                # 立刻读会拿到上一笔还没扣的快照,把第 2/3 笔买额高估。
                available_cash -= buy_volume * current_price + cost
                current_holdings += 1
    else:
        _log("[{0}] 大盘弱势，换仓日跳过买入".format(current_date), ctx)


def _do_refill(ctx, hist_close, hist_volume, sold_today, scored,
               total_assets, available_cash, current_date):
    """非换仓日补仓。v1 行 718-772。"""
    if ctx.market_ok_streak < 2:
        return
    current_holdings = len(ctx.positions)
    if current_holdings >= MAX_POSITIONS:
        return
    for code, s in scored:
        if current_holdings >= MAX_POSITIONS:
            break
        if code in ctx.positions or code in sold_today:
            continue
        if code not in hist_close or len(hist_close[code]) < 70:
            continue
        if code not in hist_volume or len(hist_volume[code]) < 20:
            continue
        prices_arr = np.array(hist_close[code], dtype=float)
        volumes_arr = np.array(hist_volume[code], dtype=float)
        if not check_buy_signal(prices_arr, volumes_arr):
            continue
        current_price = float(prices_arr[-1])
        buy_amount = position_size(total_assets, available_cash, MAX_POSITIONS)
        if buy_amount < 1000:
            continue
        buy_volume = int(buy_amount / current_price / 100) * 100
        if buy_volume < 100:
            continue
        success, cost = _execute_buy(ctx, code, buy_volume, current_price, current_date, score=s)
        if success:
            ctx.positions[code] = Position(
                stockcode=code, buy_price=current_price, buy_date=current_date,
                volume=buy_volume, buy_trading_day_idx=ctx.trading_day_index,
            )
            # 手动扣减,本 bar 不再读 broker（同 _do_rebalance）
            available_cash -= buy_volume * current_price + cost
            current_holdings += 1


def _log_status(ctx, current_date):
    """v1 行 885-1034 简化版：~10 行概要日志（持仓数、总资产、现金）。"""
    holdings = list(ctx.positions.keys())
    sold = getattr(ctx, 'daily_sold_records', [])
    if len(holdings) == 0 and len(sold) == 0:
        total, _ = _get_account(ctx)
        _log("[{0}] 当前持仓: 空仓 | 总资产: {1:.0f}元".format(current_date, total), ctx)
        return
    total, cash = _get_account(ctx)
    _log("[{0}] 持仓 {1} 只 | 总资产: {2:.0f}元 | 现金: {3:.0f}元".format(
        current_date, len(holdings), total, cash), ctx)


def handlebar(ContextInfo):
    """主调度。整个 handlebar 内只 ~30 行；细节都在 helper 里。"""
    if not _is_actionable_bar(ContextInfo):
        return

    current_date = timetag_to_datetime(ContextInfo.get_bar_timetag(ContextInfo.barpos), '%Y%m%d')

    _daily_setup(ContextInfo)
    _sync_positions(ContextInfo, current_date)

    universe = ContextInfo.get_sector(INDEX_CODE)
    if not universe:
        _log("[{0}] 无法获取沪深300成分股".format(current_date), ContextInfo)
        return

    # set_universe 仅当持仓股缺失时（v1 行 369-374）
    held = list(ContextInfo.positions.keys())
    missing = [c for c in held if c not in universe]
    if missing:
        ContextInfo.set_universe(list(set(universe + held + [INDEX_CODE])))

    buy_universe = _filter_buyable(
        [c for c in universe if c != INDEX_CODE],
        ContextInfo
    )

    hist_close, hist_volume, idx_prices = _fetch_data(ContextInfo)
    _update_market_streak(ContextInfo, idx_prices)
    _log("[{0}] 持仓 {1} 只 | 大盘OK连{2}天 弱连{3}天 | 距换仓 {4} 日".format(
        current_date, len(held), ContextInfo.market_ok_streak,
        ContextInfo.market_weak_streak, REBALANCE_INTERVAL - ContextInfo.rebalance_count
    ), ContextInfo)

    sold_today, n_risk_sells = _evaluate_and_execute_sells(ContextInfo, hist_close, current_date)
    # 实盘下,卖单回报到位后再读 broker 现金；超时则强制内部账本估算
    risk_sells_synced = _wait_for_sell_settlement(ContextInfo, n_risk_sells, current_date)
    total_assets, available_cash = _get_account(ContextInfo, force_internal=not risk_sells_synced)
    scored = _score_universe(ContextInfo, buy_universe, hist_close, hist_volume)

    if _is_rebalance_day(ContextInfo):
        _do_rebalance(ContextInfo, hist_close, hist_volume, sold_today, scored,
                      total_assets, available_cash, current_date)
    else:
        _do_refill(ContextInfo, hist_close, hist_volume, sold_today, scored,
                   total_assets, available_cash, current_date)

    _log_status(ContextInfo, current_date)
