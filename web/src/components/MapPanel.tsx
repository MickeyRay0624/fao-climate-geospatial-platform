import { useEffect, useMemo, useRef } from "react";
import { defaults as defaultControls } from "ol/control/defaults.js";
import GeoJSON from "ol/format/GeoJSON";
import { defaults as defaultInteractions } from "ol/interaction/defaults.js";
import Map from "ol/Map";
import VectorLayer from "ol/layer/Vector";
import VectorSource from "ol/source/Vector";
import { Fill, Stroke, Style } from "ol/style";
import View from "ol/View";

import type { AreaResult, Catalog, GeoFeatureCollection } from "../types";

type Props = {
  catalog: Catalog;
  geojson: GeoFeatureCollection | null;
  metric: string;
  selectedId: string | number | null;
  datasetLabel: string;
  onMetricChange: (metric: string) => void;
  onSelect: (area: AreaResult) => void;
};

const PRIORITY_COLOURS = ["#eee9d3", "#d9d994", "#b5c06b", "#e1a246", "#bf5a2c"];

function colourFor(value: number | null, eligible = true): string {
  if (!eligible || value === null || Number.isNaN(value)) return "#d9dedb";
  const index = Math.min(PRIORITY_COLOURS.length - 1, Math.floor(value * 5));
  return PRIORITY_COLOURS[index];
}

function MapPanel({
  catalog,
  geojson,
  metric,
  selectedId,
  datasetLabel,
  onMetricChange,
  onSelect,
}: Props) {
  const mapNode = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<Map | null>(null);
  const vectorSourceRef = useRef(new VectorSource());
  const vectorLayerRef = useRef<VectorLayer<VectorSource> | null>(null);
  const metricRef = useRef(metric);
  const selectedIdRef = useRef(selectedId);
  const hasFitRef = useRef(false);

  metricRef.current = metric;
  selectedIdRef.current = selectedId;

  const legendLabel = useMemo(
    () => (metric === "priority" ? "Priority score" : catalog.indicators[metric]?.label),
    [catalog.indicators, metric],
  );

  useEffect(() => {
    if (!mapNode.current || mapRef.current) return;

    const vectorLayer = new VectorLayer({
      source: vectorSourceRef.current,
      style: (feature) => {
        const properties = feature.getProperties() as AreaResult;
        const rawValue =
          metricRef.current === "priority"
            ? properties.score / 100
            : properties.indicators?.[metricRef.current];
        const isSelected = String(feature.getId()) === String(selectedIdRef.current);
        return new Style({
          fill: new Fill({ color: colourFor(rawValue ?? null, properties.eligible) }),
          stroke: new Stroke({
            color: isSelected ? "#173f3b" : "rgba(255,255,255,0.82)",
            width: isSelected ? 3 : 1,
          }),
          zIndex: isSelected ? 10 : 1,
        });
      },
    });
    vectorLayerRef.current = vectorLayer;

    const map = new Map({
      target: mapNode.current,
      layers: [vectorLayer],
      view: new View({
        center: [11_688_000, 1_400_000],
        zoom: 6.3,
        minZoom: 5,
        maxZoom: 12,
      }),
      controls: defaultControls({ attribution: false, rotate: false }),
      interactions: defaultInteractions({ mouseWheelZoom: false }),
    });
    mapRef.current = map;

    map.on("singleclick", (event) => {
      const feature = map.forEachFeatureAtPixel(event.pixel, (candidate) => candidate);
      if (!feature) return;
      onSelect(feature.getProperties() as AreaResult);
    });
    map.on("pointermove", (event) => {
      if (!mapNode.current) return;
      mapNode.current.style.cursor = map.hasFeatureAtPixel(event.pixel) ? "pointer" : "grab";
    });

    return () => {
      map.setTarget(undefined);
      mapRef.current = null;
    };
  }, [onSelect]);

  useEffect(() => {
    const source = vectorSourceRef.current;
    source.clear();
    if (!geojson) return;
    const features = new GeoJSON().readFeatures(geojson, {
      dataProjection: "EPSG:4326",
      featureProjection: "EPSG:3857",
    });
    features.forEach((feature) => feature.setId(String(feature.get("id") ?? feature.getId() ?? feature.getProperties().id)));
    source.addFeatures(features);
    if (!hasFitRef.current && features.length && mapRef.current) {
      const extent = source.getExtent();
      if (extent) {
        mapRef.current.getView().fit(extent, {
          padding: [42, 42, 42, 42],
          duration: 450,
          maxZoom: 7.4,
        });
        hasFitRef.current = true;
      }
    }
  }, [geojson]);

  useEffect(() => {
    vectorLayerRef.current?.changed();
  }, [metric, selectedId, geojson]);

  return (
    <section className="map-panel panel">
      <div className="map-toolbar">
        <div>
          <p className="section-kicker">Priority surface</p>
          <strong>{legendLabel}</strong>
        </div>
        <label className="map-mode">
          <span>Map layer</span>
          <select value={metric} onChange={(event) => onMetricChange(event.target.value)}>
            <option value="priority">Composite priority</option>
            {Object.entries(catalog.indicators).map(([code, indicator]) => (
              <option value={code} key={code}>
                {indicator.label}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="map-frame">
        <div ref={mapNode} className="map-canvas" aria-label="Interactive priority map" />
        <div className="map-watermark">VERSIONED DATA · {datasetLabel}</div>
        <div className="legend" aria-label={`${legendLabel} legend`}>
          <span>Lower</span>
          <div className="legend-ramp">
            {PRIORITY_COLOURS.map((colour) => (
              <i key={colour} style={{ background: colour }} />
            ))}
          </div>
          <span>Higher</span>
          <i className="excluded-swatch" />
          <span>Excluded</span>
        </div>
        <div className="map-instruction">Page wheel remains available · use map buttons to zoom</div>
      </div>
    </section>
  );
}

export default MapPanel;
