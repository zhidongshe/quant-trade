from xtquant_live.reconcile import (
    classify_buy_outcome,
    classify_sell_outcome,
    volume_delta_after_buy,
    volume_delta_after_sell,
)


def test_classify_buy_outcome_marks_filled_when_volume_increases():
    before_positions = {'600000.SH': {'volume': 1000}}
    after_positions = {'600000.SH': {'volume': 1500}}

    outcome = classify_buy_outcome('600000.SH', 500, before_positions, after_positions)

    assert outcome == 'filled'


def test_classify_sell_outcome_marks_unchanged_when_position_still_same():
    before_positions = {'600000.SH': {'volume': 1000}}
    after_positions = {'600000.SH': {'volume': 1000}}

    outcome = classify_sell_outcome('600000.SH', 1000, before_positions, after_positions)

    assert outcome == 'unchanged'


def test_volume_delta_helpers_report_actual_broker_changes():
    before_positions = {'600000.SH': {'volume': 1000}}
    after_positions = {'600000.SH': {'volume': 1300}}

    assert volume_delta_after_buy('600000.SH', before_positions, after_positions) == 300
    assert volume_delta_after_sell('600000.SH', after_positions, before_positions) == 300
