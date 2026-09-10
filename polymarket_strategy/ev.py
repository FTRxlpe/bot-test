"""Expected value of a binary-contract trade.

EV = (P_win * Gain) - (P_loss * Cost)

For a Polymarket-style share priced at `price` in (0, 1) that pays out $1 if
it resolves YES and $0 otherwise:
  Gain = 1 - price   (profit per share if it wins)
  Cost = price        (amount lost per share if it loses)
"""
from __future__ import annotations


def expected_value(win_probability: float, price: float) -> float:
    if not 0.0 <= win_probability <= 1.0:
        raise ValueError("win_probability must be in [0, 1]")
    if not 0.0 < price < 1.0:
        raise ValueError("price must be in (0, 1)")

    gain = 1.0 - price
    cost = price
    loss_probability = 1.0 - win_probability
    return (win_probability * gain) - (loss_probability * cost)
