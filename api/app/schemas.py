from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.catalog import INDICATORS


class AnalysisRequest(BaseModel):
    dataset_version_id: int = Field(gt=0)
    scenario_key: str = "balanced"
    weights: dict[str, float] | None = None
    min_rice_area_ha: float = Field(default=750, ge=0, le=10_000)

    @field_validator("weights")
    @classmethod
    def validate_weights(
        cls, weights: dict[str, float] | None
    ) -> dict[str, float] | None:
        if weights is None:
            return None
        unknown = set(weights) - set(INDICATORS)
        if unknown:
            raise ValueError(f"Unknown indicators: {', '.join(sorted(unknown))}")
        if any(value < 0 for value in weights.values()):
            raise ValueError("Weights cannot be negative")
        if sum(weights.values()) <= 0:
            raise ValueError("At least one weight must be greater than zero")
        return weights
