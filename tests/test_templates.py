"""Snapshot tests for templated finding text."""

from __future__ import annotations

import unittest

from src.analysis.detectors import (
    DETECTOR_EARLY_BRAKING,
    DETECTOR_EXIT_PHASE_LOSS,
    DETECTOR_LATE_BRAKING,
    DETECTOR_OVER_SLOW_MID_CORNER,
    DETECTOR_STEERING_INSTABILITY,
    DETECTOR_TRAIL_BRAKE_PAST_APEX,
    DETECTOR_WEAK_EXIT,
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


class TestLateBrakingText(unittest.TestCase):
    def _metrics(self) -> dict:
        return {
            "brake_point_delta_m": 10.0,
            "candidate_brake_distance_m": 510.0,
            "baseline_brake_distance_m": 500.0,
            "min_speed_delta_kph": -4.0,
            "exit_speed_delta_kph": -3.0,
            "entry_speed_delta_kph": 0.0,
            "corner_time_delta_s": 0.20,
        }

    def test_moderate_text(self) -> None:
        text = render_finding_text(
            detector=DETECTOR_LATE_BRAKING,
            corner_id=2,
            severity="moderate",
            metrics=self._metrics(),
        )
        self.assertIn("T2", text)
        self.assertIn("Late brake point", text)
        self.assertIn("10 m", text)
        self.assertIn("-4.0 kph", text)

    def test_minor_text(self) -> None:
        text = render_finding_text(
            detector=DETECTOR_LATE_BRAKING,
            corner_id=2,
            severity="minor",
            metrics=self._metrics(),
        )
        self.assertIn("T2", text)
        self.assertIn("10 m later", text)
        self.assertIn("braking a touch earlier", text.lower())


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


class TestWeakExitText(unittest.TestCase):
    def _metrics(self) -> dict:
        return {
            "exit_full_throttle_fraction": 0.35,
            "baseline_exit_full_throttle_fraction": 0.70,
            "exit_full_throttle_fraction_delta": 0.35,
            "exit_speed_delta_kph": -4.0,
            "throttle_pickup_delay_m": 2.0,
            "corner_time_delta_s": 0.15,
        }

    def test_moderate_text(self) -> None:
        text = render_finding_text(
            detector=DETECTOR_WEAK_EXIT,
            corner_id=6,
            severity="moderate",
            metrics=self._metrics(),
        )
        self.assertIn("T6", text)
        self.assertIn("35%", text)
        self.assertIn("70%", text)
        self.assertIn("Commit to full throttle", text)

    def test_minor_text(self) -> None:
        text = render_finding_text(
            detector=DETECTOR_WEAK_EXIT,
            corner_id=6,
            severity="minor",
            metrics=self._metrics(),
        )
        self.assertIn("T6", text)
        self.assertIn("35%", text)
        self.assertIn("committing", text.lower())


class TestSteeringInstabilityText(unittest.TestCase):
    def _metrics(self) -> dict:
        return {
            "exit_steering_correction_count": 7,
            "baseline_exit_steering_correction_count": 2,
            "correction_count_delta": 5,
            "corner_time_delta_s": 0.10,
        }

    def test_moderate_text(self) -> None:
        text = render_finding_text(
            detector=DETECTOR_STEERING_INSTABILITY,
            corner_id=3,
            severity="moderate",
            metrics=self._metrics(),
        )
        self.assertIn("T3", text)
        self.assertIn("7 steering corrections", text)
        self.assertIn("2 on best", text)

    def test_minor_text(self) -> None:
        text = render_finding_text(
            detector=DETECTOR_STEERING_INSTABILITY,
            corner_id=3,
            severity="minor",
            metrics=self._metrics(),
        )
        self.assertIn("T3", text)
        self.assertIn("7 steering corrections", text)
        self.assertIn("unwinding", text.lower())


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
