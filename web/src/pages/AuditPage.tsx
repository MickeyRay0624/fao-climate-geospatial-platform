import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { exportAuditEvents, getAuditEvents } from "../api";
import type { AuditList } from "../platform/types";

export default function AuditPage() {
  const [params, setParams] = useSearchParams();
  const [data, setData] = useState<AuditList | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const query = useMemo(() => {
    const next = new URLSearchParams(params);
    const resource = next.get("resource");
    if (resource) {
      next.delete("resource");
      next.set("resource_id", resource);
    }
    const from = next.get("date_from");
    const to = next.get("date_to");
    if (from?.length === 10) next.set("date_from", `${from}T00:00:00Z`);
    if (to?.length === 10) next.set("date_to", `${to}T23:59:59Z`);
    return next;
  }, [params]);

  useEffect(() => {
    setError(null);
    void getAuditEvents(query).then(setData).catch((caught) => setError(caught instanceof Error ? caught.message : "Audit log unavailable"));
  }, [query]);

  const update = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value); else next.delete(key);
    setParams(next);
  };

  return (
    <div className="platform-page audit-page">
      <header className="page-heading">
        <div><p className="platform-kicker">Append-only evidence</p><h1>Workspace audit log</h1><p>Trace identity, data lifecycle, access and processing actions using stable correlation IDs.</p></div>
        <span className="read-only-badge">Read only · database enforced</span>
      </header>
      <section className="audit-filters">
        <label className="catalogue-search"><span>⌕</span><input value={params.get("search") ?? ""} onChange={(event) => update("search", event.target.value)} placeholder="Action, resource or rationale" /></label>
        <label><span>Action</span><input value={params.get("action") ?? ""} onChange={(event) => update("action", event.target.value)} placeholder="Exact action" /></label>
        <label><span>Actor UUID</span><input value={params.get("actor_id") ?? ""} onChange={(event) => update("actor_id", event.target.value)} placeholder="Optional actor" /></label>
        <label><span>Outcome</span><select value={params.get("outcome") ?? ""} onChange={(event) => update("outcome", event.target.value)}><option value="">All outcomes</option><option value="success">Success</option><option value="denied">Denied</option><option value="failure">Failure</option></select></label>
        <label><span>Resource</span><select value={params.get("resource_type") ?? ""} onChange={(event) => update("resource_type", event.target.value)}><option value="">All resources</option><option value="dataset">Dataset</option><option value="dataset_version">Dataset version</option><option value="asset">Asset</option><option value="review_request">Review</option><option value="processing_job">Job</option><option value="module">Module</option></select></label>
        <label><span>From</span><input type="date" value={params.get("date_from") ?? ""} onChange={(event) => update("date_from", event.target.value)} /></label>
        <label><span>To</span><input type="date" value={params.get("date_to") ?? ""} onChange={(event) => update("date_to", event.target.value)} /></label>
        <button className="platform-secondary" type="button" onClick={() => void exportAuditEvents(query).catch((caught) => setError(String(caught)))}>Export filtered CSV</button>
      </section>
      {error && <div className="platform-alert error">{error}</div>}
      <section className="detail-panel audit-table">
        <div className="panel-title"><div><p className="platform-kicker">Recorded events</p><h2>Newest first</h2></div><span>{data?.meta.total ?? 0} events</span></div>
        {!data ? <div className="platform-loading">Loading audit evidence…</div> : data.items.length ? <div className="audit-rows">
          {data.items.map((event) => <article key={event.id} className={expanded === event.id ? "expanded" : ""}>
            <button type="button" onClick={() => setExpanded((current) => current === event.id ? null : event.id)}>
              <span className={`audit-outcome ${event.outcome}`}>{event.outcome === "success" ? "✓" : "!"}</span>
              <time>{new Date(event.event_time).toLocaleString()}</time>
              <div><strong>{event.action}</strong><small>{event.resource_type} · {event.resource_id}</small></div>
              <code>{event.correlation_id.slice(0, 12)}…</code><i>{expanded === event.id ? "⌃" : "⌄"}</i>
            </button>
            {expanded === event.id && <div className="audit-detail"><dl><div><dt>Actor</dt><dd>{event.actor_id ?? "system"}</dd></div><div><dt>Severity</dt><dd>{event.severity}</dd></div><div><dt>Rationale</dt><dd>{event.reason ?? "—"}</dd></div><div><dt>Correlation ID</dt><dd>{event.correlation_id}</dd></div></dl><div className="audit-json bounded"><section><strong>Redacted before fields</strong><pre>{JSON.stringify(event.before, null, 2)}</pre></section><section><strong>Redacted after fields</strong><pre>{JSON.stringify(event.after, null, 2)}</pre></section></div></div>}
          </article>)}
        </div> : <div className="inline-empty">No events match these filters.</div>}
      </section>
    </div>
  );
}
