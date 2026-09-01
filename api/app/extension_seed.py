from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.extension_models import (
    ActivityPlan,
    ActivityStep,
    AssessmentCandidate,
    CaseAssignment,
    CaseStatusHistory,
    ExtensionCase,
    FollowUp,
    KnowledgeItem,
    KnowledgeSource,
    KnowledgeVersion,
    Observation,
    VerificationItem,
    VerificationResponse,
    VerificationSession,
    VerificationTemplateVersion,
)
from app.platform_models import User, Workspace
from app.platform_seed import stable_id


DEMO_TIME = datetime(2026, 8, 20, 8, 0, tzinfo=timezone.utc)


def seed_extension_demo(
    session: Session,
    workspace: Workspace,
    users: dict[str, User],
) -> None:
    """Add deterministic non-operational records without changing user-created data."""
    officer_1 = users["dev-extension-officer-1"]
    officer_2 = users["dev-extension-officer-2"]
    supervisor = users["dev-extension-supervisor"]
    editor = users["dev-knowledge-editor"]
    approver = users["dev-knowledge-approver"]

    knowledge_specs = [
        (
            "observation-completeness",
            "Field observation completeness checklist",
            "observation-template",
            ["Record crop and stage", "Record observed time", "Describe visible evidence", "Note missing information"],
        ),
        (
            "water-condition-template",
            "Water-condition observation template",
            "possible-cause-category",
            ["Observe standing water without inference", "Record recent visible field conditions", "Schedule verification if uncertain"],
        ),
        (
            "photo-evidence-checklist",
            "Pest or disease photo evidence checklist",
            "evidence-template",
            ["Use a general field view", "Use a close view of visible signs", "Avoid people and identifying documents"],
        ),
        (
            "follow-up-template",
            "Follow-up scheduling template",
            "follow-up-template",
            ["State the observation objective", "Set a responsible officer", "Set a due date", "Record outcome without personal names"],
        ),
    ]
    knowledge_versions: dict[str, KnowledgeVersion] = {}
    for key, title, category, checklist in knowledge_specs:
        item_id = stable_id("extension-knowledge", f"{workspace.id}:{key}")
        item = session.get(KnowledgeItem, item_id)
        if item is None:
            item = KnowledgeItem(
                id=item_id,
                workspace_id=workspace.id,
                item_key=key,
                title=title,
                category=category,
                status="ACTIVE",
                demonstration=True,
            )
            session.add(item)
            session.flush()
        version_id = stable_id("extension-knowledge-version", f"{item_id}:1")
        version = session.get(KnowledgeVersion, version_id)
        if version is None:
            version = KnowledgeVersion(
                id=version_id,
                workspace_id=workspace.id,
                knowledge_item_id=item.id,
                version_number=1,
                status="DEMO_APPROVED",
                content_json={
                    "purpose": "Demonstration workflow template; not agronomic advice.",
                    "checklist": checklist,
                    "automatic_advice": False,
                },
                source_summary=(
                    "Placeholder source metadata for a demonstration-only template. "
                    "No FAO or expert endorsement is claimed."
                ),
                created_by=editor.id,
                approved_by=approver.id,
                approved_at=DEMO_TIME,
            )
            session.add(version)
            session.flush()
            session.add(
                KnowledgeSource(
                    id=stable_id("extension-knowledge-source", str(version.id)),
                    knowledge_version_id=version.id,
                    title="Placeholder source — replace before operational use",
                    citation="Demonstration workspace placeholder; source validation pending.",
                    placeholder=True,
                )
            )
            item.current_version_id = version.id
        knowledge_versions[key] = version

    template_id = stable_id("extension-verification-template", f"{workspace.id}:field-check:1")
    template = session.get(VerificationTemplateVersion, template_id)
    if template is None:
        template = VerificationTemplateVersion(
            id=template_id,
            workspace_id=workspace.id,
            template_key="field-evidence-check",
            name="Demonstration field evidence verification",
            version_number=1,
            status="DEMO_APPROVED",
            created_by=editor.id,
            approved_by=approver.id,
        )
        session.add(template)
        session.flush()
        for ordinal, prompt in enumerate(
            [
                "Was the crop and growth stage recorded?",
                "Was the affected area estimated?",
                "Is visible evidence described without automated interpretation?",
                "Is missing information stated explicitly?",
            ],
            start=1,
        ):
            session.add(
                VerificationItem(
                    id=stable_id("extension-verification-item", f"{template.id}:{ordinal}"),
                    template_version_id=template.id,
                    ordinal=ordinal,
                    prompt=prompt,
                    response_type="YES_NO_UNKNOWN",
                    required=True,
                    required_evidence="Short officer note; no personal names.",
                )
            )

    case_specs = [
        ("DEMO-001", "Visible leaf colour change", "ASSIGNED", "HIGH", officer_1, "Tillering", 0.8, "Demo zone A"),
        ("DEMO-002", "Uneven standing water", "IN_OBSERVATION", "NORMAL", officer_1, "Vegetative", 1.2, "Demo zone B"),
        ("DEMO-003", "Patchy plant growth", "IN_VERIFICATION", "HIGH", officer_2, "Tillering", 0.6, "Demo zone C"),
        ("DEMO-004", "General field evidence review", "ACTION_PLANNED", "NORMAL", officer_2, "Heading", 1.8, "Demo zone D"),
        ("DEMO-005", "Follow-up evidence check", "FOLLOW_UP", "URGENT", officer_1, "Flowering", 0.5, "Demo zone E"),
        ("DEMO-006", "Observation record completed", "CLOSED", "LOW", officer_2, "Maturity", 1.0, "Demo zone F"),
        ("DEMO-007", "New unassigned demonstration case", "NEW", "NORMAL", None, "Not recorded", None, "Demo zone G"),
        ("DEMO-008", "Second follow-up evidence check", "FOLLOW_UP", "HIGH", officer_2, "Vegetative", 0.9, "Demo zone H"),
    ]
    cases: dict[str, ExtensionCase] = {}
    for index, (number, title, status, priority, officer, stage, area, location) in enumerate(case_specs):
        case_id = stable_id("extension-case", f"{workspace.id}:{number}")
        item = session.get(ExtensionCase, case_id)
        if item is None:
            item = ExtensionCase(
                id=case_id,
                workspace_id=workspace.id,
                case_number=number,
                title=title,
                crop="Rice",
                growth_stage=stage,
                severity="MODERATE" if priority != "URGENT" else "HIGH",
                affected_area_ha=area,
                location_label=location,
                approximate_lat=11.55 + index * 0.09,
                approximate_lon=104.75 + index * 0.07,
                priority=priority,
                status=status,
                notes=(
                    "DEMONSTRATION record using a fictional location and no farmer "
                    "identity. Manual observation workflow only."
                ),
                demonstration=True,
                created_by=(officer or supervisor).id,
                current_assignee_id=officer.id if officer else None,
                next_action={
                    "NEW": "Supervisor assignment",
                    "ASSIGNED": "Record first observation",
                    "IN_OBSERVATION": "Complete field evidence",
                    "IN_VERIFICATION": "Complete checklist",
                    "ACTION_PLANNED": "Supervisor activity review",
                    "FOLLOW_UP": "Record follow-up outcome",
                    "CLOSED": "No action",
                }[status],
                sync_status="SYNCED",
                created_at=DEMO_TIME,
                updated_at=DEMO_TIME,
                closed_at=DEMO_TIME if status == "CLOSED" else None,
            )
            session.add(item)
            session.flush()
            session.add(
                CaseStatusHistory(
                    id=stable_id("extension-case-history", f"{item.id}:seed"),
                    workspace_id=workspace.id,
                    case_id=item.id,
                    from_status=None,
                    to_status=status,
                    reason="Deterministic demonstration seed state.",
                    changed_by=supervisor.id,
                    changed_at=DEMO_TIME,
                )
            )
            if officer:
                session.add(
                    CaseAssignment(
                        id=stable_id("extension-assignment", f"{item.id}:{officer.id}"),
                        workspace_id=workspace.id,
                        case_id=item.id,
                        officer_id=officer.id,
                        assigned_by=supervisor.id,
                        reason="Demonstration workload assignment.",
                        active=True,
                        assigned_at=DEMO_TIME,
                    )
                )
        cases[number] = item

    for number in ("DEMO-002", "DEMO-003", "DEMO-004", "DEMO-005", "DEMO-006", "DEMO-008"):
        case = cases[number]
        observation_id = stable_id("extension-observation", f"{case.id}:1")
        if session.get(Observation, observation_id) is None:
            observation = Observation(
                id=observation_id,
                workspace_id=workspace.id,
                case_id=case.id,
                client_uuid=stable_id("extension-observation-client", f"{case.id}:1"),
                status="COMPLETED",
                observed_at=DEMO_TIME,
                severity=case.severity,
                affected_area_ha=case.affected_area_ha,
                approximate_location=case.location_label,
                notes="Visible conditions recorded manually; no automated conclusion.",
                structured_json={"evidence_complete": True, "automatic_assessment": False},
                created_by=case.current_assignee_id or supervisor.id,
                completed_at=DEMO_TIME,
            )
            session.add(observation)
            case.last_observation_at = DEMO_TIME

    assessment_case = cases["DEMO-003"]
    candidate_id = stable_id("extension-assessment", f"{assessment_case.id}:water-condition")
    if session.get(AssessmentCandidate, candidate_id) is None:
        session.add(
            AssessmentCandidate(
                id=candidate_id,
                workspace_id=workspace.id,
                case_id=assessment_case.id,
                knowledge_version_id=knowledge_versions["water-condition-template"].id,
                status="PROPOSED",
                supporting_observation_ids=[str(stable_id("extension-observation", f"{assessment_case.id}:1"))],
                missing_information=["Follow-up water-depth observation"],
                selected_by=officer_2.id,
                review_reason="Officer-selected demonstration category; verification pending.",
            )
        )

    verification_case = cases["DEMO-004"]
    verification_id = stable_id("extension-verification-session", f"{verification_case.id}:1")
    if session.get(VerificationSession, verification_id) is None:
        verification = VerificationSession(
            id=verification_id,
            workspace_id=workspace.id,
            case_id=verification_case.id,
            template_version_id=template.id,
            revision_number=1,
            status="DRAFT",
            created_by=officer_2.id,
            created_at=DEMO_TIME,
            completed_at=None,
        )
        session.add(verification)
        session.flush()
        template_items = session.scalars(
            select(VerificationItem)
            .where(VerificationItem.template_version_id == template.id)
            .order_by(VerificationItem.ordinal)
        ).all()
        for template_item in template_items:
            session.add(
                VerificationResponse(
                    id=stable_id("extension-verification-response", f"{verification.id}:{template_item.id}"),
                    verification_session_id=verification.id,
                    verification_item_id=template_item.id,
                    response_json={"value": "YES"},
                    evidence_note="Demonstration evidence note.",
                )
            )
        session.flush()
        verification.status = "COMPLETED"
        verification.completed_at = DEMO_TIME

    activity_specs = [
        ("DEMO-004", "field_visit", "Review visible field evidence with the assigned officer.", officer_2, date(2026, 9, 5), "PENDING_APPROVAL"),
        ("DEMO-005", "group_session", "Demonstrate complete, non-identifying observation records.", officer_1, date(2026, 8, 25), "APPROVED"),
    ]
    activities: dict[str, ActivityPlan] = {}
    for number, kind, objective, officer, due, status in activity_specs:
        plan_id = stable_id("extension-activity", f"{cases[number].id}:{kind}")
        plan = session.get(ActivityPlan, plan_id)
        if plan is None:
            plan = ActivityPlan(
                id=plan_id,
                workspace_id=workspace.id,
                case_id=cases[number].id,
                activity_type=kind,
                objective=objective,
                participant_count=0,
                responsible_officer_id=officer.id,
                due_date=due,
                status=status,
                created_by=officer.id,
                approved_by=supervisor.id if status == "APPROVED" else None,
                approved_at=DEMO_TIME if status == "APPROVED" else None,
            )
            session.add(plan)
            session.flush()
            for ordinal, description in enumerate(
                ["Confirm scope and privacy boundary", "Record structured evidence", "Schedule documented follow-up"],
                start=1,
            ):
                session.add(
                    ActivityStep(
                        id=stable_id("extension-activity-step", f"{plan.id}:{ordinal}"),
                        activity_plan_id=plan.id,
                        ordinal=ordinal,
                        description=description,
                        responsible_officer_id=officer.id,
                        due_date=due,
                    )
                )
        activities[number] = plan

    for number, due in (("DEMO-005", date(2026, 8, 22)), ("DEMO-008", date(2026, 8, 24))):
        follow_up_id = stable_id("extension-follow-up", f"{cases[number].id}:overdue")
        if session.get(FollowUp, follow_up_id) is None:
            session.add(
                FollowUp(
                    id=follow_up_id,
                    workspace_id=workspace.id,
                    case_id=cases[number].id,
                    activity_plan_id=activities.get(number).id if number in activities else None,
                    due_date=due,
                    status="OPEN",
                    objective="Record a second structured observation and any remaining information gaps.",
                    created_by=supervisor.id,
                )
            )
