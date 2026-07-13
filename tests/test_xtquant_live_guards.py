from xtquant_live.guards import guard_can_open_new_positions, guard_can_continue_cycle


def test_guard_blocks_new_buys_when_asset_query_missing():
    allowed, reason = guard_can_open_new_positions(None, {"600000.SH": {"volume": 100}}, True)
    assert allowed is False
    assert reason == "asset_unavailable"


def test_guard_allows_cycle_when_positions_exist_even_if_asset_missing():
    allowed, reason = guard_can_continue_cycle(None, {"600000.SH": {"volume": 100}})
    assert allowed is True
    assert reason == "sell_only"
