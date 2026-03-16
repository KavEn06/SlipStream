# SlipStream

SlipStream is a telemetry-first racing coach for Forza telemetry.

The core idea is:

`telemetry -> measurable driving behavior -> time-loss analysis -> structured findings`

The system is being built as an engineering-driven pipeline first. Any future AI or ML layer should explain or extend findings that already come from telemetry analysis rather than replacing it.

## Current Scope

The repository now covers Phase 1 and the foundations of Phase 2:

- raw Forza UDP ingestion into per-lap CSV files
- session metadata capture with track enrichment from `TrackOrdinal`
- canonical processed lap generation
- derived telemetry feature generation
- track-aligned lap segmentation
- lap comparison and structured findings

## Pipeline

```mermaid
flowchart LR
forzaUdp[ForzaUDPTelemetry] --> rawLogger[RawLapLogger]
rawLogger --> rawStore[RawLapCSVsAndSessionMetadata]
rawStore --> canonicalBuilder[CanonicalLapProcessing]
canonicalBuilder --> processedStore[ProcessedLapStore]
processedStore --> segmentation[LapSegmentation]
segmentation --> comparison[LapComparisonEngine]
comparison --> findings[StructuredFindings]
```

## Repository Layout

- `src/ingest/datacollector.py`: UDP capture, raw lap logging, session metadata
- `src/processing/distance.py`: canonical processed-lap builder, feature engineering, resampling helpers
- `src/analysis/segmentation.py`: straight / braking / entry / apex / exit segmentation
- `src/analysis/comparison.py`: reference lap generation, time-loss comparison, findings
- `src/tracks.py`: track ordinal lookup
- `tests/`: fixture-based coverage for ingest, processing, and analysis

## Canonical Processed Lap

Processed laps are the single source of truth for downstream analysis.

The canonical processed lap includes:

- sample timing: `TimestampMS`, `ElapsedTimeS`, `DeltaTimeS`
- path alignment: `CumulativeDistanceM`, `NormalizedDistance`
- core signals: speed, RPM, throttle, brake, steering, gear, power, torque, boost, position
- derived signals: longitudinal acceleration, throttle/brake rates, steering rate, steering smoothness, coasting flags
- lap-level validation fields: `LapTimeS`, `LapIsValid`

## Setup

Install dependencies:

```bash
python3 -m pip install -r requirements.txt
```

## Usage

Capture a raw session:

```bash
python3 src/ingest/datacollector.py --ip 127.0.0.1 --port 5300
```

Build processed laps for a session:

```bash
python3 src/processing/distance.py data/raw/session_20260316_120000
```

Plot a raw or processed lap for debugging:

```bash
python3 src/ingest/raceplots.py data/processed/session_20260316_120000/lap_001.csv
```

Run tests:

```bash
python3 -m unittest discover -s tests -v
```

## Current Findings Layer

The comparison layer can already emit structured measurements for:

- time loss by driving region
- minimum-speed deltas
- brake-point deltas
- throttle pickup deltas
- coasting deltas
- basic overdriving / underdriving indicators when supported by the telemetry