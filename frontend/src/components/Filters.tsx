import type { AnalyticsFilters } from "../api/types";
import { seasonLabel } from "../lib/format";

type FiltersProps = {
  value: AnalyticsFilters;
  disabled: boolean;
  onChange: (filters: AnalyticsFilters) => void;
};

const SEASONS = [2023, 2022, 2021, 2020, 2019, 2018];

export function Filters({ value, disabled, onChange }: FiltersProps) {
  return (
    <fieldset className="filters" disabled={disabled}>
      <legend>Shot population</legend>
      <label>
        Season
        <select
          aria-label="Season"
          value={value.season_start ?? "all"}
          onChange={(event) =>
            onChange({
              ...value,
              season_start:
                event.target.value === "all" ? null : Number(event.target.value),
            })
          }
        >
          <option value="all">All six seasons</option>
          {SEASONS.map((season) => (
            <option key={season} value={season}>
              {seasonLabel(season)}
            </option>
          ))}
        </select>
      </label>
      <label>
        Shot type
        <select
          aria-label="Shot type"
          value={value.shot_type ?? "all"}
          onChange={(event) =>
            onChange({
              ...value,
              shot_type:
                event.target.value === "all"
                  ? null
                  : (event.target.value as AnalyticsFilters["shot_type"]),
            })
          }
        >
          <option value="all">All field goals</option>
          <option value="2PT Field Goal">2-point</option>
          <option value="3PT Field Goal">3-point</option>
        </select>
      </label>
      <label>
        Team role
        <select
          aria-label="Team role"
          value={
            value.shooter_is_home === null
              ? "all"
              : String(value.shooter_is_home)
          }
          onChange={(event) =>
            onChange({
              ...value,
              shooter_is_home:
                event.target.value === "all"
                  ? null
                  : event.target.value === "true",
            })
          }
        >
          <option value="all">All roles</option>
          <option value="true">Home-designated</option>
          <option value="false">Away-designated</option>
        </select>
      </label>
    </fieldset>
  );
}
