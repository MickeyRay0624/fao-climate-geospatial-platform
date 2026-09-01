import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, Navigate, Route, Routes, useNavigate, useParams } from "react-router-dom";

import {
  approveExtensionActivity,
  assignExtensionCase,
  completeExtensionFollowUp,
  createExtensionActivity,
  createExtensionAssessment,
  createExtensionCase,
  createExtensionFollowUp,
  createExtensionObservation,
  getDevPersonas,
  getExtensionActivities,
  getExtensionCase,
  getExtensionCases,
  getExtensionKnowledge,
  getExtensionMap,
  getExtensionOverview,
  getExtensionSupervision,
  getExtensionSyncStatus,
  getExtensionVerificationTemplates,
  saveExtensionVerification,
  startExtensionVerification,
  transitionExtensionCase,
  uploadExtensionMedia,
} from "../../api";
import { usePlatform } from "../../platform/AppShell";
import type {
  DevPersona,
  ExtensionActivity,
  ExtensionCaseDetail,
  ExtensionCaseSummary,
  ExtensionKnowledge,
  ExtensionSupervision,
  ExtensionVerification,
} from "../../platform/types";
import ExtensionMap from "./ExtensionMap";

const base = "/apps/extension-field-support";
const terminal = new Set(["CLOSED", "CANCELLED"]);

function human(value: string) {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function when(value: string | null) {
  return value ? new Intl.DateTimeFormat("en-GB", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)) : "Not recorded";
}

function Status({ value }: { value: string }) {
  return <span className={`extension-status ${value.toLowerCase().replaceAll("_", "-")}`}>{human(value)}</span>;
}

function Notice({ error }: { error: string | null }) {
  return error ? <div className="error-banner" role="alert"><strong>Action not completed.</strong> {error}</div> : null;
}

function Loading() {
  return <div className="platform-loading">Loading extension workflow records…</div>;
}

function useOnline() {
  const [online, setOnline] = useState(navigator.onLine);
  useEffect(() => {
    const update = () => setOnline(navigator.onLine);
    window.addEventListener("online", update);
    window.addEventListener("offline", update);
    return () => { window.removeEventListener("online", update); window.removeEventListener("offline", update); };
  }, []);
  return online;
}

function ExtensionNav() {
  const { capabilities } = usePlatform();
  return <nav className="extension-nav" aria-label="Extension field support"><Link to={`${base}/worklist`}>Worklist</Link><Link to={`${base}/map`}>Map</Link><Link to={`${base}/cases`}>Cases</Link><Link to={`${base}/knowledge`}>Knowledge</Link><Link to={`${base}/activities`}>Activities</Link>{capabilities.effective_permissions.includes("apps.extension.supervise") && <Link to={`${base}/supervision`}>Supervision</Link>}<Link to={`${base}/sync`}>Sync</Link></nav>;
}

function CaseCards({ items }: { items: ExtensionCaseSummary[] }) {
  if (!items.length) return <div className="platform-empty-state"><span>✓</span><h2>No cases match this view</h2><p>Access scope and filters are applied by the API.</p></div>;
  return <div className="extension-case-grid">{items.map((item) => <Link className="extension-case-card" to={`${base}/cases/${item.id}/summary`} key={item.id}><header><div><small>{item.case_number}</small><Status value={item.status} /></div><span className={`extension-priority ${item.priority.toLowerCase()}`}>{item.priority}</span></header><h3>{item.title}</h3><p>{item.crop} · {item.growth_stage} · {item.location_label}</p><dl><div><dt>Assigned</dt><dd>{item.assignee?.display_name ?? "Unassigned"}</dd></div><div><dt>Last observation</dt><dd>{when(item.last_observation_at)}</dd></div><div><dt>Next action</dt><dd>{item.next_action}</dd></div><div><dt>Sync</dt><dd>{item.sync_status}</dd></div></dl>{item.overdue_follow_ups > 0 && <strong className="overdue-label">{item.overdue_follow_ups} overdue follow-up</strong>}<footer><span>DEMONSTRATION</span><b>Open case →</b></footer></Link>)}</div>;
}

function WorklistPage() {
  const [items, setItems] = useState<ExtensionCaseSummary[] | null>(null);
  const [status, setStatus] = useState("");
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { void getExtensionCases(true).then((response) => setItems(response.items)).catch((caught) => setError(String(caught))); }, []);
  if (!items) return error ? <Notice error={error} /> : <Loading />;
  const visible = items.filter((item) => (!status || item.status === status) && (!query || `${item.case_number} ${item.title} ${item.location_label}`.toLowerCase().includes(query.toLowerCase())));
  return <><Notice error={error} /><section className="extension-page-heading"><div><p className="platform-kicker">Assigned field workflow</p><h2>My worklist</h2><p>Fictional demonstration cases only. No personal names, exact farms or automated advice.</p></div><Link className="platform-primary" to={`${base}/cases/new`}>New case</Link></section><div className="extension-filters"><label>Search<input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Case, title or demo zone" /></label><label>Status<select value={status} onChange={(event) => setStatus(event.target.value)}><option value="">All active states</option>{["ASSIGNED", "IN_OBSERVATION", "IN_VERIFICATION", "ACTION_PLANNED", "FOLLOW_UP", "CLOSED"].map((value) => <option key={value} value={value}>{human(value)}</option>)}</select></label></div><CaseCards items={visible} /></>;
}

function CasesPage() {
  const [items, setItems] = useState<ExtensionCaseSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { void getExtensionCases().then((response) => setItems(response.items)).catch((caught) => setError(String(caught))); }, []);
  if (!items) return error ? <Notice error={error} /> : <Loading />;
  return <><section className="extension-page-heading"><div><p className="platform-kicker">Permission-scoped register</p><h2>Cases</h2><p>Only assigned, owned or workspace-supervised records are returned.</p></div><Link className="platform-primary" to={`${base}/cases/new`}>New case</Link></section><CaseCards items={items} /></>;
}

function NewCasePage() {
  const navigate = useNavigate();
  const storageKey = "extension:draft:new-case";
  const stored = sessionStorage.getItem(storageKey);
  const initial = stored ? JSON.parse(stored) as Record<string, string> : {};
  const [title, setTitle] = useState(initial.title ?? "");
  const [stage, setStage] = useState(initial.stage ?? "Tillering");
  const [severity, setSeverity] = useState(initial.severity ?? "MODERATE");
  const [area, setArea] = useState(initial.area ?? "");
  const [location, setLocation] = useState(initial.location ?? "Fictional demo zone");
  const [notes, setNotes] = useState(initial.notes ?? "");
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { sessionStorage.setItem(storageKey, JSON.stringify({ title, stage, severity, area, location, notes })); }, [title, stage, severity, area, location, notes]);
  const submit = async () => {
    try {
      const item = await createExtensionCase({ title, crop: "Rice", growth_stage: stage, severity, affected_area_ha: area ? Number(area) : null, location_label: location, priority: severity === "HIGH" ? "HIGH" : "NORMAL", notes });
      sessionStorage.removeItem(storageKey);
      navigate(`${base}/cases/${item.id}/summary`);
    } catch (caught) { setError(String(caught)); }
  };
  return <><Notice error={error} /><section className="panel extension-form"><p className="platform-kicker">Offline-capable local draft</p><h2>New demonstration case</h2><div className="method-note inline"><span>!</span><p>Do not enter farmer names, phone numbers, exact farm coordinates or other personal information. Draft text remains in this browser session until submitted or cleared.</p></div><div className="form-grid"><label className="wide">Case summary<input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Visible field condition" /></label><label>Crop<input value="Rice" disabled /></label><label>Growth stage<select value={stage} onChange={(event) => setStage(event.target.value)}><option>Tillering</option><option>Vegetative</option><option>Heading</option><option>Flowering</option><option>Maturity</option><option>Not recorded</option></select></label><label>Severity<select value={severity} onChange={(event) => setSeverity(event.target.value)}><option>LOW</option><option>MODERATE</option><option>HIGH</option></select></label><label>Affected area (ha)<input type="number" min="0" step="0.1" value={area} onChange={(event) => setArea(event.target.value)} /></label><label className="wide">Approximate fictional location<input value={location} onChange={(event) => setLocation(event.target.value)} /></label><label className="wide">Observation context<textarea value={notes} onChange={(event) => setNotes(event.target.value)} /></label></div><div className="analysis-actions"><button className="secondary-button" type="button" onClick={() => { sessionStorage.removeItem(storageKey); setTitle(""); setNotes(""); }}>Clear local draft</button><button className="primary-button" type="button" disabled={title.trim().length < 3} onClick={() => void submit()}>Submit new case</button></div></section></>;
}

function CaseNav({ item }: { item: ExtensionCaseDetail }) {
  return <nav className="extension-case-nav" aria-label={`Case ${item.case_number}`}><Link to={`${base}/cases/${item.id}/summary`}>Summary</Link><Link to={`${base}/cases/${item.id}/observations`}>Observations</Link><Link to={`${base}/cases/${item.id}/assessment`}>Field assessment</Link><Link to={`${base}/cases/${item.id}/verification`}>Verification</Link><Link to={`${base}/cases/${item.id}/action`}>Action</Link><Link to={`${base}/cases/${item.id}/follow-up`}>Follow-up</Link><Link to={`${base}/cases/${item.id}/activity`}>Activity</Link></nav>;
}

function CaseSummaryView({ item, reload }: { item: ExtensionCaseDetail; reload: () => void }) {
  const { capabilities } = usePlatform();
  const [error, setError] = useState<string | null>(null);
  const close = async () => { try { await transitionExtensionCase(item, "CLOSED", "Supervisor reviewed completed follow-up and closure evidence."); reload(); } catch (caught) { setError(String(caught)); } };
  return <><Notice error={error} /><div className="extension-detail-grid"><section className="panel extension-summary"><p className="platform-kicker">Case evidence</p><h3>Summary</h3><dl><div><dt>Crop / stage</dt><dd>{item.crop} · {item.growth_stage}</dd></div><div><dt>Severity / area</dt><dd>{item.severity} · {item.affected_area_ha ?? "—"} ha</dd></div><div><dt>Approximate location</dt><dd>{item.location_label}</dd></div><div><dt>Assigned officer</dt><dd>{item.assignee?.display_name ?? "Unassigned"}</dd></div><div><dt>Next action</dt><dd>{item.next_action}</dd></div><div><dt>Sync status</dt><dd>{item.sync_status}</dd></div></dl><p>{item.notes}</p>{capabilities.effective_permissions.includes("extension.case.close") && item.status === "FOLLOW_UP" && item.follow_ups.every((value) => value.status === "COMPLETED") && <button className="primary-button" type="button" onClick={() => void close()}>Close with recorded rationale</button>}</section><section className="panel extension-history"><p className="platform-kicker">Append-only history</p><h3>Status timeline</h3>{item.history.map((event) => <article key={event.id}><i /><div><strong>{event.from_status ? `${human(event.from_status)} → ` : ""}{human(event.to_status)}</strong><p>{event.reason}</p><small>{when(event.changed_at)}</small></div></article>)}</section></div></>;
}

function ObservationsView({ item, reload }: { item: ExtensionCaseDetail; reload: () => void }) {
  const storageKey = `extension:draft:observation:${item.id}`;
  const [notes, setNotes] = useState(sessionStorage.getItem(storageKey) ?? "");
  const [severity, setSeverity] = useState(item.severity);
  const [area, setArea] = useState(item.affected_area_ha?.toString() ?? "");
  const [media, setMedia] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { sessionStorage.setItem(storageKey, notes); }, [notes, storageKey]);
  const submit = async (complete: boolean) => {
    try {
      const observation = await createExtensionObservation(item.id, { client_uuid: crypto.randomUUID(), status: complete ? "COMPLETED" : "DRAFT", observed_at: new Date().toISOString(), severity, affected_area_ha: area ? Number(area) : null, approximate_location: item.location_label, notes, structured: { evidence_source: "officer_manual_entry", automatic_interpretation: false } });
      if (media) await uploadExtensionMedia(item.id, media, observation.id);
      sessionStorage.removeItem(storageKey);
      setNotes(""); setMedia(null); reload();
    } catch (caught) { setError(String(caught)); }
  };
  return <><Notice error={error} /><section className="panel extension-form"><p className="platform-kicker">Structured field evidence</p><h3>New observation</h3><div className="form-grid"><label>Observed time<input type="datetime-local" value={new Date().toISOString().slice(0, 16)} readOnly /></label><label>Severity<select value={severity} onChange={(event) => setSeverity(event.target.value)}><option>LOW</option><option>MODERATE</option><option>HIGH</option></select></label><label>Affected area (ha)<input type="number" min="0" step="0.1" value={area} onChange={(event) => setArea(event.target.value)} /></label><label>Optional evidence image<input type="file" accept="image/jpeg,image/png,image/webp" onChange={(event) => setMedia(event.target.files?.[0] ?? null)} /></label><label className="wide">Visible observations and missing information<textarea value={notes} onChange={(event) => setNotes(event.target.value)} /></label></div><div className="analysis-actions"><button className="secondary-button" type="button" disabled={!notes.trim()} onClick={() => void submit(false)}>Save draft</button><button className="primary-button" type="button" disabled={!notes.trim() || terminal.has(item.status)} onClick={() => void submit(true)}>Complete immutable observation</button></div><small className="extension-limit">Images are restricted, scanned through the configured abstraction and never auto-registered in Data Hub. The local app shell does not cache media.</small></section><section className="panel extension-record-list"><h3>Observation revisions</h3>{item.observations.map((observation) => <article key={observation.id}><div><Status value={observation.status} /><strong>{when(observation.observed_at)}</strong></div><p>{observation.notes}</p><small>{observation.status === "COMPLETED" ? "Immutable completed evidence" : "Editable draft"} · {observation.severity}</small></article>)}</section></>;
}

function AssessmentView({ item, reload }: { item: ExtensionCaseDetail; reload: () => void }) {
  const [knowledge, setKnowledge] = useState<ExtensionKnowledge[]>([]);
  const [versionId, setVersionId] = useState("");
  const [missing, setMissing] = useState("");
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { void getExtensionKnowledge().then((response) => { const possible = response.items.filter((value) => value.category === "possible-cause-category"); setKnowledge(possible); setVersionId(possible[0]?.current_version_id ?? ""); }).catch((caught) => setError(String(caught))); }, []);
  const submit = async () => { try { await createExtensionAssessment(item.id, { knowledge_version_id: versionId, supporting_observation_ids: item.observations.filter((value) => value.status === "COMPLETED").map((value) => value.id), missing_information: missing.split("\n").map((value) => value.trim()).filter(Boolean), note: "Officer manually selected this demonstration category." }); reload(); } catch (caught) { setError(String(caught)); } };
  return <><Notice error={error} /><section className="panel extension-form"><p className="platform-kicker">Manual, controlled selection</p><h3>Field assessment</h3><div className="method-note inline"><span>i</span><p>No ranking, model or generated explanation is used. The officer chooses one approved-in-demo category and cites completed observations.</p></div><div className="form-grid"><label className="wide">Possible cause category<select value={versionId} onChange={(event) => setVersionId(event.target.value)}>{knowledge.map((entry) => <option value={entry.current_version_id ?? ""} key={entry.id}>{entry.title} · exact version</option>)}</select></label><label className="wide">Missing information, one item per line<textarea value={missing} onChange={(event) => setMissing(event.target.value)} /></label></div><p className="extension-limit">Supporting evidence: {item.observations.filter((value) => value.status === "COMPLETED").length} completed observation(s).</p><button className="primary-button" type="button" disabled={!versionId || item.status !== "IN_OBSERVATION"} onClick={() => void submit()}>Record manual category and begin verification</button></section><section className="panel extension-record-list"><h3>Recorded assessments</h3>{item.assessments.map((assessment) => <article key={assessment.id}><div><Status value={assessment.status} /><strong>{assessment.possible_cause_category}</strong></div><p>{assessment.review_reason}</p><small>{assessment.supporting_observation_ids.length} supporting observations · {assessment.missing_information.length} information gaps</small></article>)}</section></>;
}

function VerificationView({ item, reload }: { item: ExtensionCaseDetail; reload: () => void }) {
  const [templates, setTemplates] = useState<Array<{ id: string; name: string; version_number: number }>>([]);
  const [session, setSession] = useState<ExtensionVerification | null>(item.verifications.find((value) => value.status === "DRAFT") ?? null);
  const [responses, setResponses] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { void getExtensionVerificationTemplates().then((value) => setTemplates(value.items)).catch((caught) => setError(String(caught))); }, []);
  const start = async () => { if (!templates[0]) return; try { const next = await startExtensionVerification(item.id, templates[0].id); setSession(next); } catch (caught) { setError(String(caught)); } };
  const save = async (complete: boolean) => { if (!session) return; try { const next = await saveExtensionVerification(session, session.items.map((entry) => ({ verification_item_id: entry.id, value: responses[entry.id] ?? entry.response?.value ?? "UNKNOWN", evidence_note: "Officer-recorded demonstration response." })), complete); setSession(next.status === "COMPLETED" ? null : next); reload(); } catch (caught) { setError(String(caught)); } };
  return <><Notice error={error} /><section className="panel extension-form"><p className="platform-kicker">Versioned structured checklist</p><h3>Verification</h3>{!session ? <button className="primary-button" type="button" disabled={item.status !== "IN_VERIFICATION" || !templates.length} onClick={() => void start()}>Start new verification revision</button> : <><p>{session.template.name} · version {session.template.version_number} · revision {session.revision_number}</p><div className="verification-list">{session.items.map((entry) => <label key={entry.id}><span><strong>{entry.ordinal}. {entry.prompt}</strong><small>{entry.required_evidence}</small></span><select value={responses[entry.id] ?? entry.response?.value ?? "UNKNOWN"} onChange={(event) => setResponses((current) => ({ ...current, [entry.id]: event.target.value }))}><option>YES</option><option>NO</option><option>UNKNOWN</option></select></label>)}</div><div className="analysis-actions"><button className="secondary-button" type="button" onClick={() => void save(false)}>Save draft</button><button className="primary-button" type="button" onClick={() => void save(true)}>Complete immutable revision</button></div></>}</section><section className="panel extension-record-list"><h3>Verification history</h3>{item.verifications.map((entry) => <article key={entry.id}><div><Status value={entry.status} /><strong>Revision {entry.revision_number}</strong></div><p>{entry.template.name} · version {entry.template.version_number}</p><small>{entry.status === "COMPLETED" ? "Immutable" : "Draft"} · {entry.items.length} items</small></article>)}</section></>;
}

function ActionView({ item, reload }: { item: ExtensionCaseDetail; reload: () => void }) {
  const { capabilities } = usePlatform();
  const [objective, setObjective] = useState("Review structured field evidence and schedule a documented follow-up.");
  const [due, setDue] = useState("2026-09-15");
  const [error, setError] = useState<string | null>(null);
  const create = async () => { if (!item.assignee) return; try { await createExtensionActivity({ case_id: item.id, activity_type: "field_visit", objective, participant_count: 0, responsible_officer_id: item.assignee.id, due_date: due, steps: ["Confirm privacy boundary", "Review structured evidence", "Schedule follow-up"], submit_for_approval: true }); reload(); } catch (caught) { setError(String(caught)); } };
  const approve = async (activity: ExtensionActivity) => { try { await approveExtensionActivity(activity, "APPROVE"); reload(); } catch (caught) { setError(String(caught)); } };
  return <><Notice error={error} /><section className="panel extension-form"><p className="platform-kicker">Structured extension activity</p><h3>Action plan</h3><div className="form-grid"><label>Activity type<select><option>field_visit</option><option>demo</option><option>group_session</option><option>individual_follow_up</option></select></label><label>Due date<input type="date" value={due} onChange={(event) => setDue(event.target.value)} /></label><label className="wide">Objective<textarea value={objective} onChange={(event) => setObjective(event.target.value)} /></label></div><button className="primary-button" type="button" disabled={item.status !== "IN_VERIFICATION" || !item.verifications.some((value) => value.status === "COMPLETED")} onClick={() => void create()}>Submit plan for supervisor approval</button></section><section className="panel extension-record-list"><h3>Case activities</h3>{item.activities.map((activity) => <article key={activity.id}><div><Status value={activity.status} /><strong>{human(activity.activity_type)}</strong></div><p>{activity.objective}</p><small>Due {activity.due_date} · {activity.steps.length} steps · participants {activity.participant_count}</small>{capabilities.effective_permissions.includes("extension.activity.approve") && activity.status === "PENDING_APPROVAL" && <button className="secondary-button" type="button" onClick={() => void approve(activity)}>Approve with separation check</button>}</article>)}</section></>;
}

function FollowUpView({ item, reload }: { item: ExtensionCaseDetail; reload: () => void }) {
  const [due, setDue] = useState("2026-09-20");
  const [objective, setObjective] = useState("Record a second structured observation and remaining evidence gaps.");
  const [outcome, setOutcome] = useState("Demonstration follow-up completed with structured evidence.");
  const [error, setError] = useState<string | null>(null);
  const approved = item.activities.find((value) => value.status === "APPROVED");
  const create = async () => { try { await createExtensionFollowUp(item.id, { activity_plan_id: approved?.id ?? null, due_date: due, objective }); reload(); } catch (caught) { setError(String(caught)); } };
  const complete = async (followUp: ExtensionCaseDetail["follow_ups"][number]) => { try { await completeExtensionFollowUp(followUp, outcome); reload(); } catch (caught) { setError(String(caught)); } };
  return <><Notice error={error} /><section className="panel extension-form"><p className="platform-kicker">Dated accountability</p><h3>Follow-up</h3><div className="form-grid"><label>Due date<input type="date" value={due} onChange={(event) => setDue(event.target.value)} /></label><label className="wide">Objective<textarea value={objective} onChange={(event) => setObjective(event.target.value)} /></label></div><button className="primary-button" type="button" disabled={item.status !== "ACTION_PLANNED" || !approved} onClick={() => void create()}>Schedule follow-up</button></section><section className="panel extension-record-list"><h3>Follow-up records</h3>{item.follow_ups.map((followUp) => <article key={followUp.id}><div><Status value={followUp.status} /><strong>{followUp.due_date}</strong></div><p>{followUp.objective}</p>{followUp.overdue && <strong className="overdue-label">Overdue</strong>}{followUp.status === "OPEN" && <><label>Outcome<input value={outcome} onChange={(event) => setOutcome(event.target.value)} /></label><button className="secondary-button" type="button" onClick={() => void complete(followUp)}>Complete with outcome</button></>}</article>)}</section></>;
}

function ActivityView({ item }: { item: ExtensionCaseDetail }) {
  return <section className="panel extension-record-list"><p className="platform-kicker">Case-linked evidence</p><h3>Activity log</h3>{item.activities.map((activity) => <article key={activity.id}><div><Status value={activity.status} /><strong>{human(activity.activity_type)}</strong></div><p>{activity.objective}</p><ol>{activity.steps.map((step) => <li key={step.id}>{step.description} · {human(step.status)}</li>)}</ol><small>Responsible officer {activity.responsible_officer_id.slice(0, 8)} · due {activity.due_date}</small></article>)}</section>;
}

function CaseDetailPage() {
  const { caseId = "", view = "summary" } = useParams();
  const [item, setItem] = useState<ExtensionCaseDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => { void getExtensionCase(caseId).then(setItem).catch((caught) => setError(String(caught))); }, [caseId]);
  useEffect(load, [load]);
  if (!item) return error ? <Notice error={error} /> : <Loading />;
  const content = view === "observations" ? <ObservationsView item={item} reload={load} /> : view === "assessment" ? <AssessmentView item={item} reload={load} /> : view === "verification" ? <VerificationView item={item} reload={load} /> : view === "action" ? <ActionView item={item} reload={load} /> : view === "follow-up" ? <FollowUpView item={item} reload={load} /> : view === "activity" ? <ActivityView item={item} /> : <CaseSummaryView item={item} reload={load} />;
  return <><section className="extension-case-hero"><div><p className="platform-kicker">{item.case_number} · DEMONSTRATION</p><h2>{item.title}</h2><p>{item.crop} · {item.growth_stage} · {item.location_label}</p></div><div><Status value={item.status} /><span className={`extension-priority ${item.priority.toLowerCase()}`}>{item.priority}</span></div></section><CaseNav item={item} />{content}</>;
}

function MapPage() {
  const [data, setData] = useState<Awaited<ReturnType<typeof getExtensionMap>> | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { void getExtensionMap().then(setData).catch((caught) => setError(String(caught))); }, []);
  if (!data) return error ? <Notice error={error} /> : <Loading />;
  return <section className="panel extension-map-panel"><p className="platform-kicker">Approximate case context</p><h2>Demonstration case map</h2><p>No exact farm coordinates or personal identities are displayed.</p><ExtensionMap data={data} /></section>;
}

function KnowledgePage() {
  const [items, setItems] = useState<ExtensionKnowledge[] | null>(null);
  const [warning, setWarning] = useState("");
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { void getExtensionKnowledge().then((response) => { setItems(response.items); setWarning(response.warning); }).catch((caught) => setError(String(caught))); }, []);
  if (!items) return error ? <Notice error={error} /> : <Loading />;
  return <><section className="extension-page-heading"><div><p className="platform-kicker">Versioned content workflow</p><h2>Knowledge templates</h2><p>{warning}</p></div></section><div className="extension-knowledge-grid">{items.map((item) => { const current = item.versions.find((value) => value.id === item.current_version_id) ?? item.versions[0]; return <article className="panel" key={item.id}><header><Status value={current?.status ?? item.status} /><span>v{current?.version_number ?? "—"}</span></header><h3>{item.title}</h3><p>{current?.content.purpose}</p><ul>{current?.content.checklist?.map((entry) => <li key={entry}>{entry}</li>)}</ul><small>{current?.source_summary}</small><footer>DEMONSTRATION · NO ENDORSEMENT CLAIM</footer></article>; })}</div></>;
}

function ActivitiesPage() {
  const { capabilities } = usePlatform();
  const [items, setItems] = useState<ExtensionActivity[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => { void getExtensionActivities().then((response) => setItems(response.items)).catch((caught) => setError(String(caught))); }, []);
  useEffect(load, [load]);
  const approve = async (item: ExtensionActivity) => { try { await approveExtensionActivity(item, "APPROVE"); load(); } catch (caught) { setError(String(caught)); } };
  if (!items) return error ? <Notice error={error} /> : <Loading />;
  return <><Notice error={error} /><section className="extension-page-heading"><div><p className="platform-kicker">Activities without participant identity lists</p><h2>Extension activities</h2><p>Field visits, demonstrations, group sessions and individual follow-ups remain linked to case evidence.</p></div></section><div className="extension-case-grid">{items.map((item) => <article className="extension-case-card" key={item.id}><header><Status value={item.status} /><span>{item.due_date}</span></header><h3>{human(item.activity_type)}</h3><p>{item.objective}</p><dl><div><dt>Participants</dt><dd>{item.participant_count}</dd></div><div><dt>Steps</dt><dd>{item.steps.length}</dd></div></dl>{capabilities.effective_permissions.includes("extension.activity.approve") && item.status === "PENDING_APPROVAL" && <button className="secondary-button" type="button" onClick={() => void approve(item)}>Approve plan</button>}</article>)}</div></>;
}

function SupervisionPage() {
  const [data, setData] = useState<ExtensionSupervision | null>(null);
  const [officers, setOfficers] = useState<DevPersona[]>([]);
  const [selection, setSelection] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => { void Promise.all([getExtensionSupervision(), getDevPersonas()]).then(([summary, personas]) => { setData(summary); setOfficers(personas.items.filter((value) => value.external_subject.startsWith("dev-extension-officer"))); }).catch((caught) => setError(String(caught))); }, []);
  useEffect(load, [load]);
  const assign = async (item: ExtensionCaseSummary) => { const officer = selection[item.id] ?? officers[0]?.id; if (!officer) return; try { await assignExtensionCase(item, officer, item.priority); load(); } catch (caught) { setError(String(caught)); } };
  if (!data) return error ? <Notice error={error} /> : <Loading />;
  return <><Notice error={error} /><section className="extension-page-heading"><div><p className="platform-kicker">Workspace supervision</p><h2>Team workload and exceptions</h2><p>Assignments and priority changes require a reason and are audited.</p></div><Link to={data.case_map_path}>Open case map →</Link></section><div className="extension-supervision-grid"><section className="panel"><h3>Team workload</h3>{data.team_workload.map((value) => <div className="workload-row" key={value.officer_id}><span>{value.display_name}</span><strong>{value.active_cases} active cases</strong></div>)}</section><section className="panel"><h3>Overdue follow-ups</h3>{data.overdue_follow_ups.map((value) => <Link to={`${base}/cases/${value.case_id}/follow-up`} key={value.id}>{value.due_date} · {value.objective}</Link>)}</section><section className="panel"><h3>Pending activity approvals</h3>{data.pending_activity_approvals.map((value) => <Link to={`${base}/cases/${value.case_id}/action`} key={value.id}>{human(value.activity_type)} · due {value.due_date}</Link>)}</section></div><section className="panel extension-record-list"><h3>Unassigned cases</h3>{data.unassigned_cases.map((item) => <article key={item.id}><div><Status value={item.status} /><strong>{item.case_number} · {item.title}</strong></div><div className="extension-assign"><select value={selection[item.id] ?? officers[0]?.id ?? ""} onChange={(event) => setSelection((current) => ({ ...current, [item.id]: event.target.value }))}>{officers.map((officer) => <option value={officer.id} key={officer.id}>{officer.display_name}</option>)}</select><button className="primary-button" type="button" onClick={() => void assign(item)}>Assign</button></div></article>)}</section></>;
}

function SyncPage() {
  const online = useOnline();
  const [status, setStatus] = useState<Awaited<ReturnType<typeof getExtensionSyncStatus>> | null>(null);
  const draftKeys = useMemo(() => Object.keys(sessionStorage).filter((key) => key.startsWith("extension:draft:")), []);
  useEffect(() => { if (online) void getExtensionSyncStatus().then(setStatus); }, [online]);
  return <section className="panel extension-sync"><div className={`connectivity ${online ? "online" : "offline"}`}><i />{online ? "Online" : "Offline"}</div><p className="platform-kicker">Device-local demonstration queue</p><h2>Offline drafts and sync</h2><div className="result-summary-grid"><article><span>Local drafts</span><strong>{draftKeys.length}</strong></article><article><span>Pending server sync</span><strong>0</strong></article><article><span>Server</span><strong>{status?.server ?? "unreachable"}</strong></article><article><span>Conflict mode</span><strong className="small-authority">limited demo</strong></article></div><h3>Honest limitations</h3><ul>{status?.limitations.map((value) => <li key={value}>{value}</li>) ?? <li>Server status is unavailable while offline.</li>}</ul><button className="secondary-button" type="button" onClick={() => { draftKeys.forEach((key) => sessionStorage.removeItem(key)); window.location.reload(); }}>Clear restricted local drafts</button></section>;
}

export default function ExtensionPage() {
  const online = useOnline();
  const [overview, setOverview] = useState<Awaited<ReturnType<typeof getExtensionOverview>> | null>(null);
  useEffect(() => { void getExtensionOverview().then(setOverview); }, []);
  return <main className="extension-module"><header className="extension-header"><div><p className="platform-kicker">Installed application · non-AI thin workflow</p><h1>Extension Officer Field Support</h1><p>Case → observation → manual assessment → verification → activity → follow-up</p></div><div className={`connectivity ${online ? "online" : "offline"}`}><i />{online ? "Online" : "Offline"}</div></header><div className="extension-boundary"><strong>DEMONSTRATION</strong><span>{overview?.disclaimer ?? "No automated diagnosis or agronomic advice."}</span><small>Scanner: {overview?.scanner_mode?.replaceAll("_", " ")}</small></div><ExtensionNav /><div className="extension-content"><Routes><Route index element={<Navigate replace to="worklist" />} /><Route path="worklist" element={<WorklistPage />} /><Route path="map" element={<MapPage />} /><Route path="cases" element={<CasesPage />} /><Route path="cases/new" element={<NewCasePage />} /><Route path="cases/:caseId/diagnosis" element={<CaseDiagnosisRedirect />} /><Route path="cases/:caseId/:view" element={<CaseDetailPage />} /><Route path="knowledge" element={<KnowledgePage />} /><Route path="activities" element={<ActivitiesPage />} /><Route path="supervision" element={<SupervisionPage />} /><Route path="sync" element={<SyncPage />} /><Route path="*" element={<Navigate replace to="worklist" />} /></Routes></div><nav className="extension-bottom-nav" aria-label="Mobile extension navigation"><Link to={`${base}/worklist`}>⌂<span>Worklist</span></Link><Link to={`${base}/map`}>⌖<span>Map</span></Link><Link to={`${base}/cases/new`}>＋<span>New</span></Link><Link to={`${base}/knowledge`}>▤<span>Knowledge</span></Link><Link to={`${base}/sync`}>↻<span>Sync</span></Link></nav></main>;
}

function CaseDiagnosisRedirect() {
  const { caseId = "" } = useParams();
  return <Navigate replace to={`${base}/cases/${caseId}/assessment`} />;
}
