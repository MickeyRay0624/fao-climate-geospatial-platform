import { useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";

import {
  createDatasetGrant,
  deleteDatasetGrant,
  getDataHubDataset,
  getDatasetGrants,
} from "../api";
import { usePlatform } from "../platform/AppShell";
import type { DataHubDataset, DatasetGrant } from "../platform/types";

const tabs = ["Overview", "Versions", "Metadata", "Lineage", "Access", "Activity"] as const;

export default function DatasetDetailPage() {
  const { datasetId = "" } = useParams();
  const { capabilities } = usePlatform();
  const [dataset, setDataset] = useState<DataHubDataset | null>(null);
  const [activeTab, setActiveTab] = useState<(typeof tabs)[number]>("Overview");
  const [error, setError] = useState<string | null>(null);
  const [grants, setGrants] = useState<DatasetGrant[]>([]);
  const [grantsLoading, setGrantsLoading] = useState(false);
  const [grantError, setGrantError] = useState<string | null>(null);
  const [grantBusy, setGrantBusy] = useState(false);
  const [grantDraft, setGrantDraft] = useState<{
    subject_type: "user" | "group";
    subject_id: string;
    permission_code: string;
    effect: "ALLOW" | "DENY";
    expires_at: string;
    reason: string;
  }>({
    subject_type: "user",
    subject_id: "",
    permission_code: "dataset.view_metadata",
    effect: "ALLOW",
    expires_at: "",
    reason: "",
  });
  const canManageAccess = capabilities.effective_permissions.includes("dataset.manage_access");

  useEffect(() => {
    void getDataHubDataset(datasetId).then(setDataset).catch((caught) => setError(caught instanceof Error ? caught.message : "Dataset unavailable"));
  }, [datasetId]);
  useEffect(() => {
    if (activeTab !== "Access" || !canManageAccess) return;
    setGrantsLoading(true);
    void getDatasetGrants(datasetId)
      .then((response) => { setGrants(response.items); setGrantError(null); })
      .catch((caught) => setGrantError(caught instanceof Error ? caught.message : "Access grants unavailable"))
      .finally(() => setGrantsLoading(false));
  }, [activeTab, canManageAccess, datasetId]);

  const reloadGrants = async () => {
    const response = await getDatasetGrants(datasetId);
    setGrants(response.items);
  };

  const saveGrant = async (event: FormEvent) => {
    event.preventDefault();
    setGrantBusy(true);
    setGrantError(null);
    try {
      await createDatasetGrant(datasetId, {
        ...grantDraft,
        expires_at: grantDraft.expires_at ? new Date(grantDraft.expires_at).toISOString() : null,
      });
      await reloadGrants();
      setGrantDraft((current) => ({ ...current, subject_id: "", expires_at: "", reason: "" }));
    } catch (caught) {
      setGrantError(caught instanceof Error ? caught.message : "Grant could not be created");
    } finally {
      setGrantBusy(false);
    }
  };

  const removeGrant = async (grant: DatasetGrant) => {
    if (!window.confirm(`Remove this ${grant.effect.toLowerCase()} grant? The change is audited.`)) return;
    setGrantBusy(true);
    setGrantError(null);
    try {
      await deleteDatasetGrant(datasetId, grant.id);
      await reloadGrants();
    } catch (caught) {
      setGrantError(caught instanceof Error ? caught.message : "Grant could not be removed");
    } finally {
      setGrantBusy(false);
    }
  };

  if (error) return <div className="platform-alert error">{error}</div>;
  if (!dataset) return <div className="platform-loading">Loading dataset…</div>;

  const current = dataset.versions?.find((version) => version.id === dataset.current_published_version?.id);
  return (
    <div className="platform-page detail-page">
      <header className="detail-hero">
        <div className={`dataset-identity-mark ${dataset.data_kind}`}>▦</div>
        <div className="detail-hero-copy"><div className="detail-badges"><span>{dataset.data_kind}</span><span>{dataset.visibility}</span><span>{dataset.classification}</span></div><h1>{dataset.title}</h1><p>{dataset.abstract}</p><small>{dataset.slug} · owner {dataset.owner.display_name}</small></div>
        <div className="detail-hero-actions">
          {capabilities.effective_permissions.includes("dataset.upload_version") && <Link className="platform-primary" to={`/data/datasets/new?dataset=${dataset.id}`}>＋ New version</Link>}
        </div>
      </header>
      <nav className="detail-tabs" aria-label="Dataset sections">
        {tabs.map((tab) => <button type="button" key={tab} className={activeTab === tab ? "active" : ""} onClick={() => setActiveTab(tab)}>{tab}</button>)}
      </nav>

      {activeTab === "Overview" && <section className="detail-layout"><div className="detail-main"><article className="detail-panel"><p className="platform-kicker">Current release</p>{current ? <><div className="current-release"><div><span className="state-pill published">{current.state}</span><h2>Version {current.version_label}</h2><p>{current.change_summary || "Initial governed catalogue backfill."}</p></div><Link to={`/data/versions/${current.id}`}>Open version →</Link></div><div className="release-stats"><div><span>Profile</span><strong>{current.profile_key}</strong></div><div><span>Records</span><strong>{String(current.quality?.summary.record_count ?? "—")}</strong></div><div><span>Quality</span><strong>{current.quality?.status ?? "—"}</strong></div><div><span>Published</span><strong>{current.published_at ? new Date(current.published_at).toLocaleDateString() : "—"}</strong></div></div></> : <div className="inline-empty">No published version is currently selected.</div>}</article><article className="detail-panel"><p className="platform-kicker">Purpose &amp; use</p><h2>Data product summary</h2><p>{dataset.abstract}</p><dl className="metadata-list"><div><dt>Licence</dt><dd>{dataset.licence_code ?? "Not specified"}</dd></div><div><dt>Lifecycle</dt><dd>{dataset.lifecycle_status}</dd></div><div><dt>Workspace</dt><dd>Cambodia Rice Resilience</dd></div></dl></article></div><aside><article className="detail-panel governance-summary"><p className="platform-kicker">Governance</p><h2>Access posture</h2><dl><div><dt>Visibility</dt><dd>{dataset.visibility}</dd></div><div><dt>Classification</dt><dd>{dataset.classification}</dd></div><div><dt>Owner</dt><dd>{dataset.owner.display_name}</dd></div><div><dt>Immutable release</dt><dd>{current ? "Enforced" : "Not published"}</dd></div></dl></article></aside></section>}

      {activeTab === "Versions" && <section className="detail-panel version-list"><div className="panel-title"><div><p className="platform-kicker">Version history</p><h2>Exact, reproducible snapshots</h2></div><span>{dataset.versions?.length ?? 0} total</span></div>{dataset.versions?.map((version) => <Link key={version.id} to={`/data/versions/${version.id}`}><span className={`state-pill ${version.state.toLowerCase()}`}>{version.state}</span><div><strong>{version.version_label}</strong><small>{version.profile_key}</small></div><p>{version.change_summary || "No change summary"}</p><b>Open →</b></Link>)}</section>}
      {activeTab === "Metadata" && <section className="detail-panel"><p className="platform-kicker">Product metadata</p><h2>Dataset-level defaults</h2><dl className="metadata-grid"><div><dt>Title</dt><dd>{dataset.title}</dd></div><div><dt>Slug</dt><dd>{dataset.slug}</dd></div><div><dt>Data kind</dt><dd>{dataset.data_kind}</dd></div><div><dt>Licence</dt><dd>{dataset.licence_code ?? "—"}</dd></div><div className="wide"><dt>Abstract</dt><dd>{dataset.abstract}</dd></div></dl><p className="panel-note">Each published version carries its own frozen metadata snapshot. Dataset-level edits do not rewrite history.</p></section>}
      {activeTab === "Lineage" && <section className="detail-panel"><p className="platform-kicker">Lineage</p><h2>Version-level evidence chain</h2><p>Select a version to inspect its exact ingestion or migration process, method identifier and source assets.</p><div className="link-stack">{dataset.versions?.map((version) => <Link key={version.id} to={`/data/versions/${version.id}`}>{version.version_label}<span>Inspect lineage →</span></Link>)}</div></section>}
      {activeTab === "Access" && <section className="detail-panel access-management"><p className="platform-kicker">Resource access</p><h2>Visibility, classification and grants</h2><div className="access-policy"><div><span>Default visibility</span><strong>{dataset.visibility}</strong><p>Controls who may discover and request this resource.</p></div><div><span>Classification ceiling</span><strong>{dataset.classification}</strong><p>Limits how far the resource may be shared, regardless of visibility.</p></div><div><span>Explicit deny</span><strong>Always wins</strong><p>User and group grants are re-evaluated for preview and download.</p></div></div>{grantError && <div className="platform-alert error">{grantError}</div>}{!canManageAccess ? <p className="panel-note">Only the owner or an explicitly authorised policy administrator can inspect and change resource grants.</p> : <><div className="panel-title access-title"><div><p className="platform-kicker">Current grants</p><h3>Dataset-specific policy</h3></div><span>{grants.length} entries</span></div>{grantsLoading ? <div className="platform-loading">Loading access grants…</div> : grants.length ? <div className="grant-table-wrap"><table className="grant-table"><thead><tr><th>Effect</th><th>Subject</th><th>Permission</th><th>Expiry</th><th>Reason</th><th><span className="sr-only">Actions</span></th></tr></thead><tbody>{grants.map((grant) => <tr key={grant.id}><td><span className={`grant-effect ${grant.effect.toLowerCase()}`}>{grant.effect}</span></td><td><small>{grant.subject_type}</small><code>{grant.subject_id}</code></td><td><code>{grant.permission_code}</code></td><td>{grant.expires_at ? new Date(grant.expires_at).toLocaleString() : "No expiry"}</td><td>{grant.reason}</td><td><button type="button" className="grant-remove" disabled={grantBusy} onClick={() => void removeGrant(grant)}>Remove</button></td></tr>)}</tbody></table></div> : <div className="inline-empty">No dataset-specific grants. Workspace policy and ownership still apply.</div>}<form className="grant-form" onSubmit={(event) => void saveGrant(event)}><div><label><span>Subject type</span><select value={grantDraft.subject_type} onChange={(event) => setGrantDraft((current) => ({ ...current, subject_type: event.target.value as "user" | "group" }))}><option value="user">User</option><option value="group">Group</option></select></label><label><span>Subject UUID</span><input required value={grantDraft.subject_id} onChange={(event) => setGrantDraft((current) => ({ ...current, subject_id: event.target.value }))} placeholder="User or workspace group UUID" /></label><label><span>Permission</span><select value={grantDraft.permission_code} onChange={(event) => setGrantDraft((current) => ({ ...current, permission_code: event.target.value }))}><option value="dataset.view_metadata">View metadata</option><option value="dataset.preview">Preview</option><option value="dataset.download">Download</option><option value="dataset.edit_metadata">Edit metadata</option><option value="dataset.upload_version">Upload version</option><option value="dataset.submit_review">Submit review</option><option value="dataset.manage_access">Manage access</option><option value="lineage.view">View lineage</option></select></label><label><span>Effect</span><select value={grantDraft.effect} onChange={(event) => setGrantDraft((current) => ({ ...current, effect: event.target.value as "ALLOW" | "DENY" }))}><option value="ALLOW">Allow</option><option value="DENY">Deny (takes precedence)</option></select></label><label><span>Expires (optional)</span><input type="datetime-local" value={grantDraft.expires_at} onChange={(event) => setGrantDraft((current) => ({ ...current, expires_at: event.target.value }))} /></label><label className="wide"><span>Reason</span><input required minLength={5} value={grantDraft.reason} onChange={(event) => setGrantDraft((current) => ({ ...current, reason: event.target.value }))} placeholder="Why this access is required" /></label></div><button className="platform-primary" disabled={grantBusy || !grantDraft.subject_id || grantDraft.reason.length < 5}>{grantBusy ? "Saving…" : "Add audited grant"}</button></form></>}</section>}
      {activeTab === "Activity" && <section className="detail-panel"><p className="platform-kicker">Activity</p><h2>Audited lifecycle events</h2><p>Creation, upload, review, publication, preview, download and access changes are append-only audit events.</p>{capabilities.effective_permissions.includes("audit.view") ? <Link className="platform-secondary inline-button" to={`/governance/audit?resource=${dataset.id}`}>Open filtered audit log</Link> : <p className="panel-note">Your current role does not include audit-log access.</p>}</section>}
    </div>
  );
}
