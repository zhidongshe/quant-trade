"""回测账户：现金/持仓/订单/快照。T+1 严格模拟。"""
from dataclasses import dataclass, field
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from strategy_hs300 import trade_cost


@dataclass
class AccountPosition:
    code: str
    volume: int
    can_use_volume: int
    buy_price: float
    buy_date: str


@dataclass
class Trade:
    trade_id: int
    date: str
    code: str
    name: str
    side: str          # 'buy' / 'sell'
    volume: int
    price: float
    amount: float
    cost: float
    reason: str
    status: str        # 'FILLED' / 'REJECTED'
    realized_pnl: float = 0.0


@dataclass
class Snapshot:
    date: str
    cash: float
    position_value: float
    total_equity: float
    n_positions: int
    daily_return: float = 0.0


class Account:
    def __init__(self, initial_capital: float):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.positions: dict[str, AccountPosition] = {}
        self.trades: list[Trade] = []
        self.snapshots: list[Snapshot] = []
        self._trade_seq = 0
        self._current_date: str = ''

    def advance_day(self, date_str: str):
        """T+1 解锁：所有持仓 can_use_volume = volume；推进当前日。"""
        self._current_date = date_str
        for pos in self.positions.values():
            pos.can_use_volume = pos.volume

    def _next_trade_id(self) -> int:
        self._trade_seq += 1
        return self._trade_seq

    def fill_buy(self, code: str, name: str, volume: int, price: float,
                 date_str: str, reason: str) -> bool:
        """买入成交。现金不足则拒单入 trades 并返回 False。"""
        amount = volume * price
        cost = trade_cost('buy', amount)
        total = amount + cost
        if total > self.cash:
            self.record_reject(code, name, 'buy', volume, price, date_str, 'CASH_SHORT')
            return False

        self.cash -= total

        if code in self.positions:
            old = self.positions[code]
            new_vol = old.volume + volume
            # 加权平均买价
            old.buy_price = (old.buy_price * old.volume + price * volume) / new_vol
            old.volume = new_vol
            # 当日新增量仍锁定；已有 can_use_volume 不变
        else:
            self.positions[code] = AccountPosition(
                code=code,
                volume=volume,
                can_use_volume=0,   # T+1：当日买入不可卖
                buy_price=price,
                buy_date=date_str,
            )

        self.trades.append(Trade(
            trade_id=self._next_trade_id(),
            date=date_str,
            code=code,
            name=name,
            side='buy',
            volume=volume,
            price=price,
            amount=amount,
            cost=cost,
            reason=reason,
            status='FILLED',
        ))
        return True

    def fill_sell(self, code: str, name: str, volume: int, price: float,
                  date_str: str, reason: str) -> bool:
        """卖出成交。无持仓或 T+1 锁定则拒单入 trades 并返回 False。"""
        if code not in self.positions:
            self.record_reject(code, name, 'sell', volume, price, date_str, 'NO_POSITION')
            return False

        pos = self.positions[code]
        if pos.can_use_volume < volume:
            self.record_reject(code, name, 'sell', volume, price, date_str, 'T1_LOCKED')
            return False

        amount = volume * price
        cost = trade_cost('sell', amount)
        realized_pnl = (price - pos.buy_price) * volume - cost
        self.cash += amount - cost

        pos.volume -= volume
        pos.can_use_volume -= volume
        if pos.volume == 0:
            del self.positions[code]

        self.trades.append(Trade(
            trade_id=self._next_trade_id(),
            date=date_str,
            code=code,
            name=name,
            side='sell',
            volume=volume,
            price=price,
            amount=amount,
            cost=cost,
            reason=reason,
            status='FILLED',
            realized_pnl=realized_pnl,
        ))
        return True

    def record_reject(self, code: str, name: str, side: str, volume: int,
                      price: float, date_str: str, reason: str) -> None:
        """记录拒单（进 trades，status='REJECTED'，cost=0）。"""
        self.trades.append(Trade(
            trade_id=self._next_trade_id(),
            date=date_str,
            code=code,
            name=name,
            side=side,
            volume=volume,
            price=price,
            amount=volume * price,
            cost=0.0,
            reason=reason,
            status='REJECTED',
        ))

    def snapshot(self, date_str: str, close_prices: dict) -> Snapshot:
        """EOD 快照：总权益 = 现金 + 持仓市值；计算日收益率。"""
        position_value = sum(
            close_prices.get(c, p.buy_price) * p.volume
            for c, p in self.positions.items()
        )
        total_equity = self.cash + position_value
        if self.snapshots:
            prev_equity = self.snapshots[-1].total_equity
            daily_return = (total_equity - prev_equity) / prev_equity if prev_equity > 0 else 0.0
        else:
            daily_return = 0.0  # 第一根 snapshot 总是 0
        snap = Snapshot(
            date=date_str,
            cash=self.cash,
            position_value=position_value,
            total_equity=total_equity,
            n_positions=len(self.positions),
            daily_return=daily_return,
        )
        self.snapshots.append(snap)
        return snap
