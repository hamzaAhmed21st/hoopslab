import type { ShotQualitySummary } from "../api/types";
import { formatPercentagePoints, formatPercent } from "../lib/format";

type SummaryProps = {
  summary: ShotQualitySummary;
};

export function Summary({ summary }: SummaryProps) {
  const metrics = [
    { label: "Shot attempts", value: summary.attempts.toLocaleString("en-US") },
    { label: "Actual FG%", value: formatPercent(summary.actual_fg_pct) },
    { label: "Expected FG%", value: formatPercent(summary.expected_fg_pct) },
    {
      label: "Actual − expected",
      value: formatPercentagePoints(summary.actual_minus_expected_fg_pct),
      tone:
        summary.actual_minus_expected_fg_pct === null
          ? "neutral"
          : summary.actual_minus_expected_fg_pct >= 0
            ? "positive"
            : "negative",
    },
  ];
  return (
    <section aria-labelledby="summary-title">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Full filtered population</p>
          <h2 id="summary-title">Shooting against context</h2>
        </div>
        <p>
          Expected FG% is the locked model’s contextual make probability—not a
          causal measure of player value.
        </p>
      </div>
      <dl className="summary-grid">
        {metrics.map((metric) => (
          <div className={`metric metric-${metric.tone ?? "neutral"}`} key={metric.label}>
            <dt>{metric.label}</dt>
            <dd>{metric.value}</dd>
          </div>
        ))}
      </dl>
      {summary.attempts === 0 ? (
        <p className="empty-note">No shots match this player and filter scope.</p>
      ) : null}
    </section>
  );
}
