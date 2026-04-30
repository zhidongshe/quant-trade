# 沪深300多头趋势策略 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现一个基于QMT Python API的沪深300多头趋势量化交易策略，支持选股、入场、卖出、止损功能。

**Architecture:** 策略采用模块化设计，将QMT依赖的框架代码（init/handlebar）与纯Python的计算逻辑（指标、风控）分离。纯Python模块可独立测试，QMT主文件在运行时调用这些模块。持仓状态通过全局字典维护，在init中初始化，在handlebar中更新。

**Tech Stack:** Python 3.6.8 (QMT内置), NumPy, Pandas, TA-Lib (QMT内置), pytest (本地测试)

---

## 文件结构

| 文件 | 职责 |
|------|------|
| `strategy/indicators.py` | 纯Python指标计算：均线、MACD、成交量均值、信号判断 |
| `strategy/portfolio.py` | 持仓管理与风控逻辑：止损检查、止盈检查、仓位计算 |
| `strategy/hs300_trend_strategy.py` | QMT策略主文件：init, handlebar, 调用indicators和portfolio |
| `tests/test_indicators.py` | indicators.py 的单元测试 |
| `tests/test_portfolio.py` | portfolio.py 的单元测试 |

---

## Task 1: 指标计算模块 (indicators.py)

**Files:**
- Create: `strategy/indicators.py`
- Test: `tests/test_indicators.py`

**背景:** QMT提供了`get_history_data`和`get_market_data`获取行情，但具体的指标计算（均线、MACD）需要我们自己实现。把这些逻辑抽成纯函数，可以在本地用pytest测试，也能在QMT中复用。

### Step 1.1: 写失败测试 - 简单移动平均线

```python
# tests/test_indicators.py
import sys
sys.path.insert(0, '/Users/shezhidong/Documents/代码库/quant-trade')

import numpy as np
import pytest
from strategy.indicators import sma


def test_sma_basic():
    prices = np.array([10.0, 11.0, 12.0, 13.0, 14.0, 15.0])
    result = sma(prices, period=3)
    expected = np.array([np.nan, np.nan, 11.0, 12.0, 13.0, 14.0])
    np.testing.assert_array_almost_equal(result, expected)


def test_sma_short_input():
    prices = np.array([10.0, 11.0])
    result = sma(prices, period=3)
    assert np.all(np.isnan(result))
```

Run: `pytest tests/test_indicators.py::test_sma_basic -v`
Expected: FAIL with "cannot import name 'sma'"

### Step 1.2: 实现 sma 函数

```python
# strategy/indicators.py
import numpy as np


def sma(prices: np.ndarray, period: int) -> np.ndarray:
    """计算简单移动平均线 (Simple Moving Average)

    Args:
        prices: 价格数组，时间顺序由早到晚
        period: 均线周期

    Returns:
        与prices等长的数组，前period-1个值为nan
    """
    if len(prices) < period:
        return np.full_like(prices, np.nan, dtype=float)
    result = np.convolve(prices, np.ones(period) / period, mode='same')
    # 前period-1个值不是有效均值，置为nan
    result[:period - 1] = np.nan
    return result
```

Run: `pytest tests/test_indicators.py::test_sma_basic tests/test_indicators.py::test_sma_short_input -v`
Expected: PASS

### Step 1.3: 写失败测试 - MACD计算

在 `tests/test_indicators.py` 中追加：

```python
from strategy.indicators import macd


def test_macd_basic():
    # 构造一个上涨序列，MACD应该为正
    prices = np.array([10.0] * 26 + [11.0] * 10)
    dif, dea, hist = macd(prices, fast=12, slow=26, signal=9)
    # 最后几个点的hist应该为正（上涨趋势）
    assert hist[-1] > 0
    assert dif[-1] > dea[-1]


def test_macd_flat():
    prices = np.array([10.0] * 50)
    dif, dea, hist = macd(prices, fast=12, slow=26, signal=9)
    # 平坦价格，后期dif/dea/hist都趋近于0
    assert abs(hist[-1]) < 1e-10
```

Run: `pytest tests/test_indicators.py::test_macd_basic -v`
Expected: FAIL with "cannot import name 'macd'"

### Step 1.4: 实现 macd 函数

在 `strategy/indicators.py` 中追加：

```python

def macd(prices: np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9):
    """计算MACD指标

    Args:
        prices: 收盘价数组
        fast: 快线周期
        slow: 慢线周期
        signal: 信号线周期

    Returns:
        (dif, dea, hist) 三个等长数组
    """
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
```

Run: `pytest tests/test_indicators.py::test_macd_basic tests/test_indicators.py::test_macd_flat -v`
Expected: PASS

### Step 1.5: 写失败测试 - 买入信号判断

在 `tests/test_indicators.py` 中追加：

```python
from strategy.indicators import check_buy_signal


def test_buy_signal_all_pass():
    """三因子全部满足，应返回True"""
    # 构造一个明确上涨趋势： prices[i] = 10 + i*0.5
    prices = np.array([10.0 + i * 0.5 for i in range(70)])
    volumes = np.array([1000] * 70)
    # 最近一天放量
    volumes[-1] = 2000
    result = check_buy_signal(prices, volumes)
    assert result is True


def test_buy_signal_below_ma60():
    """价格低于60日均线，应返回False"""
    prices = np.array([100.0] * 69 + [50.0])  # 最后一天暴跌
    volumes = np.array([2000] * 70)
    result = check_buy_signal(prices, volumes)
    assert result is False


def test_buy_signal_macd_negative():
    """MACD柱状线为负，应返回False"""
    # 先涨后跌，MACD变负
    prices = np.array([10.0 + i * 0.3 for i in range(50)] + [25.0 - i * 0.5 for i in range(20)])
    volumes = np.array([2000] * 70)
    result = check_buy_signal(prices, volumes)
    assert result is False


def test_buy_signal_volume_low():
    """成交量未放大，应返回False"""
    prices = np.array([10.0 + i * 0.5 for i in range(70)])
    volumes = np.array([1000] * 70)  # 无放量
    result = check_buy_signal(prices, volumes)
    assert result is False
```

Run: `pytest tests/test_indicators.py::test_buy_signal_all_pass -v`
Expected: FAIL with "cannot import name 'check_buy_signal'"

### Step 1.6: 实现 check_buy_signal 函数

在 `strategy/indicators.py` 中追加：

```python

def check_buy_signal(prices: np.ndarray, volumes: np.ndarray) -> bool:
    """判断当前是否满足三因子共振买入信号

    Args:
        prices: 收盘价数组，至少70个数据点（满足60日均线+MACD）
        volumes: 成交量数组，与prices等长

    Returns:
        True: 满足全部买入条件
        False: 任一条件不满足
    """
    if len(prices) < 70 or len(volumes) < 20:
        return False

    # 趋势因子1: 收盘价 > 60日均线
    ma60 = sma(prices, 60)
    if np.isnan(ma60[-1]) or prices[-1] <= ma60[-1]:
        return False

    # 趋势因子2: 5日均线 > 20日均线
    ma5 = sma(prices, 5)
    ma20 = sma(prices, 20)
    if np.isnan(ma5[-1]) or np.isnan(ma20[-1]) or ma5[-1] <= ma20[-1]:
        return False

    # 动量因子: MACD柱状线 > 0
    dif, dea, hist = macd(prices)
    if hist[-1] <= 0:
        return False

    # 资金因子: 当日成交量 > 20日平均成交量
    vol_ma20 = sma(volumes.astype(float), 20)
    if np.isnan(vol_ma20[-1]) or volumes[-1] <= vol_ma20[-1]:
        return False

    return True
```

Run: `pytest tests/test_indicators.py -v`
Expected: 全部6个测试 PASS

### Step 1.7: Commit

```bash
cd /Users/shezhidong/Documents/代码库/quant-trade
git add strategy/indicators.py tests/test_indicators.py
git commit -m "feat: add indicator calculations with tests (sma, macd, buy signal)"
```

---

## Task 2: 持仓管理与风控模块 (portfolio.py)

**Files:**
- Create: `strategy/portfolio.py`
- Test: `tests/test_portfolio.py`

**背景:** 策略需要维护每只持仓的买入价、最高价、当前状态，并检查是否触发止损或止盈。这些逻辑与QMT API无关，是纯计算逻辑，适合独立测试。

### Step 2.1: 写失败测试 - 硬止损检查

```python
# tests/test_portfolio.py
import sys
sys.path.insert(0, '/Users/shezhidong/Documents/代码库/quant-trade')

import numpy as np
import pytest
from strategy.portfolio import Position, check_stop_loss, check_trailing_stop, calculate_buy_amount


def test_position_creation():
    pos = Position(stockcode='000001.SZ', buy_price=10.0, buy_date='20240101', volume=1000)
    assert pos.stockcode == '000001.SZ'
    assert pos.buy_price == 10.0
    assert pos.highest_price == 10.0


def test_hard_stop_loss_triggered():
    """下跌3%应触发止损"""
    pos = Position('000001.SZ', buy_price=100.0, buy_date='20240101', volume=100)
    current_price = 96.9  # 下跌3.1%
    assert check_stop_loss(pos, current_price, hard_stop_pct=0.03) is True


def test_hard_stop_loss_not_triggered():
    """下跌2%不应触发"""
    pos = Position('000001.SZ', buy_price=100.0, buy_date='20240101', volume=100)
    current_price = 98.0
    assert check_stop_loss(pos, current_price, hard_stop_pct=0.03) is False
```

Run: `pytest tests/test_portfolio.py::test_hard_stop_loss_triggered -v`
Expected: FAIL with import error

### Step 2.2: 实现 Position 类和硬止损检查

```python
# strategy/portfolio.py
from dataclasses import dataclass, field


@dataclass
class Position:
    """持仓记录"""
    stockcode: str
    buy_price: float
    buy_date: str
    volume: int
    highest_price: float = field(init=False)

    def __post_init__(self):
        self.highest_price = self.buy_price


def check_stop_loss(pos: Position, current_price: float, hard_stop_pct: float = 0.03) -> bool:
    """检查是否触发硬止损或趋势破坏止损

    Args:
        pos: 持仓对象
        current_price: 当前价格
        hard_stop_pct: 硬止损比例，默认0.03即3%

    Returns:
        True: 应卖出（触发硬止损）
        False: 继续持有
    """
    # 硬止损: 从买入价下跌超过 hard_stop_pct
    if current_price <= pos.buy_price * (1 - hard_stop_pct):
        return True
    return False
```

Run: `pytest tests/test_portfolio.py::test_hard_stop_loss_triggered tests/test_portfolio.py::test_hard_stop_loss_not_triggered -v`
Expected: PASS

### Step 2.3: 写失败测试 - 趋势破坏止损

在 `tests/test_portfolio.py` 中追加：

```python
from strategy.portfolio import check_trend_break


def test_trend_break_triggered():
    """收盘价跌破20日均线，应触发"""
    pos = Position('000001.SZ', buy_price=100.0, buy_date='20240101', volume=100)
    current_price = 95.0
    ma20 = 96.0
    assert check_trend_break(current_price, ma20) is True


def test_trend_break_not_triggered():
    """收盘价在20日均线上方，不应触发"""
    pos = Position('000001.SZ', buy_price=100.0, buy_date='20240101', volume=100)
    current_price = 97.0
    ma20 = 96.0
    assert check_trend_break(current_price, ma20) is False
```

Run: `pytest tests/test_portfolio.py::test_trend_break_triggered -v`
Expected: FAIL with import error

### Step 2.4: 实现趋势破坏检查

在 `strategy/portfolio.py` 中追加：

```python

def check_trend_break(current_price: float, ma20: float) -> bool:
    """检查是否触发趋势破坏止损（收盘价跌破20日均线）

    Args:
        current_price: 当前收盘价
        ma20: 20日均线值

    Returns:
        True: 应卖出（趋势破坏）
        False: 继续持有
    """
    if current_price <= ma20:
        return True
    return False
```

Run: `pytest tests/test_portfolio.py::test_trend_break_triggered tests/test_portfolio.py::test_trend_break_not_triggered -v`
Expected: PASS

### Step 2.5: 写失败测试 - 跟踪止盈

在 `tests/test_portfolio.py` 中追加：

```python
def test_trailing_stop_not_triggered_yet():
    """盈利未超5%，不启动跟踪止盈"""
    pos = Position('000001.SZ', buy_price=100.0, buy_date='20240101', volume=100)
    current_price = 103.0  # 盈利3%，未达5%启动线
    assert check_trailing_stop(pos, current_price, profit_threshold=0.05, pullback_pct=0.05) is False


def test_trailing_stop_triggered():
    """盈利超5%后，从最高点回落5%，应触发"""
    pos = Position('000001.SZ', buy_price=100.0, buy_date='20240101', volume=100)
    pos.highest_price = 110.0  # 曾经涨到110（盈利10%）
    current_price = 104.4  # 从110回落5.09%，应触发
    assert check_trailing_stop(pos, current_price, profit_threshold=0.05, pullback_pct=0.05) is True


def test_trailing_stop_not_triggered_after_profit():
    """盈利超5%，但回落不足5%，不触发"""
    pos = Position('000001.SZ', buy_price=100.0, buy_date='20240101', volume=100)
    pos.highest_price = 110.0
    current_price = 105.0  # 从110回落4.55%，未达5%
    assert check_trailing_stop(pos, current_price, profit_threshold=0.05, pullback_pct=0.05) is False


def test_trailing_stop_updates_high():
    """跟踪止盈应动态更新最高价"""
    pos = Position('000001.SZ', buy_price=100.0, buy_date='20240101', volume=100)
    check_trailing_stop(pos, 106.0, profit_threshold=0.05, pullback_pct=0.05)
    assert pos.highest_price == 106.0
    check_trailing_stop(pos, 108.0, profit_threshold=0.05, pullback_pct=0.05)
    assert pos.highest_price == 108.0
```

Run: `pytest tests/test_portfolio.py::test_trailing_stop_not_triggered_yet -v`
Expected: FAIL

### Step 2.6: 实现跟踪止盈检查

在 `strategy/portfolio.py` 中追加：

```python

def check_trailing_stop(pos: Position, current_price: float, profit_threshold: float = 0.05, pullback_pct: float = 0.05) -> bool:
    """检查是否触发跟踪止盈

    规则:
    1. 先更新最高价（动态只升不降）
    2. 若当前盈利 <= profit_threshold，不启动跟踪止盈
    3. 若当前盈利 > profit_threshold，检查是否从最高价回落超过 pullback_pct

    Args:
        pos: 持仓对象
        current_price: 当前价格
        profit_threshold: 启动跟踪止盈的盈利比例，默认0.05即5%
        pullback_pct: 从最高价回落的比例，默认0.05即5%

    Returns:
        True: 应卖出（触发跟踪止盈）
        False: 继续持有
    """
    # 更新最高价
    if current_price > pos.highest_price:
        pos.highest_price = current_price

    current_profit_pct = (current_price - pos.buy_price) / pos.buy_price

    # 盈利未达阈值，不启动
    if current_profit_pct <= profit_threshold:
        return False

    # 从最高价回落超过阈值
    if current_price <= pos.highest_price * (1 - pullback_pct):
        return True

    return False
```

Run: `pytest tests/test_portfolio.py::test_trailing_stop_not_triggered_yet tests/test_portfolio.py::test_trailing_stop_triggered tests/test_portfolio.py::test_trailing_stop_not_triggered_after_profit tests/test_portfolio.py::test_trailing_stop_updates_high -v`
Expected: PASS

### Step 2.7: 写失败测试 - 买入金额计算

在 `tests/test_portfolio.py` 中追加：

```python
def test_calculate_buy_amount_basic():
    """可用资金50万，应买入10万（单只20%上限）"""
    assert calculate_buy_amount(total_capital=1000000, available_cash=500000, max_positions=5) == 100000


def test_calculate_buy_amount_low_cash():
    """可用资金只剩8万，最多买8万"""
    assert calculate_buy_amount(total_capital=1000000, available_cash=80000, max_positions=5) == 80000


def test_calculate_buy_amount_rounding():
    """计算结果应为100的整数倍（A股最小交易单位）"""
    amount = calculate_buy_amount(total_capital=1000000, available_cash=123456, max_positions=5)
    assert amount % 100 == 0
```

Run: `pytest tests/test_portfolio.py::test_calculate_buy_amount_basic -v`
Expected: FAIL

### Step 2.8: 实现买入金额计算

在 `strategy/portfolio.py` 中追加：

```python

def calculate_buy_amount(total_capital: float, available_cash: float, max_positions: int = 5) -> int:
    """计算单只股票的买入金额

    规则:
    - 每只最多投入 total_capital / max_positions
    - 不能超过 available_cash
    - 结果向下取整到100的倍数（A股最小交易单位100股，按金额下单时取整）

    Args:
        total_capital: 总资金
        available_cash: 可用现金
        max_positions: 最大持仓数

    Returns:
        买入金额（整数）
    """
    target_per_stock = total_capital / max_positions
    amount = min(target_per_stock, available_cash)
    # 向下取整到100的倍数
    return int(amount // 100 * 100)
```

Run: `pytest tests/test_portfolio.py -v`
Expected: 全部10个测试 PASS

### Step 2.9: Commit

```bash
cd /Users/shezhidong/Documents/代码库/quant-trade
git add strategy/portfolio.py tests/test_portfolio.py
git commit -m "feat: add portfolio management with tests (stop-loss, trailing-stop, position sizing)"
```

---

## Task 3: QMT策略主文件 (hs300_trend_strategy.py)

**Files:**
- Create: `strategy/hs300_trend_strategy.py`

**背景:** 这是QMT客户端直接加载的策略文件，必须包含 `init(ContextInfo)` 和 `handlebar(ContextInfo)`。它会调用前面实现的 indicators.py 和 portfolio.py 中的纯函数。

### Step 3.1: 编写策略主文件框架

```python
# -*- coding: gbk -*-
"""
沪深300多头趋势策略

策略逻辑:
1. 股票池: 沪深300成分股，每日更新
2. 入场: 三因子共振 (60日线上 + 5日>20日 + MACD>0 + 放量)
3. 卖出: 3%硬止损 / 跌破20日线 / 盈利5%后跟踪止盈(回落5%)
4. 仓位: 最多5只，每只20%
"""

import numpy as np

# QMT环境路径处理
import sys
sys.path.insert(0, 'C:/Users/shezhidong/Documents/代码库/quant-trade')  # 需要根据实际QMT安装路径调整
from strategy.indicators import check_buy_signal
from strategy.portfolio import Position, check_stop_loss, check_trend_break, check_trailing_stop, calculate_buy_amount


# 全局配置
MAX_POSITIONS = 5
HARD_STOP_PCT = 0.03
PROFIT_THRESHOLD = 0.05
TRAILING_PULLBACK_PCT = 0.05
SINGLE_POSITION_PCT = 0.20


def init(ContextInfo):
    """初始化函数，策略启动时执行一次"""
    ContextInfo.set_account('')  # 实盘时填入资金账号
    ContextInfo.capital = 1000000  # 回测初始资金100万

    # 持仓状态字典: {stockcode: Position}
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
    ContextInfo.set_universe(universe)

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
        del ContextInfo.positions[stockcode]

    # 4. 检查买入信号（未满仓时）
    current_holdings = len(ContextInfo.positions)
    if current_holdings >= MAX_POSITIONS:
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

    # 5. 输出日志
    log_msg = f"[{current_date}] 持仓: {list(ContextInfo.positions.keys())}"
    print(log_msg)


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
            1101,  # 按股数（先查询持仓数量）
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
```

### Step 3.2: 本地语法检查

```bash
cd /Users/shezhidong/Documents/代码库/quant-trade
python3 -m py_compile strategy/hs300_trend_strategy.py
```
Expected: 无输出表示语法正确（QMT专有函数如passorder会报NameError，这是正常的，因为本地没有QMT环境）

### Step 3.3: Commit

```bash
cd /Users/shezhidong/Documents/代码库/quant-trade
git add strategy/hs300_trend_strategy.py
git commit -m "feat: add QMT strategy main file with init and handlebar"
```

---

## Task 4: 配置文件与使用说明

**Files:**
- Create: `README.md`

### Step 4.1: 编写项目README

```markdown
# 沪深300多头趋势量化策略

## 策略概述

基于迅投QMT极速策略交易系统的Python量化策略，以沪深300成分股为标的，采用多因子共振方式选股，配合严格止损机制。

## 核心参数

| 参数 | 值 |
|------|-----|
| 股票池 | 沪深300成分股 |
| 最大持仓 | 5只 |
| 单只仓位 | 20% |
| 硬止损 | -3% |
| 趋势止损 | 跌破20日均线 |
| 跟踪止盈 | 盈利>5%后，从最高点回落5% |
| 佣金 | 万分之一 |
| 印花税 | 千分之一（卖出） |

## 入场条件（三因子共振）

1. 收盘价 > 60日均线
2. 5日均线 > 20日均线
3. MACD柱状线 > 0
4. 当日成交量 > 20日平均成交量

## 文件说明

- `strategy/hs300_trend_strategy.py` — QMT策略主文件
- `strategy/indicators.py` — 技术指标计算（均线、MACD、信号判断）
- `strategy/portfolio.py` — 持仓管理与风控逻辑
- `tests/` — 单元测试

## 使用步骤

### 1. 环境准备

在QMT客户端的【数据管理】中补充以下数据：
- 沪深300成分股的日线历史数据（至少覆盖回测区间+60个交易日）
- 前复权数据

### 2. 导入策略

1. 打开QMT客户端，进入【模型研究】
2. 点击【新建模型】→ 选择Python模型
3. 将 `strategy/hs300_trend_strategy.py` 的代码复制到策略编辑器中
4. 修改 `init` 中的资金账号 `ContextInfo.set_account('你的账号')`

### 3. 设置回测参数

在策略编辑器右侧【回测参数】中设置：
- 开始时间、结束时间
- 初始资金：默认100万
- 滑点：0.01元或0.1%
- 买入佣金：0.0001（万分之一）
- 卖出佣金：0.0001
- 卖出印花税：0.001
- 最低佣金：5元
- 基准：000300.SH

### 4. 运行回测

点击【回测】按钮，查看历史表现。

### 5. 实盘/模拟交易

回测满意后，将策略加入【模型交易】，以模拟或实盘方式运行。

## 本地测试

```bash
cd /Users/shezhidong/Documents/代码库/quant-trade
pytest tests/ -v
```

## 风险提示

1. 最大回撤5%是理想目标，极端行情下可能突破
2. 集中持仓（5只）在单票黑天鹅时风险较大
3. 震荡市中趋势策略可能产生连续磨损
4. 策略历史表现不代表未来收益
```

### Step 4.2: Commit

```bash
cd /Users/shezhidong/Documents/代码库/quant-trade
git add README.md
git commit -m "docs: add README with usage instructions"
```

---

## Self-Review

### Spec Coverage Check

| 需求 | 对应Task/Step |
|------|--------------|
| 选股：沪深300成分股 | Task 3, Step 3.1 (get_sector) |
| 选股：每天更新 | Task 3, Step 3.1 (每个交易日开头更新universe) |
| 入场：三因子共振 | Task 1, Step 1.6 (check_buy_signal) |
| 入场：60日线上 | Task 1, Step 1.6 |
| 入场：5日>20日 | Task 1, Step 1.6 |
| 入场：MACD>0 | Task 1, Step 1.6 |
| 入场：放量 | Task 1, Step 1.6 |
| 止损：3%硬止损 | Task 2, Step 2.2 (check_stop_loss) |
| 止损：跌破20日线 | Task 2, Step 2.4 (check_trend_break) |
| 止盈：盈利5%后跟踪止盈 | Task 2, Step 2.6 (check_trailing_stop) |
| 仓位：最多5只 | Task 3, Step 3.1 (MAX_POSITIONS) |
| 仓位：每只20% | Task 2, Step 2.8 (calculate_buy_amount) |
| 佣金：万分之一 | README.md 回测参数说明 |

全部需求均已覆盖。

### Placeholder Scan

- 无 "TBD"、"TODO"、"implement later"
- 无 "Add appropriate error handling" 等模糊描述
- 每个step都有具体代码和命令

### Type Consistency

- `check_buy_signal` 签名: `(np.ndarray, np.ndarray) -> bool` — 全文档一致
- `Position` dataclass 字段 — Task 2和Task 3一致
- `calculate_buy_amount` 签名 — Task 2和Task 3一致

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-30-hs300-trend-strategy.md`.

**Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
