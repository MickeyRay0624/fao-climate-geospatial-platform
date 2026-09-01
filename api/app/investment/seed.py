from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.catalog import INDICATORS
from app.config import DEMO_DISCLAIMER
from app.investment.canonical import checksum_json
from app.investment.constants import (
    LEGACY_METHOD_SPEC,
    METHOD_IMPLEMENTATION_KEY,
    METHOD_KEY,
    METHOD_VERSION_LABEL,
    SCENARIO_SEED,
)
from app.investment.service import canonical_input_set, validate_input_set
from app.platform_models import (
    CatalogDataset,
    CatalogDatasetVersion,
    Group,
    InvestmentAnalysisInputMember,
    InvestmentAnalysisInputSet,
    InvestmentIndicatorDefinition,
    InvestmentMethodDefinition,
    InvestmentMethodVersion,
    InvestmentScenario,
    InvestmentScenarioParameter,
    Representation,
    User,
    Workspace,
)


NAMESPACE = uuid.UUID("47dbe377-b763-5bc1-af09-430af281a965")


def investment_id(kind: str, value: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, f"{kind}:{value}")


def _user(session: Session, subject: str) -> User:
    user = session.scalar(select(User).where(User.external_subject == subject))
    if user is None:
        raise RuntimeError(f"Required seeded persona {subject} is unavailable")
    return user


def seed_investment_governance(session: Session) -> dict[str, object]:
    workspace = session.scalar(select(Workspace).where(Workspace.slug == "cambodia-rice-resilience"))
    if workspace is None:
        raise RuntimeError("Cambodia Rice Resilience workspace is unavailable")
    editor = _user(session, "dev-method-editor")
    approver = _user(session, "dev-method-approver")
    legacy_user = _user(session, "mickey-legacy")
    owner_group = session.scalar(
        select(Group).where(Group.workspace_id == workspace.id, Group.slug == "investment-method-board")
    )

    for code, definition in INDICATORS.items():
        row = session.scalar(select(InvestmentIndicatorDefinition).where(InvestmentIndicatorDefinition.code == code))
        if row is None:
            session.add(
                InvestmentIndicatorDefinition(
                    id=investment_id("indicator", code),
                    code=code,
                    title=definition["label"],
                    description=definition["description"],
                    unit=definition["unit"],
                    direction="higher_is_priority",
                    expected_profile="normalised-indicator-layer@1.0",
                    owner_group_id=owner_group.id if owner_group else None,
                    state="APPROVED",
                    created_by=editor.id,
                    updated_by=editor.id,
                )
            )

    method = session.scalar(
        select(InvestmentMethodDefinition).where(InvestmentMethodDefinition.method_key == METHOD_KEY)
    )
    if method is None:
        method = InvestmentMethodDefinition(
            id=investment_id("method", METHOD_KEY),
            method_key=METHOD_KEY,
            name="Legacy weighted linear combination",
            description="Versioned preservation of the synthetic Cambodia prioritisation demonstrator.",
            owner_group_id=owner_group.id if owner_group else None,
            status="ACTIVE",
            created_by=editor.id,
            updated_by=editor.id,
        )
        session.add(method)
        session.flush()
    method_version = session.scalar(
        select(InvestmentMethodVersion).where(
            InvestmentMethodVersion.method_id == method.id,
            InvestmentMethodVersion.version_label == METHOD_VERSION_LABEL,
        )
    )
    if method_version is None:
        approved_at = datetime.now(timezone.utc)
        method_version = InvestmentMethodVersion(
            id=investment_id("method-version", METHOD_VERSION_LABEL),
            method_id=method.id,
            version_label=METHOD_VERSION_LABEL,
            state="APPROVED",
            specification_json=LEGACY_METHOD_SPEC,
            checksum=checksum_json(LEGACY_METHOD_SPEC),
            implementation_key=METHOD_IMPLEMENTATION_KEY,
            code_ref="git:71c4bd152b68359a7c84824ab673ec089f60b547:preserved-phase1-method",
            container_metadata={"historical_baseline": True, "image_digest": None, "digest_verified": False},
            validation_evidence={
                "legacy_regression": {"areas": 111, "rank_1": "Prey Veng Demo Commune 03", "displayed_score": 65.32},
                "business_validation": "not_performed",
            },
            disclaimer=DEMO_DISCLAIMER,
            created_by=editor.id,
            submitted_by=editor.id,
            approved_by=approver.id,
            submitted_at=approved_at,
            approved_at=approved_at,
        )
        session.add(method_version)
        session.flush()

    scenarios: dict[str, InvestmentScenario] = {}
    for key, definition in SCENARIO_SEED.items():
        scenario = session.scalar(
            select(InvestmentScenario).where(
                InvestmentScenario.workspace_id == workspace.id,
                InvestmentScenario.scenario_key == key,
                InvestmentScenario.version_label == definition["version_label"],
            )
        )
        if scenario is None:
            approved_at = datetime.now(timezone.utc)
            scenario = InvestmentScenario(
                id=investment_id("scenario", f"{workspace.id}:{key}:1.0.0"),
                workspace_id=workspace.id,
                scenario_key=key,
                version_label=definition["version_label"],
                name=definition["name"],
                description=definition["description"],
                method_version_id=method_version.id,
                state="DRAFT",
                parameters_json=definition["parameters"],
                checksum=checksum_json(definition["parameters"]),
                disclaimer=DEMO_DISCLAIMER,
                created_by=editor.id,
                submitted_by=editor.id,
                approved_by=approver.id,
                submitted_at=approved_at,
                approved_at=approved_at,
            )
            session.add(scenario)
            session.flush()
            for ordinal, (parameter_key, value) in enumerate(definition["parameters"]["weights"].items()):
                session.add(
                    InvestmentScenarioParameter(
                        id=investment_id("scenario-parameter", f"{scenario.id}:{parameter_key}"),
                        scenario_id=scenario.id,
                        parameter_key=parameter_key,
                        numeric_value=float(value),
                        ordinal=ordinal,
                    )
                )
            session.add(
                InvestmentScenarioParameter(
                    id=investment_id("scenario-parameter", f"{scenario.id}:min_rice_area_ha"),
                    scenario_id=scenario.id,
                    parameter_key="min_rice_area_ha",
                    numeric_value=float(definition["parameters"]["min_rice_area_ha"]),
                    ordinal=len(definition["parameters"]["weights"]),
                )
            )
            session.flush()
            scenario.state = "APPROVED"
        scenarios[key] = scenario

    bundle_input = _ensure_bundle_input_set(session, workspace, legacy_user)
    session.flush()
    return {
        "workspace": workspace,
        "method": method,
        "method_version": method_version,
        "scenarios": scenarios,
        "bundle_input_set": bundle_input,
    }


def _ensure_bundle_input_set(
    session: Session, workspace: Workspace, creator: User
) -> InvestmentAnalysisInputSet | None:
    version = session.scalar(
        select(CatalogDatasetVersion)
        .join(CatalogDataset, CatalogDataset.id == CatalogDatasetVersion.dataset_id)
        .where(
            CatalogDataset.slug == "cambodia-rice-priority-synthetic",
            CatalogDatasetVersion.version_label == "1.0.0",
        )
    )
    if version is None:
        return None
    representation = session.scalar(
        select(Representation).where(
            Representation.dataset_version_id == version.id,
            Representation.representation_type == "legacy_priority_bundle",
        )
    )
    if representation is None:
        return None
    input_set_id = investment_id("input-set", f"{workspace.id}:legacy-bundle-1.0")
    item = session.get(InvestmentAnalysisInputSet, input_set_id)
    if item is None:
        item = InvestmentAnalysisInputSet(
            id=input_set_id,
            workspace_id=workspace.id,
            name="legacy-bundle-1.0",
            label="Cambodia synthetic priority bundle 1.0",
            profile_mode="LEGACY_BUNDLE",
            status="DRAFT",
            study_area_ref={"country": "KH", "level": "commune", "synthetic": True},
            run_mode_compatibility=["FORMAL"],
            strictest_classification="FAO_INTERNAL",
            created_by=creator.id,
        )
        session.add(item)
        session.flush()
        session.add(
            InvestmentAnalysisInputMember(
                id=investment_id("input-member", f"{input_set_id}:bundle"),
                input_set_id=input_set_id,
                dataset_version_id=version.id,
                representation_id=representation.id,
                input_role="legacy_priority_bundle",
                join_key="code",
                geometry_field="geometry",
                required=True,
                transform_config={"admin_level": "commune"},
                ordinal=0,
            )
        )
        session.flush()
        readiness = validate_input_set(session, item, require_published=True)
        if not readiness["ready"]:
            raise RuntimeError(f"Seeded legacy input set is not ready: {readiness['errors']}")
        members = session.scalars(
            select(InvestmentAnalysisInputMember).where(InvestmentAnalysisInputMember.input_set_id == item.id)
        ).all()
        item.readiness_result = readiness
        item.warnings_json = readiness["warnings"]
        item.strictest_classification = readiness["strictest_classification"]
        item.checksum = checksum_json(canonical_input_set(item, list(members)))
        item.status = "LOCKED"
        item.locked_by = creator.id
        item.locked_at = datetime.now(timezone.utc)
    return item
