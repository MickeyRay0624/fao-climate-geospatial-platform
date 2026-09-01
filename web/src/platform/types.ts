export type Principal = {
  id: string;
  external_subject: string;
  issuer: string;
  display_name: string;
  email: string | null;
  active_workspace: { id: string; name: string };
  workspace_memberships: Array<{ workspace_id: string; name: string; status: string }>;
  group_ids: string[];
  roles: string[];
  effective_permissions: string[];
  enabled_modules: string[];
  dev_auth: boolean;
};

export type NavigationItem = {
  path: string;
  title: string;
  section: string;
  permission: string;
  module?: string;
  icon: string;
};

export type Capabilities = {
  current_user: Principal;
  active_workspace: { id: string; name: string };
  effective_permissions: string[];
  enabled_modules: string[];
  navigation: NavigationItem[];
  feature_flags: Record<string, boolean>;
  development_identity: boolean;
  auth_mode: string;
};

export type DevPersona = {
  id: string;
  external_subject: string;
  display_name: string;
  email: string | null;
  status: string;
  locale: string;
};

export type DevPersonaList = { items: DevPersona[]; development_only: boolean };

export type ModuleRecord = {
  id: string;
  module_key: string;
  name: string;
  description: string;
  module_version: string;
  contract_version: string;
  status: string;
  enabled: boolean;
  manifest_valid: boolean;
  routes: Array<{ path: string; title: string }>;
  feature_flags: Record<string, boolean>;
  owner: string | null;
  required_permission: string | null;
  last_activity: string | null;
};

export type ModuleList = { items: ModuleRecord[] };

export type HomeDashboard = {
  workspace: { id: string; name: string };
  catalogue: {
    visible_datasets: number;
    published_datasets: number;
    real_samples: number;
    recent: Array<{ id: string; title: string; data_kind: string; published: boolean; updated_at: string | null }>;
  };
  jobs: { active: number; failed: number };
  role_cards: Record<string, Record<string, unknown>>;
  disclaimer: string;
};

export type SearchResponse = {
  query: string;
  items: Array<{ type: string; id: string; title: string; subtitle: string; path: string }>;
  meta: { returned: number };
};

export type DataHubDatasetSummary = {
  id: string;
  workspace_id: string;
  slug: string;
  title: string;
  abstract: string;
  data_kind: string;
  owner: { id: string; display_name: string };
  visibility: string;
  classification: string;
  lifecycle_status: string;
  licence_code: string | null;
  current_published_version: { id: string; version_label: string; state: string; profile_key: string } | null;
  version_count: number;
  quality_status: string | null;
  tags: string[];
  evidence_type: "REAL_SAMPLE" | "SYNTHETIC_DEMO" | "GOVERNED";
  licence_status: "NOT_CONFIRMED" | "DECLARED" | "NOT_DECLARED";
  spatial: { crs: string | null; bbox: number[] | null; geometry_type: string | null } | null;
  temporal: { start: string | null; end: string | null } | null;
  row_version: number;
  created_at: string | null;
  updated_at: string | null;
};

export type QualityIssue = {
  id: string;
  code: string;
  name: string;
  severity: string;
  affected_count: number;
  details: { message?: string; [key: string]: unknown };
  resolution_status: string;
};

export type DataHubVersion = {
  id: string;
  dataset_id: string;
  version_label: string;
  state: string;
  profile_key: string;
  change_summary: string;
  metadata: Record<string, unknown> | null;
  metadata_snapshot: Record<string, unknown>;
  assets: Array<{ id: string; filename: string; media_type: string; size_bytes: number; sha256: string; scan_status: string; role: string }>;
  representations: Array<{ id: string; representation_type: string; status: string; crs: string | null; geometry_type: string | null; bbox: number[] | null; schema: Record<string, unknown>; statistics: Record<string, unknown>; preview: unknown }>;
  quality: { id: string; status: string; engine_version: string; summary: Record<string, number | string>; issues: QualityIssue[] } | null;
  reviews: Array<{ id: string; review_type: string; status: string; requested_by: string; requested_at: string }>;
  created_by: string;
  approved_by: string | null;
  published_by: string | null;
  row_version: number;
  created_at: string | null;
  submitted_at: string | null;
  approved_at: string | null;
  published_at: string | null;
};

export type DataHubDataset = DataHubDatasetSummary & { versions?: DataHubVersion[] };
export type DataHubDatasetList = { items: DataHubDatasetSummary[]; meta: { page: number; page_size: number; total: number; pages: number; sort: string } };

export type DataHubCollection = {
  id: string;
  workspace_id: string;
  slug: string;
  title: string;
  description: string;
  tags: string[];
  status: "ACTIVE" | "ARCHIVED";
  owner: { id: string; display_name: string };
  can_manage: boolean;
  member_count: number;
  members: Array<{
    id: string;
    role: string;
    ordinal: number;
    dataset: { id: string; slug: string; title: string; classification: string };
    version: { id: string; version_label: string; state: string; profile_key: string };
  }> | null;
  row_version: number;
  created_at: string | null;
  updated_at: string | null;
};

export type DataHubCollectionList = {
  items: DataHubCollection[];
  meta: { page: number; page_size: number; total: number };
};

export type VersionPreview = {
  representation_type: string;
  preview_kind: "vector" | "table" | "stored_sample" | "metadata";
  preview: unknown;
  schema: Record<string, unknown>;
  statistics: Record<string, unknown>;
  bbox: number[] | null;
  crs: string | null;
  geometry_type: string | null;
  page: { number: number; size: number; total: number };
  simplified: boolean;
  source_asset_unchanged: boolean;
  display_cap: number | null;
};

export type DatasetGrant = {
  id: string;
  subject_type: "user" | "group";
  subject_id: string;
  permission_code: string;
  effect: "ALLOW" | "DENY";
  expires_at: string | null;
  reason: string;
  created_by: string;
  created_at: string | null;
};

export type DatasetGrantList = { items: DatasetGrant[]; meta: { total: number } };

export type UploadSession = {
  id: string;
  dataset_version_id: string;
  status: string;
  expires_at: string;
  files: Array<{ id: string; filename: string; media_type: string; size_bytes: number; upload_url: string; method: "PUT"; multipart: boolean }>;
};

export type ProcessingJob = {
  id: string;
  job_type: string;
  resource_type: string;
  resource_id: string;
  status: string;
  progress: number;
  attempt: number;
  max_attempts: number;
  result: Record<string, unknown>;
  error: { code: string; message: string } | null;
  steps: Array<{ key: string; label: string; status: string; details: Record<string, unknown> }>;
  created_at: string | null;
  completed_at: string | null;
};

export type JobList = { items: ProcessingJob[]; meta: { total: number } };
export type ReviewList = { items: Array<{ id: string; review_type: string; status: string; requested_at: string; requested_by: string; dataset: { id: string; title: string }; version: { id: string; version_label: string; state: string; created_by: string } }>; meta: { total: number } };

export type AuditList = { items: Array<{ id: string; event_time: string; actor_id: string | null; action: string; resource_type: string; resource_id: string; outcome: string; reason: string | null; correlation_id: string; before: Record<string, unknown>; after: Record<string, unknown>; severity: string }>; meta: { total: number } };

export type GovernanceMembers = { items: Array<Principal & { membership_status: string; joined_at: string; expires_at: string | null }> };
export type GovernanceGroups = { items: Array<{ id: string; slug: string; name: string; description: string; members: Principal[] }> };
export type GovernanceRoles = { items: Array<{ id: string; role_key: string; name: string; description: string; assignments: Array<{ id: string; subject: Principal; valid_until: string | null; reason: string }> }> };

export type ExtensionCaseSummary = {
  id: string;
  workspace_id: string;
  case_number: string;
  title: string;
  crop: string;
  growth_stage: string;
  severity: string;
  affected_area_ha: number | null;
  location_label: string;
  approximate_location: { lat: number; lon: number } | null;
  priority: string;
  status: string;
  notes: string;
  demonstration: boolean;
  assignee: { id: string; display_name: string } | null;
  last_observation_at: string | null;
  next_action: string;
  overdue_follow_ups: number;
  sync_status: string;
  row_version: number;
  created_at: string | null;
  updated_at: string | null;
};

export type ExtensionObservation = {
  id: string;
  case_id: string;
  client_uuid: string;
  status: "DRAFT" | "COMPLETED";
  observed_at: string;
  severity: string;
  affected_area_ha: number | null;
  approximate_location: string;
  notes: string;
  structured: Record<string, unknown>;
  created_by: string;
  row_version: number;
  completed_at: string | null;
};

export type ExtensionAssessment = {
  id: string;
  case_id: string;
  status: string;
  possible_cause_category: string;
  knowledge_version_id: string;
  supporting_observation_ids: string[];
  missing_information: string[];
  selected_by: string;
  reviewed_by: string | null;
  review_reason: string;
  row_version: number;
};

export type ExtensionVerification = {
  id: string;
  case_id: string;
  revision_number: number;
  status: "DRAFT" | "COMPLETED";
  template: { id: string; name: string; version_number: number };
  items: Array<{
    id: string;
    ordinal: number;
    prompt: string;
    response_type: string;
    required: boolean;
    required_evidence: string;
    response: { value: string } | null;
    evidence_note: string;
  }>;
  row_version: number;
  completed_at: string | null;
};

export type ExtensionActivity = {
  id: string;
  case_id: string | null;
  activity_type: string;
  objective: string;
  participant_count: number;
  responsible_officer_id: string;
  due_date: string;
  status: string;
  outcome: string;
  closure_evidence: string;
  created_by: string;
  approved_by: string | null;
  row_version: number;
  steps: Array<{ id: string; ordinal: number; description: string; status: string; due_date: string | null }>;
};

export type ExtensionFollowUp = {
  id: string;
  case_id: string;
  activity_plan_id: string | null;
  due_date: string;
  status: string;
  objective: string;
  outcome: string;
  overdue: boolean;
  row_version: number;
};

export type ExtensionCaseDetail = ExtensionCaseSummary & {
  assessment: Record<string, unknown>;
  observations: ExtensionObservation[];
  assessments: ExtensionAssessment[];
  verifications: ExtensionVerification[];
  activities: ExtensionActivity[];
  follow_ups: ExtensionFollowUp[];
  history: Array<{ id: string; from_status: string | null; to_status: string; reason: string; changed_by: string; changed_at: string }>;
};

export type ExtensionKnowledge = {
  id: string;
  item_key: string;
  title: string;
  category: string;
  status: string;
  demonstration: boolean;
  current_version_id: string | null;
  versions: Array<{
    id: string;
    version_number: number;
    status: string;
    content: { purpose?: string; checklist?: string[]; [key: string]: unknown };
    source_summary: string;
    created_by: string;
    approved_by: string | null;
    row_version: number;
  }>;
};

export type ExtensionSupervision = {
  unassigned_cases: ExtensionCaseSummary[];
  team_workload: Array<{ officer_id: string; display_name: string; active_cases: number }>;
  overdue_follow_ups: ExtensionFollowUp[];
  pending_activity_approvals: ExtensionActivity[];
  case_map_path: string;
};
