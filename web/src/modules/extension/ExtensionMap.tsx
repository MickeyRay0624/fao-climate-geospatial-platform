import { useEffect, useRef } from "react";
import { defaults as defaultControls } from "ol/control/defaults.js";
import GeoJSON from "ol/format/GeoJSON";
import Map from "ol/Map";
import VectorLayer from "ol/layer/Vector";
import VectorSource from "ol/source/Vector";
import { Circle as CircleStyle, Fill, Stroke, Style } from "ol/style";
import View from "ol/View";

type MapData = {
  type: "FeatureCollection";
  features: Array<{
    type: "Feature";
    id: string;
    geometry: { type: "Point"; coordinates: number[] };
    properties: Record<string, unknown>;
  }>;
};

const priorityColours: Record<string, string> = {
  LOW: "#6a9a82",
  NORMAL: "#d19a42",
  HIGH: "#cb6948",
  URGENT: "#9e3434",
};

export default function ExtensionMap({ data }: { data: MapData }) {
  const node = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!node.current) return;
    const source = new VectorSource({
      features: new GeoJSON().readFeatures(data, {
        dataProjection: "EPSG:4326",
        featureProjection: "EPSG:3857",
      }),
    });
    const layer = new VectorLayer({
      source,
      style: (feature) => new Style({
        image: new CircleStyle({
          radius: 8,
          fill: new Fill({ color: priorityColours[String(feature.get("priority"))] ?? "#28786e" }),
          stroke: new Stroke({ color: "#fff", width: 2 }),
        }),
      }),
    });
    const map = new Map({
      target: node.current,
      layers: [layer],
      view: new View({ center: [11_670_000, 1_390_000], zoom: 6.3 }),
      controls: defaultControls({ attribution: false, rotate: false }),
    });
    const extent = source.getExtent();
    if (source.getFeatures().length && extent) map.getView().fit(extent, { padding: [45, 45, 45, 45], maxZoom: 9 });
    return () => map.setTarget(undefined);
  }, [data]);
  return <div className="extension-map-frame"><div ref={node} className="extension-map-canvas" aria-label="Approximate demonstration case map" /><span>APPROXIMATE DEMONSTRATION LOCATIONS · NO FARM COORDINATES</span></div>;
}
