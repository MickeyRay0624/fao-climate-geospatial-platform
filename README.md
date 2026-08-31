# Cambodia Climate-Resilient Rice Prioritisation MVP

A local, transparent spatial decision-support demonstrator for the question:

> Which Cambodian communes should be prioritised for climate-resilient rice investment or extension support?

The current dataset is deliberately synthetic. The system demonstrates a complete workflow and technical architecture; it does **not** produce operational advice.

## What the demonstrator does

- provides one document-level page scroll instead of separately scrolling left,
  map, and results columns;
- maintains a team data catalogue with named datasets and immutable version labels;
- stores every uploaded source file and records its SHA-256 checksum;
- checks schema, row completeness, commune-code uniqueness, polygon validity,
  numeric fields, 0–1 indicator ranges, missing values, and Cambodia extent;
- separates upload, validation, publication, and analysis so drafts cannot silently
  enter a ranking;
- makes the user select one published data version for every analysis run and records
  that lineage in the result and exports;
- displays synthetic commune geometries in an interactive map;
- combines seven decision indicators through visible, adjustable weights;
- provides four policy presets: balanced resilience, productivity, climate resilience, and equity;
- applies a minimum rice-area eligibility rule;
- generates a priority score, band, and ranked commune worklist;
- explains each score through factor-level contributions;
- flags missing data and shows data completeness;
- compares the results of all four policy presets; and
- exports complete results as CSV or GeoJSON.

## Local architecture

```text
Browser
  │
  ▼
React + TypeScript + Vite + OpenLayers + ECharts
  │  /api proxy
  ▼
FastAPI + transparent multi-criteria analysis
  ├──────────────► PostgreSQL + PostGIS
  │                 catalogue metadata, versions, quality checks,
  │                 commune geometry/indicators, analysis runs and results
  │
  └──────────────► MinIO object storage
                    original uploaded GeoJSON/CSV files

Deterministic synthetic-data seed ──► version 1.0.0 in both stores

Optional: GeoServer ───────────────► PostGIS
```

The web application uses FastAPI GeoJSON directly for the core demonstration. GeoServer is an optional publication layer and is not a dependency of the scoring workflow.

## Run it locally

Requirements: Docker Desktop with Docker Compose.

```bash
cd "/Users/lei/Documents/联合国工作/数字孪生/cambodia-rice-dss"
cp .env.example .env
docker compose up --build -d
```

Open:

- Web demonstrator: <http://localhost:3000>
- API documentation: <http://localhost:8000/docs>
- MinIO object-storage console: <http://localhost:9001>
- PostGIS: `127.0.0.1:5432`

The default values in `.env.example` are only local demonstration credentials. Change them before using the stack on any shared host. MinIO is running locally in Docker: open source does not mean that a third party is providing free cloud storage.

## Data workflow

The page follows one controlled path:

```text
upload source → automatic quality checks → validated draft → publish
              → select published version → analyse → export result
```

Use **Upload data version** in the data catalogue. A new upload can create a new
dataset or add a version to an existing dataset. The raw source is preserved even
when validation fails, but a failed draft cannot be published or analysed.

Supported MVP inputs:

- GeoJSON/JSON `FeatureCollection` with Polygon or MultiPolygon geometry; or
- CSV with an EPSG:4326 polygon in a `geometry_wkt` column.

Every row/feature must contain `code`, `name`, `province`, `rice_area_ha`, and the
seven indicator fields listed below. `population` and `data_quality` are optional.
Indicator values must be numeric from 0 to 1; empty indicator values are accepted
with a visible warning and the documented missing-value policy. The local upload
limit is 25 MB.

Publishing makes a version analysis-ready and marks it as the current version of
its dataset. Existing published versions remain available for reproducibility.
Changing the selected version does not silently replace the current map: the page
marks the configuration as pending until **Run analysis** is selected.

Stop the services:

```bash
docker compose down
```

Delete the local database volume and regenerate the synthetic dataset:

```bash
docker compose down -v
docker compose up --build -d
```

## Optional GeoServer

Start the optional service:

```bash
docker compose --profile geoserver up -d geoserver
```

Then open <http://localhost:8080/geoserver>. To add the database as a PostGIS store from inside GeoServer, use:

- host: `db`
- port: `5432`
- database: the `POSTGRES_DB` value;
- schema: `public`; and
- username/password: the matching values from `.env`.

GeoServer publishes layers; it does not store the source dataset. The source records remain in PostGIS.

## Decision model

All indicators are normalised to 0–1 and oriented so that a higher value means a stronger reason to prioritise support.

```text
score = Σ(normalised weight × oriented indicator) × quality adjustment
```

The seven synthetic indicators are:

1. yield gap;
2. drought risk;
3. flood risk;
4. poverty and livelihood vulnerability;
5. irrigation-access gap;
6. market isolation; and
7. nature-based-solutions opportunity.

Missing values receive a neutral value of 0.5, reduce data completeness, and remain visibly flagged. This is a demonstration policy, not an endorsed FAO methodology.

## Synthetic data

The seed is deterministic, so a reset produces the same records. It creates roughly 110 clipped grid polygons loosely based on Cambodia's geographic extent, assigns demonstration commune/province labels, and generates spatially correlated indicator values. A small number of values are deliberately missing to exercise the quality-warning workflow.

No displayed polygon is an official administrative boundary. No displayed indicator is an official FAO, Cambodian government, satellite, climate, census, or programme output.

## Main API routes

- `GET /health`
- `GET /api/catalog`
- `GET /api/data-catalog`
- `POST /api/data-catalog/upload`
- `GET /api/data-versions/available`
- `POST /api/data-versions/{version_id}/publish`
- `GET /api/data-versions/{version_id}/preview`
- `GET /api/data-versions/{version_id}/download`
- `GET /api/areas?dataset_version_id={version_id}`
- `GET /api/scenarios`
- `POST /api/analysis/run`
- `GET /api/analysis/{run_id}`
- `GET /api/analysis/{run_id}/ranking`
- `GET /api/analysis/{run_id}/export.csv`
- `GET /api/analysis/{run_id}/export.geojson`

## Tests

```bash
make test
npm --prefix web run build
```

## Replacing synthetic data

Before a real pilot, the team should confirm the primary decision-maker, intervention being prioritised, spatial unit, authoritative datasets, indicator direction, weighting/governance process, and success criteria. A production data pipeline should then:

1. upload an analysis bundle through the data catalogue;
2. review automatic checks and add domain review/approval checks where needed;
3. retain source licences, dates, spatial resolution and transformation metadata;
4. publish only after the geometry, indicators and provenance are accepted;
5. review weights and missing-data rules with domain and government counterparts; and
6. validate the resulting ranking against field and programme knowledge.

The MVP intentionally excludes authentication, cloud deployment, real-time sensors, Earth-observation ingestion, water-balance models, AI-generated agronomic advice, and integration with Farmerbook or MetKasekor.
