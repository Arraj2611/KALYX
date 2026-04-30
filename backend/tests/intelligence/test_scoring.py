"""Exhaustive tests for compute_isq composite scoring."""
import pytest


def test_weight_profiles_sum_to_one():
    from app.intelligence.scoring.weights import WEIGHT_PROFILES

    for profile, weights in WEIGHT_PROFILES.items():
        assert abs(sum(weights) - 1.0) < 0.001, f"Profile '{profile}' weights don't sum to 1.0"


def test_signal_quality_dataclass():
    from app.intelligence.scoring.composite import SignalQuality

    sq = SignalQuality(
        confidence=0.8, intensity=0.6, expectation_gap=0.5,
        timeliness=0.7, composite=0.7, tier="notable",
    )
    assert sq.composite == 0.7
    assert sq.tier == "notable"


def test_compute_isq_strong_tier():
    from app.intelligence.scoring.composite import compute_isq

    sq = compute_isq(
        source_count=3, is_alert=True, source_tier=1,
        intensity_value=1.0, expectation_gap_value=0.8,
        velocity_level="spike", velocity_trend="rising",
        profile="default",
    )
    assert sq.tier == "strong"
    assert sq.composite >= 0.75


def test_compute_isq_noise_tier():
    from app.intelligence.scoring.composite import compute_isq

    sq = compute_isq(
        source_count=1, is_alert=False, source_tier=None,
        intensity_value=0.1, expectation_gap_value=0.1,
        velocity_level="normal", velocity_trend=None,
        profile="default",
    )
    assert sq.tier == "noise"


def test_compute_isq_confidence_high_with_3_sources():
    from app.intelligence.scoring.composite import compute_isq

    sq = compute_isq(
        source_count=3, is_alert=False, source_tier=None,
        intensity_value=0.5, expectation_gap_value=0.5,
        velocity_level="normal", velocity_trend=None,
        profile="default",
    )
    assert sq.confidence == 1.0


def test_compute_isq_confidence_medium_with_2_sources():
    from app.intelligence.scoring.composite import compute_isq

    sq = compute_isq(
        source_count=2, is_alert=False, source_tier=None,
        intensity_value=0.5, expectation_gap_value=0.5,
        velocity_level="normal", velocity_trend=None,
        profile="default",
    )
    assert sq.confidence == 0.7


def test_compute_isq_confidence_low_with_1_source():
    from app.intelligence.scoring.composite import compute_isq

    sq = compute_isq(
        source_count=1, is_alert=False, source_tier=None,
        intensity_value=0.5, expectation_gap_value=0.5,
        velocity_level="normal", velocity_trend=None,
        profile="default",
    )
    assert sq.confidence == 0.4


def test_compute_isq_alert_boost():
    from app.intelligence.scoring.composite import compute_isq

    plain = compute_isq(
        source_count=2, is_alert=False, source_tier=None,
        intensity_value=0.5, expectation_gap_value=0.5,
        velocity_level="normal", velocity_trend=None,
    )
    alert = compute_isq(
        source_count=2, is_alert=True, source_tier=None,
        intensity_value=0.5, expectation_gap_value=0.5,
        velocity_level="normal", velocity_trend=None,
    )
    assert alert.confidence > plain.confidence


def test_compute_isq_tier_boost():
    from app.intelligence.scoring.composite import compute_isq

    no_tier = compute_isq(
        source_count=2, is_alert=False, source_tier=None,
        intensity_value=0.5, expectation_gap_value=0.5,
        velocity_level="normal", velocity_trend=None,
    )
    tier1 = compute_isq(
        source_count=2, is_alert=False, source_tier=1,
        intensity_value=0.5, expectation_gap_value=0.5,
        velocity_level="normal", velocity_trend=None,
    )
    assert tier1.confidence > no_tier.confidence


def test_compute_isq_velocity_spike():
    from app.intelligence.scoring.composite import compute_isq

    normal = compute_isq(
        source_count=2, is_alert=False, source_tier=None,
        intensity_value=0.5, expectation_gap_value=0.5,
        velocity_level="normal", velocity_trend=None,
    )
    spike = compute_isq(
        source_count=2, is_alert=False, source_tier=None,
        intensity_value=0.5, expectation_gap_value=0.5,
        velocity_level="spike", velocity_trend=None,
    )
    assert spike.timeliness > normal.timeliness
    assert spike.timeliness == 1.0


def test_compute_isq_velocity_rising_boost():
    from app.intelligence.scoring.composite import compute_isq

    elevated = compute_isq(
        source_count=2, is_alert=False, source_tier=None,
        intensity_value=0.5, expectation_gap_value=0.5,
        velocity_level="elevated", velocity_trend=None,
    )
    rising = compute_isq(
        source_count=2, is_alert=False, source_tier=None,
        intensity_value=0.5, expectation_gap_value=0.5,
        velocity_level="elevated", velocity_trend="rising",
    )
    assert rising.timeliness > elevated.timeliness


def test_compute_isq_risk_profile_weights_confidence_higher():
    from app.intelligence.scoring.composite import compute_isq

    default = compute_isq(
        source_count=3, is_alert=True, source_tier=1,
        intensity_value=0.3, expectation_gap_value=0.3,
        velocity_level="normal", velocity_trend=None,
        profile="default",
    )
    risk = compute_isq(
        source_count=3, is_alert=True, source_tier=1,
        intensity_value=0.3, expectation_gap_value=0.3,
        velocity_level="normal", velocity_trend=None,
        profile="risk",
    )
    assert risk.composite > default.composite


def test_compute_isq_macro_profile_weights_intensity_higher():
    from app.intelligence.scoring.composite import compute_isq

    default = compute_isq(
        source_count=1, is_alert=False, source_tier=None,
        intensity_value=1.0, expectation_gap_value=0.3,
        velocity_level="normal", velocity_trend=None,
        profile="default",
    )
    macro = compute_isq(
        source_count=1, is_alert=False, source_tier=None,
        intensity_value=1.0, expectation_gap_value=0.3,
        velocity_level="normal", velocity_trend=None,
        profile="macro",
    )
    assert macro.composite > default.composite


def test_compute_isq_unknown_profile_raises():
    from app.intelligence.scoring.composite import compute_isq

    with pytest.raises(KeyError):
        compute_isq(
            source_count=1, is_alert=False, source_tier=None,
            intensity_value=0.5, expectation_gap_value=0.5,
            velocity_level="normal", velocity_trend=None,
            profile="nonexistent",
        )


def test_compute_isq_tier_boundaries():
    from app.intelligence.scoring.composite import compute_isq

    very_high = compute_isq(
        source_count=3, is_alert=True, source_tier=1,
        intensity_value=1.0, expectation_gap_value=1.0,
        velocity_level="spike", velocity_trend="rising",
        profile="default",
    )
    assert very_high.tier == "strong"

    very_low = compute_isq(
        source_count=1, is_alert=False, source_tier=None,
        intensity_value=0.0, expectation_gap_value=0.0,
        velocity_level="normal", velocity_trend=None,
        profile="default",
    )
    assert very_low.tier in ("noise", "weak")
