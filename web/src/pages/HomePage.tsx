import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { getDataHubDatasets, getModules } from "../api";
import { usePlatform } from "../platform/AppShell";
import type { DataHubDatasetSummary, ModuleRecord } from "../platform/types";

export default function HomePage() {
  const { capabilities, jobs } = usePlatform();
  const [datasets, setDatasets] = useState<DataHubDatasetSummary[]>([]);
  const [modules, setModules] = useState<ModuleRecord[]>([]);

  useEffect(() => {
    void Promise.all([getDataHubDatasets(), getModules()]).then(([catalogue, registry]) => {
      setDatasets(catalogue.items);
      setModules(registry.items);
    });
  }, []);

  const metrics = useMemo(() => ({
    datasets: datasets.length,
    published: datasets.filter((item) => item.current_published_version).length,
    attention: datasets.filter((item) => ["FAILED", "WARNING"].includes(item.quality_status ?? "")).length,
    jobs: jobs.filter((item) => ["QUEUED", "RUNNING"].includes(item.status)).length,
  }), [datasets, jobs]);

  return (
    <div className="platform-page home-page">
      <section className="home-hero">
        <div>
          <p className="platform-kicker">FAO Climate Change Group · Cambodia pilot workspace</p>
          <h1>Govern geospatial evidence.<br />Make decisions that can be traced.</h1>
          <p className="hero-copy">A modular local platform for cataloguing, reviewing and publishing climate data—then using exact published versions in transparent decision workflows.</p>
          <div className="hero-actions">
            {capabilities.effective_permissions.includes("dataset.create") && <Link className="platform-primary" to="/data/datasets/new">Add a dataset <span>→</span></Link>}
            <Link className="platform-secondary" to="/data/catalog">Explore the catalogue</Link>
          </div>
        </div>
        <div className="hero-map-card" aria-label="Cambodia pilot coverage illustration">
          <div className="map-grid" />
          <div className="map-orbit orbit-one" /><div className="map-orbit orbit-two" />
          <span className="map-pin pin-one">1</span><span className="map-pin pin-two">2</span><span className="map-pin pin-three">3</span>
          <div className="map-caption"><small>Pilot geography</small><strong>Cambodia</strong><span>111 synthetic commune records</span></div>
        </div>
      </section>

      <section className="metric-strip" aria-label="Workspace summary">
        <article><span className="metric-icon">▦</span><div><strong>{metrics.datasets}</strong><small>catalogued datasets</small></div></article>
        <article><span className="metric-icon">✓</span><div><strong>{metrics.published}</strong><small>published products</small></div></article>
        <article><span className="metric-icon amber">!</span><div><strong>{metrics.attention}</strong><small>quality items to review</small></div></article>
        <article><span className="metric-icon blue">↻</span><div><strong>{metrics.jobs}</strong><small>active processing jobs</small></div></article>
      </section>

      <section className="home-grid">
        <div className="home-main-column">
          <div className="platform-section-heading"><div><p className="platform-kicker">Controlled data lifecycle</p><h2>From source file to reusable evidence</h2></div><Link to="/help">View platform boundaries</Link></div>
          <div className="lifecycle-cards">
            {[
              ["01", "Register", "Describe the dataset, ownership, classification and intended use."],
              ["02", "Upload & validate", "Send files directly to quarantine and inspect them against a versioned profile."],
              ["03", "Review", "Separate contributor, reviewer and publisher actions with rationale and evidence."],
              ["04", "Publish & use", "Freeze the approved version and preserve lineage for every downstream decision."],
            ].map(([number, title, copy]) => <article key={number}><span>{number}</span><h3>{title}</h3><p>{copy}</p></article>)}
          </div>
          <div className="platform-section-heading module-heading"><div><p className="platform-kicker">Module registry</p><h2>Applications in this workspace</h2></div></div>
          <div className="module-cards">
            {modules.map((module) => (
              <article key={module.id} className={module.enabled ? "enabled" : "disabled"}>
                <div><span>{module.enabled ? "Enabled" : "Not enabled"}</span><small>v{module.module_version} · contract {module.contract_version}</small></div>
                <h3>{module.name}</h3><p>{module.description}</p>
                {module.enabled ? <Link to={module.routes[0]?.path ?? "/home"}>Open application <span>→</span></Link> : <em>Future module · no functional route exposed</em>}
              </article>
            ))}
          </div>
        </div>
        <aside className="home-side-column">
          <section className="boundary-card">
            <span className="boundary-label">Demonstration boundary</span>
            <h2>Evidence, not operational advice</h2>
            <p>The current commune boundaries and all seven indicators are deterministic synthetic data. They do not represent FAO, government, satellite, census or programme outputs.</p>
            <ul><li>No real-time sensors or weather</li><li>No field-level digital twin</li><li>No agronomic recommendation engine</li></ul>
          </section>
          <section className="workspace-activity-card">
            <div><p className="platform-kicker">Workspace controls</p><h2>Current security posture</h2></div>
            <dl>
              <div><dt>Identity</dt><dd className="warning-dot">Development mode</dd></div>
              <div><dt>Object access</dt><dd className="ok-dot">Short-lived URLs</dd></div>
              <div><dt>File scanner</dt><dd className="warning-dot">Dev bypass</dd></div>
              <div><dt>Published versions</dt><dd className="ok-dot">Immutable</dd></div>
            </dl>
          </section>
        </aside>
      </section>
    </div>
  );
}
