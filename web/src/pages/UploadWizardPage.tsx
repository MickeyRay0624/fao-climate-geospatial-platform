import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import {
  completeUploadSession,
  createDataHubDataset,
  createDataHubVersion,
  createDirectUploadSession,
  getDataHubDatasets,
  getDataHubVersion,
  getJob,
  submitVersionReview,
  uploadDirect,
} from "../api";
import type { DataHubDatasetSummary, DataHubVersion, ProcessingJob } from "../platform/types";

const steps = ["Dataset", "Version", "Metadata", "Source files", "Direct upload", "Processing", "Quality", "Review"];

export default function UploadWizardPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const initialDataset = searchParams.get("dataset") ?? "";
  const [stage, setStage] = useState(initialDataset ? 1 : 0);
  const [mode, setMode] = useState<"new" | "existing">(initialDataset ? "existing" : "new");
  const [datasets, setDatasets] = useState<DataHubDatasetSummary[]>([]);
  const [datasetId, setDatasetId] = useState(initialDataset);
  const [title, setTitle] = useState("");
  const [abstract, setAbstract] = useState("");
  const [dataKind, setDataKind] = useState("vector");
  const [visibility, setVisibility] = useState("PRIVATE");
  const [classification, setClassification] = useState("FAO_INTERNAL");
  const [licence, setLicence] = useState("FAO-PILOT");
  const [versionLabel, setVersionLabel] = useState("1.0.0");
  const [changeSummary, setChangeSummary] = useState("Initial governed version");
  const [profile, setProfile] = useState("generic-vector@1.0");
  const [producer, setProducer] = useState("FAO Climate Change Group");
  const [provenance, setProvenance] = useState("");
  const [useLimitation, setUseLimitation] = useState("For internal pilot evaluation only.");
  const [methodology, setMethodology] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [job, setJob] = useState<ProcessingJob | null>(null);
  const [createdVersion, setCreatedVersion] = useState<DataHubVersion | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { void getDataHubDatasets().then((response) => setDatasets(response.items)); }, []);
  useEffect(() => {
    const next = dataKind === "table" ? "generic-table@1.0" : dataKind === "document" ? "document@1.0" : "generic-vector@1.0";
    setProfile(next);
  }, [dataKind]);

  const selectedDataset = datasets.find((item) => item.id === datasetId);
  const nextAllowed = stage === 0 ? (mode === "existing" ? Boolean(datasetId) : title.length >= 3 && abstract.length >= 10) : stage === 1 ? Boolean(versionLabel && changeSummary) : stage === 2 ? provenance.length >= 5 && useLimitation.length >= 5 : stage === 3 ? Boolean(file) : true;

  const begin = async () => {
    if (!file) return;
    setBusy(true); setError(null);
    try {
      let activeDatasetId = datasetId;
      if (mode === "new") {
        const dataset = await createDataHubDataset({ title, abstract, data_kind: dataKind, visibility, classification, licence_code: licence });
        activeDatasetId = dataset.id;
        setDatasetId(dataset.id);
      }
      const datasetTitle = mode === "new" ? title : selectedDataset?.title ?? "Dataset";
      const datasetAbstract = mode === "new" ? abstract : selectedDataset?.abstract ?? "Governed dataset version metadata.";
      const version = await createDataHubVersion(activeDatasetId, {
        version_label: versionLabel,
        profile_key: profile,
        change_summary: changeSummary,
        metadata: {
          title: datasetTitle,
          abstract: datasetAbstract,
          purpose: "Climate geospatial evidence management and decision support.",
          producer,
          provenance,
          licence_code: licence || null,
          use_limitation: useLimitation,
          crs: dataKind === "vector" ? "EPSG:4326" : null,
          methodology,
          quality_statement: "Validated using the selected versioned platform profile.",
          keywords: ["climate", "geospatial", "pilot"],
          language: "en",
          sensitive_data_declaration: classification === "SENSITIVE_FIELD" ? "Potentially sensitive field data." : "No sensitive data declared.",
          citation: "",
          source_url: null,
        },
      });
      setCreatedVersion(version);
      setStage(4);
      const upload = await createDirectUploadSession(version.id, file);
      await uploadDirect(upload.files[0].upload_url, file, setUploadProgress);
      setUploadProgress(100);
      const nextJob = await completeUploadSession(upload.id);
      setJob(nextJob);
      setStage(5);
      let current = nextJob;
      for (let attempt = 0; attempt < 90 && ["QUEUED", "RUNNING"].includes(current.status); attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 1000));
        current = await getJob(nextJob.id);
        setJob(current);
      }
      if (current.status !== "SUCCEEDED") throw new Error(current.error?.message ?? "The processing job did not complete.");
      const refreshed = await getDataHubVersion(version.id);
      setCreatedVersion(refreshed);
      setStage(6);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The upload workflow could not be completed.");
    } finally {
      setBusy(false);
    }
  };

  const submit = async () => {
    if (!createdVersion) return;
    setBusy(true); setError(null);
    try {
      await submitVersionReview(createdVersion);
      setStage(7);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Review submission failed.");
    } finally { setBusy(false); }
  };

  return (
    <div className="platform-page wizard-page">
      <header className="page-heading"><div><p className="platform-kicker">Controlled ingestion</p><h1>Add data to the workspace</h1><p>Create an exact version, upload directly to quarantine, validate, then request independent review.</p></div><button className="platform-secondary" type="button" onClick={() => navigate(-1)}>Cancel</button></header>
      <ol className="wizard-steps">{steps.map((label, index) => <li key={label} className={index < stage ? "complete" : index === stage ? "active" : ""}><i>{index < stage ? "✓" : index + 1}</i><span>{label}</span></li>)}</ol>
      {error && <div className="platform-alert error">{error}<button onClick={() => setError(null)}>×</button></div>}
      <section className="wizard-card">
        {stage === 0 && <div className="wizard-section"><div className="wizard-title"><span>01</span><div><h2>Choose or create a logical dataset</h2><p>A dataset is the long-lived data product; versions are exact snapshots.</p></div></div><div className="choice-cards"><button type="button" className={mode === "new" ? "selected" : ""} onClick={() => setMode("new")}><span>＋</span><strong>New dataset</strong><small>Register a new logical data product</small></button><button type="button" className={mode === "existing" ? "selected" : ""} onClick={() => setMode("existing")}><span>↻</span><strong>New version</strong><small>Add a snapshot to an existing product</small></button></div>{mode === "new" ? <div className="form-grid"><label className="wide"><span>Dataset title</span><input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="e.g. Cambodia drought exposure index" /></label><label className="wide"><span>Abstract</span><textarea value={abstract} onChange={(event) => setAbstract(event.target.value)} placeholder="What the data represents, where it applies, and why it exists" /></label><label><span>Data kind</span><select value={dataKind} onChange={(event) => setDataKind(event.target.value)}><option value="vector">Vector</option><option value="table">Table</option><option value="document">Document</option></select></label><label><span>Licence</span><input value={licence} onChange={(event) => setLicence(event.target.value)} /></label></div> : <label className="wide standalone-field"><span>Existing dataset</span><select value={datasetId} onChange={(event) => setDatasetId(event.target.value)}><option value="">Select a dataset…</option>{datasets.map((dataset) => <option key={dataset.id} value={dataset.id}>{dataset.title}</option>)}</select></label>}</div>}
        {stage === 1 && <div className="wizard-section"><div className="wizard-title"><span>02</span><div><h2>Version and access posture</h2><p>Visibility says who can see it; classification limits how far it may be shared.</p></div></div><div className="form-grid"><label><span>Version label</span><input value={versionLabel} onChange={(event) => setVersionLabel(event.target.value)} /></label><label><span>Validation profile</span><select value={profile} onChange={(event) => setProfile(event.target.value)}><option value="generic-vector@1.0">Generic vector 1.0</option><option value="generic-table@1.0">Generic table 1.0</option><option value="document@1.0">Document 1.0</option><option value="analysis-ready-priority-bundle@1.0">Priority bundle 1.0</option></select></label><label><span>Visibility</span><select value={visibility} disabled={mode === "existing"} onChange={(event) => setVisibility(event.target.value)}><option>PRIVATE</option><option>RESTRICTED</option><option>WORKSPACE</option><option>TEAM</option><option>FAO_INTERNAL</option><option>PUBLIC</option></select></label><label><span>Classification</span><select value={classification} disabled={mode === "existing"} onChange={(event) => setClassification(event.target.value)}><option>PUBLIC</option><option>FAO_INTERNAL</option><option>RESTRICTED</option><option>SENSITIVE_FIELD</option></select></label><label className="wide"><span>Change summary</span><textarea value={changeSummary} onChange={(event) => setChangeSummary(event.target.value)} /></label></div><div className="classification-note"><strong>Classification is the ceiling.</strong><span>SENSITIVE_FIELD data can never be published with PUBLIC visibility.</span></div></div>}
        {stage === 2 && <div className="wizard-section"><div className="wizard-title"><span>03</span><div><h2>Record provenance and use constraints</h2><p>These fields become part of the immutable metadata snapshot at publication.</p></div></div><div className="form-grid"><label><span>Producer</span><input value={producer} onChange={(event) => setProducer(event.target.value)} /></label><label><span>Licence</span><input value={licence} onChange={(event) => setLicence(event.target.value)} /></label><label className="wide"><span>Provenance</span><textarea value={provenance} onChange={(event) => setProvenance(event.target.value)} placeholder="Source organisation, acquisition date, transformations and responsible analyst" /></label><label className="wide"><span>Use limitation</span><textarea value={useLimitation} onChange={(event) => setUseLimitation(event.target.value)} /></label><label className="wide"><span>Methodology / transformations</span><textarea value={methodology} onChange={(event) => setMethodology(event.target.value)} /></label></div></div>}
        {stage === 3 && <div className="wizard-section"><div className="wizard-title"><span>04</span><div><h2>Select the source file</h2><p>The browser uploads directly to MinIO quarantine using a short-lived signed URL.</p></div></div><label className={`drop-zone ${file ? "has-file" : ""}`}><input type="file" onChange={(event) => setFile(event.target.files?.[0] ?? null)} accept=".geojson,.json,.csv,.pdf,.docx,.md,.txt" /><span>{file ? "✓" : "⇧"}</span><strong>{file?.name ?? "Choose a file or drop it here"}</strong><small>{file ? `${(file.size / 1024).toFixed(1)} KB · ${file.type || "type unknown"}` : "GeoJSON, CSV, PDF, DOCX, Markdown or text · up to 100 MB"}</small></label><div className="scan-warning"><span>!</span><p><strong>Development scan bypass is active.</strong> The scanner abstraction fails closed outside development; this local file will be visibly marked BYPASSED DEV, never “clean”.</p></div></div>}
        {stage === 4 && <div className="wizard-progress"><span className="large-progress">{uploadProgress}%</span><h2>Uploading directly to quarantine</h2><p>The API issued the URL, but the file body does not pass through FastAPI.</p><div><i style={{ width: `${uploadProgress}%` }} /></div></div>}
        {stage === 5 && <div className="wizard-section"><div className="wizard-title"><span className="spinning">↻</span><div><h2>Background validation job</h2><p>Database job state is authoritative; Redis carries execution only.</p></div></div>{job && <div className="job-steps">{job.steps.map((item) => <article key={item.key} className={item.status.toLowerCase()}><i>{item.status === "SUCCEEDED" ? "✓" : item.status === "RUNNING" ? "↻" : "·"}</i><div><strong>{item.label}</strong><small>{item.status}</small></div></article>)}</div>}<div className="job-progress"><i style={{ width: `${job?.progress ?? 0}%` }} /></div></div>}
        {stage === 6 && createdVersion && <div className="wizard-section"><div className="quality-result-hero"><span className={createdVersion.state === "VALIDATED" ? "success" : "failure"}>{createdVersion.state === "VALIDATED" ? "✓" : "×"}</span><div><p className="platform-kicker">Validation complete</p><h2>{createdVersion.state === "VALIDATED" ? "Version is ready for review" : "Blocking issues need attention"}</h2><p>{createdVersion.quality?.status} · {String(createdVersion.quality?.summary.record_count ?? 0)} records · {createdVersion.quality?.issues.length ?? 0} open issues</p></div></div>{createdVersion.quality?.issues.map((issue) => <article className={`compact-issue ${issue.severity.toLowerCase()}`} key={issue.id}><strong>{issue.code}</strong><span>{issue.details.message}</span></article>)}{createdVersion.state === "VALIDATED" && <button className="platform-primary review-submit" disabled={busy} onClick={() => void submit()}>Submit publication review →</button>}</div>}
        {stage === 7 && createdVersion && <div className="wizard-complete"><span>✓</span><p className="platform-kicker">Review requested</p><h2>The contributor action is complete.</h2><p>Switch to the Data reviewer persona to make an independent decision, then use the Data publisher persona to publish the approved immutable version.</p><div><button className="platform-primary" onClick={() => navigate(`/data/versions/${createdVersion.id}`)}>Open version</button><button className="platform-secondary" onClick={() => navigate("/data/reviews")}>Open review queue</button></div></div>}
        {stage < 4 && <footer className="wizard-actions"><button className="platform-secondary" type="button" disabled={stage === 0} onClick={() => setStage((value) => Math.max(0, value - 1))}>← Back</button>{stage < 3 ? <button className="platform-primary" type="button" disabled={!nextAllowed} onClick={() => setStage((value) => value + 1)}>Continue →</button> : <button className="platform-primary" type="button" disabled={!file || busy} onClick={() => void begin()}>{busy ? "Preparing upload…" : "Upload & validate →"}</button>}</footer>}
      </section>
    </div>
  );
}
