import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import App from "./App";
import {
  getCapabilities,
  getDataHubDataset,
  getDataHubDatasets,
  getDataHubVersion,
  getDatasetGrants,
  getDevPersonas,
  getExtensionCases,
  getExtensionOverview,
  getJobs,
  getHomeDashboard,
  getModules,
} from "./api";
import type { Capabilities, DataHubDataset, DataHubVersion, ProcessingJob } from "./platform/types";

vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  return {
    ...actual,
    getCapabilities: vi.fn(),
    getDevPersonas: vi.fn(),
    getJobs: vi.fn(),
    getHomeDashboard: vi.fn(),
    getModules: vi.fn(),
    getDataHubDatasets: vi.fn(),
    getDataHubDataset: vi.fn(),
    getDataHubVersion: vi.fn(),
    getDatasetGrants: vi.fn(),
    getExtensionCases: vi.fn(),
    getExtensionOverview: vi.fn(),
  };
});

vi.mock("./modules/investment/InvestmentPage", () => ({
  default: () => <section><h1>Native investment module test surface</h1></section>,
}));

const principal = {
  id: "user-1",
  external_subject: "dev-admin",
  issuer: "urn:fao:climate-platform:dev",
  display_name: "Amina Sok",
  email: "amina@example.invalid",
  active_workspace: { id: "workspace-1", name: "Cambodia Rice Resilience" },
  workspace_memberships: [{ workspace_id: "workspace-1", name: "Cambodia Rice Resilience", status: "active" }],
  group_ids: [],
  roles: ["workspace_admin"],
  effective_permissions: [],
  enabled_modules: ["investment-prioritisation"],
  dev_auth: true,
};

const nav = {
  home: { path: "/home", title: "Overview", section: "Workspace", permission: "workspace.view", icon: "home" },
  catalog: { path: "/data/catalog", title: "Team catalogue", section: "Data Hub", permission: "data.catalog.enter", icon: "database" },
  reviews: { path: "/data/reviews", title: "Reviews", section: "Data Hub", permission: "dataset.review", icon: "check" },
  investment: { path: "/apps/investment-prioritisation/overview", title: "Investment prioritisation", section: "Applications", permission: "apps.investment.use", module: "investment-prioritisation", icon: "map" },
  extension: { path: "/apps/extension-field-support/worklist", title: "Extension field support", section: "Applications", permission: "apps.extension.use", module: "extension-field-support", icon: "users" },
  audit: { path: "/governance/audit", title: "Audit log", section: "Governance", permission: "audit.view", icon: "audit" },
};

function capabilities(permissions: string[], navigation = [nav.home, nav.catalog]): Capabilities {
  return {
    current_user: { ...principal, effective_permissions: permissions },
    active_workspace: principal.active_workspace,
    effective_permissions: permissions,
    enabled_modules: ["investment-prioritisation"],
    navigation,
    feature_flags: { "development_scan_bypass": true },
    development_identity: true,
    auth_mode: "dev",
  };
}

const publishedVersion: DataHubVersion = {
  id: "version-1",
  dataset_id: "dataset-1",
  version_label: "1.0.0",
  state: "PUBLISHED",
  profile_key: "generic-vector@1.0",
  change_summary: "Governed release",
  metadata: { title: "Published test dataset" },
  metadata_snapshot: { title: "Published test dataset", provenance: "Verified fixture" },
  assets: [{ id: "asset-1", filename: "source.geojson", media_type: "application/geo+json", size_bytes: 100, sha256: "a".repeat(64), scan_status: "CLEAN", role: "source" }],
  representations: [],
  quality: { id: "quality-1", status: "PASSED", engine_version: "1", summary: { record_count: 2 }, issues: [] },
  reviews: [{ id: "review-1", review_type: "publication", status: "APPROVED", requested_by: "user-2", requested_at: "2026-08-31T00:00:00Z" }],
  created_by: "user-2",
  approved_by: "user-3",
  published_by: "user-4",
  row_version: 5,
  created_at: "2026-08-31T00:00:00Z",
  submitted_at: "2026-08-31T00:01:00Z",
  approved_at: "2026-08-31T00:02:00Z",
  published_at: "2026-08-31T00:03:00Z",
};

const runningJob: ProcessingJob = {
  id: "job-1",
  job_type: "catalog:validate-version:v1",
  resource_type: "dataset_version",
  resource_id: "version-1",
  status: "RUNNING",
  progress: 42,
  attempt: 1,
  max_attempts: 3,
  result: {},
  error: null,
  steps: [{ key: "validate", label: "Validate profile", status: "RUNNING", details: {} }],
  created_at: "2026-08-31T00:00:00Z",
  completed_at: null,
};

const governedDataset: DataHubDataset = {
  id: "dataset-1",
  workspace_id: "workspace-1",
  slug: "governed-test",
  title: "Governed test dataset",
  abstract: "A governed dataset used for component contract tests.",
  data_kind: "vector",
  owner: { id: "user-1", display_name: "Amina Sok" },
  visibility: "PRIVATE",
  classification: "FAO_INTERNAL",
  lifecycle_status: "ACTIVE",
  licence_code: "TEST",
  current_published_version: { id: "version-1", version_label: "1.0.0", state: "PUBLISHED", profile_key: "generic-vector@1.0" },
  version_count: 1,
  quality_status: "PASSED",
  tags: ["test"],
  evidence_type: "GOVERNED",
  licence_status: "DECLARED",
  spatial: { crs: "EPSG:4326", bbox: [104, 11, 105, 12], geometry_type: "Polygon" },
  temporal: null,
  row_version: 2,
  created_at: "2026-08-31T00:00:00Z",
  updated_at: "2026-08-31T00:00:00Z",
  versions: [publishedVersion],
};

function renderRoute(path: string) {
  return render(<MemoryRouter initialEntries={[path]}><App /></MemoryRouter>);
}

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  vi.mocked(getCapabilities).mockResolvedValue(capabilities(["workspace.view", "data.catalog.enter"]));
  vi.mocked(getDevPersonas).mockResolvedValue({
    development_only: true,
    items: [{ id: "user-1", external_subject: "dev-admin", display_name: "Amina Sok", email: "amina@example.invalid", status: "active", locale: "en" }],
  });
  vi.mocked(getJobs).mockResolvedValue({ items: [], meta: { total: 0 } });
  vi.mocked(getHomeDashboard).mockResolvedValue({
    workspace: { id: "workspace-1", name: "Cambodia Rice Resilience" },
    catalogue: { visible_datasets: 0, published_datasets: 0, real_samples: 0, recent: [] },
    jobs: { active: 0, failed: 0 },
    role_cards: {},
    disclaimer: "Demonstration boundaries apply.",
  });
  vi.mocked(getModules).mockResolvedValue({ items: [] });
  vi.mocked(getDataHubDatasets).mockResolvedValue({ items: [], meta: { page: 1, page_size: 20, total: 0, pages: 0, sort: "-updated_at" } });
  vi.mocked(getDataHubDataset).mockResolvedValue(governedDataset);
  vi.mocked(getDataHubVersion).mockResolvedValue(publishedVersion);
  vi.mocked(getDatasetGrants).mockResolvedValue({ items: [], meta: { total: 0 } });
  vi.mocked(getExtensionOverview).mockResolvedValue({
    non_ai: true,
    demonstration: true,
    counts: { assigned: 1 },
    scanner_mode: "DEVELOPMENT_BYPASS",
    disclaimer: "Fictional demonstration records; no automated advice.",
  });
  vi.mocked(getExtensionCases).mockResolvedValue({
    items: [{
      id: "case-1",
      workspace_id: "workspace-1",
      case_number: "DEMO-001",
      title: "Fictional water-condition observation",
      crop: "Rice",
      growth_stage: "Tillering",
      severity: "MODERATE",
      affected_area_ha: 0.5,
      location_label: "Fictional demo zone",
      approximate_location: { lat: 11.5, lon: 104.9 },
      priority: "HIGH",
      status: "ASSIGNED",
      notes: "Demonstration only.",
      demonstration: true,
      assignee: { id: "user-1", display_name: "Sreypov Mom" },
      last_observation_at: null,
      next_action: "Record a structured observation",
      overdue_follow_ups: 1,
      sync_status: "SYNCED",
      row_version: 1,
      created_at: "2026-09-01T00:00:00Z",
      updated_at: "2026-09-01T00:00:00Z",
    }],
    meta: { total: 1 },
  });
});

afterEach(() => cleanup());

describe("platform shell and route policy", () => {
  it("renders the development identity boundary and capability-driven navigation", async () => {
    vi.mocked(getCapabilities).mockResolvedValue(capabilities(
      ["workspace.view", "data.catalog.enter"],
      [nav.home, nav.catalog],
    ));
    renderRoute("/home");

    expect(await screen.findByText("Development identity")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Team catalogue" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Reviews" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Audit log" })).not.toBeInTheDocument();
  });

  it("shows the forbidden surface even when a protected URL is entered directly", async () => {
    renderRoute("/governance/audit");

    expect(await screen.findByText("Access is not available for this role.")).toBeInTheDocument();
    expect(screen.getByText("403")).toBeInTheDocument();
  });

  it("mounts the native investment route behind its capability", async () => {
    vi.mocked(getCapabilities).mockResolvedValue(capabilities(
      ["workspace.view", "apps.investment.use"],
      [nav.home, nav.investment],
    ));
    renderRoute("/apps/investment-prioritisation/overview");

    expect(await screen.findByRole("heading", { name: "Native investment module test surface" })).toBeInTheDocument();
  });

  it("mounts the permission-scoped extension worklist with mobile navigation", async () => {
    vi.mocked(getCapabilities).mockResolvedValue(capabilities(
      ["workspace.view", "apps.extension.use", "extension.case.view_assigned"],
      [nav.home, nav.extension],
    ));
    renderRoute("/apps/extension-field-support/worklist");

    expect(await screen.findByRole("heading", { name: "Extension Officer Field Support" })).toBeInTheDocument();
    expect(await screen.findByText("Fictional water-condition observation")).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Mobile extension navigation" })).toBeInTheDocument();
    expect(screen.getByText("1 overdue follow-up")).toBeInTheDocument();
  });
});

describe("Data Hub interaction states", () => {
  it("binds catalogue filters to the list query contract", async () => {
    renderRoute("/data/catalog");
    await screen.findByRole("heading", { name: "Team catalogue" });

    await userEvent.selectOptions(screen.getByLabelText("Data kind"), "table");
    await waitFor(() => {
      expect(vi.mocked(getDataHubDatasets).mock.calls.some(([params]) => params?.toString().includes("data_kind=table"))).toBe(true);
    });
  });

  it("shows authoritative job progress while hiding upload actions without permission", async () => {
    vi.mocked(getJobs).mockResolvedValue({ items: [runningJob], meta: { total: 1 } });
    renderRoute("/data/uploads");

    expect(await screen.findByText("42%")).toBeInTheDocument();
    expect(screen.getByText("Validate profile")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /New upload/ })).not.toBeInTheDocument();
  });

  it("shows review decisions only to reviewers", async () => {
    vi.mocked(getCapabilities).mockResolvedValue(capabilities(["workspace.view", "dataset.review"]));
    vi.mocked(getDataHubVersion).mockResolvedValue({
      ...publishedVersion,
      state: "IN_REVIEW",
      metadata_snapshot: {},
      reviews: [{ ...publishedVersion.reviews[0], status: "OPEN" }],
      published_at: null,
    });
    renderRoute("/data/versions/version-1");
    await screen.findByRole("heading", { name: "Version 1.0.0" });
    await userEvent.click(screen.getByRole("button", { name: "Review" }));

    expect(screen.getByRole("button", { name: "Approve version" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Publish version" })).not.toBeInTheDocument();
  });

  it("renders published metadata as immutable and exposes no lifecycle mutation", async () => {
    vi.mocked(getCapabilities).mockResolvedValue(capabilities(["workspace.view", "dataset.publish", "dataset.submit_review"]));
    renderRoute("/data/versions/version-1");

    expect(await screen.findByText("Frozen publication metadata")).toBeInTheDocument();
    expect(screen.getAllByText("PUBLISHED")).toHaveLength(2);
    expect(screen.queryByRole("button", { name: "Publish version" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Submit for review" })).not.toBeInTheDocument();
  });

  it("exposes audited dataset grant management only with the capability", async () => {
    vi.mocked(getCapabilities).mockResolvedValue(capabilities(["workspace.view", "dataset.manage_access"]));
    renderRoute("/data/datasets/dataset-1");
    await screen.findByRole("heading", { name: "Governed test dataset" });
    await userEvent.click(screen.getByRole("button", { name: "Access" }));

    expect(await screen.findByRole("button", { name: "Add audited grant" })).toBeInTheDocument();
    expect(screen.getByLabelText("Subject UUID")).toBeInTheDocument();
    expect(getDatasetGrants).toHaveBeenCalledWith("dataset-1");
  });
});
