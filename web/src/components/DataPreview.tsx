import { useEffect, useRef, useState } from "react";
import { defaults as defaultControls } from "ol/control/defaults.js";
import GeoJSON from "ol/format/GeoJSON";
import Map from "ol/Map";
import VectorLayer from "ol/layer/Vector";
import VectorSource from "ol/source/Vector";
import { Fill, Stroke, Style } from "ol/style";
import View from "ol/View";

import type { VersionPreview } from "../platform/types";

function GenericVectorPreview({ data }: { data: VersionPreview }) {
  const target = useRef<HTMLDivElement | null>(null);
  const [selected, setSelected] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    if (!target.current || !data.preview || typeof data.preview !== "object") return;
    const source = new VectorSource({
      features: new GeoJSON().readFeatures(data.preview, {
        dataProjection: "EPSG:4326",
        featureProjection: "EPSG:3857",
      }),
    });
    const map = new Map({
      target: target.current,
      layers: [
        new VectorLayer({
          source,
          style: new Style({
            fill: new Fill({ color: "rgba(65, 129, 112, 0.42)" }),
            stroke: new Stroke({ color: "#245f55", width: 1.5 }),
          }),
        }),
      ],
      view: new View({ center: [11_680_000, 1_430_000], zoom: 6 }),
      controls: defaultControls({ attribution: false, rotate: false }),
    });
    if (source.getFeatures().length) {
      const extent = source.getExtent();
      if (extent) map.getView().fit(extent, { padding: [32, 32, 32, 32], maxZoom: 9 });
    }
    map.on("singleclick", (event) => {
      const feature = map.forEachFeatureAtPixel(event.pixel, (candidate) => candidate);
      setSelected(feature ? (feature.getProperties() as Record<string, unknown>) : null);
    });
    return () => map.setTarget(undefined);
  }, [data.preview]);

  return (
    <div className="generic-map-layout">
      <div>
        <div ref={target} className="generic-map" role="img" aria-label="Authorised vector feature preview" />
        <p className="preview-caption">
          {data.simplified ? "Display geometry is simplified; the source asset is unchanged." : "Source geometry preview."}
          {data.display_cap ? ` Display is capped at ${data.display_cap.toLocaleString()} features.` : ""}
        </p>
      </div>
      <aside className="preview-properties">
        <h3>Selected feature</h3>
        {selected ? (
          <dl>{Object.entries(selected).filter(([key]) => key !== "geometry").slice(0, 16).map(([key, value]) => <div key={key}><dt>{key.replaceAll("_", " ")}</dt><dd>{typeof value === "object" ? "Structured value" : String(value ?? "—")}</dd></div>)}</dl>
        ) : <p>Select a feature on the map to inspect its authorised properties.</p>}
      </aside>
    </div>
  );
}

function TablePreview({ data }: { data: VersionPreview }) {
  const rows = Array.isArray(data.preview) ? data.preview as Array<Record<string, unknown>> : [];
  const columns = rows[0] ? Object.keys(rows[0]) : [];
  return (
    <div className="preview-table-wrap">
      <table className="preview-table"><thead><tr>{columns.map((column) => <th key={column}>{column.replaceAll("_", " ")}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={index}>{columns.map((column) => <td key={column}>{String(row[column] ?? "") || <span className="missing-cell">Missing</span>}</td>)}</tr>)}</tbody></table>
      {!rows.length && <p className="inline-empty">No rows are available on this page.</p>}
    </div>
  );
}

export default function DataPreview({ data, onPage }: { data: VersionPreview; onPage: (page: number) => void }) {
  const pages = Math.max(1, Math.ceil(data.page.total / data.page.size));
  return (
    <div className="data-preview">
      <div className="preview-evidence-strip"><span><b>{data.page.total.toLocaleString()}</b> records</span><span><b>{data.crs ?? "Not applicable"}</b> CRS</span><span><b>{data.geometry_type ?? data.preview_kind}</b> representation</span><span><b>{data.source_asset_unchanged ? "Yes" : "Unknown"}</b> source unchanged</span></div>
      {data.preview_kind === "vector" ? <GenericVectorPreview data={data} /> : data.preview_kind === "table" ? <TablePreview data={data} /> : <pre className="json-preview">{JSON.stringify(data.preview, null, 2)}</pre>}
      <footer className="preview-pagination"><button type="button" disabled={data.page.number <= 1} onClick={() => onPage(data.page.number - 1)}>← Previous</button><span>Page {data.page.number} of {pages}</span><button type="button" disabled={data.page.number >= pages} onClick={() => onPage(data.page.number + 1)}>Next →</button></footer>
    </div>
  );
}
