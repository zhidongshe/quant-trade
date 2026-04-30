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
    result = np.full_like(prices, np.nan, dtype=float)
    cumsum = np.cumsum(np.insert(prices, 0, 0))
    result[period - 1:] = (cumsum[period:] - cumsum[:-period]) / period
    return result


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
