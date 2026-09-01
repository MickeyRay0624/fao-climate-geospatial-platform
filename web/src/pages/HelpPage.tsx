import { Link, Navigate, useLocation } from "react-router-dom";

type Topic = { title: string; summary: string; sections: Array<{ heading: string; body: string; links?: Array<[string, string]> }> };

const topics: Record<string, Topic> = {
  "getting-started": {
    title: "Getting started",
    summary: "Understand the workspace, persona boundary and the platform's evidence labels before demonstrating a workflow.",
    sections: [
      { heading: "Start at Home", body: "Home is role-aware. It shows governed catalogue evidence, current work, review queues, application tasks and operational status permitted to the active identity.", links: [["Open Home", "/home"], ["Browse applications", "/apps"]] },
      { heading: "Use the persona switcher only in development", body: "The amber identity banner is a local demonstration control, not FAO SSO. Changing persona clears restricted Extension drafts from session storage." },
      { heading: "Read labels literally", body: "Real source samples, synthetic analysis inputs, illustrative methods and fictional Extension records are different evidence classes. None is an operational recommendation." },
    ],
  },
  "data-hub": {
    title: "Data Hub",
    summary: "Register, validate, review, publish and reuse exact dataset versions through one governed lifecycle.",
    sections: [
      { heading: "Catalogue and collections", body: "Catalogue filters return permission-scoped datasets. Collections pin exact versions rather than silently following the latest release.", links: [["Team catalogue", "/data/catalog"], ["Real-data showcase", "/data/collections"]] },
      { heading: "Lifecycle", body: "A contributor creates a version and uploads into quarantine. Validation records quality evidence; an independent reviewer decides with rationale; a publisher freezes the approved release." },
      { heading: "Preview and lineage", body: "Vector previews are server-paged and maps have a text alternative. Table previews are paginated. Assets, quality, review, access, lineage and audit remain linked to the exact version." },
    ],
  },
  investment: {
    title: "Investment prioritisation",
    summary: "Build exact input sets and run a transparent illustrative method without disguising data gaps.",
    sections: [
      { heading: "Synthetic demonstration", body: "The locked synthetic bundle is reproducible and supports run history, map, ranking, contribution, assets, lineage and comparison. Its scores are not funding recommendations.", links: [["Investment overview", "/apps/investment-prioritisation/overview"], ["Synthetic runs", "/apps/investment-prioritisation/runs"]] },
      { heading: "Real-sample readiness", body: "The real GAUL boundary and MPI poverty sample are available, but six required roles and formal method approval remain unresolved. Lock and run stay unavailable, and no fake real ranking is created.", links: [["Readiness", "/apps/investment-prioritisation/readiness"]] },
      { heading: "Method boundary", body: "Weights, direction, normalisation, data snapshots and code reference are visible. The included method is illustrative and has not received business endorsement or operational validation." },
    ],
  },
  extension: {
    title: "Extension field support",
    summary: "Operate a fictional, manual case workflow for observation, verification, activity and follow-up.",
    sections: [
      { heading: "Officer workflow", body: "Officers see only owned or assigned cases. Record structured observations, select a demonstration knowledge category manually, complete a versioned checklist and plan a follow-up activity.", links: [["Officer worklist", "/apps/extension-field-support/worklist"], ["Offline drafts", "/apps/extension-field-support/sync"]] },
      { heading: "Supervisor workflow", body: "Supervisors see workspace workload, unassigned cases, overdue follow-ups and pending activities. Assignment, priority and approval actions require a reason and create audit evidence.", links: [["Supervision", "/apps/extension-field-support/supervision"]] },
      { heading: "Privacy and advice boundary", body: "Demo cases contain no farmer names or exact farms. Media is sensitive and assignment-scoped. Raw cases never enter Data Hub automatically. No automatic diagnosis or agronomic prescription is provided." },
    ],
  },
  governance: {
    title: "Governance",
    summary: "Inspect identities, policies, reviews, application contracts, retention, audit evidence and live dependency health.",
    sections: [
      { heading: "People and access", body: "Members come from external identity records. Groups and time-bounded roles are audited. Explicit deny grants override broader allows and are visible to administrators.", links: [["Members", "/governance/members"], ["Roles", "/governance/roles"]] },
      { heading: "Review and policy", body: "Dataset and knowledge queues remain typed and separate. Data-policy and retention pages are intentionally read-only until formal policy decisions are approved.", links: [["Review queues", "/governance/reviews"], ["Data policies", "/governance/data-policies"]] },
      { heading: "Evidence and operations", body: "Audit is append-only and exportable with actor, action, resource, outcome, date and correlation filters. System health reports dependencies, migrations, queues, scanner mode and local backup evidence without secrets.", links: [["Audit log", "/governance/audit"], ["System health", "/governance/system-health"]] },
    ],
  },
  "demo-guide": {
    title: "Demonstration guide",
    summary: "Follow the approved story from platform context to governed data, investment evidence, field workflow and operational limitations.",
    sections: [
      { heading: "1 · Establish the boundary", body: "Open Home, explain the active workspace and role, then distinguish real samples, synthetic analysis and fictional field records." },
      { heading: "2 · Trace governed evidence", body: "Preview the real GAUL boundary and MPI table, inspect licence warnings, quality and lineage, then show why the real investment bundle remains incomplete." },
      { heading: "3 · Complete the application story", body: "Open a synthetic run and its reproducibility evidence. Switch to an Extension officer for observation and verification, then to a supervisor for workload and approval. Finish with audit, health and limitations.", links: [["Start at Home", "/home"], ["Open full route guide", "/help/data-and-method-limitations"]] },
    ],
  },
  "data-and-method-limitations": {
    title: "Data and method limitations",
    summary: "The demonstrator proves governed workflows and reproducibility; it does not prove operational fitness or institutional endorsement.",
    sections: [
      { heading: "Real source samples", body: "The Cambodia GAUL and MPI samples retain checksums and lineage. Their source licence is unconfirmed, so redistribution and operational use require a documented licence decision." },
      { heading: "Synthetic analysis", body: "Commune indicators, rankings and scenarios are deterministic synthetic fixtures. The weighted method is illustrative; formal ownership, review and validation remain pending." },
      { heading: "Field workflow", body: "Extension records and locations are fictional demonstration content. Knowledge sources are placeholders. Production requires approved agronomic content, privacy review, localisation and operational field validation." },
      { heading: "Production controls", body: "FAO SSO, approved malware scanning, managed secrets, TLS and ingress, off-host backup, observability and SIEM, large-file operations and full offline conflict handling remain deployment work." },
    ],
  },
};

const order = ["getting-started", "data-hub", "investment", "extension", "governance", "demo-guide", "data-and-method-limitations"];

export default function HelpPage() {
  const location = useLocation();
  const key = location.pathname.replace(/^\/help\/?/, "") || "getting-started";
  if (location.pathname === "/help" || location.pathname === "/help/") return <Navigate replace to="/help/getting-started" />;
  const topic = topics[key];
  if (!topic) return <section className="platform-empty-state"><span>404</span><h1>Help topic not found</h1><Link to="/help/getting-started">Open getting started</Link></section>;
  return <div className="platform-page help-page"><header className="help-hero"><p className="platform-kicker">Platform guide</p><h1>{topic.title}</h1><p>{topic.summary}</p></header><div className="help-topic-layout"><nav className="detail-panel" aria-label="Help topics">{order.map((item) => <Link className={item === key ? "active" : ""} to={`/help/${item}`} key={item}>{topics[item].title}</Link>)}</nav><main>{topic.sections.map((section, index) => <article className="detail-panel help-topic" key={section.heading}><span>{String(index + 1).padStart(2, "0")}</span><h2>{section.heading}</h2><p>{section.body}</p>{section.links && <div>{section.links.map(([label, path]) => <Link to={path} key={path}>{label} →</Link>)}</div>}</article>)}</main></div></div>;
}
