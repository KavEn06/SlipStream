from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.benchmarks.bulk_ingest import DEFAULT_SAMPLE_ROWS, build_parser, run_benchmark


class BulkIngestBenchmarkTests(unittest.TestCase):
    def test_default_capacity_workload_is_larger_than_half_a_million(self) -> None:
        self.assertGreater(DEFAULT_SAMPLE_ROWS, 500_000)
        self.assertGreater(build_parser().parse_args([]).rows, 500_000)

    def test_sqlite_smoke_report_covers_bounded_ingest_idempotency_and_index_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database_url = "sqlite:///{0}".format(root / "benchmark.db")
            report_path = root / "report.json"
            first = run_benchmark(
                database_url,
                rows=1_203,
                batch_size=127,
                query_limit=37,
                report_path=report_path,
            )
            second = run_benchmark(
                database_url,
                rows=1_203,
                batch_size=127,
                query_limit=37,
                reset=False,
            )

            self.assertEqual(first["ingest"]["rows_seen"], 1_203)
            self.assertEqual(first["ingest"]["rows_inserted"], 1_203)
            self.assertEqual(first["row_counts"]["stored_native_samples"], 1_203)
            self.assertEqual(first["row_counts"]["indexed_query_rows"], 37)
            self.assertGreater(first["ingest"]["elapsed_s"], 0.0)
            self.assertGreater(first["ingest"]["throughput_rows_per_s"], 0.0)
            plan_text = json.dumps(first["query"]["plan"])
            self.assertIn("ix_raw_session_lap_time", plan_text)
            self.assertEqual(second["ingest"]["rows_inserted"], 0)
            self.assertEqual(second["ingest"]["rows_updated"], 1_203)
            self.assertEqual(second["row_counts"]["stored_native_samples"], 1_203)
            self.assertEqual(json.loads(report_path.read_text(encoding="utf-8")), first)


if __name__ == "__main__":
    unittest.main()
