import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { AnalysisFinding, CornerDefinition, SessionAnalysis } from "../types";
import { CornerDetailView } from "./CornerDetailView";

interface Props {
  sessionId: string;
  enabled: boolean;
}

const DETECTOR_LABELS: Record<string, string> = {
  early_braking: "Early Braking",
  trail_brake_past_apex: "Trail Brake Past Apex",
  abrupt_brake_release: "Abrupt Brake Release",
  over_slow_mid_corner: "Over-slowing Mid-Corner",
  exit_phase_loss: "Exit Phase Loss",
};

const SEVERITY_TONE: Record<string, string> = {
  minor: "border-border/70 bg-surface-2/84 text-text-secondary",
  moderate: "border-amber-500/28 bg-amber-500/12 text-amber-500",
  major: "border-red-500/28 bg-red-500/12 text-red-500",
};

function humanizeDetector(detector: string): string {
  return DETECTOR_LABELS[detector] ?? detector;
}

function formatSecondsLost(value: number): string {
  return `${value >= 0 ? "+" : ""}${value.toFixed(3)}s`;
}

interface FindingCardProps {
  finding: AnalysisFinding;
  selected: boolean;
  onClick: () => void;
}

function FindingCard({ finding, selected, onClick }: FindingCardProps) {
  const tone = SEVERITY_TONE[finding.severity] ?? SEVERITY_TONE.minor;
  return (
    <button
      type="button"
      onClick={onClick}
      className={`w-full rounded-2xl border p-4 text-left transition-colors cursor-pointer ${
        selected
          ? "border-accent/50 bg-accent/8 ring-1 ring-accent/25"
          : "border-border/70 bg-surface-2/78 hover:border-border-strong hover:bg-surface-2/90"
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[11px] uppercase tracking-[0.16em] text-text-muted">
            T{finding.corner_id} · Lap {finding.lap_number}
          </p>
          <p className="mt-1 text-sm font-medium text-text-primary">
            {humanizeDetector(finding.detector)}
          </p>
        </div>
        <div className="flex flex-col items-end gap-2">
          <span
            className={`inline-flex items-center rounded-full border px-2.5 py-1 text-[10px] font-medium uppercase tracking-[0.14em] ${tone}`}
          >
            {finding.severity}
          </span>
          <span className="font-mono text-xs text-text-muted">
            {formatSecondsLost(finding.time_loss_s)} lost
          </span>
        </div>
      </div>
      <p className="mt-3 text-sm text-text-secondary">{finding.templated_text}</p>
      <p className="mt-2 text-[10px] uppercase tracking-[0.16em] text-text-muted">
        Confidence {(finding.confidence * 100).toFixed(0)}%
        {selected && (
          <span className="ml-2 text-accent/80">· tap again to collapse</span>
        )}
      </p>
    </button>
  );
}

export function CornerAnalysisPanel({ sessionId, enabled }: Props) {
  const [analysis, setAnalysis] = useState<SessionAnalysis | null>(null);
  const [loading, setLoading] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [selectedFindingId, setSelectedFindingId] = useState<string | null>(null);

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

  if (!enabled) {
    return null;
  }

  const findings = showAll ? analysis?.findings_all ?? [] : analysis?.findings_top ?? [];

  const selectedFinding = selectedFindingId
    ? findings.find((f) => f.finding_id === selectedFindingId) ?? null
    : null;

  const cornerDefForFinding = (finding: AnalysisFinding): CornerDefinition | undefined =>
    analysis?.corner_definitions?.find((c) => c.corner_id === finding.corner_id);

  return (
    <div>
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-text-muted">
            Corner Analysis
          </p>
          <h3 className="mt-1 text-xl font-semibold text-text-primary">
            Where you're losing time
          </h3>
          {analysis && (
            <p className="mt-1 text-xs text-text-muted">
              Reference lap {analysis.reference_lap_number} · {analysis.findings_all.length}{" "}
              finding{analysis.findings_all.length === 1 ? "" : "s"} ·{" "}
              {analysis.analysis_version}
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
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
        <>
          <div className="mt-5 grid gap-3 md:grid-cols-2">
            {findings.map((finding) => (
              <FindingCard
                key={finding.finding_id}
                finding={finding}
                selected={finding.finding_id === selectedFindingId}
                onClick={() =>
                  setSelectedFindingId((prev) =>
                    prev === finding.finding_id ? null : finding.finding_id,
                  )
                }
              />
            ))}
          </div>

          {/* Detail panel — shown when a finding is selected */}
          {selectedFinding && (() => {
            const cornerDef = cornerDefForFinding(selectedFinding);
            if (!cornerDef || !analysis.reference_length_m) return null;
            return (
              <div className="mt-4 rounded-2xl border border-border/60 bg-surface-2/50 p-4">
                <p className="mb-3 text-[11px] font-medium uppercase tracking-[0.16em] text-text-muted">
                  T{selectedFinding.corner_id} · {humanizeDetector(selectedFinding.detector)}
                  {" · "}
                  <span className="text-accent/80">{cornerDef.direction} corner</span>
                </p>
                <CornerDetailView
                  finding={selectedFinding}
                  cornerDef={cornerDef}
                  sessionId={sessionId}
                  baselineLapNumber={analysis.reference_lap_number}
                  referenceLengthM={analysis.reference_length_m}
                />
              </div>
            );
          })()}

          {analysis.findings_all.length > analysis.findings_top.length && (
            <button
              type="button"
              onClick={() => setShowAll((prev) => !prev)}
              className="motion-safe-color mt-4 inline-flex h-9 items-center rounded-full border border-border/70 bg-surface-2/84 px-4 text-xs font-medium uppercase tracking-[0.14em] text-text-secondary hover:border-border-strong hover:bg-surface-3 hover:text-text-primary cursor-pointer"
            >
              {showAll
                ? `Show top ${analysis.findings_top.length}`
                : `Show all ${analysis.findings_all.length}`}
            </button>
          )}
        </>
      )}
    </div>
  );
}
