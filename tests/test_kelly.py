import pytest

from polymarket_strategy.kelly import kelly_fraction


def test_kelly_zero_edge_gives_zero_stake():
    # p == price -> b*p - q == 0 -> f* == 0
    f = kelly_fraction(win_probability=0.7, price=0.7)
    assert f == pytest.approx(0.0, abs=1e-9)


def test_kelly_positive_edge():
    # classic textbook case: p=0.6 win prob on an even-money bet (price=0.5, b=1)
    # f* = (p*b - q) / b = (0.6*1 - 0.4) / 1 = 0.2
    f = kelly_fraction(win_probability=0.6, price=0.5)
    assert f == pytest.approx(0.2)


def test_kelly_fractional_discount():
    full = kelly_fraction(win_probability=0.6, price=0.5, fraction=1.0)
    quarter = kelly_fraction(win_probability=0.6, price=0.5, fraction=0.25)
    assert quarter == pytest.approx(full * 0.25)


def test_kelly_never_negative_when_no_edge():
    # true win prob below the market price -> negative raw edge -> clamped to 0
    f = kelly_fraction(win_probability=0.5, price=0.8)
    assert f == 0.0


def test_kelly_rejects_bad_fraction():
    with pytest.raises(ValueError):
        kelly_fraction(win_probability=0.6, price=0.5, fraction=0.0)
    with pytest.raises(ValueError):
        kelly_fraction(win_probability=0.6, price=0.5, fraction=1.5)
