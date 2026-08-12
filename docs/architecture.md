# HoopsLab architecture

## Current boundary

HoopsLab currently provides a reproducible path from six immutable external
shot snapshots through normalized PostgreSQL storage to local feature and split
artifacts. Model training, FastAPI, and React are deliberate later boundaries.

```text
Pinned revision + six asset SHA-256 values
                 |
                 v
       ignored raw Parquet cache
                 |
        hash + schema validation
                 |
       typed full-row validation
                 |
                 v
 teams   players   games -- game_teams
    \       |       \         /
     \      |        \       /
                    shots
                 |
  quality checks + feature contract
                 |
    whole-game chronological splits
```

## Source and ingestion contract

The primary delivery path is the NBA Data Archive's per-season `shotdetail`
Parquet layout. The tracked manifest identifies regular seasons 2018-19 through
2023-24 using dataset revision
`328e29170d2b338105cbd8f61fae129dcad4b754`, exact paths, SHA-256 values, and
observed row-count checks. It provides one attempt per row with game/event,
player/team, period/clock, result, action/shot/zone, distance, legacy court
coordinates, date, and home/visitor codes. The upstream `shufinskiy/nba_data`
archive remains the fallback delivery path for the same lineage.

Direct NBA.com requests are not the bootstrap path: the endpoints have no
supported public stability or rate-limit contract, and a historical rebuild
would make many fragile calls. Source files remain outside Git. Only synthetic
fixtures exercise the tracked test suite.

Raw rows and application data are separate contracts. PyArrow checks required
column presence and broad physical types; Pydantic validates every ingested row,
including identifiers, redundant make/miss encoding, period clocks, court
extents, shot types, dates, and season metadata. Legacy `LOC_X`/`LOC_Y` integers
are stored explicitly as tenths of a foot; `SHOT_DISTANCE` remains whole feet.
Negative Y is valid behind the basket.

Each season uses two streaming passes with 1,024-row Parquet batches. The first
resolves entities and game-team roles; the second writes 5,000-shot database
batches. Teams and players use source-ID upserts. Games, participants, and shots
are inserted in one season transaction, so any invalid row or database failure
rolls the season back. A durable `ingestion_runs` record remains `failed` with
the error, becomes `completed` only with exact source/normalized counts, or is
recorded as `skipped` when the identical source was already completed. A new
hash for an already completed season is refused rather than merged silently.

## Relational model

- `teams(source_team_id, name)` and `players(source_player_id, full_name)` keep
  stable source identities separate from attempts.
- `games(source_game_id, game_date, season_start, season_type,
  home_team_code, away_team_code)` is the chronological split boundary. Raw
  codes remain provenance, not model inputs.
- `game_teams(game_id, team_id, team_code, is_home)` resolves exactly one home
  and one away source team per game.
- `shots` uses `(game_id, event_id)` as its primary key, preventing duplicate
  source attempts. Composite foreign keys ensure the shooter and opponent are
  game participants and that `shooter_is_home` matches the resolved role.
- `ingestion_runs` records immutable source identity, status, times, counts,
  normalization version, and failures without becoming a workflow engine.

Checks reject invalid season types, impossible clocks and court coordinates,
inconsistent 2PT/3PT values, and self-matched games. Names are descriptive
attributes; source numeric IDs and the composite event key establish identity.
Team-code resolution uses intersections of each stable `TEAM_ID`'s actual game
codes across a season. It fails unless every ID maps uniquely and every game has
exactly two shooting teams matching its home/visitor codes; display names are
never parsed for identity.

## Prediction and leakage boundary

The prediction is: given only information available immediately when a
field-goal attempt occurs, what is the probability that it is made? The binary
made/missed flag is the target.

The feature artifact converts coordinates to feet and adds only deterministic
shot angle. It retains the source's rounded distance rather than adding a second
derived radial-distance representation. Model inputs are coordinates, source distance, angle, period, time
remaining, `shooter_is_home`, action/type/zone categories, and season type.
Game/event/date/season/player/team/opponent identifiers remain in explicit
debug/split columns; the target remains separate. A contract test prevents raw
team codes, identities, target, and outcome/post-shot concepts from entering
the model-input list. Encoding, scaling, imputation, and all other learned
preprocessing remain unfitted until training and will fit on training data only.

Outcome/result text, points produced, post-shot scores, later events or
possessions, final game outcomes, and any aggregate fitted with validation/test
shots are prohibited. Score margin is absent from `shotdetail`; it remains
excluded until an event-level play-by-play join can prove that it represents the
score immediately before the attempt. Learned preprocessing is fit on training
data only.

## Model and evaluation path

The generated JSON manifest assigns 2018-19 through 2021-22 to training,
2022-23 to validation, and 2023-24 to the untouched test split. Assignment uses
season and whole-game IDs only, never outcomes. Artifact validation proves every
feature row has exactly one game assignment, no game crosses splits, seasons
match, and ordering is stable by game date, game ID, and event ID.

The 2019-20 source correctly extends through August 2020 and contains fewer
games; 2020-21 is also shortened. Those rows are retained. The source provides
home/visitor designation but no arena or neutral-site flag, so during the 2020
bubble `shooter_is_home` means the nominal schedule role—not verified home-court
advantage. HoopsLab does not fabricate venue context.

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
