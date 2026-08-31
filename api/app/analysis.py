from __future__ import annotations

import math
from typing import Any

from app.catalog import INDICATORS


def normalise_weights(weights: dict[str, float]) -> dict[str, float]:
    complete = {code: max(0.0, float(weights.get(code, 0.0))) for code in INDICATORS}
    total = sum(complete.values())
    if total <= 0:
        raise ValueError("At least one weight must be greater than zero")
    return {code: value / total for code, value in complete.items()}


def calculate_priorities(
    areas: list[dict[str, Any]],
    weights: dict[str, float],
    min_rice_area_ha: float,
) -> list[dict[str, Any]]:
    """Calculate transparent weighted scores from already normalised indicators.

    Every indicator is oriented so that a higher value means a stronger reason to
    prioritise an area. Missing values use a neutral 0.5 and are exposed in the
    output rather than silently discarded.
    """

    normalised_weights = normalise_weights(weights)
    scored: list[dict[str, Any]] = []

    for area in areas:
        values = area["indicators"]
        missing = [code for code in INDICATORS if values.get(code) is None]
        components: dict[str, dict[str, float | None]] = {}
        raw_score = 0.0

        for code, weight in normalised_weights.items():
            observed = values.get(code)
            value_for_score = 0.5 if observed is None else min(1.0, max(0.0, observed))
            contribution = weight * value_for_score * 100
            raw_score += contribution
            components[code] = {
                "value": None if observed is None else round(float(observed), 4),
                "weight": round(weight, 4),
                "contribution": round(contribution, 2),
            }

        completeness = 1 - len(missing) / len(INDICATORS)
        quality_adjustment = 0.92 + 0.08 * completeness
        score = raw_score * quality_adjustment
        eligible = float(area["rice_area_ha"]) >= min_rice_area_ha

        scored.append(
            {
                **area,
                "score": round(score, 2),
                "eligible": eligible,
                "components": components,
                "missing_indicators": missing,
                "data_completeness": round(completeness, 3),
            }
        )

    eligible_results = sorted(
        (item for item in scored if item["eligible"]),
        key=lambda item: (-item["score"], item["code"]),
    )
    eligible_count = len(eligible_results)

    for index, item in enumerate(eligible_results, start=1):
        item["rank"] = index
        percentile = index / max(eligible_count, 1)
        if percentile <= 0.2:
            item["priority_band"] = "Very high"
        elif percentile <= 0.5:
            item["priority_band"] = "High"
        elif percentile <= 0.8:
            item["priority_band"] = "Medium"
        else:
            item["priority_band"] = "Lower"

    for item in scored:
        if not item["eligible"]:
            item["rank"] = None
            item["priority_band"] = "Not eligible"

    return sorted(
        scored,
        key=lambda item: (
            not item["eligible"],
            item["rank"] if item["rank"] is not None else math.inf,
        ),
    )

