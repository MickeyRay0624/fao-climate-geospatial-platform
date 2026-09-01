import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { getDataHubDatasets } from "../api";
import { usePlatform } from "../platform/AppShell";
import type { DataHubDatasetList } from "../platform/types";

const kindLabel: Record<string, string> = { vector: "Vector", table: "Table", document: "Document", raster: "Raster" };

export default function CataloguePage({ mine = false }: { mine?: boolean }) {
  const { capabilities } = usePlatform();
  const [params, setParams] = useSearchParams();
  const [data, setData] = useState<DataHubDatasetList | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<"cards" | "table">("cards");

  const query = useMemo(() => {
    const next = new URLSearchParams(params);
    if (mine && !next.has("scope")) next.set("scope", "owned");
    return next;
  }, [mine, params]);

  useEffect(() => {
    setLoading(true);
    void getDataHubDatasets(query).then(setData).catch((caught) => setError(caught instanceof Error ? caught.message : "Catalogue unavailable")).finally(() => setLoading(false));
  }, [query]);

  const update = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value); else next.delete(key);
    setParams(next);
  };

  return (
    <div className="platform-page catalogue-page">
      <header className="page-heading">
        <div><p className="platform-kicker">Data Hub</p><h1>{mine ? "My data" : "Team catalogue"}</h1><p>{mine ? "Datasets you own or contribute to in this workspace." : "Discover governed datasets, exact versions and publication status."}</p></div>
        {capabilities.effective_permissions.includes("dataset.create") && <Link className="platform-primary" to="/data/datasets/new">＋ Add dataset</Link>}
      </header>
      {mine && <nav className="scope-tabs" aria-label="My data scope">{[["owned", "Owned by me"], ["contributed", "Contributed by me"], ["shared", "Shared with me"], ["awaiting_action", "Awaiting my action"]].map(([value, label]) => <button type="button" key={value} className={(params.get("scope") ?? "owned") === value ? "active" : ""} onClick={() => update("scope", value)}>{label}</button>)}</nav>}
      <section className="catalogue-filters">
        <label className="catalogue-search"><span>⌕</span><input value={params.get("search") ?? ""} onChange={(event) => update("search", event.target.value)} placeholder="Search title, abstract or slug" aria-label="Search catalogue" /></label>
        <label><span>Data kind</span><select value={params.get("data_kind") ?? ""} onChange={(event) => update("data_kind", event.target.value)}><option value="">All kinds</option><option value="vector">Vector</option><option value="table">Table</option><option value="document">Document</option></select></label>
        <label><span>Visibility</span><select value={params.get("visibility") ?? ""} onChange={(event) => update("visibility", event.target.value)}><option value="">All visibility</option><option>PRIVATE</option><option>WORKSPACE</option><option>RESTRICTED</option><option>PUBLIC</option></select></label>
        <label><span>Classification</span><select value={params.get("classification") ?? ""} onChange={(event) => update("classification", event.target.value)}><option value="">All classifications</option><option>PUBLIC</option><option>FAO_INTERNAL</option><option>RESTRICTED</option><option>SENSITIVE_FIELD</option></select></label>
        <label><span>Version state</span><select value={params.get("state") ?? ""} onChange={(event) => update("state", event.target.value)}><option value="">Any state</option><option>PUBLISHED</option><option>APPROVED</option><option>IN_REVIEW</option><option>DRAFT</option><option>DEPRECATED</option></select></label>
        <label><span>Quality</span><select value={params.get("quality") ?? ""} onChange={(event) => update("quality", event.target.value)}><option value="">Any quality</option><option>PASSED</option><option>WARNING</option><option>FAILED</option></select></label>
        <label><span>Sort</span><select value={params.get("sort") ?? "-updated_at"} onChange={(event) => update("sort", event.target.value)}><option value="-updated_at">Recently updated</option><option value="title">Title A–Z</option><option value="data_kind">Data kind</option><option value="-created_at">Recently created</option></select></label>
      </section>
      <div className="catalogue-meta"><span>{data?.meta.total ?? 0} datasets</span><small>Current published versions are shown where available.</small><div className="view-toggle"><button type="button" className={view === "cards" ? "active" : ""} onClick={() => setView("cards")}>Cards</button><button type="button" className={view === "table" ? "active" : ""} onClick={() => setView("table")}>Table</button></div></div>
      {error && <div className="platform-alert error">{error}</div>}
      {loading ? <div className="platform-loading">Loading catalogue…</div> : data?.items.length ? (
        <section className={view === "cards" ? "dataset-grid" : "dataset-table-view"}>
          {data.items.map((dataset) => (
            <Link className="dataset-card" to={`/data/datasets/${dataset.id}`} key={dataset.id}>
              <div className="dataset-card-top"><span className={`kind-badge ${dataset.data_kind}`}>{kindLabel[dataset.data_kind] ?? dataset.data_kind}</span><span className={`quality-chip ${(dataset.quality_status ?? "none").toLowerCase()}`}>{dataset.quality_status ?? "No validation"}</span></div>
              <h2>{dataset.title}</h2><p>{dataset.abstract}</p>
              <div className="dataset-tags"><span>{dataset.visibility.replace("_", " ")}</span><span>{dataset.classification.replace("_", " ")}</span><span className={`evidence-badge ${dataset.evidence_type.toLowerCase()}`}>{dataset.evidence_type === "REAL_SAMPLE" ? "Real source sample" : dataset.evidence_type === "SYNTHETIC_DEMO" ? "Synthetic demo" : "Governed"}</span>{dataset.licence_status === "NOT_CONFIRMED" && <span className="licence-warning">Licence not confirmed</span>}{dataset.current_published_version?.profile_key && <span>{dataset.current_published_version.profile_key}</span>}</div>
              <dl><div><dt>Owner</dt><dd>{dataset.owner.display_name}</dd></div><div><dt>Versions</dt><dd>{dataset.version_count}</dd></div><div><dt>Published</dt><dd>{dataset.current_published_version?.version_label ?? "—"}</dd></div></dl>
              <footer><small>Updated {dataset.updated_at ? new Date(dataset.updated_at).toLocaleDateString() : "—"}</small><b>View dataset →</b></footer>
            </Link>
          ))}
        </section>
      ) : <section className="platform-empty-state"><span>▦</span><h2>No matching datasets</h2><p>Adjust the filters or register a new data product.</p></section>}
      {data && data.meta.pages > 1 && <footer className="preview-pagination"><button type="button" disabled={data.meta.page <= 1} onClick={() => update("page", String(data.meta.page - 1))}>← Previous</button><span>Page {data.meta.page} of {data.meta.pages}</span><button type="button" disabled={data.meta.page >= data.meta.pages} onClick={() => update("page", String(data.meta.page + 1))}>Next →</button></footer>}
    </div>
  );
}
