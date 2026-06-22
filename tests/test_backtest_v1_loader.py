import os
from backtest_v1 import load_v1_module

V1_PATH = 'hs300_trend_strategy_single_file_v1.py'

def test_load_v1_module_exposes_handlebar_and_init():
    def fake_passorder(*a, **kw): pass
    def fake_get_trade_detail_data(*a, **kw): return []
    def fake_get_sector(*a, **kw): return []
    def fake_get_instrumentdetail(*a, **kw): return {}
    def fake_timetag_to_datetime(t, f): return ''
    mod = load_v1_module(V1_PATH, {
        'passorder': fake_passorder,
        'get_trade_detail_data': fake_get_trade_detail_data,
        'get_sector': fake_get_sector,
        'get_instrumentdetail': fake_get_instrumentdetail,
        'timetag_to_datetime': fake_timetag_to_datetime,
    })
    assert hasattr(mod, 'handlebar')
    assert hasattr(mod, 'init')
