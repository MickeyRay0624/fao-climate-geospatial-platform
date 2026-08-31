import type { Catalog } from "../types";

type Props = {
  catalog: Catalog;
  onClose: () => void;
};

function MethodModal({ catalog, onClose }: Props) {
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        className="method-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="method-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="modal-heading">
          <div>
            <p className="section-kicker">Audit trail</p>
            <h2 id="method-title">Method and demonstration datasets</h2>
          </div>
          <button type="button" className="icon-button" onClick={onClose} aria-label="Close method information">
            ×
          </button>
        </div>

        <div className="formula-card">
          <strong>{catalog.method.name}</strong>
          <code>{catalog.method.formula}</code>
          <p>{catalog.method.missing_value_policy}</p>
        </div>

        <div className="dataset-table" role="table" aria-label="Demonstration datasets">
          {catalog.datasets.map((dataset) => (
            <article key={dataset.indicator_code} role="row">
              <i style={{ background: catalog.indicators[dataset.indicator_code].colour }} />
              <div>
                <strong>{dataset.title}</strong>
                <span>{dataset.source_label} · {dataset.last_updated}</span>
                <p>{dataset.methodology}</p>
              </div>
              <b>{dataset.is_synthetic ? "Synthetic" : "Validated"}</b>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}

export default MethodModal;

