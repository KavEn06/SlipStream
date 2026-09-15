# SlipStream

**A telemetry-first driving coach for sim racing.** SlipStream captures live Forza telemetry, imports real Assetto Corsa datasets, stores everything in PostgreSQL, and turns each lap into ranked, corner-by-corner coaching with measured time loss.

[![Verification](https://github.com/KavEn06/SlipStream/actions/workflows/verification.yml/badge.svg)](https://github.com/KavEn06/SlipStream/actions/workflows/verification.yml)
![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?logo=postgresql&logoColor=white)
![React](https://img.shields.io/badge/React_19-20232A?logo=react&logoColor=61DAFB)
![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?logo=typescript&logoColor=white)
![Tests](https://img.shields.io/badge/tests-357_backend_%2B_6_frontend-2ea44f)

![Session analysis: a late-braking finding at T11, ranked by seconds lost, with a track overlay](docs/screenshots/analysis.png)

Most sim-racing tools show graphs and leave the reading to you. SlipStream does the reading: it reconstructs laps, finds corners, compares them to your best lap, and explains where time was lost in plain English.

```
live UDP / Parquet  →  canonical laps  →  corner segmentation  →  7 detectors  →  ranked findings  →  React UI
```

---

## At a glance

| | |
|---|---|
| **Product** | Capture, process, compare, and coach from real telemetry |
| **Stack** | Python, FastAPI, PostgreSQL, SQLAlchemy 2, React 19, TypeScript, scikit-learn, PyTorch |
| **Tests** | 357 backend tests, 6 frontend tests, strict TypeScript, production build |
| **CI** | GitHub Actions with a real PostgreSQL service, migration round-trip, and frontend typecheck/build |
| **Scale** | 260,031 real 100 Hz rows pinned from Hugging Face; 500,001-row ingest in 37.8 s (13,242 rows/s) |
| **ML stance** | Optional, leakage-safe, observational. Never overrides a measured delta |

**What this repo is meant to show:** a full ingest-to-UI data product, not a notebook. Deterministic analysis is the source of truth. Learned bands and scenario ideas are labelled, gated, and optional.

---

## Product tour

Screenshots below are from a real Interlagos (Rio de Janeiro) Forza session running locally.

### Dashboard

Live capture controls and recent sessions. Capture runs as a managed subprocess so the UI stays responsive while UDP packets stream in.

![Dashboard with capture controls and latest sessions](docs/screenshots/home.png)

### Session library

Search, status filters, and one-click **Process** or **Analyze**. Sessions prefer PostgreSQL and fall back to on-disk artifacts.

![Session library with search, filters, and process/analyze actions](docs/screenshots/sessions.png)

### Session detail

Per-lap times, validity, and raw vs processed status. Lap numbers are normalized so zero-indexed captures and one-indexed imports look the same.

![Session detail with five valid processed laps](docs/screenshots/session-detail.png)

### Lap review

An interactive track map with automatically detected corners (entry / center / exit colour-coded), plus speed, throttle, brake, and steering for the whole lap.

![Lap review track map with fourteen detected corners](docs/screenshots/lap-review.png)

![Speed, throttle, brake, and steering traces for a single lap](docs/screenshots/lap-review-charts.png)

### Multi-lap comparison

Overlay up to six same-track laps, from one session or several, on shared track progress or elapsed time. Pick any lap as the reference.

![Lap comparison setup with two selected laps](docs/screenshots/lap-compare.png)

![Two-lap track overlay and speed traces](docs/screenshots/lap-compare-charts.png)

### Corner analysis

The coaching view. Findings are ranked by time lost, each with severity, confidence, and a templated explanation. Selecting one zooms the overlay to that corner and plots the driver's inputs against the reference lap.

If a trained champion is registered, expected-input bands are drawn here too. Each scenario idea can be rated helpful or not helpful; votes are stored and are **not** used for training.

![Corner detail: late braking at T11 with overlay and input traces vs the reference lap](docs/screenshots/analysis-corner-detail.png)

---

## Architecture

```mermaid
flowchart LR
  forza["Forza UDP"] --> adapters["Simulator adapters"]
  hf["Hugging Face Parquet<br/>Assetto Corsa, 100 Hz"] --> adapters
  adapters --> pg[("PostgreSQL<br/>SQLAlchemy 2 + Alembic")]
  pg --> processing["Canonical laps"]
  processing --> exports["CSV / JSON exports"]
  processing --> segmentation["Corner segmentation"]
  segmentation --> detectors["Seven detectors"]
  detectors --> findings["Ranked findings"]
  pg --> ml["sklearn + PyTorch"]
  ml -.->|"advisory only"| detectors
  findings --> api["FastAPI"]
  api --> ui["React + TypeScript"]
```

- **Simulator-neutral contract.** Forza and Assetto Corsa map onto one versioned schema before storage. Native sample rates are kept.
- **Database first, files as exports.** PostgreSQL in development/production; SQLite in tests with no services. CSV/JSON still write so older tooling keeps working.
- **Idempotent writes.** Imports use bounded, set-based `INSERT ... ON CONFLICT` upserts. Re-running a command is safe.
- **Deterministic core.** Every finding traces to a measured delta on aligned telemetry. Learned output is labelled and gated.

---

## How coaching is produced

**1. Canonical processed laps.** Raw samples become a fixed schema: timing, path alignment (`NormalizedDistance`), core signals, and derived features (longitudinal acceleration, input rates, steering smoothness, coasting). Each lap is validated (`LapIsValid`).

**2. Corner segmentation.** Corners come from curvature, speed, and steering on the reference lap, then split into entry, center, and exit. Compound corners get sub-apexes. The same segmentation is reused for every lap in the session.

**3. Seven detectors**

| Detector | What it catches |
|---|---|
| `early_braking` | Braking started earlier than the reference |
| `late_braking` | Braking started later, costing apex and exit speed |
| `trail_brake_past_apex` | Brake still applied past the apex |
| `over_slow_mid_corner` | Minimum speed well below the baseline |
| `exit_phase_loss` | Late throttle on exit |
| `weak_exit` | Below-baseline exit speed |
| `steering_instability` | Excess steering corrections |

Two research detectors, `abrupt_brake_release` and `long_coasting_phase`, sit behind `SLIPSTREAM_EXPERIMENTAL_DETECTORS=true` and are excluded from default counts.

**4. Findings pipeline**

1. Confidence combines pattern strength, cost, and alignment quality; hits below `0.35` drop.
2. Severity bins measured `time_loss_s` into minor / moderate / major.
3. Text is templated per detector, so the same telemetry always produces the same sentence.
4. Mutual suppression removes redundant hits (for example over-slowing when trail-braking already explains the corner).
5. Caps keep at most two findings per corner; the top set is `findings_top`.
6. Reconciliation checks that corner and straight deltas sum to the actual lap-time delta. A mismatch fails the run instead of shipping bad numbers.

---

## Data and machine learning

### Real telemetry

Three Assetto Corsa datasets are pinned to immutable Hugging Face revisions in [`src/ingest/manifests.py`](src/ingest/manifests.py): Spa-Francorchamps, Nürburgring GP, and Imola. Together they are **260,031 native rows at 100 Hz**. Upstream lap counters are unusable, so laps are reconstructed from start/finish crossings with duration gates. Ambiguous ranges are rejected. Details: [`docs/data-sources.md`](docs/data-sources.md).

### Leakage-safe training

Each accepted whole lap is resampled onto a fixed progress grid. Splits are grouped by lap and session so adjacent rows never land on both sides of a train/validation cut. An immutable holdout is reserved before any search.

### Two model families

- **scikit-learn random forest** with residual-quantile calibration for expected throttle, brake, steering, and speed bands, plus section and lap pace.
- **Compact PyTorch sequence model** with expected-input, section-time, lap-time, and pairwise ranking heads.

An offline runner does grouped cross-validation with fixed seeds, scores candidates with a declared composite metric, and registers artifacts with SHA-256 checksums. The registry exposes one **champion** and keeps challengers.

### Guarded scenario ideas

The scorer perturbs one driver-actionable feature (brake onset, min speed, throttle pickup, coasting, steering) within a bound scaled to that driver's consistency. An idea is shown only if every model family predicts a section improvement, the whole-lap prediction does not regress, nearby support is sufficient, the families agree, and uncertainty is bounded. Wet, cold, or high-wear conditions abstain and fall back to a labelled conservative cue.

Every idea has a recommendation ID, model version, hypothesis, and driver baseline. UI ratings stay `training_eligible: false`.

---

## Tech stack

| Layer | Choice |
|---|---|
| Language | Python 3.9+ (CI on 3.12), TypeScript |
| API | FastAPI, Uvicorn, Pydantic |
| Data | pandas, NumPy, PyArrow |
| Storage | PostgreSQL 16, SQLite for tests, SQLAlchemy 2, Alembic, psycopg 3 |
| ML | scikit-learn, PyTorch, joblib |
| Ingest | Forza UDP, Hugging Face Hub |
| Frontend | React 19, Vite, Tailwind CSS 4, Recharts, React Router |
| Tests / CI | unittest, Vitest, GitHub Actions + PostgreSQL service |
| Local infra | Docker Compose |

---

## Quick start

**Needs:** Python 3.9+, Node 22+. Docker is optional (PostgreSQL).

Backend, SQLite, no extra services:

```bash
python3 -m pip install -r requirements.txt
python3 -m alembic upgrade head
uvicorn src.api.app:app --reload --port 8000
```

Backend with PostgreSQL:

```bash
cp .env.example .env
docker compose up -d postgres
export DATABASE_URL=postgresql+psycopg://slipstream:slipstream@localhost:5432/slipstream
python3 -m alembic upgrade head
uvicorn src.api.app:app --reload --port 8000
```

Frontend:

```bash
cd frontend
npm ci
npm run dev
```

Open the Vite URL. `/api` is proxied to port 8000.

Then get laps in:

- **Live Forza:** enable UDP data-out, press **Start Capture** on the dashboard.
- **Assetto Corsa:** `python3 -m src.ingest.huggingface_importer spa`
- **Existing CSVs:** drop them under `data/raw/<session_id>/` and run the artifact importer.

Open **Sessions**, choose the session, click **Process**, then **Analyze**.

Settings live in [`.env.example`](.env.example): `DATABASE_URL`, `SLIPSTREAM_DATA_ROOT`, `SLIPSTREAM_MODEL_ROOT`, `SLIPSTREAM_CACHE_ROOT`, `SLIPSTREAM_IMPORT_BATCH_SIZE`, `SLIPSTREAM_EXPERIMENTAL_DETECTORS`.

---

## Everyday commands

```bash
# Live Forza capture (add --no-database for files only)
python3 src/ingest/datacollector.py --ip 127.0.0.1 --port 5300

# Pinned Assetto Corsa imports (network unless --parquet is a local file)
python3 -m src.ingest.huggingface_importer all

# Existing on-disk sessions
python3 -m src.ingest.artifact_importer --raw-root data/raw --processed-root data/processed
python3 src/processing/distance.py data/raw/<session_id>
python3 -m src.analysis.session_analysis <session_id>

# Train / inspect models
python3 -m src.ml dataset-summary
python3 -m src.ml train --seed 1729        # add --no-torch to skip PyTorch
python3 -m src.ml champion

# Health
curl http://localhost:8000/api/ml/data-health
curl http://localhost:8000/api/ml/model-health

# Capacity (default 500,001 rows; second form is a smoke)
python3 -m src.benchmarks.bulk_ingest
python3 -m src.benchmarks.bulk_ingest --rows 5000 --batch-size 500 --report data/benchmarks/smoke.json
```

The recorded 500,001-row run is in [`data/benchmarks/postgres-500001.json`](data/benchmarks/postgres-500001.json), including the `EXPLAIN` plan (indexed range query **6.1 ms** on `ix_raw_session_lap_time`).

---

## Testing and CI

```bash
python3 -m alembic upgrade head && python3 -m alembic check
python3 -m unittest discover -s tests -v
python3 -m compileall -q src tests migrations
cd frontend && npm test && npm run typecheck && npm run build
```

The suite covers migration parity, idempotent upserts, lap reconstruction, grouped-split leakage, scenario vetoes, detector gating, rating persistence, and frontend request shaping. Fixtures are generated locally. Network downloads are not in the default suite.

CI ([`.github/workflows/verification.yml`](.github/workflows/verification.yml)) provisions PostgreSQL 16, runs a migration round-trip, the backend suite, a benchmark smoke, then frontend test / typecheck / build.

---

## What SlipStream does not claim

These limits are intentional.

- **Observational, not causal.** Expected bands summarize comparable laps. Scenario ideas never promise seconds saved.
- **260,031 is a row count, not a lap count.** Independent laps after reconstruction are reported separately as `effective_laps`.
- **The 500,001-row run is synthetic.** It proves ingest and query capacity. It is not upstream data.
- **A champion won its offline run.** It is not auto-promoted. The holdout is reported, not used for selection.
- **Ratings do not retrain.** Votes are stored with `training_eligible: false`. Outcome linking and online learning are future work: [`docs/verification.md`](docs/verification.md).
- **Unsupported conditions abstain.** Wet, cold, high-wear, low support, or disagreement produce a labelled conservative cue.

---

## Repository layout

```
src/
  core/          config, canonical telemetry contracts, track lookups
  db/            SQLAlchemy models, session factory, set-based repositories
  ingest/        Forza UDP, Assetto Corsa mapping, lap reconstruction, importers
  processing/    processed-lap builder, alignment, segmentation, validation
  analysis/      corner records, baselines, seven detectors, findings, templates
  ml/            datasets, sklearn/torch models, experiments, registry, scenarios
  services/      database-first telemetry store with filesystem fallback
  api/           FastAPI app, routes, session scanner, capture manager
  benchmarks/    500K-row bulk-ingest and indexed-query benchmark
migrations/      Alembic revisions
frontend/src/    pages, components, typed API client, hooks, utils
tests/           357 fixture-based backend tests
docs/            data sources, verification policy, screenshots
```

---

## Roadmap

- Hosted deployment with accounts so drivers can upload sessions without running the stack.
- Cap scenario output to one primary cue per corner.
- Import the pinned Assetto Corsa corpus and register a production champion from it.
- Close the feedback loop: link follow-up laps to recommendations, then retrain only after an independent-lap batch clears the promotion gates.

---

## Further reading

- [`docs/data-sources.md`](docs/data-sources.md) — pinned revisions, licences, how rows are counted
- [`docs/verification.md`](docs/verification.md) — verification steps, promotion criteria, feedback scope
- [`data/benchmarks/postgres-500001.json`](data/benchmarks/postgres-500001.json) — recorded capacity run and `EXPLAIN` plan
