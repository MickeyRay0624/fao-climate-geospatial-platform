from __future__ import annotations

from app.catalog import INDICATORS, SCENARIOS
from app.config import DEMO_DISCLAIMER


METHOD_KEY = "legacy-weighted-linear-combination"
METHOD_VERSION_LABEL = "legacy-wlc-1.0.0"
METHOD_IMPLEMENTATION_KEY = "investment.score_priority_areas.v1"
WORKER_TASK_VERSION = "investment:run-prioritisation:v1"

INDICATOR_CODES = tuple(INDICATORS)

LEGACY_METHOD_SPEC = {
    "schema_version": "1.0",
    "method_key": METHOD_KEY,
    "implementation_key": METHOD_IMPLEMENTATION_KEY,
    "required_indicators": [
        {
            "code": code,
            "direction": "higher_is_priority",
            "normalisation": "pre_normalised_0_1",
            "required": True,
        }
        for code in INDICATOR_CODES
    ],
    "weighting": {
        "entered_weights_normalised": True,
        "normalisation_formula": "entered_weight_i / sum(all entered weights)",
        "non_negative": True,
    },
    "missing_values": {
        "policy": "neutral_value",
        "neutral_value": 0.5,
        "reported": True,
    },
    "completeness": {
        "formula": "1 - missing_indicator_count / 7",
        "quality_adjustment_formula": "0.92 + 0.08 * completeness",
        "data_quality_field_affects_score": False,
    },
    "score": {
        "raw_formula": "sum(normalised_weight_i * indicator_i * 100)",
        "final_formula": "raw_score * quality_adjustment",
        "persisted_precision": 2,
        "display_precision": 2,
    },
    "eligibility": {
        "field": "rice_area_ha",
        "operator": ">=",
        "parameter": "min_rice_area_ha",
        "default": 750.0,
        "minimum": 0.0,
        "maximum": 10000.0,
    },
    "banding": {
        "basis": "eligible_relative_rank",
        "breaks": [
            {"maximum_percentile": 0.2, "label": "Very high"},
            {"maximum_percentile": 0.5, "label": "High"},
            {"maximum_percentile": 0.8, "label": "Medium"},
            {"maximum_percentile": 1.0, "label": "Lower"},
        ],
        "ineligible_label": "Not eligible",
    },
    "tie_breaker": ["score_desc", "area_code_asc"],
    "allowed_overrides": ["weights", "min_rice_area_ha"],
    "input_profiles": [
        "analysis-ready-priority-bundle@1.0",
        "administrative-boundary@1.0 + normalised-indicator-layer@1.0",
    ],
    "disclaimer": DEMO_DISCLAIMER,
}


SCENARIO_SEED = {
    key: {
        "scenario_key": key,
        "version_label": "1.0.0",
        "name": definition["label"],
        "description": definition["description"],
        "parameters": {
            "weights": definition["weights"],
            "min_rice_area_ha": 750.0,
        },
    }
    for key, definition in SCENARIOS.items()
}


CLASSIFICATION_ORDER = {
    "PUBLIC": 0,
    "FAO_INTERNAL": 1,
    "RESTRICTED": 2,
    "SENSITIVE_FIELD": 3,
}


def strictest_classification(values: list[str]) -> str:
    candidates = ["FAO_INTERNAL", *[value.upper() for value in values]]
    return max(candidates, key=lambda value: CLASSIFICATION_ORDER.get(value, 3))
