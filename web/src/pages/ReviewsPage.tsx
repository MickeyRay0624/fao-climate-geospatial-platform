import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { decideReview, getReviews } from "../api";
import type { ReviewList } from "../platform/types";

export default function ReviewsPage() {
  const [reviews, setReviews] = useState<ReviewList["items"]>([]);
  const [selected, setSelected] = useState<ReviewList["items"][number] | null>(null);
  const [rationale, setRationale] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const refresh = async () => { const response = await getReviews("OPEN"); setReviews(response.items); setSelected((current) => response.items.find((item) => item.id === current?.id) ?? response.items[0] ?? null); };
  useEffect(() => { void refresh().catch((caught) => setError(caught instanceof Error ? caught.message : "Review queue unavailable")); }, []);
  const decide = async (decision: "APPROVE" | "CHANGES_REQUESTED") => {
    if (!selected) return;
    setBusy(true); setError(null);
    try { await decideReview(selected.id, decision, rationale); setRationale(""); await refresh(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Decision failed"); }
    finally { setBusy(false); }
  };
  return (
    <div className="platform-page reviews-page">
      <header className="page-heading"><div><p className="platform-kicker">Independent control</p><h1>Review queue</h1><p>Review quality and metadata evidence without inheriting publication authority.</p></div><span className="queue-count">{reviews.length} awaiting action</span></header>
      {error && <div className="platform-alert error">{error}</div>}
      <section className="review-workspace">
        <div className="review-queue"><div className="review-queue-heading"><strong>Assigned scope</strong><span>OPEN</span></div>{reviews.map((review) => <button type="button" key={review.id} className={selected?.id === review.id ? "active" : ""} onClick={() => setSelected(review)}><span className="review-kind">{review.review_type[0].toUpperCase()}</span><div><strong>{review.dataset.title}</strong><small>v{review.version.version_label} · {review.review_type}</small><time>{new Date(review.requested_at).toLocaleString()}</time></div><i>›</i></button>)}{!reviews.length && <div className="inline-empty">No open reviews.</div>}</div>
        <div className="review-evidence">{selected ? <><header><div><p className="platform-kicker">Review evidence</p><h2>{selected.dataset.title}</h2><p>Version {selected.version.version_label}</p></div><Link to={`/data/versions/${selected.version.id}`}>Open complete version ↗</Link></header><div className="review-checklist"><article><span>✓</span><div><strong>Validation completed</strong><p>Inspect structured issues and the active profile on the version page.</p></div></article><article><span>✓</span><div><strong>Metadata snapshot prepared</strong><p>Title, provenance, licence and use limitation are required before publication.</p></div></article><article><span>◇</span><div><strong>Separation of duties</strong><p>Creator {selected.version.created_by.slice(0, 8)}… cannot be the sole reviewer.</p></div></article></div><label className="review-rationale"><span>Decision rationale</span><textarea value={rationale} onChange={(event) => setRationale(event.target.value)} placeholder="Describe the evidence checked and any conditions" /></label><footer><button className="platform-secondary danger-text" disabled={busy || rationale.length < 5} onClick={() => void decide("CHANGES_REQUESTED")}>Request changes</button><button className="platform-primary" disabled={busy || rationale.length < 5} onClick={() => void decide("APPROVE")}>Approve for publication</button></footer></> : <div className="platform-empty-state"><span>✓</span><h2>Queue clear</h2><p>No review requires action.</p></div>}</div>
      </section>
    </div>
  );
}
