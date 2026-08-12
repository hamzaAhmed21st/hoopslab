import type { ShotPage } from "../api/types";
import { formatDate, formatProbability } from "../lib/format";

const PAGE_SIZE = 100;
const MAX_OFFSET = 10_000;
const MAX_INSPECTABLE_ATTEMPTS = MAX_OFFSET + PAGE_SIZE;

type ShotTableProps = {
  page: ShotPage;
  onOffsetChange: (offset: number) => void;
};

export function ShotTable({ page, onOffsetChange }: ShotTableProps) {
  const { offset, total } = page.pagination;
  const canPrevious = offset > 0;
  const nextOffset = offset + PAGE_SIZE;
  const canNext = nextOffset < total && nextOffset <= MAX_OFFSET;
  const reachablePages =
    total === 0
      ? 0
      : Math.min(
          Math.ceil(total / PAGE_SIZE),
          MAX_INSPECTABLE_ATTEMPTS / PAGE_SIZE,
        );
  const currentPage = total === 0 ? 0 : Math.floor(offset / PAGE_SIZE) + 1;
  const hasInspectionBoundary = total > MAX_INSPECTABLE_ATTEMPTS;
  return (
    <section className="table-panel" aria-labelledby="shots-title">
      <div className="section-heading table-heading">
        <div>
          <p className="eyebrow">Accessible detail</p>
          <h2 id="shots-title">Shot inspection</h2>
        </div>
        <div className="pagination" aria-label="Shot page controls">
          <button
            type="button"
            disabled={!canPrevious}
            onClick={() => onOffsetChange(Math.max(0, offset - PAGE_SIZE))}
          >
            Newer
          </button>
          <span>
            Page {currentPage} of {reachablePages}
          </span>
          <button
            type="button"
            disabled={!canNext}
            onClick={() => onOffsetChange(nextOffset)}
          >
            Older
          </button>
          {hasInspectionBoundary ? (
            <span className="inspection-boundary">
              Inspection is limited to the newest{" "}
              {MAX_INSPECTABLE_ATTEMPTS.toLocaleString("en-US")} attempts.
            </span>
          ) : null}
        </div>
      </div>
      {page.items.length === 0 ? (
        <p className="empty-note">No shots are available on this page.</p>
      ) : (
        <div className="table-scroll">
          <table>
            <caption className="sr-only">
              Newest-first shots corresponding to the current court page
            </caption>
            <thead>
              <tr>
                <th scope="col">Date</th>
                <th scope="col">Result</th>
                <th scope="col">Expected</th>
                <th scope="col">Distance</th>
                <th scope="col">Action</th>
                <th scope="col">Zone</th>
              </tr>
            </thead>
            <tbody>
              {page.items.map((shot) => (
                <tr key={`${shot.game_id}-${shot.event_id}`}>
                  <td>{formatDate(shot.game_date)}</td>
                  <td><span className={`result-${shot.made ? "made" : "missed"}`}>{shot.made ? "● Made" : "× Missed"}</span></td>
                  <td>{formatProbability(shot.make_probability)}</td>
                  <td>{shot.shot_distance_ft} ft</td>
                  <td><strong>{shot.action_type}</strong><small>{shot.shot_type}</small></td>
                  <td><strong>{shot.shot_zone_basic}</strong><small>{shot.shot_zone_range}</small></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
