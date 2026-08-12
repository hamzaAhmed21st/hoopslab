# HoopsLab architecture

## Current boundary

HoopsLab currently provides a reproducible path from six immutable external
shot snapshots through normalized PostgreSQL storage to local feature and split
artifacts and a locked local model. FastAPI and React product surfaces are
deliberate later boundaries.

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
bin counts, and observed-versus-expected slices are required outputs.

## Held-out evaluation

After the procedure was locked, the selected `hgb-lr0.05-leaves15-sigmoid`
model was evaluated once on the 2023-24 regular season: 218,701 shots across
1,230 whole games from 2023-10-24 through 2024-04-14. Its log loss was
0.637055, Brier score 0.224358, ROC-AUC 0.657832, and fixed ten-bin ECE
0.006517. The locked `logistic-c1-isotonic` comparator recorded 0.642787,
0.226538, 0.650390, and 0.006944 respectively. The selected-minus-logistic
deltas were -0.005732 log loss and -0.002180 Brier.

The 300-replicate whole-game bootstrap gave selected-model 95% intervals of
[0.635614, 0.638626] for log loss and [0.223689, 0.225034] for Brier. Paired
selected-minus-logistic intervals were [-0.006609, -0.004852] and
[-0.002405, -0.001898]. The small ECE improvement is a calibration diagnostic,
not proof of uniformly calibrated probabilities in every context.

Predeclared slices show useful discrimination on attempts under 8 ft (log loss
0.601507, ROC-AUC 0.709850, ECE 0.015320), but weaker separation for threes
(0.653231, 0.529290, 0.007230) and midrange: 16–24 ft (0.675261, 0.515300,
0.021970) and 8–16 ft (0.682896, 0.538960, 0.014490). These are reported as
weak slices too, rather than selectively highlighting favorable contexts.

Selection-only descriptive checks ranked `action_type` (0.059650) and source
distance (0.021330) as the largest deterministic permutation decreases in
negative log loss. Predicted versus observed make rates were 0.651/0.669 close
to the basket and 0.359/0.355 at 25+ ft. The 4–8 ft versus 9–16 ft pattern
indicates feature interaction rather than a causal effect; no feature-importance
or distance claim is causal.

The model remains a coarse contextual contract: it intentionally excludes
player, team, and opponent identities and lacks score, defender, lineup, and
venue context. Weak midrange and three-point discrimination are material limits
for later analysis, not reasons to reopen the locked held-out evaluation.

## Frozen modeling protocol

Modeling uses exactly the 13 feature-contract inputs: six numeric geometry or
clock fields, `shooter_is_home`, and six categorical action/type/zone fields.
The target and all identifiers are excluded before every estimator fit. The
loader validates the Parquet schema and metadata, hashes both feature and split
artifacts, predicate-loads only explicitly authorized development seasons, and
cannot load 2023-24 through a development entry point.

Internal tuning uses whole-season chronological folds: train 2018-19 / validate
2019-20; train 2018-20 / validate 2020-21; and train 2018-21 / validate
2021-22. Each family is selected by mean unrounded fold log loss, mean Brier,
fold log-loss standard deviation, ROC-AUC, and stable lower-complexity ID.

The final 2022-23 validation season has a fixed chronological boundary. Games
through 2023-01-10 inclusive fit only calibrators; games from 2023-01-11 through
2023-04-09 independently select family, hyperparameters, and calibration.
Base estimators fit only 2018-19 through 2021-22. Calibration candidates are
none, sigmoid, and isotonic; frozen estimators prevent calibration from
refitting bases.

The logistic pipeline scales the six numeric fields, passes the home boolean,
and learns one-hot categories with unknown-category ignore behavior. Its only
grid is L2 `C` in 0.1, 1, and 10. Histogram gradient boosting uses train-fitted
ordinal categories with unknown/missing values represented as `NaN` and an
explicit categorical mask, never ordinal codes as continuous quantities. Its
bounded grid is learning rate 0.05/0.10 by 15/31 leaves, with 300 iterations,
100 minimum leaf samples, L2=1, and early stopping disabled.

Independent selection ranks selection log loss, Brier, fixed ten-bin ECE, mean
qualifying slice ECE, fold stability, then ROC-AUC. Exact ties prefer logistic,
no calibration, then lexical ID. Predeclared slices require at least 2,000 rows:
shot type, zone range, periods 1–4/5+, home/away, and four remaining-clock
buckets. The final report uses a 300-replicate whole-game bootstrap with seed
20260813 for selected and paired selected-minus-logistic log loss/Brier CIs.

`develop_model.py` writes an ignored local joblib bundle, adjacent portable
manifest, and explicit `pending_review` selection record. It records the full
selected and logistic-comparator variants, independent selection metrics,
runner-up deltas, segments, folds, fitted-preprocessing identity, hashes,
versions, seeds, and a no-test-access assertion. `lock_model.py` is a separate
coordinator-authorization action: it validates the records and bundle and
atomically changes only a valid pending record to `locked`. `evaluate_model.py`
validates that locked record and bundle before loading 2023-24, and refuses to
overwrite a final test report. This lets the analytics API load the selected
bundle without retraining while retaining a one-time held-out evaluation
boundary.

Final evaluation creates an ignored atomic `.final-test-reservation.json` marker
before hashing or loading test features. A pre-access validation failure releases
the marker; a failure after test loading retains it, deliberately requiring human
review before another attempt. Completed reports use atomic replacement.

Development split validation reads only the leading, chronologically ordered
2018-19 through 2022-23 game assignments, then closes before the first held-out
game object. This boundary relies on the frozen split writer's `sort_keys=True`
key order and chronological game ordering; the full split-file SHA-256 remains
part of the locked artifact identity.

## Generated artifacts

Raw/processed data, PostgreSQL volumes, feature matrices, trained models, ML
caches, and evaluation outputs are ignored. The local modeling manifest records
source/feature identities, feature/schema version, split boundaries, package
versions, seeds, parameters, metrics, artifact SHA-256, and training time.
