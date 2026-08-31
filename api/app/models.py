from __future__ import annotations

from datetime import datetime
from typing import Any

from geoalchemy2 import Geometry
from geoalchemy2.elements import WKBElement
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from uuid import UUID


class Base(DeclarativeBase):
    pass


class DataCatalogItem(Base):
    __tablename__ = "data_catalog_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    data_kind: Mapped[str] = mapped_column(String(64), default="analysis_bundle")
    owner: Mapped[str] = mapped_column(String(160), default="DSS team")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    versions: Mapped[list[DataVersion]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan"
    )


class DataVersion(Base):
    __tablename__ = "data_versions"
    __table_args__ = (
        UniqueConstraint("dataset_id", "version_label", name="uq_dataset_version_label"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset_id: Mapped[int] = mapped_column(
        ForeignKey("data_catalog_items.id", ondelete="CASCADE"), index=True
    )
    version_label: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    source_filename: Mapped[str] = mapped_column(String(255))
    object_key: Mapped[str] = mapped_column(String(500))
    checksum_sha256: Mapped[str] = mapped_column(String(64))
    file_size: Mapped[int] = mapped_column(Integer)
    media_type: Mapped[str] = mapped_column(String(160))
    record_count: Mapped[int] = mapped_column(Integer, default=0)
    schema_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    notes: Mapped[str] = mapped_column(Text, default="")
    uploaded_by: Mapped[str] = mapped_column(String(160), default="Mickey Lei")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    dataset: Mapped[DataCatalogItem] = relationship(back_populates="versions")
    quality_checks: Mapped[list[DataQualityCheck]] = relationship(
        back_populates="version", cascade="all, delete-orphan"
    )
    areas: Mapped[list[AdminArea]] = relationship(
        back_populates="dataset_version", cascade="all, delete-orphan"
    )


class DataQualityCheck(Base):
    __tablename__ = "data_quality_checks"
    __table_args__ = (
        UniqueConstraint("version_id", "check_code", name="uq_version_quality_check"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_id: Mapped[int] = mapped_column(
        ForeignKey("data_versions.id", ondelete="CASCADE"), index=True
    )
    check_code: Mapped[str] = mapped_column(String(80))
    check_name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(32))
    severity: Mapped[str] = mapped_column(String(32))
    details: Mapped[str] = mapped_column(Text)
    affected_count: Mapped[int] = mapped_column(Integer, default=0)

    version: Mapped[DataVersion] = relationship(back_populates="quality_checks")


class AdminArea(Base):
    __tablename__ = "admin_areas"
    __table_args__ = (
        UniqueConstraint("dataset_version_id", "code", name="uq_version_area_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("data_versions.id", ondelete="CASCADE"), nullable=True, index=True
    )
    catalog_version_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True, index=True
    )
    code: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(160))
    province: Mapped[str] = mapped_column(String(120), index=True)
    population: Mapped[int] = mapped_column(Integer)
    rice_area_ha: Mapped[float] = mapped_column(Float)
    data_quality: Mapped[float] = mapped_column(Float)
    geom: Mapped[WKBElement] = mapped_column(
        Geometry("MULTIPOLYGON", srid=4326, spatial_index=True), nullable=False
    )

    dataset_version: Mapped[DataVersion | None] = relationship(back_populates="areas")
    indicator_values: Mapped[list[IndicatorValue]] = relationship(
        back_populates="area", cascade="all, delete-orphan"
    )


class Dataset(Base):
    """Indicator provenance retained from the first demonstrator."""

    __tablename__ = "datasets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    indicator_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    source_label: Mapped[str] = mapped_column(String(200))
    methodology: Mapped[str] = mapped_column(Text)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True)
    last_updated: Mapped[str] = mapped_column(String(32))


class IndicatorValue(Base):
    __tablename__ = "indicator_values"
    __table_args__ = (
        UniqueConstraint("area_id", "indicator_code", name="uq_area_indicator"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    area_id: Mapped[int] = mapped_column(
        ForeignKey("admin_areas.id", ondelete="CASCADE"), index=True
    )
    indicator_code: Mapped[str] = mapped_column(String(64), index=True)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    quality_flag: Mapped[str] = mapped_column(String(32), default="synthetic")

    area: Mapped[AdminArea] = relationship(back_populates="indicator_values")


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("data_versions.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    catalog_version_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True, index=True
    )
    scenario_key: Mapped[str] = mapped_column(String(64))
    weights: Mapped[dict[str, float]] = mapped_column(JSON)
    min_rice_area_ha: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    dataset_version: Mapped[DataVersion | None] = relationship()
    results: Mapped[list[PriorityResult]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class PriorityResult(Base):
    __tablename__ = "priority_results"
    __table_args__ = (
        UniqueConstraint("run_id", "area_id", name="uq_run_area_result"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), index=True
    )
    area_id: Mapped[int] = mapped_column(
        ForeignKey("admin_areas.id", ondelete="CASCADE"), index=True
    )
    score: Mapped[float] = mapped_column(Float)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    eligible: Mapped[bool] = mapped_column(Boolean)
    priority_band: Mapped[str] = mapped_column(String(32))
    components: Mapped[dict[str, Any]] = mapped_column(JSON)
    missing_indicators: Mapped[list[str]] = mapped_column(JSON)

    run: Mapped[AnalysisRun] = relationship(back_populates="results")
    area: Mapped[AdminArea] = relationship()
