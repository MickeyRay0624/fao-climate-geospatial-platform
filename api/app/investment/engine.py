from __future__ import annotations

import math
from typing import Any

from app.investment.canonical import checksum_json


class ScoringContractError(ValueError):
    pass


def normalise_weights(
    weights: dict[str, float], required_indicators: list[str]
) -> dict[str, float]:
    unknown = set(weights) - set(required_indicators)
    if unknown:
        raise ScoringContractError(f"Unknown indicators: {', '.join(sorted(unknown))}")
    complete = {
        code: max(0.0, float(weights.get(code, 0.0))) for code in required_indicators
    }
    total = sum(complete.values())
    if total <= 0:
        raise ScoringContractError("At least one weight must be greater than zero")
    return {code: value / total for code, value in complete.items()}


def _required_codes(method_spec: dict[str, Any]) -> list[str]:
    codes = [item["code"] for item in method_spec.get("required_indicators", [])]
    if not codes:
        raise ScoringContractError("Method specification has no required indicators")
    return codes


def score_priority_areas(
    prepared_areas: list[dict[str, Any]],
    method_spec: dict[str, Any],
    parameter_snapshot: dict[str, Any],
) -> list[dict[str, Any]]:
    """Pure deterministic implementation of the preserved synthetic method."""

    required = _required_codes(method_spec)
    neutral = float(method_spec["missing_values"]["neutral_value"])
    weights = normalise_weights(parameter_snapshot["weights"], required)
    minimum_area = float(parameter_snapshot["min_rice_area_ha"])
    seen: set[str] = set()
    scored: list[dict[str, Any]] = []

    for area in prepared_areas:
        code = str(area["code"])
        if not code:
            raise ScoringContractError("Area code cannot be empty")
        if code in seen:
            raise ScoringContractError(f"Duplicate area code: {code}")
        seen.add(code)
        values = area.get("indicators", {})
        missing = [indicator for indicator in required if values.get(indicator) is None]
        components: dict[str, dict[str, float | None]] = {}
        raw_score = 0.0

        for indicator, weight in weights.items():
            observed = values.get(indicator)
            if observed is not None and not 0 <= float(observed) <= 1:
                raise ScoringContractError(
                    f"Indicator {indicator} for {code} is outside the declared 0-1 domain"
                )
            value_for_score = neutral if observed is None else float(observed)
            contribution = weight * value_for_score * 100
            raw_score += contribution
            components[indicator] = {
                "value": None if observed is None else round(float(observed), 4),
                "weight": round(weight, 4),
                "contribution": round(contribution, 2),
            }

        completeness = 1 - len(missing) / len(required)
        quality_adjustment = 0.92 + 0.08 * completeness
        score = round(raw_score * quality_adjustment, 2)
        eligible = float(area["rice_area_ha"]) >= minimum_area
        scored.append(
            {
                **area,
                "score": score,
                "eligible": eligible,
                "components": components,
                "missing_indicators": missing,
                "data_completeness": round(completeness, 3),
                "quality_adjustment": round(quality_adjustment, 12),
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
            item["code"],
        ),
    )


def result_checksum(results: list[dict[str, Any]]) -> str:
    canonical_rows = [
        {
            "area_code": item["code"],
            "area_name": item["name"],
            "score": item["score"],
            "rank": item["rank"],
            "eligible": item["eligible"],
            "priority_band": item["priority_band"],
            "components": item["components"],
            "missing_indicators": item["missing_indicators"],
            "data_completeness": item["data_completeness"],
            "quality_adjustment": item["quality_adjustment"],
        }
        for item in sorted(results, key=lambda row: row["code"])
    ]
    return checksum_json(canonical_rows)
