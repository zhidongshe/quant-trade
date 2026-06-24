import pytest
from strategy_hs300 import trade_cost


def test_buy_has_no_stamp_tax():
    # 1000 元买入：佣金 max(0.1, 5)=5 + 过户 0.01 + 滑点 0.5 = 5.51
    assert trade_cost('buy', 1000.0) == pytest.approx(5.51, abs=0.01)


def test_sell_has_stamp_tax():
    # 1000 元卖出：佣金 5 + 印花税 1 + 过户 0.01 + 滑点 0.5 = 6.51
    assert trade_cost('sell', 1000.0) == pytest.approx(6.51, abs=0.01)


def test_commission_floor_5_yuan():
    # 100 元买入：佣金 max(0.01, 5) = 5
    cost = trade_cost('buy', 100.0)
    assert cost >= 5.0


def test_buy_large_order_proportional():
    # 100w 元买入：佣金 100 + 过户 10 + 滑点 500 = 610
    assert trade_cost('buy', 1_000_000.0) == pytest.approx(610.0, abs=0.5)


def test_sell_large_order_includes_stamp():
    # 100w 元卖出：佣金 100 + 印花税 1000 + 过户 10 + 滑点 500 = 1610
    assert trade_cost('sell', 1_000_000.0) == pytest.approx(1610.0, abs=0.5)


def test_invalid_side_raises():
    with pytest.raises(ValueError):
        trade_cost('hold', 1000.0)
