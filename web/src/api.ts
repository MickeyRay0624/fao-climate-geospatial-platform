import type {
  AnalysisResponse,
  AvailableDataVersion,
  Catalog,
  DataCatalogResponse,
  DataVersion,
  UploadResult,
} from "./types";
import type {
  AuditList,
  Capabilities,
  DataHubDataset,
  DataHubDatasetList,
  DataHubVersion,
  DatasetGrant,
  DatasetGrantList,
  DevPersonaList,
  GovernanceGroups,
  GovernanceMembers,
  GovernanceRoles,
  JobList,
  ModuleList,
  Principal,
  ReviewList,
  UploadSession,
} from "./platform/types";

const DEV_SUBJECT_KEY = "fao-platform-dev-subject";

export function getDevSubject(): string {
  return window.localStorage.getItem(DEV_SUBJECT_KEY) ?? "dev-admin";
}

export function setDevSubject(subject: string): void {
  window.localStorage.setItem(DEV_SUBJECT_KEY, subject);
}

export async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (!(init?.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  headers.set("X-Dev-User-Subject", getDevSubject());
  const method = (init?.method ?? "GET").toUpperCase();
  if (["POST", "PATCH", "DELETE"].includes(method) && !headers.has("Idempotency-Key")) {
    headers.set("Idempotency-Key", crypto.randomUUID());
  }
  const response = await fetch(url, {
    ...init,
    headers,
  });

  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = (await response.json()) as {
        detail?: string;
        error?: { code?: string; message?: string; correlation_id?: string };
      };
      detail = body.error?.message ?? body.detail ?? detail;
      if (body.error?.code) detail = `${detail} [${body.error.code}]`;
    } catch {
      // Keep the HTTP status when a non-JSON error page is returned.
    }
    throw new Error(detail);
  }

  return (await response.json()) as T;
}

export function getCatalog(): Promise<Catalog> {
  return requestJson<Catalog>("/api/catalog");
}

export function runAnalysis(payload: {
  dataset_version_id: number;
  scenario_key: string;
  weights?: Record<string, number>;
  min_rice_area_ha: number;
}): Promise<AnalysisResponse> {
  return requestJson<AnalysisResponse>("/api/analysis/run", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function runAnalysisPreview(payload: {
  dataset_version_id: number;
  scenario_key: string;
  weights?: Record<string, number>;
  min_rice_area_ha: number;
}): Promise<AnalysisResponse> {
  return requestJson<AnalysisResponse>("/api/analysis/preview", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getDataCatalog(): Promise<DataCatalogResponse> {
  return requestJson<DataCatalogResponse>("/api/data-catalog");
}

export function getAvailableDataVersions(): Promise<AvailableDataVersion[]> {
  return requestJson<AvailableDataVersion[]>("/api/data-versions/available");
}

export function uploadDataVersion(formData: FormData): Promise<UploadResult> {
  return requestJson<UploadResult>("/api/data-catalog/upload", {
    method: "POST",
    body: formData,
  });
}

export function publishDataVersion(versionId: number): Promise<DataVersion> {
  return requestJson<DataVersion>(`/api/data-versions/${versionId}/publish`, {
    method: "POST",
  });
}

export function exportUrl(runId: number, format: "csv" | "geojson"): string {
  return `/api/analysis/${runId}/export.${format}`;
}

export function getMe(): Promise<Principal> {
  return requestJson<Principal>("/api/me");
}

export function getCapabilities(): Promise<Capabilities> {
  return requestJson<Capabilities>("/api/me/capabilities");
}

export function getDevPersonas(): Promise<DevPersonaList> {
  return requestJson<DevPersonaList>("/api/dev/personas");
}

export function getModules(): Promise<ModuleList> {
  return requestJson<ModuleList>("/api/modules");
}

export function getDataHubDatasets(params: URLSearchParams = new URLSearchParams()): Promise<DataHubDatasetList> {
  const query = params.toString();
  return requestJson<DataHubDatasetList>(`/api/data/v1/datasets${query ? `?${query}` : ""}`);
}

export function getDataHubDataset(id: string): Promise<DataHubDataset> {
  return requestJson<DataHubDataset>(`/api/data/v1/datasets/${id}`);
}

export function getDataHubVersion(id: string): Promise<DataHubVersion> {
  return requestJson<DataHubVersion>(`/api/data/v1/versions/${id}`);
}

export function getDatasetGrants(datasetId: string): Promise<DatasetGrantList> {
  return requestJson<DatasetGrantList>(`/api/data/v1/datasets/${datasetId}/grants`);
}

export function createDatasetGrant(
  datasetId: string,
  payload: {
    subject_type: "user" | "group";
    subject_id: string;
    permission_code: string;
    effect: "ALLOW" | "DENY";
    expires_at: string | null;
    reason: string;
  },
): Promise<DatasetGrant> {
  return requestJson<DatasetGrant>(`/api/data/v1/datasets/${datasetId}/grants`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function deleteDatasetGrant(datasetId: string, grantId: string): Promise<{ deleted: boolean; id: string }> {
  return requestJson(`/api/data/v1/datasets/${datasetId}/grants/${grantId}`, { method: "DELETE" });
}

export function createDataHubDataset(payload: Record<string, unknown>): Promise<DataHubDataset> {
  return requestJson<DataHubDataset>("/api/data/v1/datasets", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function createDataHubVersion(datasetId: string, payload: Record<string, unknown>): Promise<DataHubVersion> {
  return requestJson<DataHubVersion>(`/api/data/v1/datasets/${datasetId}/versions`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function createDirectUploadSession(versionId: string, file: File): Promise<UploadSession> {
  return requestJson<UploadSession>(`/api/data/v1/versions/${versionId}/upload-sessions`, {
    method: "POST",
    body: JSON.stringify({
      files: [{ filename: file.name, media_type: file.type || "application/octet-stream", size_bytes: file.size }],
    }),
  });
}

export async function uploadDirect(url: string, file: File, onProgress?: (progress: number) => void): Promise<void> {
  // XMLHttpRequest exposes upload progress while the body goes directly to MinIO.
  await new Promise<void>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url);
    xhr.setRequestHeader("Content-Type", file.type || "application/octet-stream");
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress?.(Math.round((event.loaded / event.total) * 100));
    };
    xhr.onerror = () => reject(new Error("The browser could not reach object storage."));
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve();
      else reject(new Error(`Object storage rejected the upload (${xhr.status}).`));
    };
    xhr.send(file);
  });
}

export function completeUploadSession(sessionId: string): Promise<import("./platform/types").ProcessingJob> {
  return requestJson<import("./platform/types").ProcessingJob>(`/api/data/v1/upload-sessions/${sessionId}/complete`, { method: "POST" });
}

export function getJob(jobId: string): Promise<import("./platform/types").ProcessingJob> {
  return requestJson<import("./platform/types").ProcessingJob>(`/api/jobs/v1/jobs/${jobId}`);
}

export function getJobs(): Promise<JobList> {
  return requestJson<JobList>("/api/jobs/v1/jobs");
}

export function submitVersionReview(version: DataHubVersion, reviewType = "publication"): Promise<{ id: string; status: string }> {
  return requestJson(`/api/data/v1/versions/${version.id}/submit-review`, {
    method: "POST",
    body: JSON.stringify({ review_type: reviewType, row_version: version.row_version }),
  });
}

export function getReviews(status = "OPEN"): Promise<ReviewList> {
  return requestJson<ReviewList>(`/api/data/v1/reviews?status=${encodeURIComponent(status)}`);
}

export function decideReview(reviewId: string, decision: string, rationale: string, exceptionReason?: string): Promise<Record<string, unknown>> {
  return requestJson(`/api/data/v1/reviews/${reviewId}/decisions`, {
    method: "POST",
    body: JSON.stringify({ decision, rationale, checklist_snapshot: { metadata: true, quality: true, provenance: true }, exception_reason: exceptionReason || null }),
  });
}

export function publishDataHubVersion(version: DataHubVersion, exceptionReason?: string): Promise<DataHubVersion> {
  return requestJson<DataHubVersion>(`/api/data/v1/versions/${version.id}/publish`, {
    method: "POST",
    body: JSON.stringify({ row_version: version.row_version, exception_reason: exceptionReason || null }),
  });
}

export function getVersionPreview(versionId: string): Promise<Record<string, unknown>> {
  return requestJson(`/api/data/v1/versions/${versionId}/preview`);
}

export function getVersionLineage(versionId: string): Promise<Record<string, unknown>> {
  return requestJson(`/api/data/v1/versions/${versionId}/lineage`);
}

export function getVersionDownload(versionId: string): Promise<{ url: string; expires_at: string; filename: string }> {
  return requestJson(`/api/data/v1/versions/${versionId}/download`);
}

export function getAuditEvents(params: URLSearchParams = new URLSearchParams()): Promise<AuditList> {
  const query = params.toString();
  return requestJson<AuditList>(`/api/audit/v1/events${query ? `?${query}` : ""}`);
}

export function getGovernanceMembers(): Promise<GovernanceMembers> {
  return requestJson("/api/governance/v1/members");
}

export function getGovernanceGroups(): Promise<GovernanceGroups> {
  return requestJson("/api/governance/v1/groups");
}

export function getGovernanceRoles(): Promise<GovernanceRoles> {
  return requestJson("/api/governance/v1/roles");
}
