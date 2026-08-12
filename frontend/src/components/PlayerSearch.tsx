import { useQuery } from "@tanstack/react-query";
import { useEffect, useId, useState } from "react";

import { errorMessage, searchPlayers } from "../api/client";
import type { Player } from "../api/types";

const SEARCH_DELAY_MS = 275;
const EMPTY_PLAYERS: Player[] = [];

function useDebouncedValue(value: string): string {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), SEARCH_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [value]);
  return debounced;
}

type PlayerSearchProps = {
  selectedPlayer: Player | null;
  onSelect: (player: Player) => void;
  onClear: () => void;
};

export function PlayerSearch({
  selectedPlayer,
  onSelect,
  onClear,
}: PlayerSearchProps) {
  const [input, setInput] = useState("");
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const debounced = useDebouncedValue(input.trim());
  const listboxId = useId();
  const query = useQuery({
    queryKey: ["players", debounced],
    queryFn: ({ signal }) => searchPlayers(debounced, signal),
    enabled: debounced.length >= 2,
    retry: false,
  });
  const players = query.data ?? EMPTY_PLAYERS;
  const effectiveActiveIndex =
    activeIndex >= 0 && activeIndex < players.length
      ? activeIndex
      : players.length > 0
        ? 0
        : -1;

  function choose(player: Player) {
    setInput(player.name);
    setOpen(false);
    onSelect(player);
  }

  return (
    <div className="player-search">
      <label htmlFor="player-search">Player</label>
      <div className="combobox-wrap">
        <input
          id="player-search"
          role="combobox"
          aria-autocomplete="list"
          aria-controls={listboxId}
          aria-expanded={open && debounced.length >= 2}
          aria-activedescendant={
            effectiveActiveIndex >= 0
              ? `${listboxId}-${effectiveActiveIndex}`
              : undefined
          }
          autoComplete="off"
          placeholder="Search an NBA player"
          value={input}
          onBlur={() => window.setTimeout(() => setOpen(false), 120)}
          onChange={(event) => {
            const next = event.target.value;
            setInput(next);
            setOpen(true);
            setActiveIndex(-1);
            if (selectedPlayer && next !== selectedPlayer.name) onClear();
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={(event) => {
            if (!open || players.length === 0) return;
            if (event.key === "ArrowDown") {
              event.preventDefault();
              setActiveIndex((current) => (current + 1) % players.length);
            } else if (event.key === "ArrowUp") {
              event.preventDefault();
              setActiveIndex(
                (current) => (current <= 0 ? players.length : current) - 1,
              );
            } else if (event.key === "Enter" && effectiveActiveIndex >= 0) {
              event.preventDefault();
              const player = players[effectiveActiveIndex];
              if (player) choose(player);
            } else if (event.key === "Escape") {
              setOpen(false);
            }
          }}
        />
        {selectedPlayer ? (
          <span className="selected-player-id">NBA ID {selectedPlayer.player_id}</span>
        ) : null}
      </div>

      {open && debounced.length >= 2 ? (
        <div className="search-popover">
          {query.isPending ? <p role="status">Searching players…</p> : null}
          {query.isError ? (
            <div className="compact-error" role="alert">
              <span>{errorMessage(query.error, "general")}</span>
              <button type="button" onClick={() => void query.refetch()}>
                Retry
              </button>
            </div>
          ) : null}
          {query.isSuccess && players.length === 0 ? (
            <p>No matching players.</p>
          ) : null}
          {players.length > 0 ? (
            <ul id={listboxId} role="listbox" aria-label="Player results">
              {players.map((player, index) => (
                <li
                  id={`${listboxId}-${index}`}
                  key={player.player_id}
                  role="option"
                  aria-selected={index === effectiveActiveIndex}
                  onClick={() => choose(player)}
                >
                  <span>{player.name}</span>
                  <small>NBA ID {player.player_id}</small>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
