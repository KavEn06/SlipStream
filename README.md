# SlipStream

**Telemetry-first driving coach for sim racing.**

```mermaid
flowchart LR
  ingest["Forza UDP<br/>AC Parquet 100 Hz"] --> store["PostgreSQL"]
  store --> laps["Canonical laps"]
  laps --> coach["7 detectors<br/>ranked time-loss"]
  store --> ml["sklearn + PyTorch<br/>expected-input bands"]
  ml --> coach
  coach --> ui["React dashboard"]
```

- **Ingest** — live Forza capture and real Assetto Corsa datasets
- **Store** — PostgreSQL as source of truth (SQLite in tests)
- **Coach** — corner-by-corner findings with measured seconds lost
- **Learn** — leakage-safe models for throttle / brake / steering / speed bands and guarded section ideas

[![Verification](https://github.com/KavEn06/SlipStream/actions/workflows/verification.yml/badge.svg)](https://github.com/KavEn06/SlipStream/actions/workflows/verification.yml)
![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?logo=postgresql&logoColor=white)
![scikit-learn](https://img.shields.io/badge/scikit--learn-F7931E?logo=scikitlearn&logoColor=white)
![PyTorch](https://img.shields.io/badge/PyTorch-EE4C2C?logo=pytorch&logoColor=white)
![React](https://img.shields.io/badge/React_19-20232A?logo=react&logoColor=61DAFB)
![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?logo=typescript&logoColor=white)
![Tests](https://img.shields.io/badge/tests-357_backend_%2B_6_frontend-2ea44f)

![Session analysis: a late-braking finding at T11, ranked by seconds lost, with a track overlay](docs/screenshots/analysis.png)

---

## What's in it

<table>
<tr>
<td width="50%" valign="top">

#### Capture & ingest

`Forza UDP` `Parquet` `Hugging Face`

- Live Forza capture
- Spa · Nürburgring GP · Imola
- Geometric lap reconstruction
- Existing-artifact importer
- Idempotent bounded upserts

</td>
<td width="50%" valign="top">

#### Processing & coaching

`7 detectors` `time-loss` `2D + 3D`

- Canonical processed laps
- Automatic corner segmentation
- Findings pipeline (suppression, caps, reconciliation)
- Multi-lap overlay (up to 6)
- Manual session conditions

</td>
</tr>
<tr>
<td width="50%" valign="top">

#### Machine learning

`sklearn` `PyTorch` `grouped CV`

- Random forest + Conv1d sequence model
- Expected throttle / brake / steering / speed bands
- Section pace, lap pace, pairwise ranking
- Leakage-safe whole-lap splits
- Guarded ideas with a whole-lap veto
- Checksummed champion registry
- Helpful / not-helpful ratings *(not used for training)*

</td>
<td width="50%" valign="top">

#### Product UI

`React 19` `FastAPI` `Recharts`

- Dashboard · session library · session detail
- Lap review · multi-lap compare · corner analysis
- Expected-band overlays and scenario cards
- Sessions, capture, analysis, ratings, ML health

</td>
</tr>
</table>

| Storage | Tests | Ingest |
|:---:|:---:|:---:|
| PostgreSQL · SQLite · Alembic | **357** backend · **6** frontend | **500,001** rows · **13,242**/s · **6.1 ms** query |
| Docker Compose · GitHub Actions | unittest · Vitest · typecheck | filesystem fallback |

### Stack

<p>
<img alt="Python" src="https://img.shields.io/badge/Python-3.9%2B-3776AB?style=for-the-badge&logo=python&logoColor=white">
<img alt="TypeScript" src="https://img.shields.io/badge/TypeScript-3178C6?style=for-the-badge&logo=typescript&logoColor=white">
<img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white">
<img alt="PostgreSQL" src="https://img.shields.io/badge/PostgreSQL-16-4169E1?style=for-the-badge&logo=postgresql&logoColor=white">
<img alt="SQLAlchemy" src="https://img.shields.io/badge/SQLAlchemy-2-D71F00?style=for-the-badge">
<img alt="scikit-learn" src="https://img.shields.io/badge/scikit--learn-F7931E?style=for-the-badge&logo=scikitlearn&logoColor=white">
<img alt="PyTorch" src="https://img.shields.io/badge/PyTorch-EE4C2C?style=for-the-badge&logo=pytorch&logoColor=white">
<img alt="React" src="https://img.shields.io/badge/React-19-20232A?style=for-the-badge&logo=react&logoColor=61DAFB">
<img alt="Vite" src="https://img.shields.io/badge/Vite-646CFF?style=for-the-badge&logo=vite&logoColor=white">
<img alt="Tailwind" src="https://img.shields.io/badge/Tailwind-4-38B2AC?style=for-the-badge&logo=tailwindcss&logoColor=white">
<img alt="Docker" src="https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white">
<img alt="GitHub Actions" src="https://img.shields.io/badge/GitHub_Actions-2088FF?style=for-the-badge&logo=githubactions&logoColor=white">
</p>

pandas · NumPy · PyArrow · Alembic · psycopg 3 · Pydantic · Uvicorn · Recharts · React Router · joblib · Hugging Face Hub · unittest · Vitest

---

## Product tour

Screenshots from a real Interlagos (Rio de Janeiro) Forza session.

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

This is a supervised telemetry problem, not a racecraft chatbot. A champion is trained offline on whole laps, registered with a checksum, and loaded at analysis time.

**It predicts, for every resampled point on a lap:**

- expected **throttle, brake, steering, and speed**, plus 10th–90th percentile bands (256 values per 64-point lap, targeting ~80% interval coverage)
- **section pace** on 8 track segments and a **whole-lap time**
- **pairwise ranking**: which of two comparable laps should be faster

**It can then:**

- overlay those expected bands on the driver’s actual traces in the React UI
- perturb one driver-actionable lever at a time (brake onset, min-speed, throttle pickup, coasting, steering) within a 2–6% bound scaled to that driver’s consistency
- veto any idea that helps a corner but is predicted to slow the full lap
- abstain on wet / cold / high-wear laps and fall back to a labelled conservative cue

Two families compete in the same experiment: a **64-tree random forest** with residual-quantile calibration, and a **32-dim Conv1d sequence net** (4 heads: profiles, section time, lap time, ranking). Selection uses 3-fold **grouped** CV on an 80/20 whole-lap split so no row from the same lap leaks into validation.

| | |
|---|---|
| Real corpus | **260,031** native 100 Hz rows across Spa, Nürburgring GP, Imola |
| Independent laps in that corpus | **30** complete source laps (5 / 10 / 15) — row count is not sample size |
| Features | 13 numeric profile features, 3 identity embeddings, **21** section features, 4 condition channels |
| Holdout / CV | 20% immutable whole-lap holdout, 3 grouped folds, seed `1729` |
| Champion objective | 35% input MAE · 20% section time · 20% lap time · 15% ranking · 5% coverage · 5% event timing |
| Typical offline champion | ~**0.82** pairwise faster-lap ranking · ~**0.80** band coverage · throttle/brake MAE ~**0.06–0.08** |
| What it is not | Not causal, not a seconds-saved promise, not live/online learning |

The 30-lap / 260k-row split is the whole point of the ML design: lots of high-rate samples, very few independent examples, so splits are by lap, not by row.

### Real telemetry

Three Assetto Corsa datasets are pinned to immutable Hugging Face revisions in [`src/ingest/manifests.py`](src/ingest/manifests.py): Spa-Francorchamps, Nürburgring GP, and Imola. Together they are **260,031 native rows at 100 Hz** and **30** complete source laps. Upstream lap counters are unusable, so laps are reconstructed from start/finish crossings with duration gates. Ambiguous ranges are rejected. Details: [`docs/data-sources.md`](docs/data-sources.md).

### Dataset construction

Each accepted lap is resampled onto a **64-point** normalized-progress grid and cut into **8** sections. The builder emits three aligned frames (samples, sections, laps) so a row-level model cannot see the future of the same lap. Faster valid laps are weighted more heavily as evidence, not as expert truth. Weather, temps, and tyre wear are features when present; missing values stay missing.

### Leakage-safe training

Splits are grouped by lap and session. An immutable 20% holdout is carved out with a fixed salt **before** any hyperparameter search. sklearn tries 3 candidates (64-tree forests, residual quantile bands); torch tries 2 (32 hidden units, kernel-5/3 Conv1d, dropout 0.10, early stopping patience 4, max 20 epochs). Repeated training stops when grouped validation plateaus.

### Two model families

- **scikit-learn random forest** — interpretable tabular baseline. Predicts 4 input channels with 10th/90th residual bands, plus section and lap pace.
- **PyTorch sequence model** — compact 1D conv encoder with identity embeddings (sim / track / car) and four heads: expected trace, section time, lap time, pairwise ranking.

Artifacts, feature definitions, source revisions, and SHA-256 checksums land in PostgreSQL. The registry marks one **champion** per run and keeps challengers. Unseen track/car combinations get an explicit uncertainty penalty rather than a fake confident trace.

### Guarded scenario ideas

The scorer perturbs one of five levers — brake onset (±3.5%), min-speed (±4%), throttle pickup (±3.5%), coasting (±6%), steering activity (±2%) — scaled down for inconsistent drivers. An idea is shown only if every configured family predicts a section improvement, the whole-lap prediction does not regress, nearby support is ≥ 0.35, families agree, and relative uncertainty stays under 0.35. Wet, cold, or high-wear conditions abstain and fall back to a labelled conservative cue.

Every idea has a recommendation ID, model version, hypothesis, and driver baseline. UI ratings stay `training_eligible: false`.

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
