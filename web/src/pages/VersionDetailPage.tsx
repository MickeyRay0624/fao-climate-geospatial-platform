import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import {
  decideReview,
  getDataHubVersion,
  getVersionDownload,
  getVersionLineage,
  getVersionPreview,
  publishDataHubVersion,
  submitVersionReview,
} from "../api";
import DataPreview from "../components/DataPreview";
import { usePlatform } from "../platform/AppShell";
import type { DataHubVersion, VersionPreview } from "../platform/types";

const tabs = ["Summary", "Preview", "Files", "Quality", "Review", "Lineage", "Download"] as const;

export default function VersionDetailPage() {
  const { versionId = "" } = useParams();
  const { capabilities } = usePlatform();
  const [version, setVersion] = useState<DataHubVersion | null>(null);
  const [activeTab, setActiveTab] = useState<(typeof tabs)[number]>("Summary");
  const [preview, setPreview] = useState<VersionPreview | null>(null);
  const [lineage, setLineage] = useState<Record<string, unknown> | null>(null);
  const [rationale, setRationale] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = async () => setVersion(await getDataHubVersion(versionId));
  useEffect(() => { void refresh().catch((caught) => setError(caught instanceof Error ? caught.message : "Version unavailable")); }, [versionId]);
  useEffect(() => {
    if (activeTab === "Preview" && preview === null) void getVersionPreview(versionId).then(setPreview).catch((caught) => setError(caught instanceof Error ? caught.message : "Preview unavailable"));
    if (activeTab === "Lineage" && lineage === null) void getVersionLineage(versionId).then(setLineage).catch((caught) => setError(caught instanceof Error ? caught.message : "Lineage unavailable"));
  }, [activeTab, lineage, preview, versionId]);

  if (!version && error) return <div className="platform-alert error">{error}</div>;
  if (!version) return <div className="platform-loading">Loading version…</div>;
  const permission = (code: string) => capabilities.effective_permissions.includes(code);
  const openReview = version.reviews.find((review) => review.status === "OPEN");
  const lifecycleStates = ["DRAFT", "UPLOADING", "PROCESSING", "VALIDATED", "IN_REVIEW", "APPROVED", "PUBLISHED"];
  const lifecycleIndex = ["DEPRECATED", "ARCHIVED"].includes(version.state)
    ? lifecycleStates.length - 1
    : lifecycleStates.indexOf(version.state);
  const displayedMetadata = ["PUBLISHED", "DEPRECATED", "ARCHIVED"].includes(version.state)
    ? version.metadata_snapshot
    : (version.metadata ?? {});

  const act = async (operation: () => Promise<unknown>, message: string) => {
    setBusy(true); setError(null);
    try { await operation(); await refresh(); setNotice(message); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Action failed"); }
    finally { setBusy(false); }
  };

  return (
    <div className="platform-page detail-page version-page">
      <header className="version-heading"><div><Link to={`/data/datasets/${version.dataset_id}`}>← Back to dataset</Link><div className="detail-badges"><span className={`state-pill ${version.state.toLowerCase()}`}>{version.state}</span><span>{version.profile_key}</span></div><h1>Version {version.version_label}</h1><p>{version.change_summary || "No change summary was provided."}</p></div><div className="version-actions">{permission("dataset.submit_review") && ["VALIDATED", "CHANGES_REQUESTED"].includes(version.state) && <button className="platform-primary" disabled={busy} onClick={() => void act(() => submitVersionReview(version), "Version submitted for independent review.")}>Submit for review</button>}{permission("dataset.publish") && version.state === "APPROVED" && <button className="platform-primary" disabled={busy} onClick={() => void act(() => publishDataHubVersion(version), "Published version is now immutable.")}>Publish version</button>}</div></header>
      {notice && <div className="platform-alert success">{notice}<button onClick={() => setNotice(null)}>×</button></div>}
      {error && <div className="platform-alert error">{error}<button onClick={() => setError(null)}>×</button></div>}
      <nav className="detail-tabs" aria-label="Version sections">{tabs.map((tab) => <button type="button" key={tab} className={activeTab === tab ? "active" : ""} onClick={() => setActiveTab(tab)}>{tab}{tab === "Quality" && version.quality?.issues.length ? <b>{version.quality.issues.length}</b> : null}</button>)}</nav>

      {activeTab === "Summary" && <section className="detail-layout"><div className="detail-main"><article className="detail-panel"><p className="platform-kicker">Version lifecycle</p><h2>Governed snapshot</h2><div className="lifecycle-track">{lifecycleStates.map((state, index) => <div key={state} className={index <= lifecycleIndex ? "complete" : ""}><i>{index < lifecycleIndex ? "✓" : index + 1}</i><span>{state.replace("_", " ")}</span></div>)}</div></article><article className="detail-panel"><p className="platform-kicker">Frozen publication metadata</p><h2>{String(displayedMetadata.title ?? "Version metadata")}</h2><dl className="metadata-grid">{Object.entries(displayedMetadata).slice(0, 12).map(([key, value]) => <div key={key} className={key === "abstract" || key === "provenance" || key === "use_limitation" ? "wide" : ""}><dt>{key.replaceAll("_", " ")}</dt><dd>{Array.isArray(value) ? value.join(", ") : String(value ?? "—")}</dd></div>)}</dl></article></div><aside><article className="detail-panel version-facts"><p className="platform-kicker">Version facts</p><dl><div><dt>Created</dt><dd>{version.created_at ? new Date(version.created_at).toLocaleString() : "—"}</dd></div><div><dt>Assets</dt><dd>{version.assets.length}</dd></div><div><dt>Quality</dt><dd>{version.quality?.status ?? "Not run"}</dd></div><div><dt>Scan</dt><dd>{version.assets[0]?.scan_status ?? "Pending"}</dd></div><div><dt>Row version</dt><dd>{version.row_version}</dd></div></dl></article></aside></section>}
      {activeTab === "Preview" && <section className="detail-panel"><p className="platform-kicker">Authorised preview</p><h2>Paginated representation</h2><p className="panel-note">Every page is re-authorised and audited. Display simplification never changes the source asset.</p>{preview ? <DataPreview data={preview} onPage={(page) => void getVersionPreview(versionId, page).then(setPreview).catch((caught) => setError(caught instanceof Error ? caught.message : "Preview unavailable"))} /> : <div className="platform-loading">Loading preview…</div>}</section>}
      {activeTab === "Files" && <section className="detail-panel file-list"><div className="panel-title"><div><p className="platform-kicker">Registered assets</p><h2>Source files</h2></div><span>{version.assets.length} files</span></div>{version.assets.map((asset) => <article key={asset.id}><span className="file-icon">◫</span><div><strong>{asset.filename}</strong><small>{asset.media_type} · {(asset.size_bytes / 1024).toFixed(1)} KB</small><code>SHA-256 {asset.sha256}</code></div><span className={`scan-chip ${asset.scan_status.toLowerCase()}`}>{asset.scan_status.replaceAll("_", " ")}</span></article>)}</section>}
      {activeTab === "Quality" && <section className="detail-panel quality-detail"><div className="panel-title"><div><p className="platform-kicker">Validation evidence</p><h2>{version.quality?.status ?? "Not validated"}</h2></div><span>{String(version.quality?.summary.record_count ?? "—")} records</span></div>{version.quality?.issues.length ? <div className="issue-list">{version.quality.issues.map((issue) => <article key={issue.id} className={issue.severity.toLowerCase()}><span>{issue.severity === "BLOCKING" ? "×" : "!"}</span><div><strong>{issue.name}</strong><code>{issue.code}</code><p>{issue.details.message ?? "Structured validation issue"}</p></div><b>{issue.affected_count}</b></article>)}</div> : <div className="quality-success"><span>✓</span><div><h3>No open validation issues</h3><p>The selected validation profile completed without warnings or blockers.</p></div></div>}</section>}
      {activeTab === "Review" && <section className="detail-panel review-detail"><p className="platform-kicker">Separation of duties</p><h2>Review evidence</h2>{version.reviews.length ? <div className="review-history">{version.reviews.map((review) => <article key={review.id}><span className={`state-pill ${review.status.toLowerCase()}`}>{review.status}</span><div><strong>{review.review_type} review</strong><small>Requested {new Date(review.requested_at).toLocaleString()}</small></div></article>)}</div> : <p>No review has been requested.</p>}{permission("dataset.review") && openReview && <form className="review-decision" onSubmit={(event) => event.preventDefault()}><label><span>Review rationale</span><textarea value={rationale} onChange={(event) => setRationale(event.target.value)} placeholder="Record the evidence and reason for this decision" /></label><div><button className="platform-secondary danger-text" disabled={busy || rationale.length < 5} onClick={() => void act(() => decideReview(openReview.id, "CHANGES_REQUESTED", rationale), "Changes requested.")}>Request changes</button><button className="platform-primary" disabled={busy || rationale.length < 5} onClick={() => void act(() => decideReview(openReview.id, "APPROVE", rationale), "Version approved for publication.")}>Approve version</button></div></form>}</section>}
      {activeTab === "Lineage" && <section className="detail-panel"><p className="platform-kicker">Lineage graph</p><h2>Processes that produced this version</h2>{lineage ? <pre className="json-preview">{JSON.stringify(lineage, null, 2)}</pre> : <div className="platform-loading">Loading lineage…</div>}</section>}
      {activeTab === "Download" && <section className="detail-panel download-panel"><span className="download-icon">⇩</span><div><p className="platform-kicker">Controlled download</p><h2>Request a short-lived source URL</h2><p>The API evaluates visibility, classification, grants and explicit denies again. The URL expires and permanent object credentials are never sent to the browser.</p><button className="platform-primary" disabled={busy || !permission("dataset.download")} onClick={() => void act(async () => { const download = await getVersionDownload(version.id); window.open(download.url, "_blank", "noopener"); }, "A short-lived download URL was issued and audited.")}>Authorise download</button></div></section>}
    </div>
  );
}
