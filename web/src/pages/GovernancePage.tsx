import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import {
  addGovernanceGroupMember,
  createGovernanceGroup,
  createGovernanceRoleAssignment,
  getGovernanceApplications,
  getGovernanceDataPolicies,
  getGovernanceGroups,
  getGovernanceKnowledgeApprovals,
  getGovernanceMembers,
  getGovernanceQualityProfiles,
  getGovernanceRetention,
  getGovernanceReviews,
  getGovernanceRoles,
  getGovernanceSystemHealth,
  removeGovernanceGroupMember,
} from "../api";
import type {
  GovernanceApplications,
  GovernanceDataPolicies,
  GovernanceGroups,
  GovernanceKnowledgeApprovals,
  GovernanceMembers,
  GovernanceQualityProfiles,
  GovernanceRetention,
  GovernanceReviews,
  GovernanceRoles,
  GovernanceSystemHealth,
} from "../platform/types";

export type GovernanceView = "reviews" | "members" | "groups" | "roles" | "data-policies" | "quality-profiles" | "knowledge-approvals" | "applications" | "retention" | "system-health";
type GovernanceData = GovernanceReviews | GovernanceMembers | GovernanceGroups | GovernanceRoles | GovernanceDataPolicies | GovernanceQualityProfiles | GovernanceKnowledgeApprovals | GovernanceApplications | GovernanceRetention | GovernanceSystemHealth;

const headings: Record<GovernanceView, [string, string]> = {
  reviews: ["Typed review queues", "Dataset publication and demonstration knowledge reviews stay separate, with quality evidence and separation rules visible."],
  members: ["Members", "Search active identities, workspace membership and explicit deny overrides. Passwords remain with the external identity provider."],
  groups: ["Groups", "Create workspace groups and manage membership through audited, idempotent actions."],
  roles: ["Roles", "Inspect permission bundles and assign time-bounded workspace roles."],
  "data-policies": ["Data policies", "Read the enforced visibility and classification boundary before changing data access."],
  "quality-profiles": ["Quality profiles", "Inspect versioned validation contracts, applicable data kinds and recent runs."],
  "knowledge-approvals": ["Knowledge approvals", "Review demonstration content independently from its creator."],
  applications: ["Application controls", "Inspect workspace enablement, owners, feature flags, permissions and manifest validity."],
  retention: ["Retention", "Current non-destructive policy, archive guidance and unresolved production decisions."],
  "system-health": ["System health", "Live dependency, migration, queue, scanner and local backup evidence without secrets."],
};

async function loadView(view: GovernanceView, search: string): Promise<GovernanceData> {
  if (view === "members") return getGovernanceMembers(search);
  if (view === "groups") return getGovernanceGroups(search);
  if (view === "roles") return getGovernanceRoles(search);
  if (view === "reviews") return getGovernanceReviews();
  if (view === "data-policies") return getGovernanceDataPolicies();
  if (view === "quality-profiles") return getGovernanceQualityProfiles();
  if (view === "knowledge-approvals") return getGovernanceKnowledgeApprovals();
  if (view === "applications") return getGovernanceApplications();
  if (view === "retention") return getGovernanceRetention();
  return getGovernanceSystemHealth();
}

function MembersView({ data }: { data: GovernanceMembers }) {
  return <section className="governance-table detail-panel"><table><thead><tr><th>Member</th><th>Identity</th><th>Status</th><th>Explicit denies</th><th>Joined</th></tr></thead><tbody>{data.items.map((item) => <tr key={item.id}><td><div className="person-cell"><span>{item.display_name.split(" ").map((part) => part[0]).slice(0, 2).join("")}</span><div><strong>{item.display_name}</strong><small>{item.email ?? "Legacy attribution identity"}</small></div></div></td><td>{item.external_subject}</td><td><span className="state-pill active">{item.membership_status}</span></td><td>{item.explicit_denies.length ? item.explicit_denies.map((deny) => <span className="deny-chip" title={deny.reason} key={`${deny.resource_id}-${deny.permission_code}`}>{deny.permission_code}</span>) : "None"}</td><td>{new Date(item.joined_at).toLocaleDateString()}</td></tr>)}</tbody></table><footer className="governance-boundary">Identity lifecycle and passwords are managed outside this application.</footer></section>;
}

function GroupsView({ data, reload }: { data: GovernanceGroups; reload: () => void }) {
  const [members, setMembers] = useState<GovernanceMembers["items"]>([]);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [selection, setSelection] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { void getGovernanceMembers().then((value) => setMembers(value.items)).catch((caught) => setError(String(caught))); }, []);
  const create = async () => { try { await createGovernanceGroup({ name, description, reason: "Workspace administrator created this group for scoped collaboration." }); setName(""); setDescription(""); reload(); } catch (caught) { setError(String(caught)); } };
  const add = async (groupId: string) => { const userId = selection[groupId] ?? members[0]?.id; if (!userId) return; try { await addGovernanceGroupMember(groupId, userId); reload(); } catch (caught) { setError(String(caught)); } };
  const remove = async (groupId: string, userId: string) => { try { await removeGovernanceGroupMember(groupId, userId); reload(); } catch (caught) { setError(String(caught)); } };
  return <>{error && <div className="platform-alert error">{error}</div>}<section className="detail-panel governance-inline-form"><h2>Create group</h2><label>Name<input value={name} onChange={(event) => setName(event.target.value)} /></label><label>Description<input value={description} onChange={(event) => setDescription(event.target.value)} /></label><button className="platform-primary" type="button" disabled={name.trim().length < 2} onClick={() => void create()}>Create audited group</button></section><section className="governance-card-grid">{data.items.map((group) => <article className="detail-panel" key={group.id}><div className="group-icon">◎</div><h2>{group.name}</h2><code>{group.slug}</code><p>{group.description || "Workspace governance group"}</p><div className="member-chips">{group.members.map((member) => <span key={member.id}>{member.display_name}<button type="button" aria-label={`Remove ${member.display_name} from ${group.name}`} onClick={() => void remove(group.id, member.id)}>×</button></span>)}{!group.members.length && <em>No members</em>}</div><div className="governance-member-add"><select aria-label={`Member for ${group.name}`} value={selection[group.id] ?? members[0]?.id ?? ""} onChange={(event) => setSelection((current) => ({ ...current, [group.id]: event.target.value }))}>{members.map((member) => <option value={member.id} key={member.id}>{member.display_name}</option>)}</select><button type="button" onClick={() => void add(group.id)}>Add member</button></div></article>)}</section></>;
}

function RolesView({ data, reload }: { data: GovernanceRoles; reload: () => void }) {
  const [members, setMembers] = useState<GovernanceMembers["items"]>([]);
  const [roleId, setRoleId] = useState(data.items[0]?.id ?? "");
  const [memberId, setMemberId] = useState("");
  const [expiry, setExpiry] = useState("");
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { void getGovernanceMembers().then((value) => { setMembers(value.items); setMemberId(value.items[0]?.id ?? ""); }).catch((caught) => setError(String(caught))); }, []);
  const assign = async () => { try { await createGovernanceRoleAssignment(roleId, memberId, expiry ? new Date(`${expiry}T23:59:59Z`).toISOString() : null); reload(); } catch (caught) { setError(String(caught)); } };
  return <>{error && <div className="platform-alert error">{error}</div>}<section className="detail-panel governance-inline-form"><h2>Assign scoped role</h2><label>Role<select value={roleId} onChange={(event) => setRoleId(event.target.value)}>{data.items.map((role) => <option value={role.id} key={role.id}>{role.name}</option>)}</select></label><label>Member<select value={memberId} onChange={(event) => setMemberId(event.target.value)}>{members.map((member) => <option value={member.id} key={member.id}>{member.display_name}</option>)}</select></label><label>Optional expiry<input type="date" value={expiry} onChange={(event) => setExpiry(event.target.value)} /></label><button className="platform-primary" type="button" disabled={!roleId || !memberId} onClick={() => void assign()}>Assign with rationale</button></section><section className="governance-card-grid role-grid">{data.items.map((role) => <article className="detail-panel" key={role.id}><div className="role-heading"><span>◇</span><div><h2>{role.name}</h2><code>{role.role_key}</code></div></div><p>{role.description}</p><details><summary>{role.permissions.length} permissions</summary><div className="permission-list">{role.permissions.map((permission) => <code key={permission}>{permission}</code>)}</div></details><strong>{role.assignments.length} assignments</strong><div className="assignment-list">{role.assignments.map((assignment) => <span key={assignment.id}>{assignment.subject.display_name}<small>{assignment.valid_until ? `until ${new Date(assignment.valid_until).toLocaleDateString()}` : "ongoing"}</small></span>)}</div></article>)}</section></>;
}

function ReviewsView({ data }: { data: GovernanceReviews }) {
  return <div className="governance-queue-grid">{(["dataset", "knowledge"] as const).map((kind) => <section className="detail-panel" key={kind}><div className="panel-title"><div><p className="platform-kicker">{kind} queue</p><h2>{kind === "dataset" ? "Dataset publication" : "Knowledge content"}</h2></div><span>{data.queues[kind].length}</span></div>{data.queues[kind].length ? data.queues[kind].map((item) => <Link className="governance-review-row" to={item.path} key={item.id}><div><strong>{item.title}</strong><small>Version {item.version} · {item.separation_rule.replaceAll("_", " ")}</small></div><span className="state-pill">{item.status}</span><b>{item.quality_status}</b><p>{item.rationale ?? "Decision and rationale pending."}</p></Link>) : <div className="inline-empty">No records in this queue.</div>}</section>)}</div>;
}

function DataPoliciesView({ data }: { data: GovernanceDataPolicies }) {
  return <><section className="detail-panel governance-policy-default"><p className="platform-kicker">Workspace default · read only</p><h2>{String(data.default_workspace_policy.visibility)} / {String(data.default_workspace_policy.classification)}</h2><p>Publication requires a declared licence. Sensitive field records require explicit scoped grants.</p></section><div className="governance-policy-grid"><section className="detail-panel"><h2>Visibility</h2>{data.visibility_definitions.map((item) => <dl key={item.key}><dt>{item.key}</dt><dd>{item.meaning}</dd></dl>)}</section><section className="detail-panel"><h2>Classification</h2>{data.classification_definitions.map((item) => <dl key={item.key}><dt>{item.key}</dt><dd>{item.meaning}</dd></dl>)}</section><section className="detail-panel blocked-policy"><h2>Blocked combinations</h2>{data.blocked_combinations.map((item) => <article key={`${item.visibility}-${item.classification}`}><strong>{item.visibility} + {item.classification}</strong><p>{item.reason}</p></article>)}</section></div></>;
}

function QualityProfilesView({ data }: { data: GovernanceQualityProfiles }) {
  return <section className="governance-card-grid">{data.items.map((profile) => <article className="detail-panel" key={profile.id}><div className="application-status"><span className="state-pill active">{profile.status}</span><small>{profile.data_kind}</small></div><h2>{profile.profile_key}</h2><code>version {profile.profile_version}</code><p>{String(profile.rules.contract ?? "Versioned validation rules")}</p><strong>{profile.recent_runs.length} recent runs</strong>{profile.recent_runs.slice(0, 3).map((run) => <div className="quality-run-row" key={run.id}><span>{run.status}</span><code>{run.dataset_version_id.slice(0, 8)}</code></div>)}</article>)}</section>;
}

function KnowledgeApprovalsView({ data }: { data: GovernanceKnowledgeApprovals }) {
  return <><div className="platform-alert warning">{data.warning}</div><section className="detail-panel governance-record-list">{data.items.map((item) => <article key={item.id}><div><strong>{item.title}</strong><small>Version {item.version_number} · by {item.creator.display_name}</small></div><span className="state-pill">{item.status}</span><p>{item.source_summary}</p><Link to={item.path}>{item.creator_can_approve ? "Open independent review →" : "Creator cannot approve this version"}</Link></article>)}{!data.items.length && <div className="inline-empty">No knowledge versions await review.</div>}</section></>;
}

function ApplicationsView({ data }: { data: GovernanceApplications }) {
  return <section className="governance-card-grid">{data.items.map((item) => <article className="detail-panel" key={item.id}><div className="application-status"><span className={`state-pill ${item.enabled ? "active" : ""}`}>{item.enabled ? "Enabled" : "Disabled"}</span><small>{item.contract_status}</small></div><h2>{item.name}</h2><p>{item.description}</p><dl><div><dt>Module</dt><dd>{item.module_version}</dd></div><div><dt>Contract</dt><dd>{item.contract_version}</dd></div><div><dt>Owner</dt><dd>{item.owner}</dd></div><div><dt>Technical owner</dt><dd>{item.technical_owner}</dd></div></dl><details><summary>{item.declared_permissions.length} declared permissions</summary><div className="permission-list">{item.declared_permissions.map((permission) => <code key={permission}>{permission}</code>)}</div></details><small>Feature flags: {Object.entries(item.feature_flags).map(([key, value]) => `${key}=${value}`).join(", ") || "none"}</small></article>)}{data.planned.map((item) => <article className="detail-panel planned" key={item.module_key}><span className="state-pill">Planned · disabled</span><h2>{item.module_key.replaceAll("-", " ")}</h2><p>No functional route or implied data.</p></article>)}</section>;
}

function RetentionView({ data }: { data: GovernanceRetention }) {
  return <><section className="governance-card-grid">{data.policies.map((policy) => <article className="detail-panel" key={policy.scope}><span className="state-pill">No automatic purge</span><h2>{policy.scope.replaceAll("_", " ")}</h2><p>{policy.current_policy}</p></article>)}</section><section className="detail-panel governance-gaps"><h2>Unresolved production decisions</h2><ul>{data.gaps.map((gap) => <li key={gap}>{gap}</li>)}</ul><h3>Archive and restore</h3><p>{data.guidance.archive}</p><p>{data.guidance.restore}</p></section></>;
}

function SystemHealthView({ data }: { data: GovernanceSystemHealth }) {
  return <><section className="health-summary detail-panel"><div><p className="platform-kicker">Live environment</p><h2>{data.status}</h2><p>{data.environment.name} · {data.environment.authentication} authentication · queue depth {data.queue_depth ?? "unavailable"}</p></div><span className={`state-pill ${data.status === "OK" ? "active" : ""}`}>No secrets exposed</span></section><section className="health-grid">{Object.entries(data.services).map(([name, service]) => <article className="detail-panel" key={name}><span className={`health-indicator ${service.status.toLowerCase()}`} aria-hidden="true" /><h2>{name.replaceAll("_", " ")}</h2><strong>{service.status}</strong>{"mode" in service && <small>{String(service.mode).replaceAll("_", " ")}</small>}{"current" in service && <code>{String(service.current)} → {String(service.expected)}</code>}</article>)}</section><section className="detail-panel backup-evidence"><p className="platform-kicker">Latest backup evidence</p><h2>{data.latest_backup_evidence.status.replaceAll("_", " ")}</h2><dl><div><dt>Evidence time</dt><dd>{data.latest_backup_evidence.created_at ? new Date(data.latest_backup_evidence.created_at).toLocaleString() : "Not available"}</dd></div><div><dt>Database dump</dt><dd>{data.latest_backup_evidence.database_dump ? "Present" : "Missing"}</dd></div><div><dt>Checksum</dt><dd>{data.latest_backup_evidence.checksum_evidence ? "Present" : "Missing"}</dd></div><div><dt>Off-host copy</dt><dd>{data.latest_backup_evidence.off_host ? "Recorded" : "Not configured"}</dd></div></dl></section></>;
}

export default function GovernancePage({ view }: { view: GovernanceView }) {
  const [data, setData] = useState<GovernanceData | null>(null);
  const [search, setSearch] = useState("");
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => { setError(null); void loadView(view, search).then(setData).catch((caught) => setError(caught instanceof Error ? caught.message : "Governance data unavailable")); }, [search, view]);
  useEffect(load, [load]);
  const searchable = ["members", "groups", "roles"].includes(view);
  return <div className="platform-page governance-page"><header className="page-heading"><div><p className="platform-kicker">Workspace governance</p><h1>{headings[view][0]}</h1><p>{headings[view][1]}</p></div><span className="read-only-badge">Policy scoped · audited</span></header>{searchable && <label className="catalogue-search governance-search"><span>⌕</span><input aria-label={`Search ${view}`} value={search} onChange={(event) => setSearch(event.target.value)} placeholder={`Search ${view}`} /></label>}{error && <div className="platform-alert error">{error}</div>}{!data ? <div className="platform-loading">Loading governance records…</div> : view === "members" ? <MembersView data={data as GovernanceMembers} /> : view === "groups" ? <GroupsView data={data as GovernanceGroups} reload={load} /> : view === "roles" ? <RolesView data={data as GovernanceRoles} reload={load} /> : view === "reviews" ? <ReviewsView data={data as GovernanceReviews} /> : view === "data-policies" ? <DataPoliciesView data={data as GovernanceDataPolicies} /> : view === "quality-profiles" ? <QualityProfilesView data={data as GovernanceQualityProfiles} /> : view === "knowledge-approvals" ? <KnowledgeApprovalsView data={data as GovernanceKnowledgeApprovals} /> : view === "applications" ? <ApplicationsView data={data as GovernanceApplications} /> : view === "retention" ? <RetentionView data={data as GovernanceRetention} /> : <SystemHealthView data={data as GovernanceSystemHealth} />}</div>;
}
