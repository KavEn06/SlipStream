# Data Sources, Attribution, and Counts

SlipStream's external telemetry manifests are code-reviewed records in `src/ingest/manifests.py`. Each download is pinned to a 40-character immutable Hugging Face revision. The importer records the revision, source URL, declared license, local SHA-256 when available, row-count check, missing-field counts, timestamp checks, reconstruction diagnostics, and insert/update counts.

## Pinned Assetto Corsa Sources

- Spa-Francorchamps: `Nasim435/spa-francorchamps-lap-data`, file `telemetry.parquet`, revision `5d20fbfbbf9958549fc6edd8793dcda1bb5b6f50`, upstream-declared MIT license, 51,554 rows. Source: https://huggingface.co/datasets/Nasim435/spa-francorchamps-lap-data/tree/5d20fbfbbf9958549fc6edd8793dcda1bb5b6f50
- Nürburgring GP: `Nasim435/Nurburgring-GP-Lap-data`, file `telemetry.parquet`, revision `89edbc576f98f85da49935be0c98f9bb056c3e3c`, upstream-declared MIT license, 91,490 rows. Source: https://huggingface.co/datasets/Nasim435/Nurburgring-GP-Lap-data/tree/89edbc576f98f85da49935be0c98f9bb056c3e3c
- Imola: `Nasim435/Imola-lap-data`, file `telemetry.parquet`, revision `baebec752f715a2af9c9a221a512b6d81ceccef8`, upstream-declared MIT license, 116,987 rows. Source: https://huggingface.co/datasets/Nasim435/Imola-lap-data/tree/baebec752f715a2af9c9a221a512b6d81ceccef8

The pinned manifest total is exactly **260,031 native source rows**, with a declared sampling rate of 100 Hz. Tests assert the arithmetic total. This wording is intentionally about rows before SlipStream filtering. It does not claim 260,031 laps, retained rows, statistically independent examples, or successful local/network import.

License values are upstream declarations captured for provenance, not a legal conclusion. Re-check the pinned source revision and its dataset card before redistribution.

## Reconstruction and Effective Laps

The upstream lap-progress and completed-lap counters may be constant or unusable. SlipStream reconstructs only unambiguous, complete laps from forward position crossings with duration/sample-count gates. Crossing intervals are half-open, so a native sample is assigned to at most one lap. Partial leading/trailing ranges and rejected intervals stay unassigned.

Model datasets resample each accepted whole lap onto fixed grids. `effective_laps` counts these independent accepted lap examples; `sample_rows` counts their resampled model rows. Neither should be compared directly with the 260,031 native-source-row total.

## Synthetic Capacity Fixture

`python3 -m src.benchmarks.bulk_ingest` generates 500,001 deterministic 100 Hz native samples by default. This fixture is CC0-style project-generated test data and is separate from the pinned corpus. The benchmark measures local database capacity only. Its JSON is written from the actual run and includes elapsed time, throughput, row counts, indexed query timing, and `EXPLAIN`; documentation does not carry invented performance numbers.

The CI workload passes a smaller `--rows` value. A full default benchmark must be run explicitly on the target PostgreSQL or SQLite environment.

## Network Policy

Unit, integration, migration, and benchmark-smoke tests use generated local fixtures. They do not download source data. Network source validation must be an explicitly opt-in test, skipped by default, and clearly labeled as network-dependent. Running an importer command without `--parquet` is a real network operation and should not be inferred from test success.
