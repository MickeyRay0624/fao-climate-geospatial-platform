import { useCallback, useEffect, useRef, useState } from "react";

import {
  getAvailableDataVersions,
  getCatalog,
  getDataCatalog,
  runAnalysis,
  runAnalysisPreview,
} from "../../api";
import ComparisonModal from "../../components/ComparisonModal";
import ControlsPanel from "../../components/ControlsPanel";
import DataCatalogSection from "../../components/DataCatalogSection";
import MapPanel from "../../components/MapPanel";
import MethodModal from "../../components/MethodModal";
import RankingPanel from "../../components/RankingPanel";
import type {
  AnalysisResponse,
  AreaResult,
  AvailableDataVersion,
  Catalog,
  ComparisonResult,
  DataCatalogResponse,
} from "../../types";

function scrollToSection(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function InvestmentPage() {
  const didInitialise = useRef(false);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [dataCatalog, setDataCatalog] = useState<DataCatalogResponse | null>(null);
  const [availableVersions, setAvailableVersions] = useState<AvailableDataVersion[]>([]);
  const [selectedVersionId, setSelectedVersionId] = useState(0);
  const [analysis, setAnalysis] = useState<AnalysisResponse | null>(null);
  const [scenarioKey, setScenarioKey] = useState("balanced");
  const [weights, setWeights] = useState<Record<string, number>>({});
  const [minRiceArea, setMinRiceArea] = useState(750);
  const [mapMetric, setMapMetric] = useState("priority");
  const [selected, setSelected] = useState<AreaResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [comparing, setComparing] = useState(false);
  const [configurationDirty, setConfigurationDirty] = useState(false);
  const [comparisonResults, setComparisonResults] = useState<ComparisonResult[] | null>(null);
  const [methodOpen, setMethodOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const initialise = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [nextCatalog, nextDataCatalog, nextVersions] = await Promise.all([
        getCatalog(),
        getDataCatalog(),
        getAvailableDataVersions(),
      ]);
      const initialVersion = nextVersions.find((version) => version.is_current) ?? nextVersions[0];
      if (!initialVersion) throw new Error("No published analysis dataset is available");
      const initialWeights = nextCatalog.scenarios.balanced.weights;
      const initialAnalysis = await runAnalysisPreview({
        dataset_version_id: initialVersion.id,
        scenario_key: "balanced",
        weights: initialWeights,
        min_rice_area_ha: 750,
      });
      setCatalog(nextCatalog);
      setDataCatalog(nextDataCatalog);
      setAvailableVersions(nextVersions);
      setSelectedVersionId(initialVersion.id);
      setWeights(initialWeights);
      setAnalysis(initialAnalysis);
      setSelected(initialAnalysis.ranking[0] ?? null);
      setConfigurationDirty(false);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to initialise the workspace");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (didInitialise.current) return;
    didInitialise.current = true;
    void initialise();
  }, [initialise]);

  const handleScenarioChange = (key: string) => {
    if (!catalog) return;
    setScenarioKey(key);
    setWeights({ ...catalog.scenarios[key].weights });
    setConfigurationDirty(true);
  };

  const handleRun = async () => {
    if (!catalog || !selectedVersionId) return;
    setLoading(true);
    setError(null);
    try {
      const nextAnalysis = await runAnalysis({
        dataset_version_id: selectedVersionId,
        scenario_key: scenarioKey,
        weights,
        min_rice_area_ha: minRiceArea,
      });
      setAnalysis(nextAnalysis);
      setSelected(nextAnalysis.ranking[0] ?? null);
      setConfigurationDirty(false);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The analysis could not be completed");
    } finally {
      setLoading(false);
    }
  };

  const handleCompare = async () => {
    if (!catalog || !selectedVersionId) return;
    setComparing(true);
    setError(null);
    try {
      const entries = Object.entries(catalog.scenarios);
      const responses = await Promise.all(
        entries.map(([key, scenario]) =>
          runAnalysis({
            dataset_version_id: selectedVersionId,
            scenario_key: key,
            weights: scenario.weights,
            min_rice_area_ha: minRiceArea,
          }),
        ),
      );
      setComparisonResults(
        responses.map((response, index) => ({
          key: entries[index][0],
          label: entries[index][1].label,
          response,
        })),
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The scenarios could not be compared");
    } finally {
      setComparing(false);
    }
  };

  const handleUseVersion = (versionId: number) => {
    setSelectedVersionId(versionId);
    setConfigurationDirty(true);
    scrollToSection("analysis-workspace");
  };

  const handleSelect = useCallback((area: AreaResult) => setSelected(area), []);

  if (error && (!catalog || !dataCatalog || !analysis)) {
    return (
      <main className="startup-state">
        <div>
          <p className="section-kicker">Local service unavailable</p>
          <h1>The data workspace could not be initialised.</h1>
          <p>{error}</p>
          <button type="button" onClick={() => void initialise()}>Try again</button>
        </div>
      </main>
    );
  }

  if (!catalog || !dataCatalog || !analysis) {
    return (
      <main className="startup-state">
        <div className="loading-mark" aria-hidden="true" />
        <p>Preparing the versioned data catalogue and priority workspace…</p>
      </main>
    );
  }

  const selectedVersion = availableVersions.find((version) => version.id === selectedVersionId);

  return (
    <main className="investment-module">
      <header className="legacy-module-header">
        <div>
          <p className="section-kicker">Installed application · legacy-compatible workflow</p>
          <h1>Investment &amp; Extension Prioritisation</h1>
          <p>Cambodia commune rice-resilience analysis using synthetic demonstration data.</p>
        </div>
        <div className="legacy-module-actions">
          <nav aria-label="Analysis page sections">
            <button type="button" onClick={() => scrollToSection("data-catalog")}>Data</button>
            <button type="button" onClick={() => scrollToSection("analysis-workspace")}>Analysis</button>
            <button type="button" onClick={() => scrollToSection("analysis-results")}>Results</button>
          </nav>
          <button className="secondary-button" type="button" onClick={() => setMethodOpen(true)}>Method &amp; data</button>
        </div>
      </header>

      {error && (
        <div className="error-banner" role="alert"><strong>Action not completed.</strong> {error}<button type="button" onClick={() => setError(null)} aria-label="Dismiss error">×</button></div>
      )}
      <section className="platform-intro">
        <div>
          <p className="section-kicker">Data first, analysis second</p>
          <h2>Store the source, validate the version, publish it, then analyse it.</h2>
        </div>
        <div className="lineage-flow" aria-label="Data workflow">
          <span>Upload</span><i>→</i><span>Validate</span><i>→</i><span>Publish</span><i>→</i><span>Analyse</span><i>→</i><span>Export</span>
        </div>
      </section>

      <DataCatalogSection
        catalog={dataCatalog}
        activeVersionId={selectedVersionId}
        onUpload={() => window.location.assign("/data/datasets/new")}
        onUseVersion={handleUseVersion}
      />

      <section id="analysis-workspace" className="page-section analysis-workspace-section">
        <div className="section-title-row">
          <div>
            <p className="section-kicker">Analysis workspace</p>
            <h2>Climate-resilient rice investment and extension prioritisation</h2>
            <p className="muted compact">The map, ranking and exports below are reproducibly linked to one published dataset version.</p>
          </div>
          <span className="lineage-badge">Source · {selectedVersion?.display_name ?? "No version selected"}</span>
        </div>

        <ControlsPanel
          catalog={catalog}
          availableVersions={availableVersions}
          selectedVersionId={selectedVersionId}
          scenarioKey={scenarioKey}
          weights={weights}
          minRiceArea={minRiceArea}
          loading={loading}
          comparing={comparing}
          configurationDirty={configurationDirty}
          onVersionChange={(versionId) => { setSelectedVersionId(versionId); setConfigurationDirty(true); }}
          onScenarioChange={handleScenarioChange}
          onWeightChange={(code, value) => { setWeights((current) => ({ ...current, [code]: value })); setConfigurationDirty(true); }}
          onMinRiceAreaChange={(value) => { setMinRiceArea(value); setConfigurationDirty(true); }}
          onRun={() => void handleRun()}
          onCompare={() => void handleCompare()}
        />

        {configurationDirty && (
          <div className="stale-result-note">The configuration above has changed. The map still shows run #{analysis.run_id} until you run the analysis again.</div>
        )}
        <MapPanel
          catalog={catalog}
          geojson={analysis.geojson}
          metric={mapMetric}
          selectedId={selected?.id ?? null}
          datasetLabel={`${analysis.dataset_version.dataset_name} ${analysis.dataset_version.version_label}`}
          onMetricChange={setMapMetric}
          onSelect={handleSelect}
        />
      </section>

      <RankingPanel catalog={catalog} analysis={analysis} selected={selected} onSelect={handleSelect} />

      <footer className="app-footer">
        <span>{catalog.disclaimer}</span>
        <span>PostGIS metadata and analysis · S3-compatible source-file storage · versioned lineage</span>
      </footer>

      {comparisonResults && <ComparisonModal results={comparisonResults} onClose={() => setComparisonResults(null)} />}
      {methodOpen && <MethodModal catalog={catalog} onClose={() => setMethodOpen(false)} />}
    </main>
  );
}

export default InvestmentPage;
