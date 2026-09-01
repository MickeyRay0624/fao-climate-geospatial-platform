# Upload and job troubleshooting

## Normal path

```text
DRAFT → UPLOADING → PROCESSING → VALIDATED
      ↘ validation or infrastructure error → VALIDATION_FAILED
```

The browser uploads directly to a short-lived MinIO URL. FastAPI never returns permanent object credentials. PostgreSQL `jobs.processing_jobs` is authoritative; Celery/Redis only transports execution.

## First checks

1. Open `/data/uploads` and note job ID, state, attempt, step, and stable error code.
2. Query health and service state:

```bash
curl -fsS http://localhost:8000/health
docker compose ps -a
docker compose logs --tail=200 api worker redis minio
```

3. Correlate API/worker structured logs by the response `X-Correlation-ID` or error-envelope `correlation_id`.
4. Do not delete quarantine objects to “unstick” a job; they are evidence.

## Failure matrix

| Symptom/code | Likely cause | Safe action |
|---|---|---|
| Browser PUT cannot connect | Public signed host is not browser-reachable. | Set `OBJECT_STORE_PUBLIC_ENDPOINT=localhost:9000`; keep internal endpoint `minio:9000`; recreate API. |
| Signature mismatch | Signed host/protocol differs from the URL actually used. | Check public endpoint and `OBJECT_STORE_SECURE`; do not proxy/rewrite the signed host. |
| `UPLOAD_OBJECT_MISSING` | Complete was called before PUT finished or for the wrong file. | Retry the upload to the URL/session while unexpired, then complete. If expired, create a new session. |
| `UPLOAD_CHECKSUM_MISMATCH` | Declared checksum differs from stored bytes. | Recompute SHA-256 locally and re-upload; never edit the server checksum. |
| `UPLOAD_SIZE_MISMATCH` | Partial or different file reached MinIO. | Re-upload the intended file and verify client progress reached 100%. |
| `FILE_SCAN_REQUIRED` | No production scanner is available or bypass is prohibited. | Configure an approved scanner. Never turn on the development bypass in staging/production. |
| `VALIDATION_FAILED` | Stable quality issues rejected the selected profile. | Inspect the Quality tab; fix source/schema and create a new version or upload session. Do not publish around blocking issues. |
| Job stays `QUEUED` | Worker/Redis unavailable. | Restore Redis/worker health. The durable job remains in PostgreSQL. |
| Job stays `RUNNING` | Worker interrupted mid-task. | Inspect step timestamps/logs; only use retry after the API marks it `FAILED`. Do not manually forge status. |
| `JOB_NOT_RETRYABLE` | Job succeeded, attempts exhausted, or original upload is unavailable. | Do not replay a success. Create a new upload session/version when the original cannot be safely retried. |
| `VERSION_STATE_CONFLICT` | Action attempted from the wrong lifecycle state. | Reload the authoritative version and follow the next allowed action. |
| `ROW_VERSION_CONFLICT` | Another actor changed the resource. | Reload, review the new state, and intentionally resubmit. |
| `RESOURCE_NOT_FOUND` on a known private item | Authorization intentionally hides existence. | Switch to an entitled persona or ask the owner for a time-bounded grant. |

## Validation expectations

- `generic-vector@1.0`: JSON, non-empty FeatureCollection, geometry validity/types, bbox, fields, record count, preview. Missing explicit CRS produces a warning because GeoJSON is treated as WGS84.
- `generic-table@1.0`: decodable CSV, unique non-empty headers, rows, sampled types, malformed/empty row issues, preview.
- `administrative-boundary@1.0`: polygonal GeoJSON with stable, unique `area_code`, `area_name`, `admin_level`, valid geometry, extent and an explicit coordinate-policy result.
- `normalised-indicator-layer@1.0`: one indicator per CSV/GeoJSON layer, unique `area_code`, controlled direction, declared unit/time coverage and values in the method contract range. Missing values warn; duplicate join keys block.
- `document@1.0`: extension/MIME consistency, size, checksum, scan status. There is no OCR and no sensitive-text preview.
- `analysis-ready-priority-bundle@1.0`: preserves the existing required fields, indicator ranges, commune-code uniqueness, geometry, Cambodia extent, and missing-value rules.

## Review/publish failures

- The creator/uploader cannot be the sole reviewer without a recorded exception reason.
- Approval does not grant publish permission.
- Publish requires `APPROVED`, required review success, no blocking issue, complete metadata, acceptable scan policy, and the expected row version.
- A published version cannot be edited. Create a new version; do not bypass the trigger.

## Query a job safely

```bash
curl -fsS -H 'X-Dev-User-Subject: dev-contributor' \
  http://localhost:8000/api/jobs/v1/jobs/<job-uuid>
```

Only a failed, still-eligible job can be retried, and a rationale is required:

```bash
curl -fsS -X POST -H 'Content-Type: application/json' \
  -H 'X-Dev-User-Subject: dev-admin' \
  -d '{"reason":"Worker interruption confirmed; original object retained"}' \
  http://localhost:8000/api/jobs/v1/jobs/<job-uuid>/retry
```

## Escalation evidence

Provide job ID, version ID, UTC timestamp, stable error code, correlation ID, failing step, health output, and relevant redacted logs. Never paste signed URLs, bearer tokens, access keys, `.env`, or unredacted sensitive metadata into an issue.
