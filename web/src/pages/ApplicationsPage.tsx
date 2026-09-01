import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { getModules } from "../api";
import type { ModuleRecord } from "../platform/types";

const planned = [
  ["Climate risk explorer", "Explore governed risk layers and time slices."],
  ["Seasonal planning", "Coordinate seasonal evidence and planning windows."],
  ["Carbon and emissions", "Manage reviewed emissions evidence and methods."],
  ["Policy simulation", "Compare transparent, versioned policy scenarios."],
];

export default function ApplicationsPage() {
  const [modules, setModules] = useState<ModuleRecord[]>([]);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { void getModules().then((response) => setModules(response.items)).catch((caught) => setError(String(caught))); }, []);
  return <div className="platform-page applications-page"><header className="page-heading"><div><p className="platform-kicker">Workspace module registry</p><h1>Applications</h1><p>Enabled modules consume governed exact versions. Planned concepts have no functional routes or implied data.</p></div></header>{error && <div className="platform-alert error">{error}</div>}<section className="applications-grid">{modules.map((module) => <article className="detail-panel" key={module.id}><div className="application-status"><span className={`state-pill ${module.enabled ? "active" : ""}`}>{module.enabled ? "Enabled" : "Disabled"}</span><small>v{module.module_version} · contract {module.contract_version}</small></div><h2>{module.name}</h2><p>{module.description}</p><dl><div><dt>Owner</dt><dd>{module.owner ?? "Not assigned"}</dd></div><div><dt>Required permission</dt><dd><code>{module.required_permission ?? "—"}</code></dd></div><div><dt>Contract</dt><dd>{module.manifest_valid ? "Valid" : "Invalid"}</dd></div><div><dt>Last activity</dt><dd>{module.last_activity ? new Date(module.last_activity).toLocaleString() : "No recorded activity"}</dd></div></dl>{module.enabled ? <Link className="platform-primary" to={module.routes[0]?.path ?? "/apps"}>Launch application →</Link> : <span className="application-unavailable">Workspace enablement required</span>}</article>)}{planned.map(([name, description]) => <article className="detail-panel planned" key={name}><div className="application-status"><span className="state-pill">Planned</span><small>No route · no data</small></div><h2>{name}</h2><p>{description}</p><em>Concept only. Capability has not been implemented.</em></article>)}</section></div>;
}
