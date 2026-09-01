import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { Link, NavLink, useLocation, useNavigate } from "react-router-dom";

import { getCapabilities, getDevPersonas, getJobs, setDevSubject } from "../api";
import type { Capabilities, DevPersona, ProcessingJob } from "./types";
type PlatformContextValue = {
  capabilities: Capabilities;
  jobs: ProcessingJob[];
  refreshJobs: () => Promise<void>;
};

const PlatformContext = createContext<PlatformContextValue | null>(null);

export function usePlatform(): PlatformContextValue {
  const value = useContext(PlatformContext);
  if (!value) throw new Error("usePlatform must be used inside AppShell");
  return value;
}

const iconGlyph: Record<string, string> = {
  home: "⌂", database: "▦", folder: "▤", upload: "⇧", check: "✓",
  map: "⌖", users: "◉", groups: "◎", shield: "◇", audit: "≡", help: "?",
  collection: "▥",
  apps: "⬡",
  policy: "§",
  quality: "◈",
  knowledge: "▤",
  archive: "□",
  health: "●",
  field: "⌖",
};

function AppShell({ children }: { children: ReactNode }) {
  const location = useLocation();
  const navigate = useNavigate();
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const [personas, setPersonas] = useState<DevPersona[]>([]);
  const [jobs, setJobs] = useState<ProcessingJob[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [mobileNav, setMobileNav] = useState(false);
  const [identityEpoch, setIdentityEpoch] = useState(0);

  const refreshJobs = useCallback(async () => {
    try {
      const response = await getJobs();
      setJobs(response.items);
    } catch {
      setJobs([]);
    }
  }, []);

  useEffect(() => {
    let active = true;
    Promise.all([getCapabilities(), getDevPersonas().catch(() => ({ items: [], development_only: false }))])
      .then(([nextCapabilities, nextPersonas]) => {
        if (!active) return;
        setCapabilities(nextCapabilities);
        setPersonas(nextPersonas.items);
        setError(null);
      })
      .catch((caught) => {
        if (active) setError(caught instanceof Error ? caught.message : "The workspace could not be loaded.");
      });
    return () => { active = false; };
  }, [identityEpoch]);

  useEffect(() => {
    if (!capabilities) return;
    void refreshJobs();
    const timer = window.setInterval(() => void refreshJobs(), 8000);
    return () => window.clearInterval(timer);
  }, [capabilities, refreshJobs]);

  const sections = useMemo(() => {
    const grouped = new Map<string, Capabilities["navigation"]>();
    if (!capabilities) return grouped;
    for (const item of capabilities.navigation) {
      grouped.set(item.section, [...(grouped.get(item.section) ?? []), item]);
    }
    return grouped;
  }, [capabilities]);

  if (error) {
    return (
      <main className="platform-startup">
        <div className="fao-seal">FAO</div>
        <p className="platform-kicker">Platform unavailable</p>
        <h1>The local workspace could not be opened.</h1>
        <p>{error}</p>
        <button type="button" onClick={() => setIdentityEpoch((value) => value + 1)}>Retry connection</button>
      </main>
    );
  }

  if (!capabilities) {
    return <main className="platform-startup"><div className="platform-spinner" /><p>Loading workspace capabilities…</p></main>;
  }

  const activeNavigation = capabilities.navigation.find((item) => location.pathname.startsWith(item.path));
  const activeJobs = jobs.filter((job) => ["QUEUED", "RUNNING"].includes(job.status));
  const contextValue = { capabilities, jobs, refreshJobs };

  return (
    <PlatformContext.Provider value={contextValue}>
      <div className="platform-root">
        {capabilities.development_identity && (
          <div className="dev-identity-banner" role="status">
            <strong>Development identity</strong>
            <span>Local persona simulation · not FAO SSO</span>
            <label>
              <span className="sr-only">Active development persona</span>
              <select
                value={capabilities.current_user.external_subject}
                onChange={(event) => {
                  Object.keys(sessionStorage)
                    .filter((key) => key.startsWith("extension:draft:"))
                    .forEach((key) => sessionStorage.removeItem(key));
                  setDevSubject(event.target.value);
                  setIdentityEpoch((value) => value + 1);
                }}
              >
                {personas.map((persona) => <option key={persona.id} value={persona.external_subject}>{persona.display_name}</option>)}
              </select>
            </label>
          </div>
        )}
        <aside className={`platform-sidebar ${mobileNav ? "open" : ""}`}>
          <Link className="platform-brand" to="/home" onClick={() => setMobileNav(false)}>
            <span className="fao-seal">FAO</span>
            <div>
              <strong>Climate Geospatial</strong>
              <small>Data &amp; Decision Platform</small>
            </div>
          </Link>
          <div className="workspace-card">
            <span>Active workspace</span>
            <strong>{capabilities.active_workspace.name}</strong>
            <small>Cambodia · local pilot</small>
          </div>
          <nav className="platform-navigation" aria-label="Platform navigation">
            {[...sections.entries()].map(([section, items]) => (
              <section key={section}>
                <p>{section}</p>
                {items.map((item) => (
                  <NavLink key={item.path} to={item.path} onClick={() => setMobileNav(false)}>
                    <i aria-hidden="true">{iconGlyph[item.icon] ?? "·"}</i>
                    <span>{item.title}</span>
                  </NavLink>
                ))}
              </section>
            ))}
          </nav>
          <div className="sidebar-boundary-note">
            <span>Synthetic demo</span>
            <p>Not for operational planning or agronomic advice.</p>
          </div>
        </aside>
        <div className="platform-stage">
          <header className="platform-topbar">
            <button className="mobile-nav-toggle" type="button" onClick={() => setMobileNav((value) => !value)} aria-label="Toggle navigation">☰</button>
            <form
              className="global-search"
              onSubmit={(event) => {
                event.preventDefault();
                navigate(`/search?q=${encodeURIComponent(search)}`);
              }}
            >
              <span aria-hidden="true">⌕</span>
              <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search datasets, versions, runs…" aria-label="Search platform" />
              <kbd>↵</kbd>
            </form>
            <div className="topbar-actions">
              <Link className="job-indicator" to="/data/uploads" title="Processing jobs">
                <span>↻</span>
                <b>{activeJobs.length}</b>
              </Link>
              <div className="current-user">
                <span>{capabilities.current_user.display_name.split(" ").map((part) => part[0]).slice(0, 2).join("")}</span>
                <div><strong>{capabilities.current_user.display_name}</strong><small>{capabilities.current_user.roles.join(" · ")}</small></div>
              </div>
            </div>
          </header>
          <div className="platform-breadcrumb">
            <Link to="/home">Workspace</Link><span>/</span><strong>{activeNavigation?.title ?? "Platform"}</strong>
          </div>
          <main className="platform-content" key={capabilities.current_user.id}>{children}</main>
        </div>
      </div>
    </PlatformContext.Provider>
  );
}

export default AppShell;
