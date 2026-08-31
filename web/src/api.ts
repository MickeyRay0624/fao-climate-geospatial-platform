import type {
  AnalysisResponse,
  AvailableDataVersion,
  Catalog,
  DataCatalogResponse,
  DataVersion,
  UploadResult,
} from "./types";

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (!(init?.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(url, {
    ...init,
    headers,
  });

  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = (await response.json()) as { detail?: string };
      detail = body.detail ?? detail;
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
