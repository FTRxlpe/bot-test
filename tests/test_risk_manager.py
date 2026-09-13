import pytest

from polymarket_strategy.risk_manager import RiskLimits, RiskManager


def test_daily_loss_cap_blocks_further_trades_same_day():
    limits = RiskLimits(max_daily_loss_fraction=0.05, hard_max_stake_fraction=0.10)
    rm = RiskManager(limits, starting_bankroll=100.0)

    assert rm.check(day_key=1).allowed is True
    rm.record_result(day_key=1, pnl=-6.0)  # exceeds 5% of 100 = $5 cap

    decision = rm.check(day_key=1)
    assert decision.allowed is False
    assert "daily loss cap" in decision.reason


def test_daily_loss_cap_resets_on_new_day():
    limits = RiskLimits(max_daily_loss_fraction=0.05)
    rm = RiskManager(limits, starting_bankroll=100.0)
    rm.record_result(day_key=1, pnl=-6.0)
    assert rm.check(day_key=1).allowed is False
    assert rm.check(day_key=2).allowed is True  # new day, daily P&L resets


def test_loss_streak_triggers_cooldown():
    limits = RiskLimits(max_consecutive_losses=3, cooldown_trades=2, max_daily_loss_fraction=1.0)
    rm = RiskManager(limits, starting_bankroll=100.0)

    for _ in range(3):
        assert rm.check(day_key=1).allowed is True
        rm.record_result(day_key=1, pnl=-1.0)

    # 3rd consecutive loss triggers the cooldown
    decision = rm.check(day_key=1)
    assert decision.allowed is False
    assert "cooldown" in decision.reason


def test_cooldown_counts_down_and_clears():
    limits = RiskLimits(max_consecutive_losses=2, cooldown_trades=2, max_daily_loss_fraction=1.0)
    rm = RiskManager(limits, starting_bankroll=100.0)
    rm.record_result(day_key=1, pnl=-1.0)
    rm.record_result(day_key=1, pnl=-1.0)  # 2 losses -> cooldown of 2 armed

    assert rm.check(day_key=1).allowed is False
    rm.record_skip_during_cooldown()
    assert rm.check(day_key=1).allowed is False
    rm.record_skip_during_cooldown()
    assert rm.check(day_key=1).allowed is True  # cooldown exhausted


def test_a_win_resets_the_consecutive_loss_counter():
    limits = RiskLimits(max_consecutive_losses=2, cooldown_trades=5, max_daily_loss_fraction=1.0)
    rm = RiskManager(limits, starting_bankroll=100.0)
    rm.record_result(day_key=1, pnl=-1.0)
    rm.record_result(day_key=1, pnl=+2.0)  # win breaks the streak
    rm.record_result(day_key=1, pnl=-1.0)
    assert rm.check(day_key=1).allowed is True  # only 1 consecutive loss, no cooldown


def test_loss_streak_carries_across_day_boundary():
    limits = RiskLimits(max_consecutive_losses=2, cooldown_trades=3, max_daily_loss_fraction=1.0)
    rm = RiskManager(limits, starting_bankroll=100.0)
    rm.record_result(day_key=1, pnl=-1.0)
    rm.record_result(day_key=1, pnl=-1.0)  # cooldown armed at end of day 1
    assert rm.check(day_key=2).allowed is False  # new day, but streak still applies


def test_hard_stake_cap_overrides_kelly_suggestion():
    limits = RiskLimits(hard_max_stake_fraction=0.02)
    rm = RiskManager(limits, starting_bankroll=1000.0)
    # Kelly (or a bug) suggests staking $500 -- must be clamped to 2% of $1000 = $20
    assert rm.cap_stake(500.0) == pytest.approx(20.0)
    assert rm.cap_stake(5.0) == pytest.approx(5.0)  # below cap: unaffected


def test_risk_limits_reject_invalid_values():
    with pytest.raises(ValueError):
        RiskLimits(max_daily_loss_fraction=0.0)
    with pytest.raises(ValueError):
        RiskLimits(max_consecutive_losses=0)
    with pytest.raises(ValueError):
        RiskLimits(cooldown_trades=-1)
    with pytest.raises(ValueError):
        RiskLimits(hard_max_stake_fraction=1.5)


def test_risk_manager_rejects_nonpositive_bankroll():
    with pytest.raises(ValueError):
        RiskManager(RiskLimits(), starting_bankroll=0.0)
