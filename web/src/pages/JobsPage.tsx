import { useEffect } from "react";
import { Link } from "react-router-dom";

import { usePlatform } from "../platform/AppShell";

export default function JobsPage() {
  const { capabilities, jobs, refreshJobs } = usePlatform();
  useEffect(() => { void refreshJobs(); }, [refreshJobs]);
  return (
    <div className="platform-page jobs-page">
      <header className="page-heading"><div><p className="platform-kicker">Operations</p><h1>Upload &amp; processing centre</h1><p>Visible, retryable steps backed by database job state.</p></div>{capabilities.effective_permissions.includes("dataset.upload_version") && <Link className="platform-primary" to="/data/datasets/new">＋ New upload</Link>}</header>
      <section className="jobs-summary"><article><strong>{jobs.filter((job) => job.status === "RUNNING").length}</strong><span>Running</span></article><article><strong>{jobs.filter((job) => job.status === "QUEUED").length}</strong><span>Queued</span></article><article><strong>{jobs.filter((job) => job.status === "SUCCEEDED").length}</strong><span>Completed</span></article><article><strong>{jobs.filter((job) => job.status === "FAILED").length}</strong><span>Failed</span></article></section>
      <section className="detail-panel jobs-list"><div className="panel-title"><div><p className="platform-kicker">Workspace jobs</p><h2>Processing history</h2></div><button className="platform-secondary" onClick={() => void refreshJobs()}>Refresh</button></div>{jobs.length ? jobs.map((job) => <article key={job.id}><div className={`job-status-icon ${job.status.toLowerCase()}`}>{job.status === "SUCCEEDED" ? "✓" : job.status === "FAILED" ? "×" : "↻"}</div><div className="job-copy"><strong>{job.job_type}</strong><small>{job.resource_type} · {job.resource_id}</small><div className="mini-progress"><i style={{ width: `${job.progress}%` }} /></div><div className="inline-steps">{job.steps.map((step) => <span key={step.key} className={step.status.toLowerCase()}>{step.label}</span>)}</div></div><div className="job-meta"><span className={`state-pill ${job.status.toLowerCase()}`}>{job.status}</span><small>attempt {job.attempt}/{job.max_attempts}</small><b>{Math.round(job.progress)}%</b></div></article>) : <div className="inline-empty">No jobs are visible for this role.</div>}</section>
    </div>
  );
}
