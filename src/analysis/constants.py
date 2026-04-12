"""Constants for the corner analysis layer.

All numerical thresholds live here so the detector code stays focused on the
logic. Bump ``ANALYSIS_VERSION`` whenever a threshold change can alter the
contents of the serialized ``session_analysis.json``.
"""

from __future__ import annotations


ANALYSIS_VERSION = "2026.04-v4-corner-analysis"

# --- Event detection --------------------------------------------------------
# Meters of approach ahead of the corner that the brake-initiation search
# covers. Mirrors APPROACH_LEAD_M from segmentation so the search window and
# the corner's ``approach_start_distance_m`` field stay aligned.
BRAKE_SEARCH_LEAD_M = 80.0

# A corner only has a brake event if the peak brake inside the (approach +
# corner) window exceeds this value. Below the threshold we treat the corner
# as lift-only and skip the three brake-family detectors.
BRAKE_PRESENCE_THRESHOLD = 0.15

# First sample with Brake above this value counts as brake-initiation.
BRAKE_INIT_THRESHOLD = 0.05

# First sample with Brake below this value (after the pedal was loaded)
# counts as brake-release.
BRAKE_RELEASE_THRESHOLD = 0.05

# Used to locate the trail-brake end (the point where brake pressure has
# decayed below a near-zero clear threshold).
TRAIL_BRAKE_CLEAR_THRESHOLD = 0.02

# First sample after min-speed with throttle above this value counts as
# throttle pickup.
THROTTLE_PICKUP_THRESHOLD = 0.10

# Threshold for considering throttle "full".
FULL_THROTTLE_THRESHOLD = 0.95

# Throttle-dip detection inside the exit region: throttle must rise to at
# least DIP_UPPER then fall below DIP_LOWER before the corner ends.
THROTTLE_DIP_UPPER = 0.50
THROTTLE_DIP_LOWER = 0.30

# Overlap metrics: consider brake active when > this.
BRAKE_ACTIVE_THRESHOLD = 0.10
# Overlap metrics: consider steering non-trivial when |steering| > this.
STEERING_ACTIVE_THRESHOLD = 0.10


# --- Detector gates ---------------------------------------------------------
# Candidate lap's brake initiation must be this many meters earlier than the
# baseline's (i.e. candidate_brake_point - baseline_brake_point <= -7m).
EARLY_BRAKE_DELTA_M = 7.0

# Trail brake release happens this many meters past the min-speed point.
TRAIL_BRAKE_PAST_APEX_M = 5.0

# For late braking: candidate braked this many meters later than baseline.
LATE_BRAKE_DELTA_M = 5.0

# For the over-slow detector, the candidate's min speed must be at least this
# much below the baseline's.
OVER_SLOW_MIN_SPEED_DELTA_KPH = -3.0

# And the exit speed must be no faster than baseline.
OVER_SLOW_EXIT_SPEED_DELTA_KPH = 0.0

# Exit-phase loss fires when throttle pickup is delayed by at least this many
# meters relative to baseline.
EXIT_PHASE_LOSS_THROTTLE_DELAY_M = 8.0

# Weak-exit detector: candidate's exit_full_throttle_fraction must be this
# much lower than the baseline's.
WEAK_EXIT_FRACTION_DELTA = 0.15
# And exit speed must be at least this much slower.
WEAK_EXIT_EXIT_SPEED_DELTA_KPH = -2.0

# Steering instability: minimum correction-count delta vs baseline to fire.
STEERING_INSTABILITY_CORRECTION_DELTA = 3
# Absolute floor: need at least this many corrections regardless of baseline.
STEERING_INSTABILITY_CORRECTION_FLOOR = 4
# Skip corners where even the baseline has this many corrections (noisy).
STEERING_INSTABILITY_BASELINE_CEILING = 8
# Ignore steering changes smaller than this (sensor noise filter).
STEERING_NOISE_THRESHOLD = 0.02

# Universal time-loss gate: nothing fires unless the candidate is at least
# this much slower than the baseline through the corner.
TIME_LOSS_GATE_S = 0.05


# --- Confidence scoring -----------------------------------------------------
# Findings below this confidence score are dropped entirely (not even in
# findings_all). v1 suppresses low-confidence output rather than flagging it.
CONFIDENCE_MIN = 0.35

# Alignment residual in meters where the alignment-quality sub-score hits 1.0.
ALIGNMENT_QUALITY_GOOD_M = 0.5
# Residual at which the alignment-quality sub-score has decayed to 0.0.
ALIGNMENT_QUALITY_POOR_M = 2.0

# Time-loss floor below which the cost-significance sub-score is 0.0, and
# ceiling above which it saturates at 1.0.
COST_SIGNIFICANCE_FLOOR_S = 0.05
COST_SIGNIFICANCE_CEIL_S = 0.50


# --- Severity ---------------------------------------------------------------
SEVERITY_MINOR_S = 0.05
SEVERITY_MODERATE_S = 0.15
SEVERITY_MAJOR_S = 0.30


# --- Output caps ------------------------------------------------------------
FINDINGS_PER_CORNER_CAP = 2
FINDINGS_SESSION_TOP_CAP = 5


# --- Reconciliation invariant -----------------------------------------------
# Integration test tolerance for |sum(corner_delta) + sum(straight_delta) -
# actual_lap_delta|. Above this, the orchestrator raises.
LAP_TIME_DELTA_RECONCILIATION_TOLERANCE_S = 0.05
