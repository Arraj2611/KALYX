"""Weight profiles for compute_isq."""

WEIGHT_PROFILES: dict[str, tuple[float, float, float, float]] = {
    "default":    (0.35, 0.30, 0.20, 0.15),
    "risk":       (0.45, 0.25, 0.20, 0.10),
    "macro":      (0.25, 0.40, 0.20, 0.15),
    "short_term": (0.30, 0.25, 0.20, 0.25),
}
