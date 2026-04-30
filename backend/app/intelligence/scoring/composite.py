"""compute_isq — 4-dimensional composite signal quality scoring."""
from dataclasses import dataclass

from app.intelligence.scoring.weights import WEIGHT_PROFILES


@dataclass
class SignalQuality:
    confidence: float
    intensity: float
    expectation_gap: float
    timeliness: float
    composite: float
    tier: str


_VELOCITY_LEVELS = {"spike": 1.0, "elevated": 0.6}
_DEFAULT_VELOCITY = 0.2


def compute_isq(
    source_count: int,
    is_alert: bool,
    source_tier: int | None,
    intensity_value: float,
    expectation_gap_value: float,
    velocity_level: str,
    velocity_trend: str | None,
    profile: str = "default",
) -> SignalQuality:
    if profile not in WEIGHT_PROFILES:
        raise KeyError(f"Unknown weight profile: {profile}")

    w_conf, w_int, w_gap, w_time = WEIGHT_PROFILES[profile]

    if source_count >= 3:
        conf_base = 1.0
    elif source_count == 2:
        conf_base = 0.7
    else:
        conf_base = 0.4
    conf = conf_base
    if is_alert:
        conf += 0.2
    if source_tier is not None and source_tier <= 2:
        conf += 0.1
    conf = min(1.0, conf)

    timeliness = _VELOCITY_LEVELS.get(velocity_level, _DEFAULT_VELOCITY)
    if velocity_trend == "rising":
        timeliness = min(1.0, timeliness + 0.2)

    composite = (
        w_conf * conf
        + w_int * intensity_value
        + w_gap * expectation_gap_value
        + w_time * timeliness
    )

    if composite >= 0.75:
        tier = "strong"
    elif composite >= 0.50:
        tier = "notable"
    elif composite >= 0.25:
        tier = "weak"
    else:
        tier = "noise"

    return SignalQuality(
        confidence=conf,
        intensity=intensity_value,
        expectation_gap=expectation_gap_value,
        timeliness=timeliness,
        composite=composite,
        tier=tier,
    )
