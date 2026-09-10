import pytest

from polymarket_strategy.ev import expected_value


def test_ev_fair_price_is_zero():
    # win_probability == price -> no edge -> EV == 0
    assert expected_value(win_probability=0.7, price=0.7) == pytest.approx(0.0, abs=1e-9)


def test_ev_positive_when_underpriced():
    # priced at 0.80 but true win rate is 0.90 -> positive EV
    ev = expected_value(win_probability=0.90, price=0.80)
    assert ev == pytest.approx(0.90 * 0.20 - 0.10 * 0.80)
    assert ev > 0


def test_ev_negative_when_overpriced():
    ev = expected_value(win_probability=0.70, price=0.80)
    assert ev < 0


def test_ev_rejects_out_of_range_inputs():
    with pytest.raises(ValueError):
        expected_value(win_probability=1.5, price=0.5)
    with pytest.raises(ValueError):
        expected_value(win_probability=0.5, price=0.0)
    with pytest.raises(ValueError):
        expected_value(win_probability=0.5, price=1.0)
