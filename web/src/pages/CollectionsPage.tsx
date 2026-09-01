import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import {
  addDataHubCollectionMember,
  archiveDataHubCollection,
  createDataHubCollection,
  getDataHubCollection,
  getDataHubCollections,
  getDataHubDatasets,
  removeDataHubCollectionMember,
  updateDataHubCollection,
} from "../api";
import { usePlatform } from "../platform/AppShell";
import type { DataHubCollection, DataHubDatasetSummary } from "../platform/types";

function CollectionDetail({ id }: { id: string }) {
  const navigate = useNavigate();
  const [item, setItem] = useState<DataHubCollection | null>(null);
  const [datasets, setDatasets] = useState<DataHubDatasetSummary[]>([]);
  const [versionId, setVersionId] = useState("");
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [tags, setTags] = useState("");
  const [error, setError] = useState<string | null>(null);
  const load = async () => {
    const [collection, catalogue] = await Promise.all([getDataHubCollection(id), getDataHubDatasets(new URLSearchParams("page_size=100"))]);
    setItem(collection); setDatasets(catalogue.items);
    setTitle(collection.title); setDescription(collection.description); setTags(collection.tags.join(", "));
  };
  useEffect(() => { void load().catch((caught) => setError(String(caught))); }, [id]);
  if (!item) return error ? <div className="platform-alert error">{error}</div> : <div className="platform-loading">Loading exact-version collection…</div>;
  const candidates = datasets.filter((dataset) => dataset.current_published_version && !item.members?.some((member) => member.version.id === dataset.current_published_version?.id));
  const act = async (operation: () => Promise<DataHubCollection>) => {
    try { const next = await operation(); setItem(next); setError(null); }
    catch (caught) { setError(caught instanceof Error ? caught.message : String(caught)); }
  };
  return <div className="platform-page collection-detail"><header className="page-heading"><div><Link to="/data/collections">← Collections</Link><p className="platform-kicker">Exact-version collection</p><h1>{item.title}</h1><p>{item.description}</p></div><span className={`state-pill ${item.status.toLowerCase()}`}>{item.status}</span></header>{error && <div className="platform-alert error">{error}</div>}<section className="detail-panel collection-summary"><dl><div><dt>Owner</dt><dd>{item.owner.display_name}</dd></div><div><dt>Members visible to you</dt><dd>{item.member_count}</dd></div><div><dt>Row version</dt><dd>{item.row_version}</dd></div><div><dt>Tags</dt><dd>{item.tags.join(", ") || "—"}</dd></div></dl></section><section className="detail-panel"><div className="panel-title"><div><p className="platform-kicker">Frozen references</p><h2>Dataset versions</h2></div></div><div className="collection-members">{item.members?.map((member) => <article key={member.id}><div><span className="kind-badge">{member.role}</span><h3>{member.dataset.title}</h3><p>Version {member.version.version_label} · {member.version.profile_key}</p><code>{member.version.id}</code></div><div><Link to={`/data/datasets/${member.dataset.id}/versions/${member.version.id}`}>Open version</Link>{item.can_manage && item.status === "ACTIVE" && <button type="button" onClick={() => void act(() => removeDataHubCollectionMember(item, member.id))}>Remove</button>}</div></article>)}{!item.members?.length && <p className="inline-empty">No authorised exact versions are in this collection.</p>}</div>{item.can_manage && item.status === "ACTIVE" && <div className="collection-add"><label><span>Published dataset version</span><select value={versionId} onChange={(event) => setVersionId(event.target.value)}><option value="">Select…</option>{candidates.map((dataset) => <option key={dataset.id} value={dataset.current_published_version?.id}>{dataset.title} · {dataset.current_published_version?.version_label}</option>)}</select></label><button className="platform-primary" type="button" disabled={!versionId} onClick={() => void act(async () => { const next = await addDataHubCollectionMember(item.id, versionId); setVersionId(""); return next; })}>Add exact version</button></div>}</section>{item.can_manage && item.status === "ACTIVE" && <section className="detail-panel"><button type="button" className="platform-secondary" onClick={() => setEditing((value) => !value)}>{editing ? "Close editor" : "Edit collection"}</button>{editing && <form className="collection-edit" onSubmit={(event) => { event.preventDefault(); void act(() => updateDataHubCollection(item, { title, description, tags: tags.split(",").map((tag) => tag.trim()).filter(Boolean) })).then(() => setEditing(false)); }}><label>Title<input value={title} onChange={(event) => setTitle(event.target.value)} /></label><label>Description<textarea value={description} onChange={(event) => setDescription(event.target.value)} /></label><label>Tags<input value={tags} onChange={(event) => setTags(event.target.value)} /></label><button className="platform-primary">Save changes</button></form>}<button type="button" className="platform-secondary danger-text" onClick={() => void act(() => archiveDataHubCollection(item)).then(() => navigate("/data/collections"))}>Archive without deleting evidence</button></section>}</div>;
}

export default function CollectionsPage() {
  const { collectionId } = useParams();
  const { capabilities } = usePlatform();
  const navigate = useNavigate();
  const [items, setItems] = useState<DataHubCollection[]>([]);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { if (!collectionId) void getDataHubCollections().then((response) => setItems(response.items)).catch((caught) => setError(String(caught))); }, [collectionId]);
  if (collectionId) return <CollectionDetail id={collectionId} />;
  const canCreate = capabilities.effective_permissions.includes("collection.create");
  return <div className="platform-page collections-page"><header className="page-heading"><div><p className="platform-kicker">Data Hub</p><h1>Collections</h1><p>Curated references to exact dataset versions. Collections do not copy or rewrite source data.</p></div></header>{error && <div className="platform-alert error">{error}</div>}<section className="collection-grid">{items.map((item) => <Link className="detail-panel" to={`/data/collections/${item.id}`} key={item.id}><span className={`state-pill ${item.status.toLowerCase()}`}>{item.status}</span><h2>{item.title}</h2><p>{item.description}</p><div>{item.tags.map((tag) => <span key={tag}>{tag}</span>)}</div><footer>{item.member_count} authorised versions · Open →</footer></Link>)}</section>{canCreate && <details className="detail-panel collection-create"><summary>Create a collection</summary><form onSubmit={(event) => { event.preventDefault(); void createDataHubCollection({ title, description, tags: ["curated"] }).then((item) => navigate(`/data/collections/${item.id}`)).catch((caught) => setError(String(caught))); }}><label>Title<input required minLength={3} value={title} onChange={(event) => setTitle(event.target.value)} /></label><label>Description<textarea value={description} onChange={(event) => setDescription(event.target.value)} /></label><button className="platform-primary">Create collection</button></form></details>}</div>;
}
