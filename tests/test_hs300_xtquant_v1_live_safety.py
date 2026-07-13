import sys
import types

xtquant = types.ModuleType('xtquant')
xttrader = types.ModuleType('xtquant.xttrader')
xttrader.XtQuantTrader = object
xttype = types.ModuleType('xtquant.xttype')
xttype.StockAccount = object
xtdata = types.ModuleType('xtquant.xtdata')
xtconstant = types.ModuleType('xtquant.xtconstant')

xtquant.xttrader = xttrader
xtquant.xttype = xttype
xtquant.xtdata = xtdata
xtquant.xtconstant = xtconstant

sys.modules.setdefault('xtquant', xtquant)
sys.modules.setdefault('xtquant.xttrader', xttrader)
sys.modules.setdefault('xtquant.xttype', xttype)
sys.modules.setdefault('xtquant.xtdata', xtdata)
sys.modules.setdefault('xtquant.xtconstant', xtconstant)

from hs300_xtquant_v1 import Strategy


class DummyTrader:
    def get_asset(self):
        return (100000.0, 50000.0, 50000.0, 0.0)

    def get_positions(self):
        return {}


class ConfirmingTrader:
    def __init__(self):
        self._positions = {}

    def get_asset(self):
        return (100000.0, 50000.0, 50000.0, 0.0)

    def get_positions(self):
        return self._positions

    def wait_order_filled(self, order_id, timeout=10):
        self._positions = {'600000.SH': {'volume': 1000, 'can_use': 1000, 'open_price': 10.0, 'market_value': 10000.0}}
        return True


def test_strategy_records_pending_order_metadata():
    strategy = Strategy(DummyTrader())
    strategy._record_pending_order('buy', '600000.SH', 1000, 'OID-1', '20260713')

    assert strategy.state['pending_orders']['buy:600000.SH']['order_id'] == 'OID-1'
    assert strategy.state['pending_orders']['buy:600000.SH']['volume'] == 1000


def test_confirm_buy_and_sync_uses_broker_positions_before_local_insert():
    strategy = Strategy(ConfirmingTrader())

    ok, outcome = strategy._confirm_buy_and_sync('600000.SH', 1000, 'OID-1', '20260713')

    assert ok is True
    assert outcome == 'filled'
    assert strategy.positions['600000.SH'].volume == 1000
