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
    """检查是否触发硬止损

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

    # 基于曾经达到的最高价计算最大盈利比例，判断是否已激活跟踪止盈
    max_profit_pct = (pos.highest_price - pos.buy_price) / pos.buy_price

    # 盈利未达阈值，不启动
    if max_profit_pct <= profit_threshold:
        return False

    # 从最高价回落超过阈值
    if current_price <= pos.highest_price * (1 - pullback_pct):
        return True

    return False


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
