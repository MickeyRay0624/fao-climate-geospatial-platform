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
  id: number;
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
  id: number;
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
