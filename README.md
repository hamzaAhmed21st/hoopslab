# HoopsLab

HoopsLab is a basketball analytics project building toward a contextual NBA
shot-quality model and an interactive shot-analysis product. It currently
implements revision/hash-pinned multi-season ingestion, normalized PostgreSQL
storage, leakage-aware feature construction, deterministic chronological
splits, a locked shot-quality model, and a read-only FastAPI inference and
player-analytics service with a responsive React dashboard.

```text
six pinned shotdetail Parquet seasons
  -> hash, schema, and row validation
  -> atomic normalized PostgreSQL ingestion
  -> local feature dataset + whole-game split manifest
  -> locally locked probability model and calibration workflow
  -> validated FastAPI inference + actual-vs-expected analytics
  -> React player search, shot-quality summary, court, and shot table
```

The initial stack is Python 3.13, uv, Pydantic, PyArrow, SQLAlchemy/Alembic,
PostgreSQL, scikit-learn, FastAPI, pytest, Ruff, mypy, React, strict TypeScript,
Vite, pnpm, TanStack Query, Vitest, and Testing Library.

## Data source

The source contract uses completed-season `shotdetail` Parquet snapshots from
the [NBA Data Archive](https://huggingface.co/datasets/cdechoch/nba-data-archive),
which mirrors Vladislav Shufinskiy's
[Apache-2.0 archive](https://github.com/shufinskiy/nba_data). Source revisions
and file hashes for the completed 2018-19 through 2023-24 regular seasons are
pinned in code before they are accepted. External source data and generated
feature/quality artifacts remain in ignored local directories.

The underlying statistics originate from NBA public services. HoopsLab is a
non-commercial portfolio project, attributes NBA.com, and does not redistribute
the dataset, logos, video, or play-by-play. Review the current
[NBA.com Terms of Use](https://www.nba.com/termsofuse) before reuse or public
deployment.

## Local setup

Requirements: uv, Docker with Compose, Git, Node.js 22 or newer, and pnpm
11.20.0.

```bash
uv sync --locked --all-groups
cp .env.example .env
docker compose up -d --wait db
uv run alembic upgrade head
uv run python scripts/validate_source.py
uv run python scripts/ingest.py
uv run python scripts/data_quality.py
uv run python scripts/build_features.py
```

The validation command downloads six pinned regular-season files (about 13 MB
total), verifies every SHA-256 and schema, and parses bounded samples. Ingestion
then validates every row and commits each season atomically. Re-running the same
source records a safe skip rather than duplicating basketball data.

Run the local checks with:

```bash
make check
make test
make frontend-sync
make frontend-check
```

The modeling commands deliberately separate development from the final held-out
season. `make develop-model` uses only 2018-19 through 2022-23 and creates a
local `pending_review` record. After independent coordinator review,
`make lock-model` validates and atomically authorizes that exact bundle.
`make verify-model` checks the record and bundle without reading test rows.
`make evaluate-model` is the single guarded 2023-24 evaluation and refuses to
overwrite an existing test report.

## Local API

The API serves only an already locked local model. Its ignored model bundle,
manifest, selection lock, and final report must exist under
`artifacts/modeling/`; startup never downloads, retrains, or substitutes a
model. A fresh clone can still start and answer liveness, but readiness and
model-dependent routes remain unavailable until those artifacts are supplied by
the documented frozen modeling workflow above.

Run the API on the host or with the local PostgreSQL stack:

```bash
make api
# or
docker compose up --build --wait db api
```

The service listens on `http://localhost:8000`. It exposes liveness/readiness,
safe locked-model metadata, strict single and batch prediction (maximum 500),
bounded player search, actual-versus-expected player shot quality (maximum
10,000 attempts), and newest-first paginated shot data (maximum 250 per page).
Generated OpenAPI is available at `/docs` and `/openapi.json`.

## Local dashboard

The dashboard consumes only the API's read-only health, model, player-search,
shot-quality, and shot-page routes. Start the API and Vite development server in
separate terminals:

```bash
make api
make frontend
```

Open `http://localhost:5173`. Vite proxies `/api` and `/health` to the API on
port 8000. The dashboard searches real player IDs, defaults to the 2023-24
season, and applies one shared season/shot-type/home-designation scope to the
full-population summary and newest-first shot page. The court and accessible
table show the newest 100 attempts at a time; the interface states that this
page is narrower than the summary and discloses any current-page coordinates
outside the physical half-court view.

Run the full local stack with:

```bash
make stack-up
```

The frontend is served at `http://localhost:5173`; nginx proxies its same-origin
API and health requests to the `api` service. A fresh clone without ignored
model artifacts still serves the interface and process liveness, while the UI
honestly reports `Analytics not ready` until the locked artifacts are present.

## Held-out 2023-24 evaluation

The locked model was evaluated once on 218,701 shots from 1,230 whole games
(2023-10-24 through 2024-04-14). These local generated outputs remain ignored;
the table is a concise record of that fixed held-out evaluation, not a claim of
production readiness or causal shot quality.

| Model | Log loss | Brier | ROC-AUC | 10-bin ECE |
| --- | ---: | ---: | ---: | ---: |
| HGB, lr=0.05/leaves=15, sigmoid | 0.637055 | 0.224358 | 0.657832 | 0.006517 |
| Locked logistic, C=1, isotonic | 0.642787 | 0.226538 | 0.650390 | 0.006944 |

See [docs/architecture.md](docs/architecture.md) for the data contract,
relational design, leakage boundary, frozen modeling protocol, and API runtime
semantics.
