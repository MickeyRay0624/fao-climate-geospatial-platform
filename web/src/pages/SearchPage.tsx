import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { searchPlatform } from "../api";
import type { SearchResponse } from "../platform/types";

export default function SearchPage() {
  const [params] = useSearchParams();
  const query = params.get("q")?.trim() ?? "";
  const [data, setData] = useState<SearchResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (query.length < 2) { setData(null); return; }
    void searchPlatform(query).then(setData).catch((caught) => setError(String(caught)));
  }, [query]);
  return <div className="platform-page search-page"><header className="page-heading"><div><p className="platform-kicker">Permission-filtered workspace search</p><h1>{query ? `Results for “${query}”` : "Search the platform"}</h1><p>Results include only resources your current workspace identity may discover.</p></div></header>{error && <div className="platform-alert error">{error}</div>}{query.length < 2 ? <section className="platform-empty-state"><span>⌕</span><h2>Enter at least two characters</h2></section> : data?.items.length ? <section className="search-results">{data.items.map((item) => <Link className="detail-panel" to={item.path} key={`${item.type}:${item.id}`}><span>{item.type.replaceAll("_", " ")}</span><div><h2>{item.title}</h2><p>{item.subtitle}</p></div><b>Open →</b></Link>)}</section> : data ? <section className="platform-empty-state"><span>⌕</span><h2>No authorised matches</h2><p>No resource names, counts or existence details are disclosed outside your permissions.</p></section> : <div className="platform-loading">Searching authorised resources…</div>}</div>;
}
