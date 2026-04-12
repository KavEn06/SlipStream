"""Snapshot tests for templated finding text."""

from __future__ import annotations

import unittest

from src.analysis.detectors import (
    DETECTOR_ABRUPT_BRAKE_RELEASE,
    DETECTOR_EARLY_BRAKING,
    DETECTOR_EXIT_PHASE_LOSS,
    DETECTOR_OVER_SLOW_MID_CORNER,
    DETECTOR_TRAIL_BRAKE_PAST_APEX,
)
from src.analysis.templates import render_finding_text


class TestEarlyBrakingText(unittest.TestCase):
    def _metrics(self) -> dict:
        return {
            "brake_point_delta_m": -15.0,
            "candidate_brake_distance_m": 485.0,
            "baseline_brake_distance_m": 500.0,
            "exit_speed_delta_kph": -4.0,
            "entry_speed_delta_kph": 0.0,
            "corner_time_delta_s": 0.25,
        }

    def test_minor_severity_text(self) -> None:
        text = render_finding_text(
            detector=DETECTOR_EARLY_BRAKING,
            corner_id=3,
            severity="minor",
            metrics=self._metrics(),
        )
        self.assertIn("T3", text)
        self.assertIn("15 m earlier", text)
        self.assertIn("0.25 s", text)
        self.assertIn("delaying", text)

    def test_moderate_severity_text(self) -> None:
        text = render_finding_text(
            detector=DETECTOR_EARLY_BRAKING,
            corner_id=3,
            severity="moderate",
            metrics=self._metrics(),
        )
        self.assertIn("Early brake point", text)
        self.assertIn("-4.0 kph", text)
        self.assertIn("0.25 s lost", text)


class TestTrailBrakePastApexText(unittest.TestCase):
    def _metrics(self) -> dict:
        return {
            "trail_brake_depth_m": 7.5,
            "baseline_trail_brake_depth_m": 1.0,
            "min_speed_delta_kph": -4.0,
            "corner_time_delta_s": 0.18,
        }

    def test_moderate_text(self) -> None:
        text = render_finding_text(
            detector=DETECTOR_TRAIL_BRAKE_PAST_APEX,
            corner_id=4,
            severity="moderate",
            metrics=self._metrics(),
        )
        self.assertIn("T4", text)
        self.assertIn("trail braking", text.lower())
        self.assertIn("8 m", text)
        self.assertIn("-4.0 kph", text)
        self.assertIn("0.18 s", text)

    def test_minor_text(self) -> None:
        text = render_finding_text(
            detector=DETECTOR_TRAIL_BRAKE_PAST_APEX,
            corner_id=4,
            severity="minor",
            metrics=self._metrics(),
        )
        self.assertIn("T4", text)
        self.assertIn("8 m", text)
        self.assertIn("releasing", text.lower())


class TestAbruptBrakeReleaseText(unittest.TestCase):
    def _metrics(self) -> dict:
        return {
            "release_rate_per_s": 6.5,
            "release_brake_value": 0.55,
            "baseline_release_rate_per_s": 1.5,
            "min_speed_delta_kph": -2.5,
            "corner_time_delta_s": 0.12,
        }

    def test_moderate_text(self) -> None:
        text = render_finding_text(
            detector=DETECTOR_ABRUPT_BRAKE_RELEASE,
            corner_id=2,
            severity="moderate",
            metrics=self._metrics(),
        )
        self.assertIn("T2", text)
        self.assertIn("Abrupt brake release", text)
        self.assertIn("0.55", text)
        self.assertIn("6.5/s", text)
        self.assertIn("-2.5 kph", text)

    def test_minor_text(self) -> None:
        text = render_finding_text(
            detector=DETECTOR_ABRUPT_BRAKE_RELEASE,
            corner_id=2,
            severity="minor",
            metrics=self._metrics(),
        )
        self.assertIn("T2", text)
        self.assertIn("6.5/s", text)
        self.assertIn("smoothing", text.lower())


class TestOverSlowMidCornerText(unittest.TestCase):
    def _metrics(self) -> dict:
        return {
            "min_speed_delta_kph": -5.0,
            "exit_speed_delta_kph": -3.0,
            "candidate_min_speed_kph": 95.0,
            "baseline_min_speed_kph": 100.0,
            "corner_time_delta_s": 0.22,
        }

    def test_moderate_text(self) -> None:
        text = render_finding_text(
            detector=DETECTOR_OVER_SLOW_MID_CORNER,
            corner_id=5,
            severity="moderate",
            metrics=self._metrics(),
        )
        self.assertIn("T5", text)
        self.assertIn("-5.0 kph", text)
        self.assertIn("-3.0 kph", text)
        self.assertIn("0.22 s", text)

    def test_minor_text(self) -> None:
        text = render_finding_text(
            detector=DETECTOR_OVER_SLOW_MID_CORNER,
            corner_id=5,
            severity="minor",
            metrics=self._metrics(),
        )
        self.assertIn("T5", text)
        self.assertIn("-5.0 kph", text)
        self.assertIn("0.22 s", text)
        self.assertNotIn("exit speed", text.lower())


class TestExitPhaseLossText(unittest.TestCase):
    def _metrics(self) -> dict:
        return {
            "throttle_pickup_delay_m": 12.0,
            "candidate_pickup_distance_from_min_speed_m": 22.0,
            "baseline_pickup_distance_from_min_speed_m": 10.0,
            "exit_speed_delta_kph": -4.0,
            "exit_full_throttle_fraction": 0.4,
            "corner_time_delta_s": 0.17,
        }

    def test_moderate_text(self) -> None:
        text = render_finding_text(
            detector=DETECTOR_EXIT_PHASE_LOSS,
            corner_id=8,
            severity="moderate",
            metrics=self._metrics(),
        )
        self.assertIn("T8", text)
        self.assertIn("12 m later", text)
        self.assertIn("-4.0 kph", text)
        self.assertIn("0.17 s", text)
        self.assertIn("Commit earlier", text)

    def test_minor_text(self) -> None:
        text = render_finding_text(
            detector=DETECTOR_EXIT_PHASE_LOSS,
            corner_id=8,
            severity="minor",
            metrics=self._metrics(),
        )
        self.assertIn("T8", text)
        self.assertIn("12 m later", text)
        self.assertIn("0.17 s", text)
        self.assertNotIn("Commit earlier", text)


class TestRenderFindingTextUnknownDetector(unittest.TestCase):
    def test_raises_on_unknown_detector(self) -> None:
        with self.assertRaises(ValueError):
            render_finding_text(
                detector="not_a_real_detector",
                corner_id=1,
                severity="minor",
                metrics={},
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
