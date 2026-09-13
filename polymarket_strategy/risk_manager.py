"""Risk management: independent of the pricing/EV/Kelly signal, this decides
whether a signal is allowed to fire at all right now, and caps how much it can
stake even when it is allowed.

Three controls, all measured against the STARTING bankroll (never the
compounded one, for the same reason `max_stake_fraction_of_starting_bankroll`
in strategy.py isn't compounded -- a growing bankroll shouldn't grow the
absolute risk taken per day or per trade):

  1. Daily loss cap: once realized P&L for the current day drops below
     `-max_daily_loss_fraction * starting_bankroll`, no more trades until the
     next day.
  2. Loss-streak pause: after `max_consecutive_losses` losing trades in a row,
     trading pauses for `cooldown_trades` subsequent candidate trades (not
     wall-clock time -- "the next N opportunities are skipped", which is what
     matters for a bot that may see trades at an irregular rate).
  3. Hard stake cap: every stake is clamped to
     `hard_max_stake_fraction * starting_bankroll`, regardless of what Kelly
     sizing (or a bug in it) suggests. This is the last line of defense
     against a sizing error blowing up the account on one trade.

A day is identified by a caller-supplied `day_key` (e.g. a date string or a
UNIX day number) rather than wall-clock time, so the same manager works for
both a live loop and a backtest replaying historical timestamps.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskLimits:
    max_daily_loss_fraction: float = 0.05
    max_consecutive_losses: int = 4
    cooldown_trades: int = 5
    hard_max_stake_fraction: float = 0.02

    def __post_init__(self) -> None:
        if not (0.0 < self.max_daily_loss_fraction <= 1.0):
            raise ValueError("max_daily_loss_fraction must be in (0, 1]")
        if self.max_consecutive_losses < 1:
            raise ValueError("max_consecutive_losses must be >= 1")
        if self.cooldown_trades < 0:
            raise ValueError("cooldown_trades must be >= 0")
        if not (0.0 < self.hard_max_stake_fraction <= 1.0):
            raise ValueError("hard_max_stake_fraction must be in (0, 1]")


@dataclass
class RiskDecision:
    allowed: bool
    reason: str = ""


class RiskManager:
    """Stateful gate: call `check(day_key)` before generating a signal, then
    `record_result(day_key, pnl)` after every trade actually taken (win or
    loss) so state advances correctly. Call `cap_stake(desired_stake)` when
    sizing any trade that is allowed through.
    """

    def __init__(self, limits: RiskLimits, starting_bankroll: float):
        if starting_bankroll <= 0:
            raise ValueError("starting_bankroll must be positive")
        self.limits = limits
        self.starting_bankroll = starting_bankroll
        self._current_day = None
        self._daily_pnl = 0.0
        self._consecutive_losses = 0
        self._cooldown_remaining = 0

    def _roll_day_if_needed(self, day_key) -> None:
        if day_key != self._current_day:
            self._current_day = day_key
            self._daily_pnl = 0.0
            # A loss streak carries across the day boundary deliberately: a
            # bot that lost 4 in a row at 23:59 is not suddenly trustworthy
            # again at 00:00. Only the daily loss cap resets on a new day.

    def check(self, day_key) -> RiskDecision:
        """Call before considering a new trade. Does NOT mutate state beyond
        rolling over the day counter, so it is safe to call repeatedly.
        """
        self._roll_day_if_needed(day_key)

        daily_cap = -self.limits.max_daily_loss_fraction * self.starting_bankroll
        if self._daily_pnl <= daily_cap:
            return RiskDecision(
                False,
                f"daily loss cap hit ({self._daily_pnl:.2f} <= {daily_cap:.2f} for {day_key})",
            )

        if self._cooldown_remaining > 0:
            return RiskDecision(
                False,
                f"cooldown active after {self.limits.max_consecutive_losses} consecutive "
                f"losses ({self._cooldown_remaining} candidate trade(s) remaining)",
            )

        return RiskDecision(True)

    def cap_stake(self, desired_stake: float) -> float:
        hard_cap = self.limits.hard_max_stake_fraction * self.starting_bankroll
        return max(0.0, min(desired_stake, hard_cap))

    def record_result(self, day_key, pnl: float) -> None:
        """Call once per trade actually taken (after check() allowed it and a
        stake was placed), with the realized P&L of that trade.
        """
        self._roll_day_if_needed(day_key)
        self._daily_pnl += pnl

        if pnl < 0:
            self._consecutive_losses += 1
            if self._consecutive_losses >= self.limits.max_consecutive_losses:
                self._cooldown_remaining = self.limits.cooldown_trades
        else:
            self._consecutive_losses = 0

    def record_skip_during_cooldown(self) -> None:
        """Call once per candidate trade that was SKIPPED because `check()`
        returned a cooldown decision, so the cooldown actually counts down in
        units of "trade opportunities seen" rather than lasting forever.
        """
        if self._cooldown_remaining > 0:
            self._cooldown_remaining -= 1

    @property
    def consecutive_losses(self) -> int:
        return self._consecutive_losses

    @property
    def cooldown_remaining(self) -> int:
        return self._cooldown_remaining

    @property
    def daily_pnl(self) -> float:
        return self._daily_pnl
