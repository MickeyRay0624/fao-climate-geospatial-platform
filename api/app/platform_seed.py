from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import DEMO_DISCLAIMER
from app.models import AdminArea, AnalysisRun, DataCatalogItem, DataVersion
from app.module_registry import load_validated_manifests
from app.platform_models import (
    CatalogAsset,
    CatalogDataset,
    CatalogDatasetVersion,
    Group,
    GroupMembership,
    LegacyIdMapping,
    LineageEdge,
    LineageProcess,
    MetadataRecord,
    Module,
    Organization,
    Permission,
    QualityIssue,
    QualityProfile,
    QualityRun,
    Role,
    RoleAssignment,
    RolePermission,
    User,
    Workspace,
    WorkspaceMembership,
    WorkspaceModule,
)


NAMESPACE = uuid.UUID("51587a7c-8ff6-5d31-a115-7aa4c6d1687c")
DEV_ISSUER = "urn:fao:climate-platform:dev"
LEGACY_ISSUER = "urn:fao:climate-platform:legacy"


PERMISSIONS = {
    "platform.admin",
    "workspace.view",
    "workspace.manage_settings",
    "workspace.manage_members",
    "workspace.manage_groups",
    "workspace.manage_roles",
    "workspace.enable_modules",
    "data.catalog.enter",
    "dataset.create",
    "dataset.view_metadata",
    "dataset.preview",
    "dataset.download",
    "dataset.edit_metadata",
    "dataset.upload_version",
    "dataset.submit_review",
    "dataset.review",
    "dataset.publish",
    "dataset.manage_access",
    "dataset.deprecate",
    "dataset.archive",
    "dataset.delete_unpublished",
    "collection.create",
    "collection.manage",
    "lineage.view",
    "quality.manage_profiles",
    "apps.investment.use",
    "investment.run.create",
    "investment.run.view",
    "investment.run.export",
    "investment.run.compare",
    "audit.view",
    "audit.export",
    "jobs.view_own",
    "jobs.view_workspace",
    "jobs.retry",
    "system.health.view",
}


ROLE_PERMISSIONS = {
    "workspace_admin": PERMISSIONS - {"platform.admin"},
    "contributor": {
        "workspace.view", "data.catalog.enter", "dataset.create", "dataset.view_metadata",
        "dataset.preview", "dataset.download", "dataset.edit_metadata", "dataset.upload_version",
        "dataset.submit_review", "dataset.manage_access", "lineage.view", "jobs.view_own", "apps.investment.use",
    },
    "data_reviewer": {
        "workspace.view", "data.catalog.enter", "dataset.view_metadata", "dataset.preview",
        "dataset.download", "dataset.review", "lineage.view", "jobs.view_own", "jobs.view_workspace",
        "apps.investment.use",
    },
    "data_publisher": {
        "workspace.view", "data.catalog.enter", "dataset.view_metadata", "dataset.preview",
        "dataset.download", "dataset.publish", "dataset.deprecate", "dataset.archive",
        "lineage.view", "jobs.view_own", "jobs.view_workspace", "apps.investment.use",
    },
    "analyst": {
        "workspace.view", "data.catalog.enter", "dataset.view_metadata", "dataset.preview",
        "dataset.download", "lineage.view", "apps.investment.use", "investment.run.create",
        "investment.run.view", "investment.run.export", "investment.run.compare", "jobs.view_own",
    },
    "viewer": {
        "workspace.view", "data.catalog.enter", "dataset.view_metadata", "dataset.preview",
        "dataset.download", "lineage.view", "apps.investment.use", "investment.run.view",
        "investment.run.export", "investment.run.compare", "jobs.view_own",
    },
    "auditor": {
        "workspace.view", "data.catalog.enter", "dataset.view_metadata", "lineage.view",
        "audit.view", "audit.export", "jobs.view_own", "jobs.view_workspace",
        "apps.investment.use", "investment.run.view", "investment.run.compare",
    },
}


PERSONAS = {
    "dev-admin": ("Amina Sok", "Workspace administrator", "workspace_admin"),
    "dev-contributor": ("Dara Chann", "Data contributor", "contributor"),
    "dev-reviewer": ("Sophea Lim", "Data reviewer", "data_reviewer"),
    "dev-publisher": ("Nita Vann", "Data publisher", "data_publisher"),
    "dev-analyst": ("Vichea Pen", "Spatial analyst", "analyst"),
    "dev-viewer": ("Maly Chea", "Programme viewer", "viewer"),
    "dev-auditor": ("Samnang Khem", "Auditor", "auditor"),
}


def stable_id(kind: str, value: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, f"{kind}:{value}")


def _get_or_create_user(session: Session, subject: str, name: str, issuer: str, email: str | None) -> User:
    user = session.scalar(select(User).where(User.issuer == issuer, User.external_subject == subject))
    if user is None:
        user = User(
            id=stable_id("user", f"{issuer}:{subject}"),
            issuer=issuer,
            external_subject=subject,
            display_name=name,
            email=email,
            status="active",
        )
        session.add(user)
        session.flush()
    return user


def _mapping(session: Session, entity_type: str, legacy_id: int, new_id: uuid.UUID) -> None:
    if session.scalar(
        select(LegacyIdMapping.id).where(
            LegacyIdMapping.entity_type == entity_type,
            LegacyIdMapping.legacy_id == str(legacy_id),
        )
    ) is None:
        session.add(LegacyIdMapping(entity_type=entity_type, legacy_id=str(legacy_id), new_id=new_id))


def seed_platform(session: Session) -> None:
    organization = session.scalar(select(Organization).where(Organization.slug == "fao-climate-change-group"))
    if organization is None:
        organization = Organization(
            id=stable_id("organization", "fao-climate-change-group"),
            slug="fao-climate-change-group",
            name="FAO Climate Change Group",
        )
        session.add(organization)
        session.flush()

    workspace = session.scalar(
        select(Workspace).where(
            Workspace.organization_id == organization.id,
            Workspace.slug == "cambodia-rice-resilience",
        )
    )
    if workspace is None:
        workspace = Workspace(
            id=stable_id("workspace", "cambodia-rice-resilience"),
            organization_id=organization.id,
            slug="cambodia-rice-resilience",
            name="Cambodia Rice Resilience",
            description="Local workspace for the synthetic prioritisation demonstrator and governed Data Hub pilot.",
            country_codes=["KH"],
            default_visibility="PRIVATE",
            default_classification="FAO_INTERNAL",
        )
        session.add(workspace)
        session.flush()

    legacy_user = _get_or_create_user(
        session,
        "mickey-legacy",
        "Mickey Lei (legacy attribution)",
        LEGACY_ISSUER,
        None,
    )
    users: dict[str, User] = {}
    for subject, (name, title, _) in PERSONAS.items():
        users[subject] = _get_or_create_user(
            session, subject, name, DEV_ISSUER, f"{subject}@example.invalid"
        )

    for user in [legacy_user, *users.values()]:
        if session.scalar(
            select(WorkspaceMembership.id).where(
                WorkspaceMembership.workspace_id == workspace.id,
                WorkspaceMembership.user_id == user.id,
            )
        ) is None:
            session.add(WorkspaceMembership(workspace_id=workspace.id, user_id=user.id, status="active"))

    group_specs = {
        "climate-data-stewards": "Climate data stewards",
        "data-review-board": "Data review board",
        "data-publishers": "Data publishers",
        "spatial-analysts": "Spatial analysts",
    }
    groups: dict[str, Group] = {}
    for slug, name in group_specs.items():
        group = session.scalar(select(Group).where(Group.workspace_id == workspace.id, Group.slug == slug))
        if group is None:
            group = Group(
                id=stable_id("group", f"{workspace.id}:{slug}"),
                workspace_id=workspace.id,
                slug=slug,
                name=name,
            )
            session.add(group)
            session.flush()
        groups[slug] = group

    group_personas = {
        "climate-data-stewards": "dev-contributor",
        "data-review-board": "dev-reviewer",
        "data-publishers": "dev-publisher",
        "spatial-analysts": "dev-analyst",
    }
    for group_slug, subject in group_personas.items():
        group, user = groups[group_slug], users[subject]
        if session.scalar(
            select(GroupMembership.id).where(GroupMembership.group_id == group.id, GroupMembership.user_id == user.id)
        ) is None:
            session.add(GroupMembership(group_id=group.id, user_id=user.id))

    permission_rows: dict[str, Permission] = {}
    for code in sorted(PERMISSIONS):
        permission = session.scalar(select(Permission).where(Permission.code == code))
        if permission is None:
            permission = Permission(id=stable_id("permission", code), code=code, description=code.replace(".", " ").replace("_", " ").title())
            session.add(permission)
            session.flush()
        permission_rows[code] = permission

    roles: dict[str, Role] = {}
    for role_key, codes in ROLE_PERMISSIONS.items():
        role = session.scalar(select(Role).where(Role.workspace_id == workspace.id, Role.role_key == role_key))
        if role is None:
            role = Role(
                id=stable_id("role", f"{workspace.id}:{role_key}"),
                workspace_id=workspace.id,
                role_key=role_key,
                name=role_key.replace("_", " ").title(),
                description=f"Seeded {role_key} role bundle for the local workspace.",
            )
            session.add(role)
            session.flush()
        roles[role_key] = role
        for code in codes:
            if session.scalar(
                select(RolePermission.id).where(
                    RolePermission.role_id == role.id,
                    RolePermission.permission_id == permission_rows[code].id,
                )
            ) is None:
                session.add(RolePermission(role_id=role.id, permission_id=permission_rows[code].id))

    for subject, (_, _, role_key) in PERSONAS.items():
        user, role = users[subject], roles[role_key]
        if session.scalar(
            select(RoleAssignment.id).where(
                RoleAssignment.subject_type == "user",
                RoleAssignment.subject_id == user.id,
                RoleAssignment.role_id == role.id,
                RoleAssignment.scope_id == workspace.id,
            )
        ) is None:
            session.add(
                RoleAssignment(
                    subject_type="user",
                    subject_id=user.id,
                    role_id=role.id,
                    scope_type="workspace",
                    scope_id=workspace.id,
                    assigned_by=users["dev-admin"].id,
                    reason="Idempotent local development persona seed",
                )
            )

    for manifest in load_validated_manifests():
        module_key = manifest["module"]["key"]
        module = session.scalar(select(Module).where(Module.module_key == module_key))
        if module is None:
            module = Module(
                id=stable_id("module", module_key),
                module_key=module_key,
                name=manifest["module"]["name"],
                description=manifest["module"]["description"],
                contract_version=manifest["contract_version"],
                module_version=manifest["module"]["version"],
                manifest=manifest,
                status="installed",
                manifest_valid=True,
            )
            session.add(module)
            session.flush()
        enabled = module_key == "investment-prioritisation"
        workspace_module = session.scalar(
            select(WorkspaceModule).where(
                WorkspaceModule.workspace_id == workspace.id,
                WorkspaceModule.module_id == module.id,
            )
        )
        if workspace_module is None:
            workspace_module = WorkspaceModule(
                workspace_id=workspace.id,
                module_id=module.id,
                enabled=enabled,
                feature_flags={item["key"]: item["default"] for item in manifest.get("feature_flags", [])},
            )
            session.add(workspace_module)

    profile_specs = {
        "analysis-ready-priority-bundle@1.0": "vector",
        "generic-vector@1.0": "vector",
        "generic-table@1.0": "table",
        "document@1.0": "document",
    }
    profiles: dict[str, QualityProfile] = {}
    for key, data_kind in profile_specs.items():
        profile_key, version = key.split("@", 1)
        profile = session.scalar(
            select(QualityProfile).where(
                QualityProfile.profile_key == profile_key,
                QualityProfile.profile_version == version,
            )
        )
        if profile is None:
            profile = QualityProfile(
                id=stable_id("quality-profile", key),
                profile_key=profile_key,
                profile_version=version,
                data_kind=data_kind,
                rules_json={"contract": key, "engine": "platform-validator/1.0"},
            )
            session.add(profile)
            session.flush()
        profiles[key] = profile

    session.flush()
    _backfill_legacy(session, workspace, legacy_user, profiles["analysis-ready-priority-bundle@1.0"])
    session.commit()


def _backfill_legacy(
    session: Session,
    workspace: Workspace,
    legacy_user: User,
    quality_profile: QualityProfile,
) -> None:
    legacy_datasets = session.scalars(select(DataCatalogItem).order_by(DataCatalogItem.id)).all()
    for legacy_dataset in legacy_datasets:
        dataset_id = stable_id("legacy-dataset", str(legacy_dataset.id))
        dataset = session.get(CatalogDataset, dataset_id)
        if dataset is None:
            dataset = CatalogDataset(
                id=dataset_id,
                workspace_id=workspace.id,
                slug=legacy_dataset.slug,
                title=legacy_dataset.name,
                abstract=legacy_dataset.description,
                data_kind="vector",
                owner_user_id=legacy_user.id,
                visibility="WORKSPACE",
                classification="FAO_INTERNAL",
                lifecycle_status="ACTIVE",
                licence_code="DEMO-ONLY",
                created_by=legacy_user.id,
                updated_by=legacy_user.id,
                created_at=legacy_dataset.created_at,
            )
            session.add(dataset)
            session.flush()
        _mapping(session, "data_catalog_items", legacy_dataset.id, dataset.id)

        for legacy_version in legacy_dataset.versions:
            version_id = stable_id("legacy-version", str(legacy_version.id))
            version = session.get(CatalogDatasetVersion, version_id)
            target_state = {
                "draft": "DRAFT",
                "validated": "VALIDATED",
                "published": "PUBLISHED",
                "archived": "ARCHIVED",
            }.get(legacy_version.status, "DRAFT")
            created_now = version is None
            if version is None:
                version = CatalogDatasetVersion(
                    id=version_id,
                    dataset_id=dataset.id,
                    version_label=legacy_version.version_label,
                    # Assets are registered before the immutable terminal state is set.
                    state="APPROVED" if target_state in {"PUBLISHED", "ARCHIVED"} else target_state,
                    profile_key="analysis-ready-priority-bundle@1.0",
                    change_summary=legacy_version.notes,
                    metadata_snapshot={
                        "title": legacy_dataset.name,
                        "abstract": legacy_dataset.description,
                        "synthetic": True,
                        "illustrative": True,
                        "operational_use": False,
                        "disclaimer": DEMO_DISCLAIMER,
                        "legacy_source": True,
                    },
                    created_by=legacy_user.id,
                    approved_by=legacy_user.id if target_state in {"PUBLISHED", "ARCHIVED"} else None,
                    published_by=legacy_user.id if target_state in {"PUBLISHED", "ARCHIVED"} else None,
                    created_at=legacy_version.created_at,
                    approved_at=legacy_version.published_at,
                    published_at=legacy_version.published_at,
                )
                session.add(version)
                session.flush()
            _mapping(session, "data_versions", legacy_version.id, version.id)
            if session.scalar(select(CatalogAsset.id).where(CatalogAsset.object_key == legacy_version.object_key)) is None:
                session.add(
                    CatalogAsset(
                        id=stable_id("legacy-asset", str(legacy_version.id)),
                        dataset_version_id=version.id,
                        role="source",
                        filename=legacy_version.source_filename,
                        object_key=legacy_version.object_key,
                        media_type=legacy_version.media_type,
                        size_bytes=legacy_version.file_size,
                        sha256=legacy_version.checksum_sha256,
                        scan_status="LEGACY_UNSCANNED",
                    )
                )
                session.flush()
            if legacy_version.is_current:
                dataset.current_published_version_id = version.id
            if session.scalar(
                select(MetadataRecord.id).where(MetadataRecord.dataset_version_id == version.id)
            ) is None:
                session.add(
                    MetadataRecord(
                        id=stable_id("legacy-metadata", str(legacy_version.id)),
                        dataset_version_id=version.id,
                        title=legacy_dataset.name,
                        abstract=legacy_dataset.description,
                        purpose="Synthetic demonstration of the prioritisation workflow.",
                        producer="FAO DSS demonstration team",
                        provenance="Deterministic local synthetic seed 260826; not an official source.",
                        licence_code="DEMO-ONLY",
                        use_limitation=DEMO_DISCLAIMER,
                        crs="EPSG:4326",
                        methodology="Synthetic correlated indicators over clipped demonstration grid cells.",
                        quality_statement="Illustrative data only; no operational or agronomic use.",
                        keywords=["synthetic", "Cambodia", "rice", "climate resilience"],
                        sensitive_data_declaration="No personal data; synthetic geometry and attributes.",
                    )
                )
                session.flush()
            if created_now and target_state in {"PUBLISHED", "ARCHIVED"}:
                version.state = target_state
                session.flush()
            quality_run = session.scalar(
                select(QualityRun).where(
                    QualityRun.dataset_version_id == version.id,
                    QualityRun.engine_version == "legacy-mvp/0.2",
                )
            )
            if quality_run is None:
                statuses = [check.status for check in legacy_version.quality_checks]
                run_status = "FAILED" if "failed" in statuses else ("WARNING" if "warning" in statuses else "PASSED")
                quality_run = QualityRun(
                    id=stable_id("legacy-quality-run", str(legacy_version.id)),
                    dataset_version_id=version.id,
                    quality_profile_id=quality_profile.id,
                    engine_version="legacy-mvp/0.2",
                    status=run_status,
                    started_at=legacy_version.created_at,
                    completed_at=legacy_version.created_at,
                    summary_json={
                        "passed": statuses.count("passed"),
                        "warning": statuses.count("warning"),
                        "failed": statuses.count("failed"),
                        "record_count": legacy_version.record_count,
                    },
                )
                session.add(quality_run)
                session.flush()
                for check in legacy_version.quality_checks:
                    if check.status == "passed":
                        continue
                    session.add(
                        QualityIssue(
                            id=stable_id("legacy-quality-issue", str(check.id)),
                            quality_run_id=quality_run.id,
                            code=check.check_code.upper(),
                            name=check.check_name,
                            severity="BLOCKING" if check.status == "failed" else "WARNING",
                            affected_count=check.affected_count,
                            details_json={"message": check.details, "legacy_check_id": check.id},
                        )
                    )

            process = session.get(LineageProcess, stable_id("legacy-lineage", str(legacy_version.id)))
            if process is None:
                process = LineageProcess(
                    id=stable_id("legacy-lineage", str(legacy_version.id)),
                    workspace_id=workspace.id,
                    process_type="import",
                    module_key="data-hub",
                    external_run_type="legacy_seed_or_upload",
                    external_run_id=str(legacy_version.id),
                    method_identifier="legacy-catalog-backfill",
                    method_version="1.0",
                    parameters_json={"object_moved": False, "legacy_version_id": legacy_version.id},
                    status="SUCCEEDED",
                    completed_at=datetime.now(timezone.utc),
                )
                session.add(process)
                session.flush()
                session.add(
                    LineageEdge(
                        process_id=process.id,
                        direction="OUTPUT",
                        dataset_version_id=version.id,
                        role="catalog-version",
                        ordinal=0,
                    )
                )
            session.query(AdminArea).filter(AdminArea.dataset_version_id == legacy_version.id).update(
                {AdminArea.catalog_version_id: version.id}, synchronize_session=False
            )
            session.query(AnalysisRun).filter(AnalysisRun.dataset_version_id == legacy_version.id).update(
                {AnalysisRun.catalog_version_id: version.id}, synchronize_session=False
            )
