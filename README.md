# HoopsLab

HoopsLab is an end-to-end basketball analytics and machine-learning project
built from six completed NBA regular seasons (2018-19 through 2023-24). It
combines reproducible, hash-pinned PostgreSQL ingestion; leakage-aware
attempt-time features and chronological whole-game splits; a locked contextual
shot-quality model served by FastAPI; and a React actual-versus-expected shot
chart.

Expected FG% is the model's contextual make probability for a shot—not a causal
estimate of player value, defender impact, or shot selection.

![HoopsLab dashboard showing LeBron James actual-versus-expected shooting and half-court shot locations](docs/images/hoopslab-dashboard.png)

## Architecture

```text
six pinned shotdetail Parquet seasons
  -> hash, schema, and row validation
  -> atomic normalized PostgreSQL ingestion
  -> local feature dataset + whole-game split manifest
  -> locally locked probability model and calibration workflow
  -> validated FastAPI inference + actual-vs-expected analytics
  -> React player search, shot-quality summary, court, and shot table
```

Ingestion validates the pinned revision, exact asset SHA-256, schema, and every
row before atomically writing a normalized season. Feature generation keeps the
binary outcome and identity/debug columns outside the 13-field model contract.
The estimator is trained, calibrated, selected, and finally evaluated across
chronologically separated seasons without splitting a game across boundaries.

See [docs/architecture.md](docs/architecture.md) for the relational contract,
leakage boundary, frozen modeling protocol, API runtime checks, and dashboard
coordinate semantics.

## Held-out result

The locked model was evaluated once on 218,701 shots from 1,230 whole games in
the held-out 2023-24 regular season. These measurements describe that fixed
evaluation; they are not a production-readiness or causal-performance claim.

| Model | Log loss | Brier | ROC-AUC | 10-bin ECE |
| --- | ---: | ---: | ---: | ---: |
| HGB, lr=0.05/leaves=15, sigmoid | 0.637055 | 0.224358 | 0.657832 | 0.006517 |
| Locked logistic, C=1, isotonic | 0.642787 | 0.226538 | 0.650390 | 0.006944 |

## Stack

- Backend: Python 3.13, uv, Pydantic, PyArrow, SQLAlchemy, Alembic, PostgreSQL,
  scikit-learn, FastAPI, pytest, Ruff, and mypy.
- Frontend: React, strict TypeScript, Vite, pnpm, TanStack Query, Vitest, and
  Testing Library.
- Runtime: separate FastAPI and nginx images composed with PostgreSQL; nginx
  provides the dashboard's same-origin `/api` and `/health` proxy.

## Data provenance

The source contract uses completed-season `shotdetail` Parquet snapshots from
the [NBA Data Archive](https://huggingface.co/datasets/cdechoch/nba-data-archive),
which mirrors Vladislav Shufinskiy's
[Apache-2.0 archive](https://github.com/shufinskiy/nba_data). Source revisions
and file hashes for the completed 2018-19 through 2023-24 regular seasons are
pinned in code before they are accepted. External source data and generated
feature/quality artifacts remain in ignored local directories.

The pinned revision and file hashes define which inputs HoopsLab accepts; raw
data and generated datasets remain outside Git. The underlying statistics
originate from NBA public services. HoopsLab is a non-commercial portfolio
project, attributes NBA.com, and does not redistribute the dataset, logos,
video, or play-by-play. Review the current
[NBA.com Terms of Use](https://www.nba.com/termsofuse) before reuse.

## Run locally

Requirements: uv, Docker with Compose, Git, Node.js 24 LTS, and pnpm 11.20.0.

```bash
uv sync --locked --all-groups
cd frontend && CI=true pnpm install --frozen-lockfile && cd ..
cp .env.example .env
docker compose up -d --wait db
uv run alembic upgrade head
```

To build the local database from the pinned source contract:

```bash
uv run python scripts/validate_source.py
uv run python scripts/ingest.py
uv run python scripts/data_quality.py
uv run python scripts/build_features.py
```

The locked model bundle and its lock/evaluation records are deliberately
ignored. When they are available under `artifacts/modeling/`, run the API and
dashboard in separate terminals:

```bash
make api
make frontend
```

Open the dashboard at `http://localhost:5173` and the generated API documentation
at `http://localhost:8000/docs`. To build the containerized stack instead:

```bash
make stack-up
```

Without the ignored locked artifacts, the API still starts and answers
`/health/live`, while readiness and model-dependent routes honestly return 503.
It never downloads, retrains, or substitutes a model at startup.

## Verification

```bash
make check
make test              # real PostgreSQL integration tests after migration
make frontend-check
docker compose config
```

CI repeats the locked backend/frontend checks against PostgreSQL and builds both
runtime images without requiring raw NBA data or the ignored locked model.

## Limitations

The model deliberately excludes player, team, and opponent identities and has
no score, defender, lineup, or verified venue context. Its discrimination is
weaker for three-point and midrange attempts, and `shooter_is_home` is only the
nominal schedule role during the 2020 bubble. Dashboard comparisons are
descriptive actual-versus-contextual-expected summaries, not causal player
rankings.
