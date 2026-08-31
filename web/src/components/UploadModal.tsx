import { useState, type FormEvent } from "react";

import { uploadDataVersion } from "../api";
import type { DataCatalogItem, UploadResult } from "../types";

type Props = {
  datasets: DataCatalogItem[];
  onClose: () => void;
  onComplete: (result: UploadResult) => void;
};

function UploadModal({ datasets, onClose, onComplete }: Props) {
  const [mode, setMode] = useState<"new" | "existing">("new");
  const [datasetId, setDatasetId] = useState(datasets[0]?.id ?? 0);
  const [datasetName, setDatasetName] = useState("");
  const [description, setDescription] = useState("");
  const [versionLabel, setVersionLabel] = useState("1.0.0");
  const [notes, setNotes] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!file) {
      setError("Choose a GeoJSON or CSV file first.");
      return;
    }
    if (mode === "existing" && !datasetId) {
      setError("Choose the dataset that this version belongs to.");
      return;
    }
    setSubmitting(true);
    setError(null);
    const formData = new FormData();
    formData.append("file", file);
    formData.append("version_label", versionLabel);
    formData.append("notes", notes);
    formData.append("uploaded_by", "Mickey Lei");
    if (mode === "existing") {
      formData.append("dataset_id", String(datasetId));
    } else {
      formData.append("dataset_name", datasetName);
      formData.append("description", description);
    }

    try {
      onComplete(await uploadDataVersion(formData));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Upload failed");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <form className="upload-modal" onSubmit={(event) => void submit(event)} onMouseDown={(event) => event.stopPropagation()}>
        <div className="modal-heading">
          <div>
            <p className="section-kicker">Controlled ingestion</p>
            <h2>Upload an analysis dataset version</h2>
            <p className="muted compact">The source file is retained before validation. Only validated versions can be published and analysed.</p>
          </div>
          <button type="button" className="icon-button" onClick={onClose} aria-label="Close upload">×</button>
        </div>

        <div className="mode-switch" role="group" aria-label="Dataset upload mode">
          <button type="button" className={mode === "new" ? "active" : ""} onClick={() => setMode("new")}>New dataset</button>
          <button type="button" className={mode === "existing" ? "active" : ""} onClick={() => setMode("existing")} disabled={!datasets.length}>New version of existing dataset</button>
        </div>

        <div className="upload-form-grid">
          {mode === "new" ? (
            <>
              <label>
                <span>Dataset name</span>
                <input required value={datasetName} onChange={(event) => setDatasetName(event.target.value)} placeholder="e.g. Cambodia rice indicators" />
              </label>
              <label>
                <span>Description</span>
                <input value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Purpose, geography and source" />
              </label>
            </>
          ) : (
            <label className="wide-field">
              <span>Existing dataset</span>
              <select value={datasetId} onChange={(event) => setDatasetId(Number(event.target.value))}>
                {datasets.map((dataset) => <option value={dataset.id} key={dataset.id}>{dataset.name}</option>)}
              </select>
            </label>
          )}
          <label>
            <span>Version label</span>
            <input required value={versionLabel} onChange={(event) => setVersionLabel(event.target.value)} placeholder="1.0.0" />
          </label>
          <label>
            <span>Source file</span>
            <input required type="file" accept=".geojson,.json,.csv,application/geo+json,text/csv" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
          </label>
          <label className="wide-field">
            <span>Version notes</span>
            <textarea value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="What changed, who supplied it, and any known limitations" />
          </label>
        </div>

        <div className="upload-requirements">
          <strong>Analysis bundle requirements</strong>
          <p>GeoJSON FeatureCollection, or CSV with <code>geometry_wkt</code>. Required properties: code, name, province, rice_area_ha, and all seven 0–1 indicators. Population and data_quality are optional.</p>
          <p>Maximum file size for this local MVP: 25 MB. Larger rasters will use a separate ingestion route later.</p>
        </div>

        {error && <div className="form-error" role="alert">{error}</div>}
        <div className="modal-actions">
          <button type="button" className="secondary-button" onClick={onClose}>Cancel</button>
          <button type="submit" className="primary-button" disabled={submitting}>{submitting ? "Storing and validating…" : "Upload and validate"}</button>
        </div>
      </form>
    </div>
  );
}

export default UploadModal;

