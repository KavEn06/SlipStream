"""Synthetic native-rate bulk ingest and indexed query benchmark."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from time import perf_counter
from typing import Any, Dict, Iterable, Optional, Sequence

from sqlalchemy import delete, func, select, text

from src.core.config import get_settings
from src.core.telemetry import (
    CanonicalTelemetrySample,
    DataSourceContract,
    LapContract,
    SessionContract,
)
from src.db import models
from src.db.repositories import (
    DataSourceRepository,
    SessionRepository,
    TelemetryRepository,
)
from src.db.session import (
    create_database_engine,
    create_schema,
    create_session_factory,
    session_scope,
)


DEFAULT_SAMPLE_ROWS = 500_001
DEFAULT_BATCH_SIZE = 5_000
DEFAULT_QUERY_LIMIT = 1_000
SOURCE_KEY = "benchmark:synthetic-native-v1"
SESSION_KEY = "benchmark-synthetic-native-v1"
NATIVE_INTERVAL_NS = 10_000_000  # 100 Hz


def synthetic_native_samples(rows: int) -> Iterable[CanonicalTelemetrySample]:
    """Generate deterministic samples lazily so memory stays batch-bounded."""

    for index in range(rows):
        phase = 2.0 * math.pi * (index % 10_000) / 10_000.0
        yield CanonicalTelemetrySample(
            source_sample_key="{0}:{1}".format(SOURCE_KEY, index),
            native_timestamp_ns=index * NATIVE_INTERVAL_NS,
            sample_index=index,
            simulator="SlipStream Synthetic",
            position_x_m=500.0 * math.cos(phase),
            position_y_m=0.0,
            position_z_m=500.0 * math.sin(phase),
            speed_mps=45.0 + 8.0 * math.sin(phase),
            throttle=0.55 + 0.35 * math.cos(phase),
            brake=max(0.0, 0.75 * math.sin(phase)),
            steering=0.2 * math.sin(phase),
            gear=4,
            engine_rpm=5_500.0 + 1_000.0 * math.sin(phase),
            lap_progress=(index % 10_000) / 9_999.0,
            completed_laps=index // 10_000,
            provenance={"generator": "synthetic-native-v1"},
        )


def run_benchmark(
    database_url: str,
    rows: int = DEFAULT_SAMPLE_ROWS,
    batch_size: int = DEFAULT_BATCH_SIZE,
    query_limit: int = DEFAULT_QUERY_LIMIT,
    reset: bool = True,
    report_path: Optional[Path] = None,
) -> Dict[str, Any]:
    if rows <= 0:
        raise ValueError("rows must be positive")
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    if query_limit <= 0:
        raise ValueError("query_limit must be positive")

    engine = create_database_engine(database_url)
    create_schema(engine)
    factory = create_session_factory(engine)
    try:
        with session_scope(factory) as database_session:
            existing = DataSourceRepository(database_session).get_by_key(SOURCE_KEY)
            if existing is not None and reset:
                database_session.execute(
                    delete(models.TelemetrySession).where(
                        models.TelemetrySession.data_source_id == existing.id
                    )
                )
                database_session.flush()
                database_session.delete(existing)
                database_session.flush()

            source = DataSourceRepository(database_session).upsert(
                DataSourceContract(
                    key=SOURCE_KEY,
                    kind="synthetic_benchmark",
                    simulator="SlipStream Synthetic",
                    provider="SlipStream",
                    dataset_name="deterministic-native-capacity-fixture",
                    license="CC0-1.0",
                    provenance={
                        "generated": True,
                        "sampling_hz": 100.0,
                        "requested_rows": rows,
                    },
                )
            )
            telemetry_session = SessionRepository(database_session).upsert_session(
                source.id,
                SessionContract(
                    external_id=SESSION_KEY,
                    simulator="SlipStream Synthetic",
                    sampling_hz=100.0,
                    provenance={"benchmark": "bulk-ingest-v1"},
                ),
            )
            lap = SessionRepository(database_session).upsert_lap(
                telemetry_session.id,
                LapContract(
                    lap_number=1,
                    source_lap_key="synthetic-capacity-lap",
                    duration_s=(rows - 1) / 100.0,
                    is_valid=True,
                    status="synthetic_benchmark",
                ),
            )
            source_id = int(source.id)
            session_id = int(telemetry_session.id)
            lap_id = int(lap.id)

        ingest_started = perf_counter()
        with session_scope(factory) as database_session:
            result = TelemetryRepository(database_session).bulk_upsert_raw(
                source_id,
                session_id,
                synthetic_native_samples(rows),
                batch_size=batch_size,
                default_lap_id=lap_id,
            )
            SessionRepository(database_session).set_lap_sample_count(lap_id, rows)
        ingest_elapsed_s = perf_counter() - ingest_started

        range_start_ns = (rows // 2) * NATIVE_INTERVAL_NS
        range_end_ns = range_start_ns + max(query_limit - 1, 0) * NATIVE_INTERVAL_NS
        query = (
            select(
                models.RawTelemetrySample.native_timestamp_ns,
                models.RawTelemetrySample.speed_mps,
            )
            .where(
                models.RawTelemetrySample.session_id == session_id,
                models.RawTelemetrySample.lap_id == lap_id,
                models.RawTelemetrySample.native_timestamp_ns >= range_start_ns,
                models.RawTelemetrySample.native_timestamp_ns <= range_end_ns,
            )
            .order_by(models.RawTelemetrySample.native_timestamp_ns)
            .limit(query_limit)
        )

        with session_scope(factory) as database_session:
            count_started = perf_counter()
            row_count = int(
                database_session.scalar(
                    select(func.count())
                    .select_from(models.RawTelemetrySample)
                    .where(models.RawTelemetrySample.data_source_id == source_id)
                )
                or 0
            )
            count_elapsed_ms = (perf_counter() - count_started) * 1_000.0

            query_started = perf_counter()
            query_rows = database_session.execute(query).all()
            query_elapsed_ms = (perf_counter() - query_started) * 1_000.0

        explain_started = perf_counter()
        query_plan = _explain(engine, query)
        explain_elapsed_ms = (perf_counter() - explain_started) * 1_000.0

        report: Dict[str, Any] = {
            "benchmark": "synthetic-native-bulk-ingest-v1",
            "database_backend": engine.dialect.name,
            "configuration": {
                "requested_rows": rows,
                "sampling_hz": 100.0,
                "batch_size": batch_size,
                "query_limit": query_limit,
                "reset_before_run": reset,
            },
            "ingest": {
                "elapsed_s": ingest_elapsed_s,
                "throughput_rows_per_s": (
                    result.rows_seen / ingest_elapsed_s
                    if ingest_elapsed_s > 0.0
                    else None
                ),
                "rows_seen": result.rows_seen,
                "rows_inserted": result.rows_inserted,
                "rows_updated": result.rows_updated,
            },
            "row_counts": {
                "stored_native_samples": row_count,
                "indexed_query_rows": len(query_rows),
            },
            "query": {
                "elapsed_ms": query_elapsed_ms,
                "count_elapsed_ms": count_elapsed_ms,
                "explain_elapsed_ms": explain_elapsed_ms,
                "range_start_ns": range_start_ns,
                "range_end_ns": range_end_ns,
                "plan": query_plan,
            },
        }
        if report_path is not None:
            resolved_report = Path(report_path)
            resolved_report.parent.mkdir(parents=True, exist_ok=True)
            resolved_report.write_text(
                json.dumps(report, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        return report
    finally:
        engine.dispose()


def _explain(engine, query) -> Any:
    compiled = query.compile(
        dialect=engine.dialect,
        compile_kwargs={"literal_binds": True},
    )
    sql = str(compiled)
    with engine.connect() as connection:
        if engine.dialect.name == "postgresql":
            rows = connection.execute(text("EXPLAIN (FORMAT JSON) " + sql)).all()
            return _json_value(rows[0][0]) if rows else []
        if engine.dialect.name == "sqlite":
            rows = connection.execute(text("EXPLAIN QUERY PLAN " + sql)).all()
            return [
                {
                    "id": int(row[0]),
                    "parent": int(row[1]),
                    "detail": str(row[3]),
                }
                for row in rows
            ]
    raise NotImplementedError(
        "Benchmark EXPLAIN supports PostgreSQL and SQLite, not {0}".format(
            engine.dialect.name
        )
    )


def _json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def build_parser() -> argparse.ArgumentParser:
    settings = get_settings()
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark bounded native telemetry ingestion and an indexed range query. "
            "The default workload is intentionally larger than 500,000 rows."
        )
    )
    parser.add_argument("--database-url", default=settings.database_url)
    parser.add_argument("--rows", type=int, default=DEFAULT_SAMPLE_ROWS)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--query-limit", type=int, default=DEFAULT_QUERY_LIMIT)
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("data/benchmarks/bulk-ingest.json"),
    )
    parser.add_argument(
        "--keep-existing",
        action="store_true",
        help="Upsert the fixed benchmark keys instead of resetting them first.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    report = run_benchmark(
        database_url=args.database_url,
        rows=args.rows,
        batch_size=args.batch_size,
        query_limit=args.query_limit,
        reset=not args.keep_existing,
        report_path=args.report,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
