from __future__ import annotations

from typing import Any

from app.catalog import INDICATORS
from app.investment.constants import LEGACY_METHOD_SPEC
from app.investment.engine import (
    normalise_weights as normalise_native_weights,
    score_priority_areas,
)


def normalise_weights(weights: dict[str, float]) -> dict[str, float]:
    return normalise_native_weights(weights, list(INDICATORS))


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

    return score_priority_areas(
        areas,
        LEGACY_METHOD_SPEC,
        {
            "weights": normalise_weights(weights),
            "min_rice_area_ha": min_rice_area_ha,
        },
    )
