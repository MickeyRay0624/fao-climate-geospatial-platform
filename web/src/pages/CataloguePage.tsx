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

  const query = useMemo(() => {
    const next = new URLSearchParams(params);
    if (mine) next.set("mine", "true");
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
      <section className="catalogue-filters">
        <label className="catalogue-search"><span>⌕</span><input value={params.get("search") ?? ""} onChange={(event) => update("search", event.target.value)} placeholder="Search title, abstract or slug" aria-label="Search catalogue" /></label>
        <label><span>Data kind</span><select value={params.get("data_kind") ?? ""} onChange={(event) => update("data_kind", event.target.value)}><option value="">All kinds</option><option value="vector">Vector</option><option value="table">Table</option><option value="document">Document</option></select></label>
        <label><span>Visibility</span><select value={params.get("visibility") ?? ""} onChange={(event) => update("visibility", event.target.value)}><option value="">All visibility</option><option>PRIVATE</option><option>WORKSPACE</option><option>RESTRICTED</option><option>PUBLIC</option></select></label>
        <label><span>Classification</span><select value={params.get("classification") ?? ""} onChange={(event) => update("classification", event.target.value)}><option value="">All classifications</option><option>PUBLIC</option><option>FAO_INTERNAL</option><option>RESTRICTED</option><option>SENSITIVE_FIELD</option></select></label>
      </section>
      <div className="catalogue-meta"><span>{data?.meta.total ?? 0} datasets</span><small>Current published versions are shown where available.</small></div>
      {error && <div className="platform-alert error">{error}</div>}
      {loading ? <div className="platform-loading">Loading catalogue…</div> : data?.items.length ? (
        <section className="dataset-grid">
          {data.items.map((dataset) => (
            <Link className="dataset-card" to={`/data/datasets/${dataset.id}`} key={dataset.id}>
              <div className="dataset-card-top"><span className={`kind-badge ${dataset.data_kind}`}>{kindLabel[dataset.data_kind] ?? dataset.data_kind}</span><span className={`quality-chip ${(dataset.quality_status ?? "none").toLowerCase()}`}>{dataset.quality_status ?? "No validation"}</span></div>
              <h2>{dataset.title}</h2><p>{dataset.abstract}</p>
              <div className="dataset-tags"><span>{dataset.visibility.replace("_", " ")}</span><span>{dataset.classification.replace("_", " ")}</span>{dataset.licence_code && <span>{dataset.licence_code}</span>}</div>
              <dl><div><dt>Owner</dt><dd>{dataset.owner.display_name}</dd></div><div><dt>Versions</dt><dd>{dataset.version_count}</dd></div><div><dt>Published</dt><dd>{dataset.current_published_version?.version_label ?? "—"}</dd></div></dl>
              <footer><small>Updated {dataset.updated_at ? new Date(dataset.updated_at).toLocaleDateString() : "—"}</small><b>View dataset →</b></footer>
            </Link>
          ))}
        </section>
      ) : <section className="platform-empty-state"><span>▦</span><h2>No matching datasets</h2><p>Adjust the filters or register a new data product.</p></section>}
    </div>
  );
}
