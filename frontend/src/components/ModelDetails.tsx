import type { ModelMetadata } from "../api/types";

type ModelDetailsProps = {
  model: ModelMetadata;
};

export function ModelDetails({ model }: ModelDetailsProps) {
  const family = model.family
    .split("_")
    .map((word) => word[0]?.toUpperCase() + word.slice(1))
    .join(" ");
  const trainingSeasons = model.training_seasons
    .map((season) => `${season}–${String(season + 1).slice(-2)}`)
    .join(", ");

  return (
    <details className="model-details">
      <summary>How expected FG% is modeled</summary>
      <div className="model-details-grid">
        <div>
          <p className="eyebrow">Locked model</p>
          <h2>{family}</h2>
          <p>
            {model.calibration} calibrated · held-out {model.heldout_season}–
            {String(model.heldout_season + 1).slice(-2)} season · version{" "}
            <code>{model.model_version}</code>
          </p>
          <p>
            Trained on {trainingSeasons}; calibration and selection use{" "}
            {model.calibration_season}–
            {String(model.selection_season + 1).slice(-2)}. Inputs ({model.feature_names.length}):{" "}
            {model.feature_names.join(", ")}.
          </p>
        </div>
        <dl className="model-metrics">
          <div><dt>Log loss</dt><dd>{model.held_out_metrics.log_loss.toFixed(3)}</dd></div>
          <div><dt>Brier</dt><dd>{model.held_out_metrics.brier_score.toFixed(3)}</dd></div>
          <div><dt>ROC-AUC</dt><dd>{model.held_out_metrics.roc_auc.toFixed(3)}</dd></div>
          <div><dt>10-bin ECE</dt><dd>{model.held_out_metrics.ece.toFixed(3)}</dd></div>
        </dl>
      </div>
      <ul className="limitations">
        {model.limitations.map((limitation) => (
          <li key={limitation}>{limitation}</li>
        ))}
      </ul>
    </details>
  );
}
