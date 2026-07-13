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

from hs300_xtquant_v1 import Strategy, Position


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

    ok, outcome, filled_volume = strategy._confirm_buy_and_sync('600000.SH', 1000, 'OID-1', '20260713')

    assert ok is True
    assert outcome == 'filled'
    assert filled_volume == 1000
    assert strategy.positions['600000.SH'].volume == 1000

class SellingTrader:
    def __init__(self):
        self._positions = {'600000.SH': {'volume': 1000, 'can_use': 1000, 'open_price': 10.0, 'market_value': 10000.0}}

    def get_asset(self):
        return (100000.0, 50000.0, 50000.0, 0.0)

    def get_positions(self):
        return self._positions

    def wait_order_filled(self, order_id, timeout=10):
        self._positions = {}
        return True


class NoAssetTrader:
    def get_asset(self):
        return None

    def get_positions(self):
        return {}

    def get_sector(self, sector_code):
        return []


class StaticTrader:
    def get_asset(self):
        return (100000.0, 50000.0, 50000.0, 0.0)

    def get_positions(self):
        return {}


def test_confirm_sell_and_sync_keeps_local_position_until_broker_clears_it():
    strategy = Strategy(SellingTrader())
    strategy.positions['600000.SH'] = Position('600000.SH', 10.0, '20260701', 1000, 1)

    ok, outcome, sold_volume = strategy._confirm_sell_and_sync('600000.SH', 1000, 'OID-2', '20260713')

    assert ok is True
    assert outcome == 'filled'
    assert sold_volume == 1000
    assert '600000.SH' not in strategy.positions


def test_strategy_marks_buy_block_reason_when_asset_unavailable():
    strategy = Strategy(NoAssetTrader())
    strategy.state['buy_block_reason'] = ''

    allowed = strategy._can_open_new_positions(history_ok=True)

    assert allowed is False
    assert strategy.state['buy_block_reason'] == 'asset_unavailable'


def test_expire_stale_pending_orders_moves_old_entries_to_manual_review():
    strategy = Strategy(StaticTrader())
    strategy.state['pending_orders'] = {
        'buy:600000.SH': {
            'side': 'buy',
            'stockcode': '600000.SH',
            'volume': 1000,
            'order_id': 'OID-STALE',
            'trade_date': '20260712',
        }
    }

    strategy._expire_stale_pending_orders('20260713')

    assert strategy.state['pending_orders'] == {}
    assert strategy.state['stale_pending_orders'][0]['order_id'] == 'OID-STALE'


def test_pending_buy_counts_as_occupied_slot_and_duplicate_guard():
    strategy = Strategy(StaticTrader())
    strategy._record_pending_order('buy', '600000', 1000, 'OID-PENDING', '20260713')

    assert strategy._occupied_slots() == 1
    assert strategy._is_position_or_pending('600000.SH') is True


def test_sync_positions_normalizes_broker_codes():
    class BareCodeTrader:
        def get_asset(self):
            return (100000.0, 50000.0, 50000.0, 0.0)

        def get_positions(self):
            return {'600000': {'volume': 1000, 'can_use': 1000, 'open_price': 10.0, 'market_value': 10000.0}}

    strategy = Strategy(BareCodeTrader())

    assert '600000.SH' in strategy.positions
    assert '600000' not in strategy.positions

