import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type {
  AnalysisFinding,
  CornerDefinition,
  ManualConditions,
  SessionAnalysis,
} from "../types";
import { shapeManualConditionRequest } from "../utils/ml";
import { CornerDetailView } from "./CornerDetailView";

interface Props {
  sessionId: string;
  enabled: boolean;
}

const DETECTOR_LABELS: Record<string, string> = {
  early_braking: "Early Braking",
  late_braking: "Late Braking",
  trail_brake_past_apex: "Long Braking",
  over_slow_mid_corner: "Over-slowing Mid-Corner",
  exit_phase_loss: "Late Throttle Pickup",
  weak_exit: "Weak Exit",
  steering_instability: "Steering Corrections",
  abrupt_brake_release: "Abrupt Brake Release",
  long_coasting_phase: "Coasting Too Long",
};

const SEVERITY_TONE: Record<string, string> = {
  minor: "border-border/70 bg-surface-2/84 text-text-secondary",
  moderate: "border-amber-500/28 bg-amber-500/12 text-amber-500",
  major: "border-red-500/28 bg-red-500/12 text-red-500",
};

const SEVERITY_DOT: Record<string, string> = {
  minor: "bg-text-muted",
  moderate: "bg-amber-500",
  major: "bg-red-500",
};

function humanizeDetector(detector: string): string {
  return DETECTOR_LABELS[detector] ?? detector;
}

/** Sub-corners use parent_id * 100 + index (e.g. 401 = T4). Always show the parent. */
function cornerLabel(cornerId: number): string {
  const parent = cornerId >= 100 ? Math.floor(cornerId / 100) : cornerId;
  return `T${parent}`;
}

function formatSecondsLost(value: number): string {
  return `${value >= 0 ? "+" : ""}${value.toFixed(3)}s`;
}

interface CompactFindingCardProps {
  finding: AnalysisFinding;
  selected: boolean;
  onClick: () => void;
}

function CompactFindingCard({ finding, selected, onClick }: CompactFindingCardProps) {
  const dot = SEVERITY_DOT[finding.severity] ?? SEVERITY_DOT.minor;
  return (
    <button
      type="button"
      onClick={onClick}
      className={`w-full rounded-xl border px-3.5 py-3 text-left transition-colors cursor-pointer ${
        selected
          ? "border-accent/50 bg-accent/8 ring-1 ring-accent/25"
          : "border-border/70 bg-surface-2/78 hover:border-border-strong hover:bg-surface-2/90"
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <p className="text-[10px] uppercase tracking-[0.16em] text-text-muted">
          {cornerLabel(finding.corner_id)} · Lap {finding.lap_number}
        </p>
        <span className="font-mono text-[10px] text-text-muted shrink-0">
          {formatSecondsLost(finding.time_loss_s)}
        </span>
      </div>
      <div className="mt-1.5 flex items-center justify-between gap-2">
        <p className="text-sm font-medium text-text-primary truncate">
          {humanizeDetector(finding.detector)}
        </p>
        <div className="flex items-center gap-1.5 shrink-0">
          <span className={`inline-block h-1.5 w-1.5 rounded-full ${dot}`} />
          <span className="text-[10px] capitalize text-text-secondary">
            {finding.severity}
          </span>
        </div>
      </div>
    </button>
  );
}

interface DetailHeaderProps {
  finding: AnalysisFinding;
  cornerDef: CornerDefinition;
}

function DetailHeader({ finding, cornerDef }: DetailHeaderProps) {
  const tone = SEVERITY_TONE[finding.severity] ?? SEVERITY_TONE.minor;
  const learned = finding.ml_context;
  const recommendation = finding.scenario_recommendation;
  return (
    <div className="mb-4">
      <div className="flex flex-wrap items-center gap-2 mb-2">
        <span className="text-[11px] font-medium uppercase tracking-[0.16em] text-text-muted">
          {cornerLabel(finding.corner_id)} · {cornerDef.direction} corner · Lap {finding.lap_number}
        </span>
        <span
          className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-[10px] font-medium uppercase tracking-[0.14em] ${tone}`}
        >
          {finding.severity}
        </span>
        <span className="inline-flex items-center rounded-full border border-border/70 bg-surface-2/84 px-2.5 py-0.5 text-[10px] font-medium uppercase tracking-[0.14em] text-text-secondary">
          Observed telemetry
        </span>
      </div>
      <div className="flex items-start justify-between gap-3">
        <h4 className="text-base font-semibold text-text-primary">
          {humanizeDetector(finding.detector)}
        </h4>
        <div className="text-right shrink-0">
          <p className="font-mono text-sm font-medium text-text-primary">
            {formatSecondsLost(finding.time_loss_s)}
          </p>
          <p className="text-[10px] text-text-muted">
            {(finding.confidence * 100).toFixed(0)}% confidence
          </p>
        </div>
      </div>
      <p className="mt-2 text-sm text-text-secondary leading-relaxed">
        {finding.templated_text}
      </p>
      {learned && (
        <div className="mt-3 rounded-xl border border-border/60 bg-surface-3/55 p-3">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] uppercase tracking-[0.13em] text-text-muted">
            <span className="text-accent">Learned context</span>
            {learned.model?.version && <span>Model {learned.model.version}</span>}
            {learned.section_key && <span>{learned.section_key}</span>}
            {typeof learned.section_priority === "number" && (
              <span>Priority {(learned.section_priority * 100).toFixed(0)}%</span>
            )}
            {typeof learned.support === "number" && (
              <span>Support {(learned.support * 100).toFixed(0)}%</span>
            )}
          </div>
          {learned.abstained && (
            <p className="mt-1.5 text-xs text-amber-500">
              Model abstained: {learned.abstention_reason || "unsupported telemetry context"}
            </p>
          )}
          {!learned.abstained && typeof finding.measured_confidence === "number" && (
            <p className="mt-1.5 text-[11px] text-text-muted">
              Measured confidence {(finding.measured_confidence * 100).toFixed(0)}%;
              learned support only tunes presentation confidence.
            </p>
          )}
        </div>
      )}
      {recommendation && (
        <div className="mt-3 rounded-xl border border-accent/20 bg-accent/8 p-3">
          <p className="text-[10px] uppercase tracking-[0.14em] text-accent">
            Scenario idea · not a time promise
          </p>
          <p className="mt-1 text-sm leading-relaxed text-text-secondary">
            {recommendation.cue}
          </p>
          <p className="mt-1 text-[10px] text-text-muted">
            {recommendation.recommendation_id}
          </p>
        </div>
      )}
    </div>
  );
}

export function CornerAnalysisPanel({ sessionId, enabled }: Props) {
  const [analysis, setAnalysis] = useState<SessionAnalysis | null>(null);
  const [loading, setLoading] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [selectedFindingId, setSelectedFindingId] = useState<string | null>(null);
  const [findingsListOpen, setFindingsListOpen] = useState(true);
  const [conditions, setConditions] = useState<Record<keyof ManualConditions, string>>({
    wetness: "",
    air_temp_c: "",
    track_temp_c: "",
    tyre_wear: "",
  });
  const [conditionsSaving, setConditionsSaving] = useState(false);
  const [conditionsMessage, setConditionsMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!enabled) return;
    setLoading(true);
    setError(null);
    try {
      const result = await api.getSessionAnalysis(sessionId);
      setAnalysis(result);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to load analysis";
      if (
        message.toLowerCase().includes("analysis not available") ||
        message.toLowerCase().includes("not found")
      ) {
        setAnalysis(null);
      } else {
        setError(message);
      }
    } finally {
      setLoading(false);
    }
  }, [sessionId, enabled]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!enabled) return;
    void api
      .getSessionConditions(sessionId)
      .then((result) => {
        setConditions({
          wetness:
            result.conditions.wetness === undefined
              ? ""
              : String(result.conditions.wetness),
          air_temp_c:
            result.conditions.air_temp_c === undefined
              ? ""
              : String(result.conditions.air_temp_c),
          track_temp_c:
            result.conditions.track_temp_c === undefined
              ? ""
              : String(result.conditions.track_temp_c),
          tyre_wear:
            result.conditions.tyre_wear === undefined
              ? ""
              : String(result.conditions.tyre_wear),
        });
      })
      .catch(() => {
        // Conditions are optional for filesystem-only and legacy sessions.
      });
  }, [enabled, sessionId]);

  // Auto-select first finding when analysis loads
  useEffect(() => {
    if (analysis) {
      const top = analysis.findings_top;
      if (top.length > 0 && !selectedFindingId) {
        setSelectedFindingId(top[0].finding_id);
      }
    }
  }, [analysis, selectedFindingId]);

  const handleRun = async () => {
    setRunning(true);
    setError(null);
    setSelectedFindingId(null);
    try {
      await api.analyzeSession(sessionId);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Analysis failed");
    } finally {
      setRunning(false);
    }
  };

  const handleSaveConditions = async () => {
    let supplied: ManualConditions;
    try {
      supplied = shapeManualConditionRequest(conditions);
    } catch (error) {
      setConditionsMessage(
        error instanceof Error ? error.message : "Invalid condition values.",
      );
      return;
    }
    setConditionsSaving(true);
    setConditionsMessage(null);
    try {
      await api.updateSessionConditions(sessionId, supplied);
      setConditionsMessage("Saved. Re-run analysis to apply these conditions.");
    } catch (err) {
      setConditionsMessage(
        err instanceof Error ? err.message : "Could not save conditions",
      );
    } finally {
      setConditionsSaving(false);
    }
  };

  if (!enabled) {
    return null;
  }

  const findings = showAll ? analysis?.findings_all ?? [] : analysis?.findings_top ?? [];

  const selectedFinding = selectedFindingId
    ? findings.find((f) => f.finding_id === selectedFindingId) ?? null
    : null;

  const cornerDefForFinding = (finding: AnalysisFinding): CornerDefinition | undefined => {
    const parentId = finding.corner_id >= 100 ? Math.floor(finding.corner_id / 100) : finding.corner_id;
    return analysis?.corner_definitions?.find((c) => c.corner_id === parentId);
  };

  const selectedCornerDef = selectedFinding ? cornerDefForFinding(selectedFinding) : null;

  return (
    <div>
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-text-muted">
            Corner Analysis
          </p>
          <h3 className="mt-1 text-xl font-semibold text-text-primary">
            Where you're losing time
          </h3>
          {analysis && (
            <>
              <p className="mt-1 text-xs text-text-muted">
                Reference lap {analysis.reference_lap_number} · {analysis.findings_all.length}{" "}
                finding{analysis.findings_all.length === 1 ? "" : "s"} ·{" "}
                {analysis.detector_configuration.active_detector_count ?? 7} detectors ·{" "}
                {analysis.analysis_version}
              </p>
              <p className="mt-1 text-[11px] text-text-muted">
                ML: {analysis.ml_context.status}
                {analysis.ml_context.model?.version
                  ? ` · ${analysis.ml_context.model.version}`
                  : ""}
                {analysis.ml_context.abstention_reasons.length > 0
                  ? ` · ${analysis.ml_context.abstention_reasons.join(", ")}`
                  : ""}
              </p>
            </>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <button
            type="button"
            onClick={handleRun}
            disabled={running}
            className="motion-safe-color inline-flex h-10 items-center rounded-full border border-accent/24 bg-accent/12 px-4 text-sm font-medium text-accent hover:bg-accent/18 disabled:opacity-50 cursor-pointer"
          >
            {running ? "Analyzing..." : analysis ? "Re-run Analysis" : "Run Analysis"}
          </button>
        </div>
      </div>

      <div className="mt-4 rounded-2xl border border-border/60 bg-surface-2/45 p-3">
        <div className="flex flex-wrap items-end gap-2">
          {(
            [
              ["wetness", "Wetness", "0–1"],
              ["air_temp_c", "Air °C", "°C"],
              ["track_temp_c", "Track °C", "°C"],
              ["tyre_wear", "Tyre wear", "0–1"],
            ] as const
          ).map(([key, label, placeholder]) => (
            <label key={key} className="min-w-[96px] flex-1">
              <span className="text-[9px] uppercase tracking-[0.13em] text-text-muted">
                {label}
              </span>
              <input
                type="number"
                step={key === "air_temp_c" || key === "track_temp_c" ? "0.5" : "0.05"}
                placeholder={placeholder}
                value={conditions[key]}
                onChange={(event) =>
                  setConditions((current) => ({
                    ...current,
                    [key]: event.target.value,
                  }))
                }
                className="mt-1 h-9 w-full rounded-lg border border-border/70 bg-surface-1/80 px-2.5 text-xs text-text-primary outline-none focus:border-accent/50"
              />
            </label>
          ))}
          <button
            type="button"
            onClick={() => void handleSaveConditions()}
            disabled={conditionsSaving}
            className="motion-safe-color h-9 rounded-full border border-border/70 bg-surface-2/84 px-3 text-[10px] font-medium uppercase tracking-[0.13em] text-text-secondary hover:border-border-strong hover:text-text-primary disabled:opacity-50"
          >
            {conditionsSaving ? "Saving…" : "Save conditions"}
          </button>
        </div>
        {conditionsMessage && (
          <p className="mt-2 text-[11px] text-text-muted">{conditionsMessage}</p>
        )}
      </div>

      {error && (
        <div className="mt-4 rounded-2xl border border-red-500/28 bg-red-500/10 p-3 text-sm text-red-500">
          {error}
        </div>
      )}

      {loading && !analysis ? (
        <p className="mt-5 text-sm text-text-muted">Loading analysis...</p>
      ) : !analysis ? (
        <p className="mt-5 text-sm text-text-muted">
          No analysis yet. Run analysis to surface coaching findings for each corner.
        </p>
      ) : findings.length === 0 ? (
        <p className="mt-5 text-sm text-text-muted">
          No findings emitted — all corners are clean or differences are below the coaching
          threshold.
        </p>
      ) : (
        <div className={`mt-5 flex flex-col gap-4 lg:gap-5 lg:items-start ${findingsListOpen ? "lg:grid lg:grid-cols-[minmax(0,300px)_1fr]" : "lg:block"}`}>
          {/* LEFT — sticky scrollable findings list */}
          {findingsListOpen && (
            <div className="flex flex-col gap-2 lg:sticky lg:top-4 lg:max-h-[calc(100vh-120px)] lg:overflow-y-auto lg:pr-2">
              <div className="flex items-center justify-between gap-2 mb-1">
                <p className="text-[10px] uppercase tracking-[0.14em] text-text-muted">Findings</p>
                <button
                  type="button"
                  onClick={() => setFindingsListOpen(false)}
                  aria-label="Hide findings list"
                  title="Hide findings list"
                  className="motion-safe-color shrink-0 rounded-full border border-border/70 bg-surface-2/84 px-2.5 py-1 text-[10px] font-medium uppercase tracking-[0.14em] text-text-secondary hover:border-border-strong hover:bg-surface-3 hover:text-text-primary cursor-pointer"
                >
                  Hide
                </button>
              </div>
              {findings.map((finding) => (
                <CompactFindingCard
                  key={finding.finding_id}
                  finding={finding}
                  selected={finding.finding_id === selectedFindingId}
                  onClick={() => setSelectedFindingId(finding.finding_id)}
                />
              ))}

              {analysis.findings_all.length > analysis.findings_top.length && (
                <button
                  type="button"
                  onClick={() => {
                    setShowAll((prev) => !prev);
                    setSelectedFindingId(null);
                  }}
                  className="motion-safe-color mt-1 mb-2 inline-flex h-9 items-center rounded-full border border-border/70 bg-surface-2/84 px-4 text-xs font-medium uppercase tracking-[0.14em] text-text-secondary hover:border-border-strong hover:bg-surface-3 hover:text-text-primary cursor-pointer self-start shrink-0"
                >
                  {showAll
                    ? `Show top ${analysis.findings_top.length}`
                    : `Show all ${analysis.findings_all.length}`}
                </button>
              )}
            </div>
          )}

          {/* RIGHT — flows with main page scroll */}
          <div>
            {!findingsListOpen && (
              <div className="mb-4">
                <button
                  type="button"
                  onClick={() => setFindingsListOpen(true)}
                  aria-label="Show findings list"
                  className="motion-safe-color inline-flex h-8 items-center rounded-full border border-accent/24 bg-accent/12 px-3 text-[10px] font-medium uppercase tracking-[0.14em] text-accent hover:bg-accent/18 cursor-pointer"
                >
                  Findings
                </button>
              </div>
            )}
            {selectedFinding && selectedCornerDef && analysis.reference_length_m ? (
              <div className="rounded-2xl border border-border/60 bg-surface-2/50 p-4">
                <DetailHeader finding={selectedFinding} cornerDef={selectedCornerDef} />
                <CornerDetailView
                  finding={selectedFinding}
                  cornerDef={selectedCornerDef}
                  sessionId={sessionId}
                  baselineLapNumber={analysis.reference_lap_number}
                  referenceLengthM={analysis.reference_length_m}
                  trackOutline={analysis.track_outline}
                />
              </div>
            ) : (
              <div className="hidden lg:flex h-48 items-center justify-center rounded-2xl border border-border/40 bg-surface-2/30">
                <p className="text-sm text-text-muted">Select a finding to view corner detail</p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
