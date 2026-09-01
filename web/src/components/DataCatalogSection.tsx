import type { DataCatalogResponse } from "../types";

type Props = {
  catalog: DataCatalogResponse;
  activeVersionId: number;
  onUpload: () => void;
  onUseVersion: (versionId: number) => void;
};

const dateFormatter = new Intl.DateTimeFormat("en-GB", {
  year: "numeric",
  month: "short",
  day: "numeric",
});

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
}

function DataCatalogSection({
  catalog,
  activeVersionId,
  onUpload,
  onUseVersion,
}: Props) {
  return (
    <section id="data-catalog" className="page-section data-catalog-section">
      <div className="section-title-row">
        <div>
          <p className="section-kicker">Data workspace</p>
          <h2>Versioned team data catalogue</h2>
          <p className="muted compact">
            Raw files are preserved in object storage; analysis-ready records, quality checks and lineage live in PostGIS.
          </p>
        </div>
        <button className="primary-button compact-button" type="button" onClick={onUpload}>
          Upload dataset version
        </button>
      </div>

      <div className="catalog-summary">
        <article><span>Datasets</span><strong>{catalog.summary.datasets}</strong></article>
        <article><span>Versions</span><strong>{catalog.summary.versions}</strong></article>
        <article><span>Published</span><strong>{catalog.summary.published_versions}</strong></article>
        <article><span>Stored source files</span><strong>{formatBytes(catalog.summary.stored_bytes)}</strong></article>
        <article><span>Quality warnings</span><strong>{catalog.summary.quality_warnings}</strong></article>
      </div>

      <div className="dataset-list">
        {catalog.datasets.map((dataset) => (
          <article className="dataset-card panel" key={dataset.id}>
            <header>
              <div>
                <div className="dataset-title-line">
                  <h3>{dataset.name}</h3>
                  <span>{dataset.data_kind.replaceAll("_", " ")}</span>
                </div>
                <p>{dataset.description}</p>
              </div>
              <small>Owner · {dataset.owner}</small>
            </header>

            <div className="version-table-wrap">
              <table className="version-table">
                <thead>
                  <tr>
                    <th>Version</th>
                    <th>Status</th>
                    <th>Records</th>
                    <th>Quality</th>
                    <th>Source file</th>
                    <th>Uploaded</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {dataset.versions.map((version) => (
                    <tr key={version.id} className={activeVersionId === version.id ? "active-version" : ""}>
                      <td>
                        <strong>{version.version_label}</strong>
                        {version.is_current && <small>current</small>}
                      </td>
                      <td><span className={`status-badge ${version.status}`}>{version.status}</span></td>
                      <td>{version.record_count.toLocaleString()}</td>
                      <td>
                        <details className="quality-details">
                          <summary>
                            <span className="quality-dot passed">{version.quality_summary.passed}</span>
                            <span className="quality-dot warning">{version.quality_summary.warning}</span>
                            <span className="quality-dot failed">{version.quality_summary.failed}</span>
                          </summary>
                          <div className="quality-popover">
                            {version.quality_checks.map((check) => (
                              <div key={check.id} className={check.status}>
                                <span>{check.status === "passed" ? "✓" : check.status === "warning" ? "!" : "×"}</span>
                                <p><strong>{check.check_name}</strong><small>{check.details}</small></p>
                              </div>
                            ))}
                          </div>
                        </details>
                      </td>
                      <td><span className="filename">{version.source_filename}</span><small>{formatBytes(version.file_size)}</small></td>
                      <td>
                        {version.created_at ? dateFormatter.format(new Date(version.created_at)) : "—"}
                        <small>{version.uploaded_by}</small>
                      </td>
                      <td>
                        <div className="row-actions">
                          <a href={version.download_url}>Download</a>
                          {version.status === "validated" && <a href="/data/catalog">Review in Data Hub</a>}
                          {version.analysis_ready && (
                            <button type="button" className="use-button" onClick={() => onUseVersion(version.id)}>
                              {activeVersionId === version.id ? "Selected" : "Use in analysis"}
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

export default DataCatalogSection;
