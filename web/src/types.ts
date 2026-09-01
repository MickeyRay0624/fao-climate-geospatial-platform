export type IndicatorDefinition = {
  label: string;
  short_label: string;
  description: string;
  unit: string;
  colour: string;
};

export type Scenario = {
  label: string;
  description: string;
  weights: Record<string, number>;
};

export type DatasetRecord = {
  indicator_code: string;
  title: string;
  source_label: string;
  methodology: string;
  is_synthetic: boolean;
  last_updated: string;
};

export type Catalog = {
  indicators: Record<string, IndicatorDefinition>;
  scenarios: Record<string, Scenario>;
  datasets: DatasetRecord[];
  disclaimer: string;
  method: {
    name: string;
    formula: string;
    missing_value_policy: string;
  };
};

export type ScoreComponent = {
  value: number | null;
  weight: number;
  contribution: number;
};

export type AreaResult = {
  id: string | number;
  code: string;
  name: string;
  province: string;
  population: number;
  rice_area_ha: number;
  data_quality: number;
  indicators: Record<string, number | null>;
  score: number;
  rank: number | null;
  eligible: boolean;
  priority_band: string;
  components: Record<string, ScoreComponent>;
  missing_indicators: string[];
  data_completeness: number;
};

export type GeoFeature = {
  type: "Feature";
  id: string | number;
  geometry: {
    type: string;
    coordinates: unknown;
  };
  properties: AreaResult;
};

export type GeoFeatureCollection = {
  type: "FeatureCollection";
  features: GeoFeature[];
};

export type AnalysisSummary = {
  total_areas: number;
  eligible_areas: number;
  excluded_areas: number;
  average_score: number;
  top_area: { name: string; score: number; province: string } | null;
  top_10_rice_area_ha: number;
};

export type AnalysisResponse = {
  run_id: number;
  persisted?: boolean;
  dataset_version: AnalysisDatasetVersionReference;
  scenario_key: string;
  weights: Record<string, number>;
  min_rice_area_ha: number;
  created_at: string | null;
  summary: AnalysisSummary;
  ranking: AreaResult[];
  geojson: GeoFeatureCollection;
  disclaimer: string;
};

export type ComparisonResult = {
  key: string;
  label: string;
  response: AnalysisResponse;
};

export type QualityCheck = {
  id: number;
  check_code: string;
  check_name: string;
  status: "passed" | "warning" | "failed";
  severity: "warning" | "error";
  details: string;
  affected_count: number;
};

export type QualitySummary = {
  passed: number;
  warning: number;
  failed: number;
};

export type DataVersion = {
  id: number;
  dataset_id: number;
  version_label: string;
  status: "draft" | "validated" | "published" | "archived";
  is_current: boolean;
  source_filename: string;
  file_size: number;
  media_type: string;
  checksum_sha256: string;
  record_count: number;
  schema_summary: Record<string, unknown>;
  notes: string;
  uploaded_by: string;
  created_at: string | null;
  published_at: string | null;
  quality_summary: QualitySummary;
  quality_checks: QualityCheck[];
  download_url: string;
  preview_url: string;
  analysis_ready: boolean;
};

export type DataCatalogItem = {
  id: number;
  slug: string;
  name: string;
  description: string;
  data_kind: string;
  owner: string;
  created_at: string | null;
  current_version_id: number | null;
  versions: DataVersion[];
};

export type DataCatalogResponse = {
  datasets: DataCatalogItem[];
  summary: {
    datasets: number;
    versions: number;
    published_versions: number;
    stored_bytes: number;
    quality_warnings: number;
    failed_versions: number;
  };
};

export type AvailableDataVersion = DataVersion & {
  dataset_name: string;
  dataset_description: string;
  display_name: string;
};

export type AnalysisDatasetVersionReference = {
  id: number;
  dataset_id: number;
  dataset_name: string;
  version_label: string;
  status: string;
  checksum_sha256: string;
  record_count: number;
};

export type UploadResult = {
  dataset: DataCatalogItem;
  uploaded_version_id: number;
};

export type NativeInputMember = {
  id: string;
  dataset_version_id: string;
  representation_id: string;
  input_role: string;
  indicator_code: string | null;
  join_key: string;
  value_field: string | null;
  geometry_field: string | null;
  unit: string | null;
  direction: string | null;
  object_sha256?: string;
  ordinal: number;
};

export type InvestmentInputCandidate = {
  dataset: { id: string; title: string; classification: string; licence_code: string | null };
  version: { id: string; version_label: string; state: string; profile_key: string };
  representation: {
    id: string;
    type: string;
    status: string;
    schema: Record<string, unknown>;
    statistics: Record<string, unknown>;
    crs: string | null;
  };
  suggested_mapping: {
    input_role: "legacy_priority_bundle" | "administrative_boundary" | "indicator";
    indicator_code: string | null;
    join_key: string;
    value_field: string | null;
    geometry_field: string | null;
    unit: string | null;
    direction: string | null;
  };
  evidence_type: "REAL_SAMPLE" | "SYNTHETIC_DEMO" | "GOVERNED";
};

export type InvestmentReadiness = {
  readiness_state: "NOT_READY" | "READY";
  ready_to_run: boolean;
  boundary_available: boolean;
  available_indicator_roles: string[];
  missing_required_roles: string[];
  roles: Array<{
    role: string;
    label: string;
    state: "AVAILABLE" | "MISSING" | "UNRESOLVED" | "MISSING_UNAPPROVED";
    reason_codes: string[];
    candidate: InvestmentInputCandidate | null;
  }>;
  profile_issues: Array<Record<string, string>>;
  spatial_compatibility: Record<string, string | null>;
  record_coverage: {
    boundary_records: number;
    poverty_records: number;
    comparable_declared_records: number;
    state: string;
    note: string;
  };
  method_readiness: { state: string; reason_code: string; note: string };
  reason_codes: string[];
  collection: { id: string; title: string; path: string } | null;
  warning: string;
};

export type NativeInputSet = {
  id: string;
  name: string;
  label: string;
  profile_mode: "LEGACY_BUNDLE" | "SEPARATE_LAYERS";
  status: "DRAFT" | "VALIDATED" | "LOCKED" | "RETIRED";
  strictest_classification: string;
  readiness: { ready?: boolean; errors?: Array<{ code: string; message: string }> };
  warnings: Array<{ code: string; message: string }>;
  evidence_mode: "REAL_SAMPLE" | "SYNTHETIC_DEMO" | "GOVERNED" | "MIXED" | "EMPTY";
  checksum: string | null;
  row_version: number;
  members: NativeInputMember[];
};

export type NativeMethodVersion = {
  id: string;
  method_id: string;
  method_key: string;
  method_name: string;
  version_label: string;
  state: "DRAFT" | "UNDER_REVIEW" | "APPROVED" | "RETIRED";
  specification: Record<string, unknown>;
  checksum: string;
  implementation_key: string;
  code_ref: string;
  validation_evidence: Record<string, unknown>;
  disclaimer: string;
  row_version: number;
};

export type NativeMethod = {
  id: string;
  method_key: string;
  name: string;
  description: string;
  status: string;
  row_version: number;
  versions: NativeMethodVersion[];
};

export type NativeScenario = {
  id: string;
  scenario_key: string;
  version_label: string;
  name: string;
  description: string;
  method_version_id: string;
  state: "DRAFT" | "UNDER_REVIEW" | "APPROVED" | "RETIRED";
  parameters: { weights: Record<string, number>; min_rice_area_ha: number };
  checksum: string;
  disclaimer: string;
  row_version: number;
};

export type NativeRun = {
  id: string;
  input_set: { id: string; label: string };
  method_version: { id: string; version_label: string };
  scenario: { id: string; name: string; version_label: string };
  run_mode: string;
  status: "queued" | "running" | "succeeded" | "succeeded_with_warnings" | "failed" | "cancel_requested" | "cancelled";
  progress: number;
  current_step: string;
  requested_by: string;
  processing_job_id: string | null;
  warnings: Array<{ code: string; message: string }>;
  failure: { code?: string; message?: string; correlation_id?: string } | null;
  result_count: number;
  result_checksum: string | null;
  output_dataset_version_id: string | null;
  migration_source: string | null;
  legacy_run_id: number | null;
  requested_at: string;
  completed_at: string | null;
  parameters_snapshot?: Record<string, unknown>;
  checksums?: Record<string, string>;
  execution?: { code_ref: string; worker_task_version: string; container: Record<string, unknown>; correlation_id: string };
  inputs?: NativeInputMember[];
};

export type NativeResultResponse = {
  run_id: string;
  status: NativeRun["status"];
  items: AreaResult[];
  geojson: GeoFeatureCollection;
  result_checksum: string | null;
  meta: { page: number; page_size: number; total: number };
  disclaimer: string;
};

export type NativeAsset = {
  id: string;
  filename: string;
  role: string;
  media_type: string;
  size_bytes: number;
  sha256: string;
  url?: string;
};

export type NativeComparison = {
  id: string;
  left_run_id: string;
  right_run_id: string;
  summary: Record<string, number>;
  differences: Record<string, unknown>;
  checksum: string;
  areas?: Array<Record<string, unknown>>;
};
