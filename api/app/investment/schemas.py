from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.investment.constants import INDICATOR_CODES


class CreateInputSetRequest(BaseModel):
    name: str = Field(min_length=3, max_length=240)
    label: str = Field(min_length=3, max_length=300)
    profile_mode: Literal["LEGACY_BUNDLE", "SEPARATE_LAYERS"]
    study_area_ref: dict[str, Any] = Field(default_factory=dict)
    run_mode_compatibility: list[Literal["FORMAL"]] = Field(default_factory=lambda: ["FORMAL"])


class PatchInputSetRequest(BaseModel):
    name: str | None = Field(default=None, min_length=3, max_length=240)
    label: str | None = Field(default=None, min_length=3, max_length=300)
    study_area_ref: dict[str, Any] | None = None
    row_version: int = Field(ge=1)


class InputMemberRequest(BaseModel):
    dataset_version_id: UUID
    representation_id: UUID
    input_role: Literal["legacy_priority_bundle", "administrative_boundary", "indicator"]
    indicator_code: str | None = None
    join_key: str = Field(default="area_code", min_length=1, max_length=120)
    value_field: str | None = Field(default=None, max_length=120)
    geometry_field: str | None = Field(default=None, max_length=120)
    unit: str | None = Field(default=None, max_length=120)
    direction: str | None = Field(default=None, max_length=64)
    time_coverage: dict[str, Any] = Field(default_factory=dict)
    required: bool = True
    transform_config: dict[str, Any] = Field(default_factory=dict)
    ordinal: int = Field(ge=0, le=100)

    @model_validator(mode="after")
    def validate_role(self):
        if self.input_role == "indicator":
            if self.indicator_code not in INDICATOR_CODES:
                raise ValueError("indicator role requires one of the approved indicator codes")
            if not self.value_field:
                raise ValueError("indicator role requires value_field")
            if self.direction != "higher_is_priority":
                raise ValueError("Phase 2A indicator direction must be higher_is_priority")
        elif self.indicator_code is not None:
            raise ValueError("indicator_code is only valid for indicator members")
        return self


class PatchInputMemberRequest(InputMemberRequest):
    row_version: int = Field(ge=1)


class CloneInputSetRequest(BaseModel):
    name: str = Field(min_length=3, max_length=240)
    label: str = Field(min_length=3, max_length=300)


class RetireRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)
    row_version: int = Field(ge=1)


class CreateMethodRequest(BaseModel):
    method_key: str = Field(pattern=r"^[a-z][a-z0-9-]+$", max_length=160)
    name: str = Field(min_length=3, max_length=300)
    description: str = Field(default="", max_length=4000)


class CreateMethodVersionRequest(BaseModel):
    version_label: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?$")
    specification: dict[str, Any]
    implementation_key: str = Field(min_length=3, max_length=200)
    code_ref: str = Field(min_length=3, max_length=240)
    container_metadata: dict[str, Any] = Field(default_factory=dict)
    validation_evidence: dict[str, Any] = Field(default_factory=dict)
    disclaimer: str = Field(min_length=10)


class PatchMethodVersionRequest(BaseModel):
    specification: dict[str, Any] | None = None
    validation_evidence: dict[str, Any] | None = None
    disclaimer: str | None = Field(default=None, min_length=10)
    row_version: int = Field(ge=1)


class WorkflowRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)
    row_version: int = Field(ge=1)


class CreateScenarioRequest(BaseModel):
    scenario_key: str = Field(pattern=r"^[a-z][a-z0-9-]+$", max_length=120)
    version_label: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?$")
    name: str = Field(min_length=3, max_length=300)
    description: str = Field(default="", max_length=4000)
    method_version_id: UUID
    parameters: dict[str, Any]
    disclaimer: str = Field(min_length=10)


class PatchScenarioRequest(BaseModel):
    name: str | None = Field(default=None, min_length=3, max_length=300)
    description: str | None = Field(default=None, max_length=4000)
    parameters: dict[str, Any] | None = None
    disclaimer: str | None = Field(default=None, min_length=10)
    row_version: int = Field(ge=1)


class CreateRunRequest(BaseModel):
    input_set_id: UUID
    method_version_id: UUID
    scenario_id: UUID
    run_mode: Literal["FORMAL"] = "FORMAL"
    overrides: dict[str, Any] = Field(default_factory=dict)

    @field_validator("overrides")
    @classmethod
    def validate_overrides(cls, value: dict[str, Any]) -> dict[str, Any]:
        unknown = set(value) - {"weights", "min_rice_area_ha"}
        if unknown:
            raise ValueError(f"Unsupported overrides: {', '.join(sorted(unknown))}")
        weights = value.get("weights")
        if weights is not None:
            if set(weights) - set(INDICATOR_CODES):
                raise ValueError("Override contains unknown indicator weights")
            if any(float(weight) < 0 for weight in weights.values()) or sum(weights.values()) <= 0:
                raise ValueError("Override weights must be non-negative and have a positive sum")
        minimum = value.get("min_rice_area_ha")
        if minimum is not None and not 0 <= float(minimum) <= 10000:
            raise ValueError("min_rice_area_ha must be between 0 and 10000")
        return value


class CancelRunRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


class CreateComparisonRequest(BaseModel):
    left_run_id: UUID
    right_run_id: UUID
    top_n: int = Field(default=20, ge=1, le=200)

    @model_validator(mode="after")
    def different_runs(self):
        if self.left_run_id == self.right_run_id:
            raise ValueError("Comparison requires two different runs")
        return self


class CreateExportRequest(BaseModel):
    asset_id: UUID
