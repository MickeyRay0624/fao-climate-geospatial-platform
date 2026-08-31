import type { ComparisonResult } from "../types";

type Props = {
  results: ComparisonResult[];
  onClose: () => void;
};

function ComparisonModal({ results, onClose }: Props) {
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        className="comparison-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="comparison-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="modal-heading">
          <div>
            <p className="section-kicker">Sensitivity check</p>
            <h2 id="comparison-title">How priorities change by policy lens</h2>
            <p className="muted compact">
              A robust choice should remain important across more than one plausible scenario.
            </p>
          </div>
          <button type="button" className="icon-button" onClick={onClose} aria-label="Close comparison">
            ×
          </button>
        </div>

        <div className="comparison-grid">
          {results.map(({ key, label, response }) => (
            <article key={key}>
              <p>{label}</p>
              <strong>{response.summary.top_area?.name ?? "No eligible area"}</strong>
              <span>Highest-ranked commune · {response.summary.top_area?.score ?? "—"}</span>
              <dl>
                <div><dt>Eligible</dt><dd>{response.summary.eligible_areas}</dd></div>
                <div><dt>Average score</dt><dd>{response.summary.average_score}</dd></div>
              </dl>
              <ol>
                {response.ranking.slice(0, 5).map((area) => (
                  <li key={area.id}>
                    <span>{area.rank}</span>
                    <div>{area.name}</div>
                    <b>{area.score.toFixed(1)}</b>
                  </li>
                ))}
              </ol>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}

export default ComparisonModal;

