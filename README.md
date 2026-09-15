# SlipStream

SlipStream is a telemetry-first racing coach for Forza telemetry.

The core idea is:

`telemetry -> measurable driving behavior -> time-loss analysis -> structured findings`

The system is built as an engineering-driven pipeline first. Any future AI or ML layer should explain or extend findings that already come from telemetry analysis rather than replacing it.

The persistence and ingestion foundation is simulator-neutral: native Assetto Corsa and Forza samples use the same SQLAlchemy repositories. Processing, analysis, and session API reads prefer database records when a session exists there, while retaining filesystem fallback for old artifacts and fresh file-only installs. CSV and JSON files remain compatible derived exports.

## Architecture

```mermaid
flowchart LR
forzaUdp[ForzaUDPTelemetry] --> rawLogger[RawLapLogger]
rawLogger --> rawStore[RawLapCSVs + SessionMetadata]
rawStore --> canonicalBuilder[CanonicalLapProcessing]
canonicalBuilder --> processedStore[ProcessedLapStore]
processedStore --> cornerRecords[CornerRecordExtraction]
cornerRecords --> baselines[PerCornerBaselines]
baselines --> detectors[SevenDetectors]
detectors --> findings[RankedFindings]
findings --> api[FastAPI]
api --> frontend[React UI]
```

## Pipeline Stages

### Ingest
- Raw Forza UDP capture into per-lap CSV files
- Session metadata with track enrichment from `TrackOrdinal`

### Processing
- Canonical processed lap generation with distance alignment and resampling
- Track segmentation into corner and straight definitions
- Derived telemetry features: longitudinal acceleration, throttle/brake rates, steering rate/smoothness, coasting flags

### Analysis
- Corner record extraction per lap
- Per-corner baselines built from the reference (best) lap
- Seven detectors run against each corner record against its baseline
- Findings pipeline: confidence scoring, severity classification, templated text, mutual suppression, per-corner and session caps

### API
- FastAPI backend serving sessions, laps, lap comparison, telemetry capture, and analysis results

### Frontend
- React + TypeScript UI with pages for session library, session detail, lap review, lap comparison, and corner analysis

## Detectors

| Detector | What it catches |
|---|---|
| `early_braking` | Braking started earlier than the reference lap |
| `late_braking` | Braking started later, costing apex and exit speed |
| `trail_brake_past_apex` | Brake overlap past the apex distance |
| `over_slow_mid_corner` | Mid-corner speed significantly below baseline |
| `exit_phase_loss` | Late throttle application on exit |
| `weak_exit` | Below-baseline exit speed fraction |
| `steering_instability` | Excess steering correction in the corner |

These seven are the complete default detector set. Two research detectors,
`abrupt_brake_release` and `long_coasting_phase`, are excluded from default
runs and counts. Enable them explicitly per analysis request or with
`SLIPSTREAM_EXPERIMENTAL_DETECTORS=true`.

## Findings Pipeline

1. **Confidence scoring** — `pattern_strength` combined with cost-significance and alignment-quality sub-scores into `[0, 1]`
2. **Confidence gate** — hits below `CONFIDENCE_MIN` are dropped
3. **Severity classification** — binned from `time_loss_s` into minor / moderate / major
4. **Templated text** — deterministic per detector
5. **Mutual suppression** — `over_slow_mid` suppressed when `trail_brake_past_apex` fires on the same corner/lap; `exit_phase_loss` suppressed when `over_slow_mid` has a larger time loss
6. **Per-corner cap** — top N findings per corner by ranking key
7. **Session cap** — top findings surfaced as `findings_top`; the rest go to `findings_all`

## Repository Layout

```
src/
  ingest/
    datacollector.py        UDP capture, raw lap logging, session metadata
    raceplots.py            debug plots for raw and processed laps
  processing/
    distance.py             canonical processed-lap builder and feature engineering
    alignment.py            lap resampling and alignment helpers
    segmentation.py         corner and straight definitions from track data
    validation.py           lap validation utilities
  analysis/
    session_analysis.py     session-level orchestrator, writes session_analysis.json
    corner_records.py       CornerRecord and StraightRecord extraction
    baselines.py            per-corner baseline construction from the reference lap
    detectors.py            seven pure-function detectors
    findings.py             confidence scoring, suppression, ranking, Finding/FindingSet
    templates.py            deterministic text templates for each detector
    constants.py            all tunable thresholds in one place
  core/
    config.py               paths and environment config
    constants.py            shared signal constants
    schemas.py              shared dataclasses and column names
    tracks.py               TrackOrdinal lookup table
  api/
    app.py                  FastAPI app with CORS and gzip
    models.py               API request/response models
    routes/
      sessions.py           session listing and metadata
      laps.py               lap retrieval and processed lap data
      compare.py            multi-lap comparison endpoint
      capture.py            live capture start/stop
      analysis.py           session analysis results
    services/
      session_scanner.py    scans processed data directory for sessions
      capture_manager.py    manages the UDP capture subprocess
frontend/
  src/
    pages/                  HomePage, SessionsPage, SessionDetailPage,
                            LapReviewPage, LapComparePage, AnalysisPage
    components/             LapChart, MultiLapChart, TrackMap, CompareTrackMap,
                            CornerAnalysisPanel, CornerDetailView, AppNavigation,
                            Layout, StatusBadge, SessionLibraryRow, AppearanceDrawer
    api/                    typed API client
    hooks/                  data-fetching hooks
    types/                  shared TypeScript types
    utils/                  helpers
run_phase1_review.py        choose a raw lap, process it, open debug plots
tests/                      fixture-based coverage for ingest, processing, and analysis
```

## Canonical Processed Lap

Processed laps are the single source of truth for downstream analysis.

Fields include:

- **Sample timing**: `TimestampMS`, `ElapsedTimeS`, `DeltaTimeS`
- **Path alignment**: `CumulativeDistanceM`, `NormalizedDistance`
- **Core signals**: speed, RPM, throttle, brake, steering, gear, power, torque, boost, position
- **Derived signals**: longitudinal acceleration, throttle/brake rates, steering rate, steering smoothness, coasting flags
- **Lap-level fields**: `LapTimeS`, `LapIsValid`

## Persistence and ML Architecture

Native simulator samples are mapped into a versioned canonical contract, stored at their original rate, reconstructed into complete laps, processed into aligned features, and then consumed by deterministic analysis. SQLAlchemy repositories use bounded, set-based PostgreSQL/SQLite upserts. CSV/JSON artifacts remain compatible exports and filesystem fallbacks.

The optional ML path builds whole-lap sample, section, and lap views. Session-grouped splits keep every row from one lap/session on one side of a split. A checksummed registry champion may add calibrated expected-input bands and guarded scenario ideas. It cannot replace measured time loss, detector gates, or lap-delta reconciliation.

## Setup

Backend with the default no-service SQLite database (`data/slipstream.db`):

```bash
python3 -m pip install -r requirements.txt
python3 -m alembic upgrade head
python3 -m alembic check
```

PostgreSQL:

```bash
cp .env.example .env
docker compose up -d postgres
export DATABASE_URL=postgresql+psycopg://slipstream:slipstream@localhost:5432/slipstream
python3 -m alembic upgrade head
```

Frontend:

```bash
cd frontend
npm ci
npm run dev
```

`SLIPSTREAM_DATA_ROOT`, `SLIPSTREAM_MODEL_ROOT`, `SLIPSTREAM_CACHE_ROOT`, and `SLIPSTREAM_IMPORT_BATCH_SIZE` configure artifacts, models, downloads, and bounded writes.

## Data Sources and Truthful Counts

The three manifests in `src/ingest/manifests.py` pin immutable upstream revisions totaling **exactly 260,031 native source rows at a declared 100 Hz before filtering**. That is a source-row count, not 260,031 independent laps, training examples, or retained processed rows. Complete laps are reconstructed from directed start/finish crossings; partial, ambiguous, invalid, or unsupported ranges remain unassigned or are filtered. The effective lap count is therefore separate and can be much smaller.

The synthetic capacity benchmark is also separate. Its default workload generates **500,001** deterministic native samples to exercise bounded ingestion and indexed querying. It is not imported upstream data and is not evidence that a network import ran. See [source attribution and revisions](docs/data-sources.md).

## Commands

Capture and persist completed Forza laps:

```bash
python3 src/ingest/datacollector.py --ip 127.0.0.1 --port 5300
```

Use `--no-database` for explicit file-only capture.

Import pinned sources (these commands perform network downloads unless `--parquet` points to a local file):

```bash
python3 -m src.ingest.huggingface_importer spa
python3 -m src.ingest.huggingface_importer nurburgring_gp
python3 -m src.ingest.huggingface_importer imola
python3 -m src.ingest.huggingface_importer all
```

Import existing artifacts, migrate, process, train, and inspect the champion:

```bash
python3 -m alembic upgrade head
python3 -m src.ingest.artifact_importer --raw-root data/raw --processed-root data/processed
python3 src/processing/distance.py data/raw/session_20260316_120000
python3 -m src.ml dataset-summary
python3 -m src.ml train --no-torch --seed 1729
python3 -m src.ml champion
```

Analyze and inspect health:

```bash
python3 -m src.analysis.session_analysis session_20260316_120000
uvicorn src.api.app:app --reload --port 8000
curl -X POST http://localhost:8000/api/sessions/session_20260316_120000/analyze
curl http://localhost:8000/api/ml/data-health
curl http://localhost:8000/api/ml/model-health
```

Run the default capacity benchmark or the fast development smoke:

```bash
python3 -m src.benchmarks.bulk_ingest
python3 -m src.benchmarks.bulk_ingest --rows 5000 --batch-size 500 \
  --report data/benchmarks/smoke.json
```

Reports contain measured elapsed time, throughput, inserted/updated/stored row counts, query timings, and the database `EXPLAIN` plan. Routine CI runs only a small PostgreSQL smoke workload; it does not run the 500,001-row default.

## Verification

```bash
python3 -m alembic upgrade head
python3 -m alembic check
python3 -m unittest discover -s tests -v
python3 -m src.benchmarks.bulk_ingest --rows 5000 --report data/benchmarks/smoke.json
python3 -m compileall -q src tests migrations
cd frontend
npm test
npm run typecheck
npm run build
```

Fixture tests are generated locally. Network downloads are not part of the default suite; any network validation must be explicitly opt-in and skipped by default. CI provisions PostgreSQL, performs a migration round-trip, runs backend integration tests and a benchmark smoke, then tests, typechecks, and builds the frontend.

## Interpretation and Feedback Limits

SlipStream reports observational associations, not causal effects. Expected bands summarize learned patterns in comparable telemetry; scenario perturbations are bounded hypotheses and never promise seconds saved. Known out-of-distribution conditions (including wetness, high tyre wear, cold track, model-declared exclusions, low support, disagreement, or high uncertainty) suppress learned specifics and may produce a deterministic conservative fallback. Manual session conditions override imported metadata. Missing condition fields are retained as missing/default model features and must not be read as measured weather.

Current feedback support is scaffolding: versioned recommendation IDs, outcome/rating payload contracts, and persistence tables exist. Automatic outcome association, user-facing rating workflows, feedback-based promotion, and live/online retraining do not exist and must not be represented as active learning.

Current experiment promotion selects the lowest grouped-cross-validation composite score among that run's candidates; the immutable holdout is reported but not used for selection. Production promotion additionally requires no group leakage, reproducibility at the declared seed and source revisions, valid interval-coverage reporting, no material holdout regression, compatible dimensions/features, and a checksummed loadable artifact. See [verification and promotion policy](docs/verification.md).
