import type { ShotPage } from "../api/types";
import {
  COURT_SVG,
  courtToSvg,
  isInsideCourtView,
  restrictedAreaPath,
  threePointPath,
} from "../lib/court";
import { formatDate, formatProbability } from "../lib/format";
import { pageScope } from "../lib/shotScope";

type ShotChartProps = {
  page: ShotPage;
};

function rectFromCourt(minX: number, maxY: number, maxX: number, minY: number) {
  const topLeft = courtToSvg(minX, maxY);
  const bottomRight = courtToSvg(maxX, minY);
  return {
    x: topLeft.x,
    y: topLeft.y,
    width: bottomRight.x - topLeft.x,
    height: bottomRight.y - topLeft.y,
  };
}

export function ShotChart({ page }: ShotChartProps) {
  const visible = page.items.filter((shot) =>
    isInsideCourtView(shot.coordinate_x_ft, shot.coordinate_y_ft),
  );
  const omitted = page.items.length - visible.length;
  const court = rectFromCourt(-25, 42.25, 25, -4.75);
  const paint = rectFromCourt(-8, 15, 8, -4.75);
  const backboardLeft = courtToSvg(-3, -0.5);
  const backboardRight = courtToSvg(3, -0.5);
  const hoop = courtToSvg(0, 0);
  const freeThrow = courtToSvg(0, 15);

  return (
    <section className="chart-panel" aria-labelledby="chart-title">
      <div className="section-heading chart-heading">
        <div>
          <p className="eyebrow">Newest-first page</p>
          <h2 id="chart-title">Shot locations</h2>
        </div>
        <div className="chart-scope">
          <strong>{pageScope(page)}</strong>
          <span>Summary above covers the full filtered population.</span>
        </div>
      </div>

      <div className="chart-layout">
        <div className="court-shell">
          <svg
            className="shot-chart"
            viewBox="0 0 500 475"
            role="img"
            aria-labelledby="chart-title chart-description"
          >
            <desc id="chart-description">
              Half-court shot chart. Filled circles are makes and crosses are misses.
              The table below provides the same shots in text.
            </desc>
            <g className="court-lines" aria-hidden="true">
              <rect {...court} />
              <line x1={COURT_SVG.left} y1={COURT_SVG.top} x2={COURT_SVG.left + COURT_SVG.width} y2={COURT_SVG.top} />
              <rect {...paint} />
              <circle cx={freeThrow.x} cy={freeThrow.y} r={(6 / 50) * COURT_SVG.width} />
              <line x1={backboardLeft.x} y1={backboardLeft.y} x2={backboardRight.x} y2={backboardRight.y} />
              <circle cx={hoop.x} cy={hoop.y} r={(0.75 / 50) * COURT_SVG.width} className="hoop" />
              <path d={restrictedAreaPath()} />
              <path d={threePointPath()} />
              <path
                className="center-arc"
                d={`M ${courtToSvg(-6, 42.25).x} ${COURT_SVG.top} A ${(6 / 50) * COURT_SVG.width} ${(6 / 47) * COURT_SVG.height} 0 0 0 ${courtToSvg(6, 42.25).x} ${COURT_SVG.top}`}
              />
            </g>
            <g className="shot-marks">
              {visible.map((shot) => {
                const point = courtToSvg(shot.coordinate_x_ft, shot.coordinate_y_ft);
                const outcome = shot.made ? "Made" : "Missed";
                const label = `${outcome} ${shot.shot_type}, ${shot.shot_distance_ft} feet, ${formatProbability(shot.make_probability)} expected, ${formatDate(shot.game_date)}`;
                return (
                  <g
                    key={`${shot.game_id}-${shot.event_id}`}
                    className={shot.made ? "shot-made" : "shot-missed"}
                    tabIndex={0}
                    role="img"
                    aria-label={label}
                  >
                    <title>{label}</title>
                    {shot.made ? (
                      <circle cx={point.x} cy={point.y} r="4.5" />
                    ) : (
                      <>
                        <line x1={point.x - 4} y1={point.y - 4} x2={point.x + 4} y2={point.y + 4} />
                        <line x1={point.x + 4} y1={point.y - 4} x2={point.x - 4} y2={point.y + 4} />
                      </>
                    )}
                  </g>
                );
              })}
            </g>
          </svg>
        </div>
        <aside className="chart-legend" aria-label="Shot chart legend">
          <div><span className="legend-made" aria-hidden="true" /> Made</div>
          <div><span className="legend-missed" aria-hidden="true">×</span> Missed</div>
          <p>Basket at (0, 0). Coordinates are feet; y runs away from the basket.</p>
          {omitted > 0 ? (
            <p className="omitted-note">
              {omitted} current-page {omitted === 1 ? "shot is" : "shots are"} outside
              the physical half-court view and omitted from the chart only.
            </p>
          ) : (
            <p>No current-page shots are omitted from the court view.</p>
          )}
        </aside>
      </div>
    </section>
  );
}
