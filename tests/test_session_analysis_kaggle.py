"""Integration test for ``session_analysis.run`` against the kaggle session.

This test is gated on the kaggle processed artifacts being present. If
they aren't (e.g. in a fresh clone), the test is skipped rather than
failing. When they are present, it enforces:

  1. The analysis pipeline runs end-to-end without raising.
  2. Every expected top-level key is populated.
  3. The per-lap reconciliation invariant holds within tolerance — this
     is the hard sanity check that makes every downstream metric trustworthy.
  4. Findings never reference a (corner, lap) pair that tripped the
     alignment-fallback gate.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from src.analysis.constants import (
    ANALYSIS_VERSION,
    FINDINGS_SESSION_TOP_CAP,
    LAP_TIME_DELTA_RECONCILIATION_TOLERANCE_S,
)
from src.analysis.session_analysis import (
    ANALYSIS_ARTIFACT_FILENAME,
    ReconciliationError,
    run,
)
from src.core.config import PROCESSED_DATA_ROOT


KAGGLE_SESSION_ID = "kaggle set"


def _kaggle_is_available() -> bool:
    session_dir = PROCESSED_DATA_ROOT / KAGGLE_SESSION_ID
    if not session_dir.is_dir():
        return False
    required = ["metadata.json", "track_segmentation.json", "reference_path.csv"]
    return all((session_dir / name).is_file() for name in required)


@unittest.skipUnless(_kaggle_is_available(), "Kaggle session artifacts unavailable")
class TestKaggleSessionAnalysis(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # Run once and reuse across assertions to keep the test fast.
        cls.result = run(KAGGLE_SESSION_ID, write=False, strict_reconciliation=True)

    def test_analysis_version(self) -> None:
        self.assertEqual(self.result.analysis_version, ANALYSIS_VERSION)

    def test_session_id(self) -> None:
        self.assertEqual(self.result.session_id, KAGGLE_SESSION_ID)

    def test_reference_lap_is_populated(self) -> None:
        self.assertGreaterEqual(self.result.reference_lap_number, 0)

    def test_analyzed_at_is_iso_format(self) -> None:
        self.assertRegex(self.result.analyzed_at_utc, r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")

    def test_fourteen_corners(self) -> None:
        # The kaggle track segmentation produces 14 corners.
        self.assertEqual(len(self.result.per_corner_records), 14)

    def test_every_corner_has_a_baseline(self) -> None:
        for corner_id in self.result.per_corner_records:
            self.assertIn(corner_id, self.result.per_corner_baselines)

    def test_findings_top_capped(self) -> None:
        self.assertLessEqual(len(self.result.findings_top), FINDINGS_SESSION_TOP_CAP)

    def test_all_findings_have_positive_time_loss(self) -> None:
        for finding in self.result.findings_all:
            self.assertGreater(finding.time_loss_s, 0.0)

    def test_findings_respect_alignment_gate(self) -> None:
        # A finding must never be emitted against a record that tripped the
        # alignment-fallback gate — the detector universal gate enforces this.
        fallback_pairs: set[tuple[int, int]] = set()
        for corner_id, records in self.result.per_corner_records.items():
            for record in records:
                if record.alignment_used_fallback:
                    fallback_pairs.add((corner_id, record.lap_number))
        for finding in self.result.findings_all:
            self.assertNotIn(
                (finding.corner_id, finding.lap_number),
                fallback_pairs,
                f"Finding emitted on fallback record: {finding.detector}",
            )

    def test_reconciliation_holds(self) -> None:
        for lap_number, entry in self.result.lap_time_delta_reconciliation.items():
            self.assertLess(
                abs(entry["residual_s"]),
                LAP_TIME_DELTA_RECONCILIATION_TOLERANCE_S,
                f"Lap {lap_number} reconciliation failed: "
                f"residual={entry['residual_s']:.4f}s",
            )

    def test_reference_lap_excluded_from_reconciliation(self) -> None:
        entries = self.result.lap_time_delta_reconciliation
        for lap_number, entry in entries.items():
            self.assertNotEqual(lap_number, entry["reference_lap_number"])

    def test_every_finding_points_to_a_real_record(self) -> None:
        # Top-level records.
        record_keys = {
            (corner_id, record.lap_number)
            for corner_id, records in self.result.per_corner_records.items()
            for record in records
        }
        # Sub-corner records (compound corners, e.g. corner 8 → sub-corners 801, 802).
        for records in self.result.per_corner_records.values():
            for record in records:
                for sub_rec in record.sub_corner_records:
                    record_keys.add((sub_rec.corner_id, sub_rec.lap_number))
        for finding in self.result.findings_all:
            self.assertIn((finding.corner_id, finding.lap_number), record_keys)

    def test_session_summary_populated(self) -> None:
        summary = self.result.session_summary
        self.assertIsNotNone(summary)
        self.assertGreater(summary.theoretical_best_lap_s, 0)
        self.assertGreater(summary.best_actual_lap_s, 0)
        self.assertGreaterEqual(summary.gap_to_theoretical_s, 0)
        self.assertGreater(len(summary.corner_cards), 0)
        self.assertTrue(len(summary.main_repeated_theme) > 0)

    def test_corner_cards_have_position_data(self) -> None:
        for card in self.result.session_summary.corner_cards:
            self.assertGreater(card.apex_m, 0)
            self.assertGreater(card.corner_start_m, 0)

    def test_theoretical_best_leq_best_actual(self) -> None:
        summary = self.result.session_summary
        self.assertLessEqual(
            summary.theoretical_best_lap_s, summary.best_actual_lap_s
        )

    def test_serialization_roundtrip(self) -> None:
        payload = self.result.to_dict()
        for key in (
            "analysis_version",
            "session_id",
            "reference_lap_number",
            "analyzed_at_utc",
            "per_corner_records",
            "per_corner_baselines",
            "straight_records",
            "findings_top",
            "findings_all",
            "lap_time_delta_reconciliation",
            "session_summary",
            "quality_report",
        ):
            self.assertIn(key, payload)


@unittest.skipUnless(_kaggle_is_available(), "Kaggle session artifacts unavailable")
class TestKaggleSessionWriteArtifact(unittest.TestCase):
    """Separate class so we only exercise disk I/O once, deliberately."""

    def test_write_produces_json_file(self) -> None:
        result = run(KAGGLE_SESSION_ID, write=True, strict_reconciliation=True)
        artifact = PROCESSED_DATA_ROOT / KAGGLE_SESSION_ID / ANALYSIS_ARTIFACT_FILENAME
        self.assertTrue(artifact.is_file())
        # Sanity-check: the written JSON opens and parses.
        import json
        payload = json.loads(artifact.read_text(encoding="utf-8"))
        self.assertEqual(payload["analysis_version"], ANALYSIS_VERSION)
        self.assertEqual(len(payload["per_corner_records"]), 14)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
