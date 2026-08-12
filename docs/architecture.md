# HoopsLab architecture

## Current boundary

HoopsLab currently proves a reproducible path from an immutable external shot
snapshot to validated application records and a normalized PostgreSQL schema.
Model training, FastAPI, and React are deliberate later boundaries.

```text
Pinned source revision + asset SHA-256
                 |
                 v
       ignored raw Parquet cache
                 |
       physical schema validation
                 |
       typed row/domain validation
                 |
                 v
  teams      players      games
       \         |         /
        \        |        /
                 shots
                 |
         chronological features
                 |
     probability model + calibration
```

## Source and ingestion contract

The primary delivery path is the NBA Data Archive's standard, per-season
`shotdetail` Parquet layout. It provides one attempt per row with game/event,
player/team, period/clock, result, action/shot/zone, distance, legacy court
coordinates, date, and home/visitor codes. The archive repository revision and
each accepted file hash are immutable manifest data. The upstream
`shufinskiy/nba_data` archive is the fallback delivery path for the same
lineage.

Direct NBA.com requests are not the bootstrap path: the endpoints have no
supported public stability or rate-limit contract, and a historical rebuild
would make many fragile calls. Source files remain outside Git. Only synthetic
fixtures exercise the tracked test suite.

Raw rows and application data are separate contracts. PyArrow checks that all
required source columns exist; Pydantic then validates each row traversed by the
adapter, including identifiers, redundant make/miss encoding, period clocks,
court extents, shot types, dates, and season metadata. The validation command
intentionally traverses a bounded sample; a persistence pipeline must traverse
every ingested row. Legacy `LOC_X`/`LOC_Y` integers are stored explicitly as
tenths of a foot; `SHOT_DISTANCE` remains whole feet. Negative Y is valid behind
the basket.

## Relational model

- `teams(source_team_id, name)` and `players(source_player_id, full_name)` keep
  stable source identities separate from attempts.
- `games(source_game_id, game_date, season_start, season_type,
  home_team_code, away_team_code)` is the chronological split boundary and
  preserves source home/visitor context.
- `shots` uses `(game_id, event_id)` as its primary key, preventing duplicate
  source attempts. It references the game, player, and shooting team and stores
  pre-shot clock/location/type context plus the binary target.

Checks reject invalid season types, impossible clocks and court coordinates,
inconsistent 2PT/3PT values, and self-matched games. Names are descriptive
attributes; source numeric IDs and the composite event key establish identity.
The first schema does not invent an opponent team ID from a three-letter code.
A later audited team-reference enrichment can add that relationship and a
resolved home/away feature without rewriting source facts.

## Prediction and leakage boundary

The prediction is: given only information available immediately when a
field-goal attempt occurs, what is the probability that it is made? The binary
made/missed flag is the target.

Allowed feature categories are court coordinates and deterministic geometry,
shot distance, action/type/zone, period, time remaining, season type, and
validated home/away context. Shooter, team, and opponent identities are not
primary-model features: keeping them as aggregation dimensions makes the output
contextual expected FG%, which can be compared with actual player/team FG%.

Outcome/result text, points produced, post-shot scores, later events or
possessions, final game outcomes, and any aggregate fitted with validation/test
shots are prohibited. Score margin is absent from `shotdetail`; it remains
excluded until an event-level play-by-play join can prove that it represents the
score immediately before the attempt. Learned preprocessing is fit on training
data only.

## Model and evaluation path

The first cohort will use complete regular seasons 2018-19 through 2023-24:
2018-19 through 2021-22 for training, 2022-23 for chronological model selection
and calibration, and 2023-24 as the untouched test season. Boundaries are whole
games. Expanding-window, season-level backtests and game-block bootstrap
intervals will test stability.

A regularized logistic regression is the interpretable probability baseline.
The main MVP candidate is scikit-learn histogram gradient boosting over the
same feature contract. A more complex model advances only if it improves log
loss and Brier score without degrading overall or major-slice calibration.
ROC-AUC is secondary; accuracy is not a selection metric. Reliability diagrams,
bin counts, and observed-versus-expected slices are required outputs. No model
results exist yet.

## Generated artifacts

Raw/processed data, PostgreSQL volumes, feature matrices, trained models, ML
caches, and evaluation outputs are ignored. A future artifact manifest must
record source hashes, feature/schema version, split boundaries, environment
lock, parameters, metrics, and training time before any generated model is
versioned or served.
