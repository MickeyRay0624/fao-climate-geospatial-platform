import { Link } from "react-router-dom";

const boundaries = [
  ["Synthetic pilot data", "The included Cambodia commune records are deterministic demonstration data. They are not observations, forecasts or agronomic advice."],
  ["No live digital twin", "Phase 1 provides governed data foundations and one legacy-compatible decision module. It does not ingest sensors or update a real-world state model."],
  ["Development identity", "The amber banner and persona switcher are local-only controls. Production startup rejects development authentication and requires configured OIDC validation."],
  ["Development file scan", "Local uploads are marked BYPASSED DEV, never clean. Non-development environments fail closed unless an operational scanner is configured."],
];

export default function HelpPage() {
  return (
    <div className="platform-page help-page">
      <header className="help-hero"><p className="platform-kicker">Platform guide</p><h1>Know what this pilot can—and cannot—tell you.</h1><p>The Foundation + Data Hub release establishes the governance boundary required before operational datasets or additional decision applications are introduced.</p></header>
      <section className="boundary-grid">{boundaries.map(([title, copy], index) => <article key={title}><span>0{index + 1}</span><h2>{title}</h2><p>{copy}</p></article>)}</section>
      <section className="help-layout">
        <article className="detail-panel"><p className="platform-kicker">Recommended workflow</p><h2>Publish evidence deliberately</h2><ol className="help-steps"><li><i>1</i><div><strong>Register the data product</strong><p>Choose ownership, visibility, classification and licence at dataset level.</p></div></li><li><i>2</i><div><strong>Create an exact version</strong><p>Record provenance, intended use, limitations and a versioned quality profile.</p></div></li><li><i>3</i><div><strong>Upload and validate</strong><p>The file goes directly to quarantine; a background job checks and registers its representation.</p></div></li><li><i>4</i><div><strong>Request independent review</strong><p>The contributor cannot approve their own work. A reviewer records evidence and rationale.</p></div></li><li><i>5</i><div><strong>Publish an immutable release</strong><p>A separate publisher freezes metadata and assets for reproducible downstream use.</p></div></li></ol></article>
        <aside><article className="detail-panel support-card"><span className="support-icon">?</span><p className="platform-kicker">Local pilot support</p><h2>Start with observable evidence</h2><p>Use the processing centre for job state, the version page for validation and lineage, and the audit log for who did what.</p><div><Link to="/data/uploads">Open processing centre →</Link><Link to="/data/catalog">Browse governed catalogue →</Link></div></article><article className="detail-panel contract-card"><p className="platform-kicker">Module boundary</p><h2>Applications consume published versions</h2><p>The investment prioritisation app remains available as an installed module. New source data must enter through the Data Hub workflow.</p><Link className="platform-secondary inline-button" to="/apps/investment-prioritisation/overview">Open application</Link></article></aside>
      </section>
    </div>
  );
}
