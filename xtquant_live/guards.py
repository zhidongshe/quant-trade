def guard_can_open_new_positions(asset: tuple | None, positions: dict | None, history_ok: bool) -> tuple[bool, str]:
    if asset is None:
        return False, "asset_unavailable"
    if positions is None:
        return False, "positions_unavailable"
    if not history_ok:
        return False, "history_unavailable"
    return True, "ok"


def guard_can_continue_cycle(asset: tuple | None, positions: dict | None) -> tuple[bool, str]:
    if positions is None:
        return False, "positions_unavailable"
    if asset is None:
        return True, "sell_only"
    return True, "ok"
