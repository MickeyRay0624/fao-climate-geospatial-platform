import { useEffect, useMemo, useState } from "react";

import { exportUrl } from "../api";
import type { AnalysisResponse, AreaResult, Catalog } from "../types";
import FactorChart from "./FactorChart";

type Props = {
  catalog: Catalog;
  analysis: AnalysisResponse;
  selected: AreaResult | null;
  onSelect: (area: AreaResult) => void;
};

const number = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const PAGE_SIZE = 12;

function RankingPanel({ catalog, analysis, selected, onSelect }: Props) {
  const [page, setPage] = useState(1);
  useEffect(() => setPage(1), [analysis.run_id]);

  const pageCount = Math.max(1, Math.ceil(analysis.ranking.length / PAGE_SIZE));
  const pageRows = useMemo(
    () => analysis.ranking.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE),
    [analysis.ranking, page],
  );
  const topDrivers = selected
    ? Object.entries(selected.components)
        .sort(([, left], [, right]) => right.contribution - left.contribution)
        .slice(0, 3)
    : [];

  return (
    <section id="analysis-results" className="page-section results-section">
      <div className="section-title-row">
        <div>
          <p className="section-kicker">Saved analysis output · Run #{analysis.run_id}</p>
          <h2>Priority results and decision trace</h2>
          <p className="muted compact">
            Based on {analysis.dataset_version.dataset_name} · {analysis.dataset_version.version_label} · checksum {analysis.dataset_version.checksum_sha256.slice(0, 10)}
          </p>
        </div>
        <div className="export-actions large">
          <a href={exportUrl(analysis.run_id, "csv")}>Export CSV</a>
          <a href={exportUrl(analysis.run_id, "geojson")}>Export GeoJSON</a>
        </div>
      </div>

      <div className="result-summary-grid">
        <article><span>Total areas</span><strong>{analysis.summary.total_areas}</strong></article>
        <article><span>Eligible</span><strong>{analysis.summary.eligible_areas}</strong></article>
        <article><span>Excluded</span><strong>{analysis.summary.excluded_areas}</strong></article>
        <article><span>Average score</span><strong>{analysis.summary.average_score}</strong></article>
        <article><span>Top-10 rice area</span><strong>{number.format(analysis.summary.top_10_rice_area_ha)} ha</strong></article>
      </div>

      {selected && (
        <div className="selected-analysis panel">
          <div className="selected-identity">
            <div className="detail-title-row">
              <div>
                <p className="section-kicker">Selected commune</p>
                <h3>{selected.name}</h3>
                <p>{selected.province} · {number.format(selected.rice_area_ha)} ha rice · {number.format(selected.population)} people</p>
              </div>
              <div className={`score-orb ${selected.eligible ? "" : "excluded"}`}>
                <strong>{selected.eligible ? selected.score.toFixed(1) : "—"}</strong>
                <small>{selected.eligible ? `rank ${selected.rank}` : "excluded"}</small>
              </div>
            </div>
            <div className="drivers">
              <span>Strongest score contributions</span>
              {topDrivers.map(([code, component]) => (
                <div key={code}>
                  <i style={{ background: catalog.indicators[code].colour }} />
                  <p><strong>{catalog.indicators[code].short_label}</strong><small>value {component.value === null ? "missing" : `${(component.value * 100).toFixed(0)}/100`}</small></p>
                  <b>+{component.contribution.toFixed(1)}</b>
                </div>
              ))}
            </div>
            <div className="quality-row">
              <span>Data completeness</span>
              <div><i style={{ width: `${selected.data_completeness * 100}%` }} /></div>
              <strong>{(selected.data_completeness * 100).toFixed(0)}%</strong>
            </div>
            {selected.missing_indicators.length > 0 && (
              <p className="quality-warning">Missing: {selected.missing_indicators.map((code) => catalog.indicators[code].short_label).join(", ")}.</p>
            )}
          </div>
          <div className="selected-chart">
            <p className="section-kicker">Contribution to composite score</p>
            <FactorChart area={selected} catalog={catalog} />
          </div>
        </div>
      )}

      <div className="ranking-table-card panel">
        <div className="ranking-table-heading">
          <div><p className="section-kicker">Prioritised worklist</p><h3>Eligible communes</h3></div>
          <span>Page {page} of {pageCount}</span>
        </div>
        <div className="ranking-table-wrap">
          <table className="ranking-table">
            <thead><tr><th>Rank</th><th>Commune</th><th>Province</th><th>Priority</th><th>Score</th><th>Rice area</th><th>Completeness</th></tr></thead>
            <tbody>
              {pageRows.map((area) => (
                <tr key={area.id} className={selected?.id === area.id ? "selected" : ""} onClick={() => onSelect(area)}>
                  <td><span className="rank-number">{area.rank}</span></td>
                  <td><strong>{area.name}</strong><small>{area.code}</small></td>
                  <td>{area.province}</td>
                  <td><span className={`priority-pill ${area.priority_band.toLowerCase().replace(" ", "-")}`}>{area.priority_band}</span></td>
                  <td><b>{area.score.toFixed(1)}</b></td>
                  <td>{number.format(area.rice_area_ha)} ha</td>
                  <td>{(area.data_completeness * 100).toFixed(0)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="pagination">
          <button type="button" onClick={() => setPage((current) => Math.max(1, current - 1))} disabled={page === 1}>Previous</button>
          <span>{(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, analysis.ranking.length)} of {analysis.ranking.length}</span>
          <button type="button" onClick={() => setPage((current) => Math.min(pageCount, current + 1))} disabled={page === pageCount}>Next</button>
        </div>
      </div>
    </section>
  );
}

export default RankingPanel;

