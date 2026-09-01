from __future__ import annotations

import hashlib
import json
import random
from collections import defaultdict
from datetime import datetime, timezone

from geoalchemy2.shape import from_shape
from shapely.geometry import MultiPolygon, Polygon, box
from sqlalchemy import func, select

from app.catalog import INDICATORS
from app.database import SessionLocal
from app.ingestion import parse_upload
from app.migrations import ensure_schema
from app.models import (
    AdminArea,
    AnalysisRun,
    DataCatalogItem,
    DataQualityCheck,
    DataVersion,
    Dataset,
    IndicatorValue,
)
from app.object_store import ensure_bucket, put_bytes


RANDOM_SEED = 260826
GRID_STEP = 0.40

CAMBODIA_DEMO_OUTLINE = Polygon(
    [
        (102.35, 14.35),
        (102.80, 14.55),
        (103.55, 14.45),
        (104.25, 14.25),
        (105.10, 14.35),
        (105.90, 14.18),
        (106.60, 13.85),
        (107.45, 13.45),
        (107.72, 12.65),
        (107.25, 12.00),
        (106.85, 11.25),
        (106.05, 10.62),
        (105.25, 10.42),
        (104.45, 10.45),
        (103.70, 10.68),
        (103.15, 11.10),
        (102.78, 11.75),
        (102.72, 12.40),
        (102.42, 13.10),
    ]
)


def clamp(value: float, lower: float = 0.04, upper: float = 0.98) -> float:
    return max(lower, min(upper, value))


def polygonal_parts(geometry: object) -> list[Polygon]:
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, MultiPolygon):
        return list(geometry.geoms)
    if hasattr(geometry, "geoms"):
        return [part for part in geometry.geoms if isinstance(part, Polygon)]
    return []


def build_demo_communes() -> list[MultiPolygon]:
    min_x, min_y, max_x, max_y = CAMBODIA_DEMO_OUTLINE.bounds
    cells: list[MultiPolygon] = []
    x = min_x
    while x < max_x:
        y = min_y
        while y < max_y:
            clipped = box(x, y, x + GRID_STEP, y + GRID_STEP).intersection(
                CAMBODIA_DEMO_OUTLINE
            )
            parts = polygonal_parts(clipped)
            if parts and sum(part.area for part in parts) >= GRID_STEP**2 * 0.24:
                cells.append(MultiPolygon(parts))
            y += GRID_STEP
        x += GRID_STEP

    return sorted(cells, key=lambda item: (-item.centroid.y, item.centroid.x))


def assign_demo_province(lon: float, lat: float) -> str:
    if lat >= 13.75 and lon < 104.2:
        return "Banteay Meanchey"
    if lat >= 13.55 and lon < 105.3:
        return "Siem Reap"
    if lat >= 13.35 and lon >= 105.3:
        return "Preah Vihear"
    if lon < 103.65 and lat >= 12.5:
        return "Battambang"
    if lon < 104.2:
        return "Pursat"
    if lat >= 12.7 and lon < 105.7:
        return "Kampong Thom"
    if lat >= 12.6 and lon >= 105.7:
        return "Kratie"
    if lon >= 106.55 and lat < 12.6:
        return "Svay Rieng"
    if lon >= 105.45 and lat < 12.6:
        return "Prey Veng"
    if lat < 11.2 and lon < 104.8:
        return "Kampot"
    if lat < 11.65:
        return "Takeo"
    if lon < 105.1:
        return "Kampong Chhnang"
    if lon < 105.75:
        return "Kampong Cham"
    return "Tbong Khmum"


def synthetic_values(
    index: int, lon: float, lat: float, rng: random.Random
) -> tuple[dict[str, float | None], float, int, float]:
    west_to_east = (lon - 102.35) / (107.72 - 102.35)
    south_to_north = (lat - 10.42) / (14.55 - 10.42)
    centrality = 1 - min(1.0, abs(west_to_east - 0.52) * 1.9)
    distance_from_hub = min(
        1.0, ((lon - 104.92) ** 2 + (lat - 11.56) ** 2) ** 0.5 / 3.25
    )

    drought_risk = clamp(
        0.25 + 0.34 * west_to_east + 0.18 * south_to_north + rng.gauss(0, 0.10)
    )
    flood_risk = clamp(
        0.22
        + 0.34 * (1 - south_to_north)
        + 0.22 * centrality
        + rng.gauss(0, 0.10)
    )
    irrigation_gap = clamp(
        0.25 + 0.26 * drought_risk + 0.17 * distance_from_hub + rng.gauss(0, 0.10)
    )
    market_isolation = clamp(
        0.12 + 0.70 * distance_from_hub + rng.gauss(0, 0.08)
    )
    poverty_index = clamp(
        0.18
        + 0.38 * market_isolation
        + 0.12 * max(drought_risk, flood_risk)
        + rng.gauss(0, 0.09)
    )
    yield_gap = clamp(
        0.18
        + 0.36 * drought_risk
        + 0.22 * irrigation_gap
        + 0.12 * market_isolation
        + rng.gauss(0, 0.09)
    )
    nbs_opportunity = clamp(
        0.18
        + 0.28 * drought_risk
        + 0.26 * flood_risk
        + 0.16 * (1 - centrality)
        + rng.gauss(0, 0.08)
    )

    values: dict[str, float | None] = {
        "yield_gap": yield_gap,
        "drought_risk": drought_risk,
        "flood_risk": flood_risk,
        "poverty_index": poverty_index,
        "irrigation_gap": irrigation_gap,
        "market_isolation": market_isolation,
        "nbs_opportunity": nbs_opportunity,
    }

    # A small, deterministic amount of missingness makes the data-quality handling visible.
    indicator_codes = list(INDICATORS)
    if index % 19 == 0:
        values[indicator_codes[(index // 19) % len(indicator_codes)]] = None

    lowland_suitability = clamp(0.72 * centrality + 0.28 * (1 - south_to_north), 0, 1)
    rice_area_ha = round(
        420 + 2_950 * lowland_suitability + 620 * rng.random(), 1
    )
    population = int(4_500 + 28_000 * centrality + 8_000 * rng.random())
    base_quality = round(0.75 + 0.22 * rng.random(), 3)
    return values, rice_area_ha, population, base_quality


def version_geojson_bytes(session: object, version_id: int) -> bytes:
    indicator_rows = session.scalars(
        select(IndicatorValue)
        .join(AdminArea, AdminArea.id == IndicatorValue.area_id)
        .where(AdminArea.dataset_version_id == version_id)
    ).all()
    values: defaultdict[int, dict[str, float | None]] = defaultdict(dict)
    for row in indicator_rows:
        values[row.area_id][row.indicator_code] = row.value

    area_rows = session.execute(
        select(AdminArea, func.ST_AsGeoJSON(AdminArea.geom, 6))
        .where(AdminArea.dataset_version_id == version_id)
        .order_by(AdminArea.code)
    ).all()
    features = []
    for area, geometry_json in area_rows:
        features.append(
            {
                "type": "Feature",
                "id": area.code,
                "geometry": json.loads(geometry_json),
                "properties": {
                    "code": area.code,
                    "name": area.name,
                    "province": area.province,
                    "population": area.population,
                    "rice_area_ha": area.rice_area_ha,
                    "data_quality": area.data_quality,
                    **{
                        code: values.get(area.id, {}).get(code) for code in INDICATORS
                    },
                },
            }
        )
    return json.dumps(
        {"type": "FeatureCollection", "features": features}, separators=(",", ":")
    ).encode("utf-8")


def seed() -> None:
    ensure_schema()
    ensure_bucket(retries=45, delay_seconds=1)

    with SessionLocal() as session:
        for code, definition in INDICATORS.items():
            if not session.scalar(select(Dataset.id).where(Dataset.indicator_code == code)):
                session.add(
                    Dataset(
                        indicator_code=code,
                        title=definition["label"],
                        source_label="Deterministic synthetic demonstration dataset",
                        methodology=(
                            "Correlated values generated with a fixed random seed and spatial "
                            "gradients. Values are normalised to 0–1 and oriented so higher "
                            "means a stronger reason to prioritise intervention."
                        ),
                        is_synthetic=True,
                        last_updated="2026-08-28",
                    )
                )

        dataset = session.scalar(
            select(DataCatalogItem).where(
                DataCatalogItem.slug == "cambodia-rice-priority-synthetic"
            )
        )
        if dataset is None:
            dataset = DataCatalogItem(
                slug="cambodia-rice-priority-synthetic",
                name="Cambodia rice priority demonstration data",
                description=(
                    "Synthetic commune geometry and seven correlated indicators for "
                    "testing the climate-resilient rice prioritisation workflow."
                ),
                data_kind="analysis_bundle",
                owner="FAO DSS demonstration team",
            )
            session.add(dataset)
            session.flush()

        version = session.scalar(
            select(DataVersion).where(
                DataVersion.dataset_id == dataset.id,
                DataVersion.version_label == "1.0.0",
            )
        )
        if version is None:
            version = DataVersion(
                dataset_id=dataset.id,
                version_label="1.0.0",
                status="published",
                is_current=True,
                source_filename="cambodia-rice-priority-synthetic-v1.geojson",
                object_key="pending",
                checksum_sha256="pending",
                file_size=0,
                media_type="application/geo+json",
                record_count=0,
                schema_summary={
                    "format": "GeoJSON",
                    "crs": "EPSG:4326",
                    "geometry_type": "MultiPolygon",
                    "indicators": list(INDICATORS),
                },
                notes="Generated locally with fixed seed 260826. Not operational data.",
                uploaded_by="System seed",
                published_at=datetime.now(timezone.utc),
            )
            session.add(version)
            session.flush()

        if version.published_at is None:
            version.published_at = datetime.now(timezone.utc)

        existing_count = session.scalar(select(func.count(AdminArea.id))) or 0
        if existing_count:
            session.query(AdminArea).filter(
                AdminArea.dataset_version_id.is_(None)
            ).update({AdminArea.dataset_version_id: version.id})
            session.query(AnalysisRun).filter(
                AnalysisRun.dataset_version_id.is_(None)
            ).update({AnalysisRun.dataset_version_id: version.id})
        else:
            province_sequence: defaultdict[str, int] = defaultdict(int)
            rng = random.Random(RANDOM_SEED)
            communes = build_demo_communes()

            for index, geometry in enumerate(communes, start=1):
                centroid = geometry.centroid
                province = assign_demo_province(centroid.x, centroid.y)
                province_sequence[province] += 1
                local_number = province_sequence[province]
                values, rice_area_ha, population, data_quality = synthetic_values(
                    index, centroid.x, centroid.y, rng
                )

                area = AdminArea(
                    dataset_version_id=version.id,
                    code=f"SYN-COM-{index:03d}",
                    name=f"{province} Demo Commune {local_number:02d}",
                    province=province,
                    population=population,
                    rice_area_ha=rice_area_ha,
                    data_quality=data_quality,
                    geom=from_shape(geometry, srid=4326),
                )
                for code, value in values.items():
                    area.indicator_values.append(
                        IndicatorValue(
                            indicator_code=code,
                            value=None if value is None else round(value, 4),
                            quality_flag=(
                                "synthetic-missing" if value is None else "synthetic"
                            ),
                        )
                    )
                session.add(area)

        session.commit()
        session.refresh(version)

        payload = version_geojson_bytes(session, version.id)
        object_key = f"datasets/{dataset.id}/versions/{version.id}/{version.source_filename}"
        put_bytes(object_key, payload, "application/geo+json")
        version.object_key = object_key
        version.file_size = len(payload)
        version.checksum_sha256 = hashlib.sha256(payload).hexdigest()
        version.record_count = (
            session.scalar(
                select(func.count(AdminArea.id)).where(
                    AdminArea.dataset_version_id == version.id
                )
            )
            or 0
        )

        if not version.quality_checks:
            parsed = parse_upload(version.source_filename, payload)
            for check in parsed.checks:
                version.quality_checks.append(
                    DataQualityCheck(
                        check_code=check.code,
                        check_name=check.name,
                        status=check.status,
                        severity=check.severity,
                        details=check.details,
                        affected_count=check.affected_count,
                    )
                )
        session.commit()
        print(
            f"Data catalogue ready: {version.record_count} synthetic communes in "
            f"dataset version {version.version_label}; source stored in object storage."
        )

    # Platform seed and legacy backfill run only after the original source
    # checksum/object metadata have been finalised. The operation is idempotent.
    from app.platform_seed import seed_platform

    with SessionLocal() as platform_session:
        seed_platform(platform_session)
        print("Platform identity, workspace, modules, permissions, and catalog backfill are ready.")


if __name__ == "__main__":
    seed()
