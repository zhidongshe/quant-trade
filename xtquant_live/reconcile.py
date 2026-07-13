def _volume_of(positions: dict, code: str) -> int:
    info = positions.get(code) or {}
    return int(info.get('volume', 0))


def classify_buy_outcome(code: str, requested_volume: int, before_positions: dict, after_positions: dict) -> str:
    before_volume = _volume_of(before_positions, code)
    after_volume = _volume_of(after_positions, code)
    if code not in before_positions and before_volume == 0:
        if after_volume == 0:
            return 'missing_before'
    delta = after_volume - before_volume
    if delta >= requested_volume:
        return 'filled'
    if delta > 0:
        return 'partial'
    return 'unchanged'


def classify_sell_outcome(code: str, requested_volume: int, before_positions: dict, after_positions: dict) -> str:
    before_volume = _volume_of(before_positions, code)
    after_volume = _volume_of(after_positions, code)
    if before_volume == 0:
        return 'missing_before'
    delta = before_volume - after_volume
    if delta >= requested_volume:
        return 'filled'
    if delta > 0:
        return 'partial'
    return 'unchanged'
