import type { AvailableDataVersion, Catalog } from "../types";

type Props = {
  catalog: Catalog;
  availableVersions: AvailableDataVersion[];
  selectedVersionId: number;
  scenarioKey: string;
  weights: Record<string, number>;
  minRiceArea: number;
  loading: boolean;
  comparing: boolean;
  configurationDirty: boolean;
  onVersionChange: (versionId: number) => void;
  onScenarioChange: (key: string) => void;
  onWeightChange: (code: string, value: number) => void;
  onMinRiceAreaChange: (value: number) => void;
  onRun: () => void;
  onCompare: () => void;
};

function ControlsPanel({
  catalog,
  availableVersions,
  selectedVersionId,
  scenarioKey,
  weights,
  minRiceArea,
  loading,
  comparing,
  configurationDirty,
  onVersionChange,
  onScenarioChange,
  onWeightChange,
  onMinRiceAreaChange,
  onRun,
  onCompare,
}: Props) {
  const totalWeight = Object.values(weights).reduce((sum, value) => sum + value, 0);
  const selectedVersion = availableVersions.find((version) => version.id === selectedVersionId);

  return (
    <section className="analysis-setup panel">
      <div className="analysis-setup-heading">
        <div>
          <p className="section-kicker">Analysis configuration</p>
          <h2>Choose a published data version before calculating priorities</h2>
          <p className="muted compact">
            Every run records the exact source version, weights and threshold used.
          </p>
        </div>
        {configurationDirty && <span className="pending-badge">Configuration not yet run</span>}
      </div>

      <div className="analysis-primary-controls">
        <label>
          <span>Published data version</span>
          <select
            value={selectedVersionId}
            onChange={(event) => onVersionChange(Number(event.target.value))}
          >
            {availableVersions.map((version) => (
              <option value={version.id} key={version.id}>
                {version.display_name}{version.is_current ? " — current" : ""}
              </option>
            ))}
          </select>
          <small>
            {selectedVersion?.record_count ?? 0} spatial records · checksum {selectedVersion?.checksum_sha256.slice(0, 8)}
          </small>
        </label>

        <label>
          <span>Policy scenario</span>
          <select value={scenarioKey} onChange={(event) => onScenarioChange(event.target.value)}>
            {Object.entries(catalog.scenarios).map(([key, scenario]) => (
              <option key={key} value={key}>
                {scenario.label}
              </option>
            ))}
          </select>
          <small>{catalog.scenarios[scenarioKey].description}</small>
        </label>

        <label>
          <span>Minimum rice area</span>
          <strong>{minRiceArea.toLocaleString()} ha</strong>
          <input
            aria-label="Minimum rice area in hectares"
            type="range"
            min="0"
            max="3000"
            step="100"
            value={minRiceArea}
            onChange={(event) => onMinRiceAreaChange(Number(event.target.value))}
          />
          <small>Smaller areas stay visible but are excluded from ranking.</small>
        </label>
      </div>

      <details className="weight-disclosure">
        <summary>
          <span>Review and adjust indicator weights</span>
          <small>Normalised automatically to 100%</small>
        </summary>
        <div className="weight-grid">
          {Object.entries(catalog.indicators).map(([code, indicator]) => {
            const normalised = totalWeight > 0 ? (weights[code] / totalWeight) * 100 : 0;
            return (
              <label className="weight-control" key={code}>
                <span>
                  {indicator.short_label}
                  <strong>{normalised.toFixed(0)}%</strong>
                </span>
                <input
                  aria-label={`${indicator.label} weight`}
                  type="range"
                  min="0"
                  max="50"
                  step="1"
                  value={Math.round((weights[code] ?? 0) * 100)}
                  onChange={(event) =>
                    onWeightChange(code, Number(event.target.value) / 100)
                  }
                />
              </label>
            );
          })}
        </div>
      </details>

      <div className="analysis-actions">
        <div className="method-note inline">
          <span aria-hidden="true">i</span>
          <p>Missing values remain visible and use the documented neutral-value policy.</p>
        </div>
        <button className="secondary-button" type="button" onClick={onCompare} disabled={loading || comparing}>
          {comparing ? "Comparing presets…" : "Compare four presets"}
        </button>
        <button className="primary-button" type="button" onClick={onRun} disabled={loading}>
          {loading ? "Calculating priorities…" : "Run prioritisation"}
        </button>
      </div>
    </section>
  );
}

export default ControlsPanel;

