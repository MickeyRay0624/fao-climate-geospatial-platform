import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import AppShell, { usePlatform } from "./platform/AppShell";
import AuditPage from "./pages/AuditPage";
import ApplicationsPage from "./pages/ApplicationsPage";
import CataloguePage from "./pages/CataloguePage";
import CollectionsPage from "./pages/CollectionsPage";
import DatasetDetailPage from "./pages/DatasetDetailPage";
import GovernancePage from "./pages/GovernancePage";
import HelpPage from "./pages/HelpPage";
import HomePage from "./pages/HomePage";
import JobsPage from "./pages/JobsPage";
import ReviewsPage from "./pages/ReviewsPage";
import SearchPage from "./pages/SearchPage";
import UploadWizardPage from "./pages/UploadWizardPage";
import VersionDetailPage from "./pages/VersionDetailPage";

const InvestmentPage = lazy(() => import("./modules/investment/InvestmentPage"));
const ExtensionPage = lazy(() => import("./modules/extension/ExtensionPage"));

function RequirePermission({ permission, children }: { permission: string; children: React.ReactNode }) {
  const { capabilities } = usePlatform();
  if (!capabilities.effective_permissions.includes(permission)) {
    return (
      <section className="platform-empty-state forbidden-state">
        <span>403</span>
        <h1>Access is not available for this role.</h1>
        <p>The route is hidden from navigation and the API independently enforces the same permission.</p>
      </section>
    );
  }
  return children;
}

function RequireAnyPermission({ permissions, children }: { permissions: string[]; children: React.ReactNode }) {
  const { capabilities } = usePlatform();
  if (!permissions.some((permission) => capabilities.effective_permissions.includes(permission))) {
    return (
      <section className="platform-empty-state forbidden-state">
        <span>403</span>
        <h1>Access is not available for this role.</h1>
        <p>The route is hidden from navigation and the API independently enforces the same permission.</p>
      </section>
    );
  }
  return children;
}

function PlatformRoutes() {
  return (
    <Routes>
      <Route path="/" element={<Navigate replace to="/home" />} />
      <Route path="/home" element={<HomePage />} />
      <Route path="/search" element={<SearchPage />} />
      <Route path="/data/catalog" element={<CataloguePage />} />
      <Route path="/data/mine" element={<CataloguePage mine />} />
      <Route path="/data/collections" element={<CollectionsPage />} />
      <Route path="/data/collections/:collectionId" element={<CollectionsPage />} />
      <Route path="/data/uploads" element={<JobsPage />} />
      <Route path="/data/reviews" element={<RequirePermission permission="dataset.review"><ReviewsPage /></RequirePermission>} />
      <Route path="/data/datasets/new" element={<RequirePermission permission="dataset.create"><UploadWizardPage /></RequirePermission>} />
      <Route path="/data/datasets/:datasetId" element={<DatasetDetailPage />} />
      <Route path="/data/versions/:versionId" element={<VersionDetailPage />} />
      <Route path="/data/datasets/:datasetId/versions/:versionId/*" element={<VersionDetailPage />} />
      <Route
        path="/apps/investment-prioritisation/*"
        element={
          <RequirePermission permission="apps.investment.use">
            <Suspense fallback={<div className="platform-loading">Loading the spatial analysis module…</div>}><InvestmentPage /></Suspense>
          </RequirePermission>
        }
      />
      <Route
        path="/apps/extension-field-support/*"
        element={
          <RequirePermission permission="apps.extension.use">
            <Suspense fallback={<div className="platform-loading">Loading the extension field workflow…</div>}><ExtensionPage /></Suspense>
          </RequirePermission>
        }
      />
      <Route path="/apps" element={<ApplicationsPage />} />
      <Route path="/governance/reviews" element={<RequireAnyPermission permissions={["dataset.review", "extension.knowledge.approve", "workspace.manage_settings"]}><GovernancePage view="reviews" /></RequireAnyPermission>} />
      <Route path="/governance/members" element={<RequirePermission permission="workspace.manage_members"><GovernancePage view="members" /></RequirePermission>} />
      <Route path="/governance/groups" element={<RequirePermission permission="workspace.manage_groups"><GovernancePage view="groups" /></RequirePermission>} />
      <Route path="/governance/roles" element={<RequirePermission permission="workspace.manage_roles"><GovernancePage view="roles" /></RequirePermission>} />
      <Route path="/governance/data-policies" element={<RequirePermission permission="workspace.manage_settings"><GovernancePage view="data-policies" /></RequirePermission>} />
      <Route path="/governance/quality-profiles" element={<RequirePermission permission="quality.manage_profiles"><GovernancePage view="quality-profiles" /></RequirePermission>} />
      <Route path="/governance/knowledge-approvals" element={<RequirePermission permission="extension.knowledge.approve"><GovernancePage view="knowledge-approvals" /></RequirePermission>} />
      <Route path="/governance/applications" element={<RequirePermission permission="workspace.enable_modules"><GovernancePage view="applications" /></RequirePermission>} />
      <Route path="/governance/audit" element={<RequirePermission permission="audit.view"><AuditPage /></RequirePermission>} />
      <Route path="/governance/retention" element={<RequirePermission permission="workspace.manage_settings"><GovernancePage view="retention" /></RequirePermission>} />
      <Route path="/governance/system-health" element={<RequirePermission permission="system.health.view"><GovernancePage view="system-health" /></RequirePermission>} />
      <Route path="/help/*" element={<HelpPage />} />
      <Route path="*" element={<section className="platform-empty-state"><span>404</span><h1>Page not found</h1><p>Use the workspace navigation to continue.</p></section>} />
    </Routes>
  );
}

export default function App() {
  return <AppShell><PlatformRoutes /></AppShell>;
}
