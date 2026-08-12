import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import {
  errorMessage,
  getModel,
  getReadiness,
  getShotQuality,
  getShots,
} from "./api/client";
import type { AnalyticsFilters, Player } from "./api/types";
import { AsyncState } from "./components/AsyncState";
import { Filters } from "./components/Filters";
import { ModelDetails } from "./components/ModelDetails";
import { PlayerSearch } from "./components/PlayerSearch";
import { ShotChart } from "./components/ShotChart";
import { ShotTable } from "./components/ShotTable";
import { Summary } from "./components/Summary";
import { seasonLabel } from "./lib/format";

const DEFAULT_FILTERS: AnalyticsFilters = {
  season_start: 2023,
  shot_type: null,
  shooter_is_home: null,
};

function scopeLabel(player: Player, filters: AnalyticsFilters): string {
  const parts = [
    player.name,
    filters.season_start === null ? "all six seasons" : seasonLabel(filters.season_start),
  ];
  if (filters.shot_type) {
    parts.push(filters.shot_type === "2PT Field Goal" ? "2-point shots" : "3-point shots");
  }
  if (filters.shooter_is_home !== null) {
    parts.push(filters.shooter_is_home ? "home-designated" : "away-designated");
  }
  return parts.join(" · ");
}

export default function App() {
  const [selectedPlayer, setSelectedPlayer] = useState<Player | null>(null);
  const [filters, setFilters] = useState<AnalyticsFilters>(DEFAULT_FILTERS);
  const [offset, setOffset] = useState(0);

  const readiness = useQuery({
    queryKey: ["readiness"],
    queryFn: ({ signal }) => getReadiness(signal),
    retry: false,
    refetchInterval: 30_000,
  });
  const model = useQuery({
    queryKey: ["model"],
    queryFn: ({ signal }) => getModel(signal),
    retry: false,
    staleTime: Number.POSITIVE_INFINITY,
  });
  const playerId = selectedPlayer?.player_id;
  const summary = useQuery({
    queryKey: ["shot-quality", playerId, filters],
    queryFn: ({ signal }) => getShotQuality(playerId as number, filters, signal),
    enabled: playerId !== undefined,
    retry: false,
  });
  const shots = useQuery({
    queryKey: ["shots", playerId, filters, offset],
    queryFn: ({ signal }) => getShots(playerId as number, filters, offset, signal),
    enabled: playerId !== undefined,
    retry: false,
  });

  function selectPlayer(player: Player) {
    setSelectedPlayer(player);
    setOffset(0);
  }

  function clearPlayer() {
    setSelectedPlayer(null);
    setOffset(0);
  }

  function updateFilters(next: AnalyticsFilters) {
    setFilters(next);
    setOffset(0);
  }

  return (
    <>
      <header className="site-header">
        <div className="brand-lockup">
          <span className="brand-mark" aria-hidden="true">H</span>
          <div>
            <a href="#main" className="brand-name">HoopsLab</a>
            <p>NBA shot-quality analytics</p>
          </div>
        </div>
        <div
          className={`service-status ${readiness.isSuccess ? "status-ready" : "status-unavailable"}`}
          role="status"
        >
          <span aria-hidden="true" />
          {readiness.isPending
            ? "Checking analytics"
            : readiness.isSuccess
              ? "Analytics ready"
              : "Analytics not ready"}
          {readiness.isError ? (
            <button type="button" onClick={() => void readiness.refetch()}>
              Retry
            </button>
          ) : null}
        </div>
      </header>

      <main id="main">
        <section className="intro">
          <div>
            <p className="eyebrow">Context before outcome</p>
            <h1>See the shots behind the percentage.</h1>
            <p className="intro-copy">
              Compare a player’s actual field-goal rate with the make probability
              expected from shot location and game context.
            </p>
          </div>
          <p className="data-note">
            Six completed NBA seasons · 2018–19 through 2023–24 · newest shots first
          </p>
        </section>

        <section className="control-bar" aria-label="Dashboard controls">
          <PlayerSearch
            selectedPlayer={selectedPlayer}
            onSelect={selectPlayer}
            onClear={clearPlayer}
          />
          <Filters value={filters} disabled={!selectedPlayer} onChange={updateFilters} />
        </section>

        {!selectedPlayer ? (
          <section className="initial-state" aria-labelledby="initial-title">
            <div className="initial-court" aria-hidden="true">
              <span />
            </div>
            <div>
              <p className="eyebrow">Start an analysis</p>
              <h2 id="initial-title">Search for a player to open the court.</h2>
              <p>
                Choose a real NBA player, then refine the season, shot type, or
                team designation. No sample statistics are shown before selection.
              </p>
            </div>
          </section>
        ) : (
          <div className="dashboard" aria-live="polite">
            <div className="active-scope">
              <span>Active population</span>
              <strong>{scopeLabel(selectedPlayer, filters)}</strong>
            </div>

            {summary.isPending ? (
              <AsyncState title="Calculating full-population shot quality…" />
            ) : summary.isError ? (
              <AsyncState
                title={errorMessage(summary.error, "summary")}
                message="The chart and shot page remain independent."
                role="alert"
                onRetry={() => void summary.refetch()}
              />
            ) : summary.data ? (
              <Summary summary={summary.data} />
            ) : null}

            {shots.isPending ? (
              <AsyncState title="Loading the newest 100 shots…" />
            ) : shots.isError ? (
              <AsyncState
                title={errorMessage(shots.error, "player-analytics")}
                message="Summary results remain independent."
                role="alert"
                onRetry={() => void shots.refetch()}
              />
            ) : shots.data ? (
              <>
                <ShotChart page={shots.data} />
                <ShotTable page={shots.data} onOffsetChange={setOffset} />
              </>
            ) : null}
          </div>
        )}

        <section className="model-section" aria-label="Model context">
          {model.isPending ? (
            <p role="status">Loading locked-model context…</p>
          ) : model.isError ? (
            <AsyncState
              title={errorMessage(model.error, "general")}
              role="alert"
              onRetry={() => void model.refetch()}
            />
          ) : model.data ? (
            <ModelDetails model={model.data} />
          ) : null}
        </section>
      </main>

      <footer>
        <p>HoopsLab is a non-commercial analytics project using NBA public data.</p>
        <p>Expected FG% is contextual, not causal or defender-adjusted.</p>
      </footer>
    </>
  );
}
