import { useEffect, useState } from "react";

import { getGovernanceGroups, getGovernanceMembers, getGovernanceRoles } from "../api";
import type { GovernanceGroups, GovernanceMembers, GovernanceRoles } from "../platform/types";

export default function GovernancePage({ view }: { view: "members" | "groups" | "roles" }) {
  const [data, setData] = useState<GovernanceMembers | GovernanceGroups | GovernanceRoles | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const loader = view === "members" ? getGovernanceMembers : view === "groups" ? getGovernanceGroups : getGovernanceRoles;
    void loader().then(setData).catch((caught) => setError(caught instanceof Error ? caught.message : "Governance data unavailable"));
  }, [view]);
  return (
    <div className="platform-page governance-page">
      <header className="page-heading"><div><p className="platform-kicker">Workspace governance</p><h1>{view[0].toUpperCase() + view.slice(1)}</h1><p>{view === "members" ? "Active identities and workspace membership status." : view === "groups" ? "Teams used for review scope, stewardship and resource grants." : "Composable role bundles and time-bounded assignments."}</p></div><span className="read-only-badge">Minimum admin UI · audited API</span></header>
      {error && <div className="platform-alert error">{error}</div>}
      {!data ? <div className="platform-loading">Loading governance records…</div> : view === "members" ? <section className="governance-table detail-panel"><table><thead><tr><th>Member</th><th>Identity</th><th>Status</th><th>Joined</th></tr></thead><tbody>{(data as GovernanceMembers).items.map((item) => <tr key={item.id}><td><div className="person-cell"><span>{item.display_name.split(" ").map((part) => part[0]).slice(0, 2).join("")}</span><div><strong>{item.display_name}</strong><small>{item.email ?? "Legacy attribution identity"}</small></div></div></td><td>{item.external_subject}</td><td><span className="state-pill active">{item.membership_status}</span></td><td>{new Date(item.joined_at).toLocaleDateString()}</td></tr>)}</tbody></table></section> : view === "groups" ? <section className="governance-card-grid">{(data as GovernanceGroups).items.map((group) => <article className="detail-panel" key={group.id}><div className="group-icon">◎</div><h2>{group.name}</h2><code>{group.slug}</code><p>{group.description || "Workspace governance group"}</p><div className="member-chips">{group.members.map((member) => <span key={member.id}>{member.display_name}</span>)}{!group.members.length && <em>No members</em>}</div></article>)}</section> : <section className="governance-card-grid role-grid">{(data as GovernanceRoles).items.map((role) => <article className="detail-panel" key={role.id}><div className="role-heading"><span>◇</span><div><h2>{role.name}</h2><code>{role.role_key}</code></div></div><p>{role.description}</p><strong>{role.assignments.length} assignments</strong><div className="assignment-list">{role.assignments.map((assignment) => <span key={assignment.id}>{assignment.subject.display_name}<small>{assignment.valid_until ? `until ${assignment.valid_until}` : "ongoing"}</small></span>)}</div></article>)}</section>}
    </div>
  );
}
