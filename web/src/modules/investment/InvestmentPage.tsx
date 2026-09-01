import { useCallback, useEffect, useState } from "react";
import { Link, Navigate, Route, Routes, useNavigate, useParams } from "react-router-dom";

import {
  addInvestmentInputMember,
  cancelInvestmentRun,
  cloneInvestmentInputSet,
  createInvestmentComparison,
  createInvestmentInputSet,
  createInvestmentRun,
  getInvestmentAssets,
  getInvestmentAudit,
  getInvestmentDataProfiles,
  getInvestmentInputSet,
  getInvestmentInputSets,
  getInvestmentLineage,
  getInvestmentMethods,
  getInvestmentOverview,
  getInvestmentReadiness,
  getInvestmentResults,
  getInvestmentRun,
  getInvestmentRuns,
  getInvestmentScenarios,
  lockInvestmentInputSet,
  validateInvestmentInputSet,
} from "../../api";
import MapPanel from "../../components/MapPanel";
import { usePlatform } from "../../platform/AppShell";
import type {
  AreaResult,
  Catalog,
  InvestmentInputCandidate,
  InvestmentReadiness,
  NativeAsset,
  NativeComparison,
  NativeInputSet,
  NativeMethod,
  NativeResultResponse,
  NativeRun,
  NativeScenario,
} from "../../types";

const colours = ["#d97706", "#c2410c", "#2563eb", "#7c3aed", "#0891b2", "#475569", "#15803d"];
const terminal = new Set(["succeeded", "succeeded_with_warnings", "failed", "cancelled"]);
const modulePath = "/apps/investment-prioritisation";

function readable(value: string) {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function short(value: string | null | undefined, length = 10) {
  return value ? value.slice(0, length) : "—";
}

function timestamp(value: string | null | undefined) {
  return value ? new Intl.DateTimeFormat("en-GB", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)) : "—";
}

function ErrorNotice({ error, onRetry }: { error: string; onRetry?: () => void }) {
  return <div className="error-banner" role="alert"><strong>Action not completed.</strong> {error}{onRetry && <button type="button" onClick={onRetry}>Retry</button>}</div>;
}

function Loading() {
  return <div className="platform-loading">Loading governed investment records…</div>;
}

function StateBadge({ value }: { value: string }) {
  return <span className={`native-state ${value.toLowerCase().replaceAll("_", "-")}`}>{readable(value)}</span>;
}

function ModuleNav() {
  return (
    <nav className="native-module-nav" aria-label="Investment prioritisation">
      <Link to={`${modulePath}/overview`}>Overview</Link><Link to={`${modulePath}/new-run`}>New run</Link>
      <Link to={`${modulePath}/runs`}>Run history</Link><Link to={`${modulePath}/input-sets`}>Input sets</Link>
      <Link to={`${modulePath}/compare`}>Compare</Link><Link to={`${modulePath}/methods`}>Methods</Link>
      <Link to={`${modulePath}/scenarios`}>Scenarios</Link><Link to={`${modulePath}/readiness`}>Real-data readiness</Link>
    </nav>
  );
}

function useNativeCatalog() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [scenarios, setScenarios] = useState<NativeScenario[]>([]);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    void Promise.all([getInvestmentDataProfiles(), getInvestmentScenarios()]).then(([profiles, scenarioResponse]) => {
      const indicators = Object.fromEntries(profiles.indicators.map((item, index) => [item.code, {
        label: item.title, short_label: item.title,
        description: `${item.direction}; governed ${item.unit} input.`, unit: item.unit,
        colour: colours[index % colours.length],
      }]));
      const scenarioMap = Object.fromEntries(scenarioResponse.items.map((item) => [item.scenario_key, {
        label: item.name, description: item.description, weights: item.parameters.weights,
      }]));
      setScenarios(scenarioResponse.items);
      setCatalog({
        indicators, scenarios: scenarioMap, datasets: [],
        disclaimer: "Synthetic demonstration data — not for operational planning, funding decisions, or agronomic advice.",
        method: {
          name: "Approved native weighted linear combination",
          formula: "score = Σ(normalised weight × indicator × 100) × quality adjustment",
          missing_value_policy: "Missing indicators use the governed neutral value 0.5 and remain visible.",
        },
      });
    }).catch((caught) => setError(caught instanceof Error ? caught.message : "Unable to load method metadata"));
  }, []);
  return { catalog, scenarios, error };
}

function RunTable({ runs }: { runs: NativeRun[] }) {
  if (!runs.length) return <p className="muted">No analysis runs have been created.</p>;
  return (
    <div className="ranking-table-wrap"><table className="ranking-table native-run-table"><thead><tr><th>Run</th><th>Scenario</th><th>Status</th><th>Results</th><th>Requested</th></tr></thead><tbody>
      {runs.map((run) => <tr key={run.id}><td><Link to={`${modulePath}/runs/${run.id}`}>{short(run.id, 8)}</Link>{run.legacy_run_id && <small>legacy #{run.legacy_run_id}</small>}</td><td>{run.scenario.name}<small>{run.scenario.version_label}</small></td><td><StateBadge value={run.status} /></td><td>{run.result_count || "—"}</td><td>{timestamp(run.requested_at)}</td></tr>)}
    </tbody></table></div>
  );
}

function OverviewPage() {
  const [overview, setOverview] = useState<Record<string, any> | null>(null);
  const [readiness, setReadiness] = useState<InvestmentReadiness | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { void Promise.all([getInvestmentOverview(), getInvestmentReadiness()]).then(([summary, pilot]) => { setOverview(summary); setReadiness(pilot); }).catch((caught) => setError(String(caught))); }, []);
  if (error) return <ErrorNotice error={error} />;
  if (!overview) return <Loading />;
  const counts = overview.counts as Record<string, number>;
  const recent = overview.recent_runs as NativeRun[];
  return (
    <>
      <section className="native-hero panel"><div><p className="section-kicker">Installed application · governed analysis</p><h2>Prioritise investments from exact, approved inputs.</h2><p>Runs are explicit, asynchronous and reproducible. Opening this page never starts an analysis. Real source samples remain separate from the deterministic synthetic demonstration.</p></div><div className="native-hero-actions"><Link className="primary-button native-link-button" to={`${modulePath}/new-run`}>Run synthetic demonstration</Link><Link className="secondary-button native-link-button" to={`${modulePath}/readiness`}>Review real-data gaps</Link></div></section>
      <div className="result-summary-grid native-summary"><article><span>Locked input sets</span><strong>{counts.locked_input_sets}</strong></article><article><span>Approved scenarios</span><strong>{counts.approved_scenarios}</strong></article><article><span>Recorded runs</span><strong>{counts.runs}</strong></article><article><span>Write authority</span><strong className="small-authority">investment.*</strong></article></div>
      {readiness && <section className="panel native-readiness-callout"><div><p className="section-kicker">Real-data pilot readiness</p><h2>{readiness.ready_to_run ? "Ready" : "Not ready"}</h2><p>{readiness.available_indicator_roles.length} of 7 required indicator roles available. Exact source lineage is visible, but missing roles and method mapping prevent a real run.</p></div><div><StateBadge value={readiness.readiness_state} /><Link to={`${modulePath}/readiness`}>Open gap assessment →</Link></div></section>}
      <section className="panel native-list-card"><div className="section-title-row"><div><p className="section-kicker">Recent evidence</p><h2>Latest analysis runs</h2></div><Link to={`${modulePath}/runs`}>View all</Link></div><RunTable runs={recent} /></section>
      <section className="panel native-evidence"><p className="section-kicker">Lineage boundary</p><h2>Every result binds exact evidence</h2><p>Input representations, method and scenario checksums, execution metadata, output versions and audit events remain linked. The approved method and scenarios are illustrative and are not endorsed for operational investment or funding decisions.</p></section>
    </>
  );
}

function ReadinessPage() {
  const [readiness, setReadiness] = useState<InvestmentReadiness | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { void getInvestmentReadiness().then(setReadiness).catch((caught) => setError(String(caught))); }, []);
  if (error) return <ErrorNotice error={error} />;
  if (!readiness) return <Loading />;
  return <>
    <section className="panel native-readiness-header"><div><p className="section-kicker">Read-only real-source assessment</p><h2>HIH Cambodia pilot readiness</h2><p>{readiness.warning}</p></div><div><StateBadge value={readiness.readiness_state} /><strong>Ready to run: No</strong><small>No bypass or run action is available.</small></div></section>
    <section className="readiness-role-grid">{readiness.roles.map((role) => <article className={`panel readiness-role ${role.state.toLowerCase().replaceAll("_", "-")}`} key={role.role}><div><StateBadge value={role.state} /><code>{role.role}</code></div><h3>{role.label}</h3>{role.candidate ? <><Link to={`/data/datasets/${role.candidate.dataset.id}`}>{role.candidate.dataset.title}</Link><p>Exact version {role.candidate.version.version_label} · {role.candidate.version.profile_key}</p><small>{String(role.candidate.representation.statistics.record_count ?? "—")} records · join {role.candidate.suggested_mapping.join_key}</small></> : <p>{role.reason_codes.map(readable).join(" · ")}</p>}</article>)}</section>
    <section className="readiness-evidence-grid">
      <article className="panel native-list-card"><p className="section-kicker">Declared record coverage</p><h2>{readiness.record_coverage.comparable_declared_records} comparable records</h2><dl className="native-evidence-list"><div><dt>Boundary</dt><dd>{readiness.record_coverage.boundary_records}</dd></div><div><dt>Poverty</dt><dd>{readiness.record_coverage.poverty_records}</dd></div><div><dt>Join state</dt><dd>{readable(String(readiness.spatial_compatibility.state))}</dd></div><div><dt>Method</dt><dd>{readable(readiness.method_readiness.state)}</dd></div></dl><p className="muted compact">{readiness.record_coverage.note}</p></article>
      <article className="panel native-list-card"><p className="section-kicker">Blocking reason codes</p><h2>Why a real run is unavailable</h2><ul className="reason-code-list">{readiness.reason_codes.map((code) => <li key={code}><code>{code}</code></li>)}</ul>{readiness.collection && <Link className="secondary-button native-link-button" to={readiness.collection.path}>Open {readiness.collection.title}</Link>}</article>
    </section>
    {readiness.profile_issues.length > 0 && <section className="panel native-list-card"><p className="section-kicker">Preserved history</p><h2>Historical profile mismatches</h2><div className="ranking-table-wrap"><table className="ranking-table"><thead><tr><th>Dataset</th><th>Version</th><th>Historic profile</th><th>Effect</th></tr></thead><tbody>{readiness.profile_issues.map((issue) => <tr key={issue.version_id}><td><Link to={`/data/datasets/${issue.dataset_id}`}>{issue.dataset_title}</Link></td><td>{issue.version_label}</td><td><code>{issue.profile_key}</code></td><td>{issue.effect}</td></tr>)}</tbody></table></div></section>}
  </>;
}

function RunsPage() {
  const [runs, setRuns] = useState<NativeRun[] | null>(null);
  const [status, setStatus] = useState("");
  const [owner, setOwner] = useState("");
  const [scenario, setScenario] = useState("");
  const [method, setMethod] = useState("");
  const [inputSet, setInputSet] = useState("");
  const [since, setSince] = useState("");
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { void getInvestmentRuns().then((response) => setRuns(response.items)).catch((caught) => setError(String(caught))); }, []);
  if (error) return <ErrorNotice error={error} />;
  if (!runs) return <Loading />;
  const visible = runs.filter((run) => (!status || run.status === status) && (!owner || run.requested_by === owner) && (!scenario || run.scenario.id === scenario) && (!method || run.method_version.id === method) && (!inputSet || run.input_set.id === inputSet) && (!since || run.requested_at.slice(0, 10) >= since));
  const unique = <T,>(values: T[]) => [...new Set(values)];
  return <section className="panel native-list-card"><div className="section-title-row"><div><p className="section-kicker">Durable analysis history</p><h2>Runs</h2><p className="muted compact">Filtering reads immutable records only and never starts analysis.</p></div></div><div className="native-run-filters"><label>Status<select value={status} onChange={(event) => setStatus(event.target.value)}><option value="">All</option>{["queued", "running", "succeeded", "succeeded_with_warnings", "failed", "cancelled"].map((item) => <option key={item}>{item}</option>)}</select></label><label>Owner<select value={owner} onChange={(event) => setOwner(event.target.value)}><option value="">All</option>{unique(runs.map((run) => run.requested_by)).map((item) => <option key={item} value={item}>{short(item, 12)}</option>)}</select></label><label>Method<select value={method} onChange={(event) => setMethod(event.target.value)}><option value="">All</option>{unique(runs.map((run) => run.method_version.id)).map((id) => <option key={id} value={id}>{runs.find((run) => run.method_version.id === id)?.method_version.version_label}</option>)}</select></label><label>Scenario<select value={scenario} onChange={(event) => setScenario(event.target.value)}><option value="">All</option>{unique(runs.map((run) => run.scenario.id)).map((id) => <option key={id} value={id}>{runs.find((run) => run.scenario.id === id)?.scenario.name}</option>)}</select></label><label>Input set<select value={inputSet} onChange={(event) => setInputSet(event.target.value)}><option value="">All</option>{unique(runs.map((run) => run.input_set.id)).map((id) => <option key={id} value={id}>{runs.find((run) => run.input_set.id === id)?.input_set.label}</option>)}</select></label><label>Since<input type="date" value={since} onChange={(event) => setSince(event.target.value)} /></label></div><RunTable runs={visible} /></section>;
}

function InputSetsPage() {
  const { capabilities } = usePlatform();
  const canCreate = capabilities.effective_permissions.includes("investment.input_set.create");
  const [items, setItems] = useState<NativeInputSet[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { void getInvestmentInputSets().then((response) => setItems(response.items)).catch((caught) => setError(String(caught))); }, []);
  if (!items) return error ? <ErrorNotice error={error} /> : <Loading />;
  return (
    <>{error && <ErrorNotice error={error} />}<section className="panel native-list-card"><div className="section-title-row"><div><p className="section-kicker">Frozen source selection</p><h2>Analysis input sets</h2></div>{canCreate && <Link className="primary-button native-link-button" to={`${modulePath}/input-sets/new`}>Create input set</Link>}</div><div className="native-card-grid">{items.map((item) => <Link className="native-record-card" to={`${modulePath}/input-sets/${item.id}`} key={item.id}><div><StateBadge value={item.status} /><span>{item.evidence_mode.replaceAll("_", " ")}</span></div><h3>{item.label}</h3><p>{item.members.length} exact representations · {item.strictest_classification}</p><code>{short(item.checksum, 16)}</code></Link>)}</div></section></>
  );
}

function InputSetNewPage() {
  const navigate = useNavigate();
  const [name, setName] = useState("new-analysis-inputs");
  const [label, setLabel] = useState("New analysis inputs");
  const [mode, setMode] = useState<"LEGACY_BUNDLE" | "SEPARATE_LAYERS">("SEPARATE_LAYERS");
  const [error, setError] = useState<string | null>(null);
  const create = async () => {
    try {
      const item = await createInvestmentInputSet({ name, label, profile_mode: mode, study_area_ref: {}, run_mode_compatibility: ["FORMAL"] });
      navigate(`${modulePath}/input-sets/${item.id}`);
    } catch (caught) { setError(String(caught)); }
  };
  return <>{error && <ErrorNotice error={error} />}<section className="panel native-list-card"><p className="section-kicker">Input set builder · step 1</p><h2>Create an editable draft</h2><p className="muted compact">A draft has no run authority. Add exact published representations, map every required role, validate, then lock.</p><div className="native-form-grid"><label>Machine name<input value={name} onChange={(event) => setName(event.target.value)} /></label><label>Display label<input value={label} onChange={(event) => setLabel(event.target.value)} /></label><label>Profile mode<select value={mode} onChange={(event) => setMode(event.target.value as typeof mode)}><option value="SEPARATE_LAYERS">Separate governed layers</option><option value="LEGACY_BUNDLE">Legacy compatibility bundle</option></select></label><button className="primary-button" type="button" onClick={() => void create()}>Create draft and map inputs</button></div></section></>;
}

function InputSetDetailPage() {
  const { inputSetId = "" } = useParams();
  const navigate = useNavigate();
  const { capabilities } = usePlatform();
  const [item, setItem] = useState<NativeInputSet | null>(null);
  const [candidates, setCandidates] = useState<InvestmentInputCandidate[]>([]);
  const [candidateId, setCandidateId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => { void Promise.all([getInvestmentInputSet(inputSetId), getInvestmentDataProfiles()]).then(([input, profiles]) => { setItem(input); setCandidates(profiles.candidates); setCandidateId((current) => current || profiles.candidates[0]?.representation.id || ""); }).catch((caught) => setError(String(caught))); }, [inputSetId]);
  useEffect(load, [load]);
  const validate = async () => { try { setItem((await validateInvestmentInputSet(inputSetId)).input_set); } catch (caught) { setError(String(caught)); } };
  const lock = async () => { if (!item) return; try { setItem(await lockInvestmentInputSet(item)); } catch (caught) { setError(String(caught)); } };
  const add = async () => { const candidate = candidates.find((value) => value.representation.id === candidateId); if (!item || !candidate) return; try { setItem(await addInvestmentInputMember(item.id, candidate, item.members.length)); } catch (caught) { setError(String(caught)); } };
  const clone = async () => { if (!item) return; try { const next = await cloneInvestmentInputSet(item); navigate(`${modulePath}/input-sets/${next.id}`); } catch (caught) { setError(String(caught)); } };
  if (!item) return error ? <ErrorNotice error={error} /> : <Loading />;
  const selectable = candidates.filter((candidate) => !item.members.some((member) => member.representation_id === candidate.representation.id));
  const errors = item.readiness?.errors ?? [];
  return <>{error && <ErrorNotice error={error} />}<section className="panel native-list-card"><div className="section-title-row"><div><p className="section-kicker">Exact-version input contract</p><h2>{item.label}</h2><p className="muted compact">{item.name} · {item.profile_mode.replaceAll("_", " ")} · {item.evidence_mode.replaceAll("_", " ")}</p></div><StateBadge value={item.status} /></div><dl className="native-evidence-list"><div><dt>Canonical checksum</dt><dd><code>{item.checksum ?? "Not locked"}</code></dd></div><div><dt>Classification</dt><dd>{item.strictest_classification}</dd></div><div><dt>Readiness</dt><dd>{item.readiness?.ready ? "Ready" : "Not ready"}</dd></div><div><dt>Row version</dt><dd>{item.row_version}</dd></div></dl>
    {item.status === "LOCKED" || item.status === "RETIRED" ? <div className="method-note inline"><span>i</span><p>This checksum and every exact member are immutable. Clone to make a governed revision.</p><button className="secondary-button" type="button" onClick={() => void clone()}>Clone editable set</button></div> : <section className="input-candidate-builder"><div><p className="section-kicker">Exact published candidates</p><h3>Add boundary or indicator representation</h3></div>{selectable.length ? <div className="native-form-grid"><label>Candidate<select value={candidateId} onChange={(event) => setCandidateId(event.target.value)}>{selectable.map((candidate) => <option value={candidate.representation.id} key={candidate.representation.id}>{candidate.evidence_type.replaceAll("_", " ")} · {candidate.dataset.title} · {candidate.suggested_mapping.indicator_code ?? "boundary"}</option>)}</select><small>Role, representation, join key, value field, unit and direction remain explicit below.</small></label><button className="secondary-button" type="button" onClick={() => void add()}>Add exact version</button></div> : <p className="muted">No additional accessible candidates are available.</p>}</section>}
    <h3>Mapped members</h3><div className="ranking-table-wrap"><table className="ranking-table"><thead><tr><th>Order</th><th>Role</th><th>Indicator</th><th>Dataset version</th><th>Representation</th><th>Join key</th></tr></thead><tbody>{item.members.map((member) => <tr key={member.id}><td>{member.ordinal}</td><td>{member.input_role}</td><td>{member.indicator_code ?? "—"}</td><td><code>{short(member.dataset_version_id, 14)}</code></td><td><code>{short(member.representation_id, 14)}</code></td><td><code>{(member as typeof member & { join_key?: string }).join_key ?? "area_code"}</code></td></tr>)}</tbody></table></div>
    {errors.length > 0 && <div className="input-readiness-errors"><strong>Blocking readiness checks</strong><ul>{errors.map((issue) => <li key={`${issue.code}:${issue.message}`}><code>{issue.code}</code> {issue.message}</li>)}</ul></div>}
    {item.status !== "LOCKED" && item.status !== "RETIRED" && <div className="analysis-actions"><button className="secondary-button" type="button" onClick={() => void validate()}>Run readiness checks</button>{capabilities.effective_permissions.includes("investment.input_set.lock") && <button className="primary-button" type="button" disabled={!item.readiness?.ready} onClick={() => void lock()}>Lock immutable set</button>}</div>}</section></>;
}

function MethodsPage() {
  const [methods, setMethods] = useState<NativeMethod[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { void getInvestmentMethods().then((response) => setMethods(response.items)).catch((caught) => setError(String(caught))); }, []);
  if (!methods) return error ? <ErrorNotice error={error} /> : <Loading />;
  return <section className="panel native-list-card"><p className="section-kicker">Governed methodology</p><h2>Methods and immutable versions</h2>{methods.map((method) => <article className="native-governance-card" key={method.id}><h3>{method.name}</h3><p>{method.description}</p>{method.versions.map((version) => <Link className="native-version-row" to={`${modulePath}/methods/${version.id}`} key={version.id}><StateBadge value={version.state} /><strong>{version.version_label}</strong><code>{short(version.checksum, 16)}</code><span>{version.implementation_key}</span><small>{version.code_ref}</small></Link>)}</article>)}</section>;
}

function MethodVersionDetailPage() {
  const { methodVersionId = "" } = useParams();
  const [version, setVersion] = useState<NativeMethod["versions"][number] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { void getInvestmentMethods().then((response) => { const match = response.items.flatMap((method) => method.versions).find((item) => item.id === methodVersionId); if (!match) throw new Error("Method version was not found."); setVersion(match); }).catch((caught) => setError(String(caught))); }, [methodVersionId]);
  if (error) return <ErrorNotice error={error} />;
  if (!version) return <Loading />;
  const required = (version.specification.required_indicators as Array<Record<string, unknown>> | undefined) ?? [];
  return <section className="panel native-list-card"><div className="section-title-row"><div><p className="section-kicker">Versioned method definition</p><h2>{version.method_name} · {version.version_label}</h2><p className="muted compact">{version.implementation_key} · {version.code_ref}</p></div><StateBadge value={version.state} /></div><dl className="native-evidence-list"><div><dt>Checksum</dt><dd><code>{version.checksum}</code></dd></div><div><dt>Creator / approver</dt><dd>Recorded in immutable audit workflow</dd></div><div><dt>Validation evidence</dt><dd>{Object.keys(version.validation_evidence).length ? "Attached" : "Not attached"}</dd></div><div><dt>Allowed overrides</dt><dd>{((version.specification.allowed_overrides as string[] | undefined) ?? []).join(", ") || "None"}</dd></div></dl><h3>Required indicators</h3><div className="native-card-grid">{required.map((item) => <article className="native-record-card" key={String(item.code)}><div><StateBadge value={item.required ? "required" : "optional"} /><span>{String(item.direction ?? "—")}</span></div><h3>{String(item.code)}</h3><p>{String(item.normalisation ?? "No normalisation declared")}</p></article>)}</div><div className="method-note inline"><span>i</span><p>{version.disclaimer}</p></div></section>;
}

function ScenariosPage() {
  const { catalog, scenarios, error } = useNativeCatalog();
  if (error) return <ErrorNotice error={error} />;
  if (!catalog) return <Loading />;
  return <section className="panel native-list-card"><p className="section-kicker">Approved policy lenses</p><h2>Versioned scenarios</h2><div className="native-card-grid">{scenarios.map((scenario) => <article className="native-record-card" key={scenario.id}><div><StateBadge value={scenario.state} /><span>v{scenario.version_label}</span></div><h3>{scenario.name}</h3><p>{scenario.description}</p><div className="scenario-weight-list">{Object.entries(scenario.parameters.weights).map(([code, weight]) => <span key={code}><i style={{ background: catalog.indicators[code]?.colour }} />{catalog.indicators[code]?.short_label}<b>{Math.round(weight * 100)}%</b></span>)}</div><code>{short(scenario.checksum, 16)}</code></article>)}</div></section>;
}

function NewRunPage() {
  const navigate = useNavigate();
  const { catalog, scenarios, error: catalogError } = useNativeCatalog();
  const [inputs, setInputs] = useState<NativeInputSet[]>([]);
  const [methods, setMethods] = useState<NativeMethod[]>([]);
  const [inputId, setInputId] = useState("");
  const [scenarioId, setScenarioId] = useState("");
  const [weights, setWeights] = useState<Record<string, number>>({});
  const [minimum, setMinimum] = useState(750);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { void Promise.all([getInvestmentInputSets(), getInvestmentMethods()]).then(([inputResponse, methodResponse]) => { const locked = inputResponse.items.filter((item) => item.status === "LOCKED"); setInputs(locked); setMethods(methodResponse.items); setInputId(locked[0]?.id ?? ""); }).catch((caught) => setError(String(caught))); }, []);
  useEffect(() => { if (!scenarios.length || scenarioId) return; const first = scenarios.find((item) => item.state === "APPROVED"); if (first) { setScenarioId(first.id); setWeights(first.parameters.weights); setMinimum(first.parameters.min_rice_area_ha); } }, [scenarios, scenarioId]);
  const selectedScenario = scenarios.find((item) => item.id === scenarioId);
  const selectedInput = inputs.find((item) => item.id === inputId);
  const submit = async () => { if (!selectedScenario || !inputId) return; setSubmitting(true); setError(null); try { const run = await createInvestmentRun({ input_set_id: inputId, method_version_id: selectedScenario.method_version_id, scenario_id: scenarioId, run_mode: "FORMAL", overrides: { weights, min_rice_area_ha: minimum } }); navigate(`${modulePath}/runs/${run.id}`); } catch (caught) { setError(caught instanceof Error ? caught.message : String(caught)); setSubmitting(false); } };
  if (!catalog || !inputs.length || !methods.length) return (error || catalogError) ? <ErrorNotice error={error ?? catalogError ?? "Unable to load"} /> : <Loading />;
  return <>{error && <ErrorNotice error={error} />}<section className="panel native-list-card"><div className="section-title-row"><div><p className="section-kicker">Explicit asynchronous command</p><h2>Run the synthetic demonstration</h2><p className="muted compact">Submitting freezes exact input, method, scenario, parameters, code/build metadata and a durable job. Real pilot samples are incomplete and do not appear as lockable choices.</p></div></div><ol className="native-run-wizard"><li className="complete"><span>1</span>Input set</li><li className="complete"><span>2</span>Method</li><li className="complete"><span>3</span>Scenario</li><li className="complete"><span>4</span>Parameters</li><li className="complete"><span>5</span>Readiness</li><li><span>6</span>Submit</li></ol><div className="native-form-grid run-form"><label>Locked input set<select value={inputId} onChange={(event) => setInputId(event.target.value)}>{inputs.map((item) => <option value={item.id} key={item.id}>{item.evidence_mode.replaceAll("_", " ")} · {item.label}</option>)}</select><small>Checksum {short(selectedInput?.checksum, 14)} · readiness {selectedInput?.readiness?.ready ? "passed" : "unavailable"}</small></label><label>Approved scenario<select value={scenarioId} onChange={(event) => { const next = scenarios.find((item) => item.id === event.target.value); setScenarioId(event.target.value); if (next) { setWeights(next.parameters.weights); setMinimum(next.parameters.min_rice_area_ha); } }}>{scenarios.filter((item) => item.state === "APPROVED").map((item) => <option value={item.id} key={item.id}>{item.name} · v{item.version_label}</option>)}</select><small>{selectedScenario?.description}</small></label><label>Minimum rice area<strong>{minimum.toLocaleString()} ha</strong><input type="range" min="0" max="3000" step="50" value={minimum} onChange={(event) => setMinimum(Number(event.target.value))} /></label></div><div className="native-weight-grid">{Object.keys(catalog.indicators).map((code) => <label key={code}><span><i style={{ background: catalog.indicators[code].colour }} />{catalog.indicators[code].short_label}</span><input type="number" min="0" max="1" step="0.01" value={weights[code] ?? 0} onChange={(event) => setWeights((current) => ({ ...current, [code]: Number(event.target.value) }))} /></label>)}</div><div className="analysis-actions"><div className="method-note inline"><span>i</span><p>{selectedInput?.evidence_mode === "SYNTHETIC_DEMO" ? "Deterministic synthetic data and an illustrative approved-in-demo method; no operational or funding use." : "Evidence classification is shown explicitly. All backend readiness gates remain enforced."}</p></div><button className="primary-button" type="button" disabled={submitting || !selectedInput?.readiness?.ready} onClick={() => void submit()}>{submitting ? "Queueing durable job…" : "Submit durable run"}</button></div></section></>;
}

function ComparePage() {
  const [runs, setRuns] = useState<NativeRun[] | null>(null);
  const [left, setLeft] = useState(""); const [right, setRight] = useState("");
  const [comparison, setComparison] = useState<NativeComparison | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { void getInvestmentRuns().then((response) => { const complete = response.items.filter((item) => item.status.startsWith("succeeded")); setRuns(complete); setLeft(complete[0]?.id ?? ""); setRight(complete[1]?.id ?? ""); }).catch((caught) => setError(String(caught))); }, []);
  const compare = async () => { try { setComparison(await createInvestmentComparison(left, right)); } catch (caught) { setError(String(caught)); } };
  if (!runs) return error ? <ErrorNotice error={error} /> : <Loading />;
  return <>{error && <ErrorNotice error={error} />}<section className="panel native-list-card"><p className="section-kicker">Explicit read-only comparison</p><h2>Compare two completed runs</h2><p className="muted compact">This action computes differences from immutable results and never creates analysis runs.</p><div className="native-form-grid"><label>Left run<select value={left} onChange={(event) => setLeft(event.target.value)}>{runs.map((run) => <option value={run.id} key={run.id}>{short(run.id, 8)} · {run.scenario.name}</option>)}</select></label><label>Right run<select value={right} onChange={(event) => setRight(event.target.value)}>{runs.map((run) => <option value={run.id} key={run.id}>{short(run.id, 8)} · {run.scenario.name}</option>)}</select></label><button className="primary-button" type="button" disabled={!left || !right || left === right} onClick={() => void compare()}>Create comparison evidence</button></div>{comparison && <div className="comparison-evidence"><div><span>Areas</span><strong>{comparison.summary.area_count}</strong></div><div><span>Changed bands</span><strong>{comparison.summary.changed_bands}</strong></div><div><span>Eligibility changes</span><strong>{comparison.summary.eligibility_changes}</strong></div><div><span>Top-N overlap</span><strong>{comparison.summary.top_n_overlap}</strong></div><p>Checksum <code>{comparison.checksum}</code></p></div>}</section></>;
}

function RunDetailPage() {
  const { runId = "" } = useParams();
  const { capabilities } = usePlatform();
  const { catalog, error: catalogError } = useNativeCatalog();
  const [run, setRun] = useState<NativeRun | null>(null);
  const [results, setResults] = useState<NativeResultResponse | null>(null);
  const [lineage, setLineage] = useState<Record<string, unknown> | null>(null);
  const [audit, setAudit] = useState<Array<Record<string, unknown>>>([]);
  const [assets, setAssets] = useState<NativeAsset[]>([]);
  const [selected, setSelected] = useState<AreaResult | null>(null);
  const [metric, setMetric] = useState("priority");
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => { try { const next = await getInvestmentRun(runId); setRun(next); if (next.status.startsWith("succeeded")) { const [resultResponse, lineageResponse, auditResponse] = await Promise.all([getInvestmentResults(runId), getInvestmentLineage(runId), getInvestmentAudit(runId)]); setResults(resultResponse); setSelected((current) => current ?? resultResponse.items.find((item) => item.rank === 1) ?? resultResponse.items[0] ?? null); setLineage(lineageResponse); setAudit(auditResponse.items); } } catch (caught) { setError(caught instanceof Error ? caught.message : String(caught)); } }, [runId]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => { if (!run || terminal.has(run.status)) return; const timer = window.setInterval(() => void load(), 1200); return () => window.clearInterval(timer); }, [run, load]);
  const requestAssets = async () => { try { setAssets((await getInvestmentAssets(runId)).items); } catch (caught) { setError(String(caught)); } };
  const cancel = async () => { try { setRun(await cancelInvestmentRun(runId)); } catch (caught) { setError(String(caught)); } };
  if (!run || !catalog) return (error || catalogError) ? <ErrorNotice error={error ?? catalogError ?? "Unable to load"} onRetry={() => void load()} /> : <Loading />;
  const eligible = results?.items.filter((item) => item.eligible) ?? [];
  const average = eligible.length ? eligible.reduce((sum, item) => sum + item.score, 0) / eligible.length : 0;
  return <>{error && <ErrorNotice error={error} />}<section className="panel native-run-header"><div><p className="section-kicker">Immutable analysis run</p><h2>{short(run.id, 18)}</h2><p>{run.scenario.name} · {run.input_set.label}</p></div><div><StateBadge value={run.status} /><strong>{Math.round(run.progress)}%</strong><small>{readable(run.current_step)}</small></div></section>{!terminal.has(run.status) && <section className="panel native-progress"><div><i style={{ width: `${run.progress}%` }} /></div><p>The durable worker is processing this run. This page polls status only; it does not submit work.</p>{capabilities.effective_permissions.includes("investment.run.cancel") && !["register-output", "finalise"].includes(run.current_step) && <button className="secondary-button" type="button" onClick={() => void cancel()}>Request cancellation</button>}</section>}{run.failure && <ErrorNotice error={`${run.failure.message ?? "Analysis failed"} [${run.failure.code ?? "UNKNOWN"}]`} />}
    {results && <><div className="result-summary-grid native-summary"><article><span>Total areas</span><strong>{results.meta.total}</strong></article><article><span>Eligible</span><strong>{eligible.length}</strong></article><article><span>Average score</span><strong>{average.toFixed(2)}</strong></article><article><span>Result checksum</span><strong className="small-authority">{short(run.result_checksum, 10)}</strong></article></div><MapPanel catalog={catalog} geojson={results.geojson} metric={metric} selectedId={selected?.id ?? null} datasetLabel={`Native run ${short(run.id, 8)}`} onMetricChange={setMetric} onSelect={setSelected} />{selected && <section className="panel native-selected"><div><p className="section-kicker">Selected area</p><h3>{selected.name}</h3><p>{selected.province} · {selected.rice_area_ha.toLocaleString()} ha rice</p></div><div><strong>{selected.score.toFixed(2)}</strong><span>Rank {selected.rank ?? "excluded"}</span></div><dl>{Object.entries(selected.components).map(([code, component]) => <div key={code}><dt>{catalog.indicators[code]?.short_label}</dt><dd>{component.contribution.toFixed(2)}</dd></div>)}</dl></section>}<section className="panel native-list-card"><div className="section-title-row"><div><p className="section-kicker">Priority worklist</p><h2>Eligible areas</h2></div><button className="secondary-button" type="button" onClick={() => void requestAssets()}>Request audited downloads</button></div>{assets.length > 0 && <div className="native-downloads">{assets.map((asset) => <a key={asset.id} href={asset.url} target="_blank" rel="noreferrer">{asset.filename}<small>SHA {short(asset.sha256, 12)}</small></a>)}</div>}<div className="ranking-table-wrap"><table className="ranking-table"><thead><tr><th>Rank</th><th>Area</th><th>Province</th><th>Band</th><th>Score</th><th>Completeness</th></tr></thead><tbody>{eligible.map((item) => <tr key={item.id} className={selected?.id === item.id ? "selected" : ""} onClick={() => setSelected(item)}><td>{item.rank}</td><td><strong>{item.name}</strong><small>{item.code}</small></td><td>{item.province}</td><td>{item.priority_band}</td><td>{item.score.toFixed(2)}</td><td>{Math.round(item.data_completeness * 100)}%</td></tr>)}</tbody></table></div></section></>}
    <section className="panel native-evidence"><p className="section-kicker">Reproducibility evidence</p><h2>Frozen snapshots, lineage and audit</h2><dl className="native-evidence-list"><div><dt>Input set checksum</dt><dd><code>{run.checksums?.input_set}</code></dd></div><div><dt>Method checksum</dt><dd><code>{run.checksums?.method}</code></dd></div><div><dt>Scenario checksum</dt><dd><code>{run.checksums?.scenario}</code></dd></div><div><dt>Code ref</dt><dd><code>{run.execution?.code_ref}</code></dd></div><div><dt>Worker task</dt><dd>{run.execution?.worker_task_version}</dd></div><div><dt>Input snapshots</dt><dd>{run.inputs?.length ?? 0}</dd></div><div><dt>Lineage process</dt><dd>{lineage ? "Registered" : "Pending"}</dd></div><div><dt>Audit events</dt><dd>{audit.length}</dd></div></dl></section></>;
}

function InvestmentPage() {
  return (
    <main className="investment-module native-investment-module">
      <header className="legacy-module-header native-module-header"><div><p className="section-kicker">Installed application · native governed workflow</p><h1>Investment Prioritisation</h1><p>Governed exact inputs · approved methods · durable jobs · catalogued outputs</p></div><ModuleNav /></header>
      <Routes><Route index element={<Navigate replace to="overview" />} /><Route path="overview" element={<OverviewPage />} /><Route path="new-run" element={<NewRunPage />} /><Route path="runs" element={<RunsPage />} /><Route path="runs/:runId" element={<RunDetailPage />} /><Route path="input-sets" element={<InputSetsPage />} /><Route path="input-sets/new" element={<InputSetNewPage />} /><Route path="input-sets/:inputSetId" element={<InputSetDetailPage />} /><Route path="compare" element={<ComparePage />} /><Route path="methods" element={<MethodsPage />} /><Route path="methods/:methodVersionId" element={<MethodVersionDetailPage />} /><Route path="scenarios" element={<ScenariosPage />} /><Route path="readiness" element={<ReadinessPage />} /><Route path="*" element={<Navigate replace to="overview" />} /></Routes>
      <footer className="app-footer"><span>Real samples, synthetic evidence and illustrative methods are labelled separately — no operational or funding decisions.</span><span>Native investment.* authority · exact catalog lineage · short-lived downloads</span></footer>
    </main>
  );
}

export default InvestmentPage;
