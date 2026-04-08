import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { MultiLapChart, type MultiLapSeries } from "../components/MultiLapChart";
import { CompareTrackMap } from "../components/CompareTrackMap";
import { SurfaceMessage, SurfaceSkeleton } from "../components/PageState";
import type {
  CompareCandidatesResponse,
  CompareCandidateSession,
  LapOverlayResponse,
  LapOverlaySelection,
} from "../types";
import { formatSessionTimestamp, getSessionTitle } from "../utils/sessions";

const COMPARE_COLOR_PALETTE = [
  "#4d79d8",
  "#d14b4b",
  "#3fa06f",
  "#c99635",
  "#d85e9f",
  "#8a56d8",
];

type CompareXAxisMode = "progress" | "time";

interface CompareScrubState {
  progressNorm: number | null;
  elapsedTimeS: number | null;
}

function formatLapTime(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) {
    return "--";
  }

  const mins = Math.floor(seconds / 60);
  const secs = (seconds % 60).toFixed(3);
  return mins > 0 ? `${mins}:${secs.padStart(6, "0")}` : `${secs}s`;
}

function formatBrakeValue(
  value: number | string | readonly (number | string)[] | undefined,
): string {
  if (value === undefined || Array.isArray(value)) {
    return "";
  }

  const numeric =
    typeof value === "number"
      ? value
      : typeof value === "string" && value.trim() !== ""
        ? Number(value)
        : Number.NaN;
  if (!Number.isFinite(numeric)) {
    return String(value);
  }

  return `${Math.round(numeric * 100)}%`;
}

function coerceNumber(value: number | string | null | undefined): number | null {
  if (typeof value === "number") {
    return Number.isFinite(value) ? value : null;
  }
  if (typeof value === "string" && value.trim() !== "") {
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric : null;
  }
  return null;
}

function formatProgressAxisValue(value: number | string): string {
  const numeric = coerceNumber(value);
  if (numeric === null) {
    return String(value);
  }
  return `${Math.round(numeric * 100)}%`;
}

function formatElapsedTimeTick(value: number | string): string {
  const numeric = coerceNumber(value);
  if (numeric === null) {
    return String(value);
  }

  const mins = Math.floor(numeric / 60);
  const secs = numeric % 60;
  return mins > 0 ? `${mins}:${secs.toFixed(1).padStart(4, "0")}` : `${secs.toFixed(1)}s`;
}

function interpolateRecordValue(
  records: Record<string, number | string>[],
  inputKey: string,
  outputKey: string,
  targetValue: number,
): number | null {
  const points = records
    .map((record) => ({
      input: coerceNumber(record[inputKey]),
      output: coerceNumber(record[outputKey]),
    }))
    .filter(
      (point): point is { input: number; output: number } =>
        point.input !== null && point.output !== null,
    )
    .sort((left, right) => left.input - right.input);

  if (!points.length) {
    return null;
  }

  if (targetValue <= points[0].input) {
    return points[0].output;
  }

  const lastPoint = points[points.length - 1];
  if (targetValue >= lastPoint.input) {
    return lastPoint.output;
  }

  for (let index = 1; index < points.length; index += 1) {
    const previous = points[index - 1];
    const current = points[index];
    if (targetValue > current.input) {
      continue;
    }
    if (Math.abs(current.input - previous.input) < 1e-9) {
      return current.output;
    }
    const ratio = (targetValue - previous.input) / (current.input - previous.input);
    return previous.output + ((current.output - previous.output) * ratio);
  }

  return lastPoint.output;
}

function selectionKey(selection: LapOverlaySelection): string {
  return `${selection.session_id}:${selection.lap_number}`;
}

function compareSelection(
  left: LapOverlaySelection,
  right: LapOverlaySelection,
): boolean {
  return left.session_id === right.session_id && left.lap_number === right.lap_number;
}

function getSessionTitleLabel(session: Pick<CompareCandidateSession, "session_id" | "display_name">): string {
  return getSessionTitle({
    session_id: session.session_id,
    display_name: session.display_name,
  });
}

export function LapComparePage() {
  const [searchParams] = useSearchParams();
  const seedSessionId = searchParams.get("sessionId")?.trim() ?? "";
  const seedLapNumberParam = searchParams.get("lapNumber");
  const seedLapNumber =
    seedLapNumberParam && seedLapNumberParam.trim() !== ""
      ? Number.parseInt(seedLapNumberParam, 10)
      : Number.NaN;

  const [candidateData, setCandidateData] = useState<CompareCandidatesResponse | null>(null);
  const [candidateLoading, setCandidateLoading] = useState(false);
  const [candidateError, setCandidateError] = useState<string | null>(null);
  const [overlayData, setOverlayData] = useState<LapOverlayResponse | null>(null);
  const [overlayLoading, setOverlayLoading] = useState(false);
  const [overlayError, setOverlayError] = useState<string | null>(null);
  const [selectedLaps, setSelectedLaps] = useState<LapOverlaySelection[]>([]);
  const [referenceLap, setReferenceLap] = useState<LapOverlaySelection | null>(null);
  const [xAxisMode, setXAxisMode] = useState<CompareXAxisMode>("progress");
  const [scrubState, setScrubState] = useState<CompareScrubState>({
    progressNorm: null,
    elapsedTimeS: null,
  });
  const [seedNotice, setSeedNotice] = useState<string | null>(null);
  const appliedSeedRef = useRef<string | null>(null);

  useEffect(() => {
    appliedSeedRef.current = null;
    setSelectedLaps([]);
    setReferenceLap(null);
    setOverlayData(null);
    setOverlayError(null);
    setSeedNotice(null);
    setScrubState({ progressNorm: null, elapsedTimeS: null });
  }, [seedLapNumberParam, seedSessionId]);

  useEffect(() => {
    if (!seedSessionId) {
      setCandidateData(null);
      setCandidateError(null);
      return;
    }

    let cancelled = false;

    const loadCandidates = async () => {
      setCandidateLoading(true);
      setCandidateError(null);
      try {
        const result = await api.getCompareLapCandidates(seedSessionId);
        if (!cancelled) {
          setCandidateData(result);
        }
      } catch (error) {
        if (!cancelled) {
          setCandidateData(null);
          setCandidateError(
            error instanceof Error ? error.message : "Failed to load compare candidates",
          );
        }
      } finally {
        if (!cancelled) {
          setCandidateLoading(false);
        }
      }
    };

    void loadCandidates();

    return () => {
      cancelled = true;
    };
  }, [seedSessionId]);

  useEffect(() => {
    if (!candidateData || !seedSessionId) {
      return;
    }

    const seedIdentity = `${seedSessionId}:${Number.isFinite(seedLapNumber) ? seedLapNumber : "session"}`;
    if (appliedSeedRef.current === seedIdentity) {
      return;
    }
    appliedSeedRef.current = seedIdentity;

    if (!Number.isFinite(seedLapNumber)) {
      return;
    }

    const seededSession = candidateData.sessions.find((session) => session.session_id === seedSessionId);
    const seededLap = seededSession?.laps.find((lap) => lap.lap_number === seedLapNumber);
    if (!seededSession || !seededLap) {
      setSeedNotice("The seeded lap is not eligible for compare. Select another usable processed lap.");
      return;
    }

    const seededSelection = {
      session_id: seedSessionId,
      lap_number: seedLapNumber,
    };
    setSelectedLaps([seededSelection]);
    setReferenceLap(seededSelection);
    setSeedNotice(null);
  }, [candidateData, seedLapNumber, seedSessionId]);

  useEffect(() => {
    if (!selectedLaps.length || !referenceLap) {
      setOverlayData(null);
      setOverlayLoading(false);
      setOverlayError(null);
      return;
    }

    let cancelled = false;

    const loadOverlay = async () => {
      setOverlayLoading(true);
      setOverlayError(null);
      try {
        const result = await api.buildLapCompare({
          selections: selectedLaps,
          reference_lap: referenceLap,
        });
        if (!cancelled) {
          setOverlayData(result);
        }
      } catch (error) {
        if (!cancelled) {
          setOverlayData(null);
          setOverlayError(
            error instanceof Error ? error.message : "Failed to build lap overlay",
          );
        }
      } finally {
        if (!cancelled) {
          setOverlayLoading(false);
        }
      }
    };

    void loadOverlay();

    return () => {
      cancelled = true;
    };
  }, [referenceLap, selectedLaps]);

  const sessionLookup = useMemo(() => {
    const lookup = new Map<string, CompareCandidateSession>();
    for (const session of candidateData?.sessions ?? []) {
      lookup.set(session.session_id, session);
    }
    return lookup;
  }, [candidateData]);

  const addSelection = useCallback((selection: LapOverlaySelection) => {
    setSelectedLaps((current) => {
      if (current.some((item) => compareSelection(item, selection))) {
        return current;
      }
      if (current.length >= 6) {
        return current;
      }
      return [...current, selection];
    });
    setReferenceLap((current) => current ?? selection);
  }, []);

  const removeSelection = useCallback((selection: LapOverlaySelection) => {
    setSelectedLaps((current) => {
      const remaining = current.filter((item) => !compareSelection(item, selection));
      setReferenceLap((reference) => {
        if (!reference || !compareSelection(reference, selection)) {
          return reference;
        }
        return remaining[0] ?? null;
      });
      return remaining;
    });
  }, []);

  const selectionCountReached = selectedLaps.length >= 6;

  const selectedLapCards = useMemo(
    () =>
      selectedLaps.map((selection, index) => {
        const session = sessionLookup.get(selection.session_id);
        const lap = session?.laps.find((candidate) => candidate.lap_number === selection.lap_number) ?? null;
        return {
          selection,
          color: COMPARE_COLOR_PALETTE[index % COMPARE_COLOR_PALETTE.length],
          label: session
            ? `${getSessionTitleLabel(session)} · Lap ${selection.lap_number}`
            : `${selection.session_id} · Lap ${selection.lap_number}`,
          sessionLabel: session ? getSessionTitleLabel(session) : selection.session_id,
          lapTime: lap?.lap_time_s ?? null,
          isReference: referenceLap ? compareSelection(referenceLap, selection) : false,
        };
      }),
    [referenceLap, selectedLaps, sessionLookup],
  );

  const overlaySeries = useMemo<MultiLapSeries[]>(() => {
    if (!overlayData) {
      return [];
    }

    return overlayData.series.map((series) => {
      const selection = {
        session_id: series.session_id,
        lap_number: series.lap_number,
      };
      const assignedColor =
        selectedLapCards.find((card) => compareSelection(card.selection, selection))?.color ??
        COMPARE_COLOR_PALETTE[0];
      const sessionTitle =
        sessionLookup.get(series.session_id)
          ? getSessionTitleLabel(sessionLookup.get(series.session_id)!)
          : series.display_name?.trim() || formatSessionTimestamp(series.session_id);

      return {
        id: selectionKey(selection),
        label: `${sessionTitle} · Lap ${series.lap_number}`,
        color: assignedColor,
        isReference: compareSelection(overlayData.reference_lap, selection),
        records: series.records,
      };
    });
  }, [overlayData, selectedLapCards, sessionLookup]);

  const referenceSeries = useMemo(
    () => overlaySeries.find((series) => series.isReference) ?? null,
    [overlaySeries],
  );

  const syncScrubFromProgress = useCallback(
    (progressNorm: number | null) => {
      if (progressNorm === null || !Number.isFinite(progressNorm)) {
        setScrubState({ progressNorm: null, elapsedTimeS: null });
        return;
      }

      setScrubState({
        progressNorm,
        elapsedTimeS: referenceSeries
          ? interpolateRecordValue(referenceSeries.records, "TrackProgressNorm", "ElapsedTimeS", progressNorm)
          : null,
      });
    },
    [referenceSeries],
  );

  const syncScrubFromElapsedTime = useCallback(
    (elapsedTimeS: number | null) => {
      if (elapsedTimeS === null || !Number.isFinite(elapsedTimeS)) {
        setScrubState({ progressNorm: null, elapsedTimeS: null });
        return;
      }

      setScrubState({
        elapsedTimeS,
        progressNorm: referenceSeries
          ? interpolateRecordValue(referenceSeries.records, "ElapsedTimeS", "TrackProgressNorm", elapsedTimeS)
          : null,
      });
    },
    [referenceSeries],
  );

  const handleActiveProgressChange = useCallback(
    (value: number | null) => {
      syncScrubFromProgress(value);
    },
    [syncScrubFromProgress],
  );

  const handleActiveChartValueChange = useCallback(
    (value: number | null) => {
      if (xAxisMode === "time") {
        syncScrubFromElapsedTime(value);
        return;
      }
      syncScrubFromProgress(value);
    },
    [syncScrubFromElapsedTime, syncScrubFromProgress, xAxisMode],
  );

  const chartXAxisKey = xAxisMode === "time" ? "ElapsedTimeS" : "TrackProgressNorm";
  const activeChartXValue = xAxisMode === "time" ? scrubState.elapsedTimeS : scrubState.progressNorm;
  const chartTickFormatter = xAxisMode === "time" ? formatElapsedTimeTick : formatProgressAxisValue;
  const chartTooltipLabelFormatter = useCallback(
    (value: number | string) =>
      xAxisMode === "time"
        ? `Time ${formatLapTime(coerceNumber(value) ?? Number.NaN)}`
        : `Progress ${formatProgressAxisValue(value)}`,
    [xAxisMode],
  );

  const compareWorkspaceReady = overlaySeries.length > 0 && overlayData !== null;

  if (!seedSessionId) {
    return (
      <SurfaceMessage
        title="No compare seed selected"
        message="Open compare from a session or lap so SlipStream knows which track family to load."
        className="max-w-6xl"
      />
    );
  }

  return (
    <div className="density-analysis-stack max-w-6xl">
      <section className="relative overflow-hidden rounded-[28px] border border-border/70 bg-surface-1/92 backdrop-blur-xl">
        <div className="hero-overlay pointer-events-none absolute inset-0" />
        <div className="hero-band pointer-events-none absolute -left-16 top-8 h-24 w-56 rotate-[-16deg]" />
        <div className="density-analysis-panel relative">
          <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-3">
                <h2 className="min-w-0 truncate text-3xl font-semibold tracking-tight text-text-primary">
                  Multi-Lap Compare
                </h2>
                <span className="inline-flex items-center rounded-full border border-accent/20 bg-accent/10 px-3 py-1 text-[10px] font-medium uppercase tracking-[0.16em] text-accent">
                  Up to 6 aligned laps
                </span>
              </div>
              <p className="mt-2 text-sm text-text-secondary">
                Overlay same-track laps from multiple sessions on one shared progress axis.
              </p>
            </div>

            <div className="flex flex-wrap items-center gap-3">
              <Link
                to={`/sessions/${seedSessionId}`}
                className="motion-safe-color inline-flex h-10 items-center rounded-full border border-border/70 bg-surface-2/84 px-4 text-sm font-medium text-text-secondary hover:border-border-strong hover:bg-surface-3 hover:text-text-primary"
              >
                Back to Session
              </Link>
            </div>
          </div>

          <div className="mt-5 flex flex-wrap gap-3">
            <div className="density-analysis-stat min-w-[130px] rounded-xl border border-border/70 bg-surface-2/80">
              <p className="text-[9px] uppercase tracking-[0.18em] text-text-muted">Track</p>
              <p className="mt-1.5 text-sm font-medium text-text-primary">
                {candidateData?.track_circuit ?? "--"}
              </p>
            </div>
            <div className="density-analysis-stat min-w-[130px] rounded-xl border border-border/70 bg-surface-2/80">
              <p className="text-[9px] uppercase tracking-[0.18em] text-text-muted">Layout</p>
              <p className="mt-1.5 text-sm font-medium text-text-primary">
                {candidateData?.track_layout ?? "--"}
              </p>
            </div>
            <div className="density-analysis-stat min-w-[130px] rounded-xl border border-border/70 bg-surface-2/80">
              <p className="text-[9px] uppercase tracking-[0.18em] text-text-muted">Selected</p>
              <p className="mt-1.5 text-sm font-medium text-text-primary">
                {selectedLaps.length} / 6 laps
              </p>
            </div>
            <div className="density-analysis-stat min-w-[180px] rounded-xl border border-border/70 bg-surface-2/80">
              <p className="text-[9px] uppercase tracking-[0.18em] text-text-muted">Reference</p>
              <p className="mt-1.5 text-sm font-medium text-text-primary">
                {referenceLap
                  ? `Lap ${referenceLap.lap_number} · ${sessionLookup.get(referenceLap.session_id)?.display_name ?? formatSessionTimestamp(referenceLap.session_id)}`
                  : "--"}
              </p>
            </div>
          </div>
        </div>
      </section>

      {candidateLoading && !candidateData ? (
        <div className="density-analysis-stack">
          <SurfaceSkeleton rows={4} />
          <SurfaceSkeleton rows={5} />
        </div>
      ) : candidateError ? (
        <SurfaceMessage
          title="Could not load compare candidates"
          message={candidateError}
          tone="danger"
        />
      ) : !candidateData ? null : (
        <>
          {seedNotice && (
            <SurfaceMessage
              title="Seeded lap not available"
              message={seedNotice}
            />
          )}

          <section className="density-analysis-panel rounded-[28px] border border-border/70 bg-surface-1/85">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-text-muted">
                  Selected Laps
                </p>
                <p className="mt-1 text-sm text-text-secondary">
                  Choose up to 6 processed, alignment-usable laps from the same circuit and layout.
                </p>
              </div>
              {selectionCountReached && (
                <span className="inline-flex items-center rounded-full border border-warning/20 bg-warning/10 px-3 py-1 text-[10px] font-medium uppercase tracking-[0.16em] text-warning">
                  Selection cap reached
                </span>
              )}
            </div>

            {selectedLapCards.length === 0 ? (
              <div className="mt-4 rounded-2xl border border-dashed border-border/70 bg-surface-2/72 p-4 text-sm text-text-muted">
                No laps selected yet. Add one or more laps below to build the overlay view.
              </div>
            ) : (
              <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                {selectedLapCards.map((card) => (
                  <div
                    key={selectionKey(card.selection)}
                    className="rounded-2xl border border-border/70 bg-surface-2/82 p-4"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span
                            className="inline-block h-2.5 w-2.5 rounded-full"
                            style={{ backgroundColor: card.color }}
                          />
                          <p className="truncate text-sm font-medium text-text-primary">
                            {card.sessionLabel}
                          </p>
                        </div>
                        <p className="mt-1 text-xs text-text-secondary">
                          Lap {card.selection.lap_number} · {formatLapTime(card.lapTime)}
                        </p>
                      </div>
                      {card.isReference && (
                        <span className="inline-flex items-center rounded-full border border-accent/20 bg-accent/10 px-2.5 py-1 text-[10px] font-medium uppercase tracking-[0.14em] text-accent">
                          Reference
                        </span>
                      )}
                    </div>
                    <div className="mt-4 flex items-center gap-2">
                      {!card.isReference && (
                        <button
                          type="button"
                          onClick={() => setReferenceLap(card.selection)}
                          className="motion-safe-color inline-flex h-8 items-center rounded-full border border-accent/24 bg-accent/12 px-3 text-[10px] font-medium uppercase tracking-[0.14em] text-accent hover:bg-accent/18 cursor-pointer"
                        >
                          Make Reference
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => removeSelection(card.selection)}
                        className="motion-safe-color inline-flex h-8 items-center rounded-full border border-border/70 bg-surface-1/84 px-3 text-[10px] font-medium uppercase tracking-[0.14em] text-text-secondary hover:border-border-strong hover:bg-surface-3 hover:text-text-primary cursor-pointer"
                      >
                        Remove
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section className="density-analysis-panel rounded-[28px] border border-border/70 bg-surface-1/85">
            <div className="flex flex-col gap-2">
              <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-text-muted">
                Eligible Same-Track Laps
              </p>
              <p className="text-sm text-text-secondary">
                Showing processed laps with alignment enabled for {candidateData.track_circuit} · {candidateData.track_layout}.
              </p>
            </div>

            <div className="mt-4 space-y-4">
              {candidateData.sessions.length === 0 ? (
                <div className="rounded-2xl border border-dashed border-border/70 bg-surface-2/72 p-4 text-sm text-text-muted">
                  SlipStream could not find any alignment-usable laps for this track yet.
                </div>
              ) : (
                candidateData.sessions.map((session) => {
                  const sessionTitle = getSessionTitleLabel(session);

                  return (
                    <div
                      key={session.session_id}
                      className="rounded-2xl border border-border/70 bg-surface-2/72 p-4"
                    >
                      <div className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
                        <div>
                          <p className="text-sm font-medium text-text-primary">{sessionTitle}</p>
                          <p className="mt-1 text-xs text-text-secondary">
                            {session.track_location || formatSessionTimestamp(session.session_id)}
                          </p>
                        </div>
                        <p className="text-[11px] uppercase tracking-[0.14em] text-text-muted">
                          {session.laps.length} eligible lap{session.laps.length !== 1 ? "s" : ""}
                        </p>
                      </div>

                      <div className="mt-4 flex flex-wrap gap-2">
                        {session.laps.map((lap) => {
                          const selection = {
                            session_id: session.session_id,
                            lap_number: lap.lap_number,
                          };
                          const isSelected = selectedLaps.some((item) => compareSelection(item, selection));
                          const disabled = !isSelected && selectionCountReached;

                          return (
                            <button
                              key={selectionKey(selection)}
                              type="button"
                              onClick={() => addSelection(selection)}
                              disabled={disabled || isSelected}
                              className={`motion-safe-color inline-flex items-center gap-2 rounded-full border px-3 py-2 text-xs font-medium cursor-pointer ${
                                isSelected
                                  ? "border-accent/24 bg-accent/12 text-accent"
                                  : disabled
                                    ? "border-border/70 bg-surface-1/80 text-text-subtle cursor-not-allowed"
                                    : "border-border/70 bg-surface-1/84 text-text-secondary hover:border-border-strong hover:bg-surface-3 hover:text-text-primary"
                              }`}
                            >
                              <span>{`Lap ${lap.lap_number}`}</span>
                              <span className="font-mono text-[11px]">{formatLapTime(lap.lap_time_s)}</span>
                              {isSelected && <span className="text-[10px] uppercase tracking-[0.1em]">Selected</span>}
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </section>

          {overlayError && (
            <SurfaceMessage
              title="Could not build compare view"
              message={overlayError}
              tone="danger"
            />
          )}

          {overlayLoading && !compareWorkspaceReady ? (
            <div className="density-analysis-stack">
              <SurfaceSkeleton rows={4} />
              <div className="grid gap-4 lg:grid-cols-2">
                <SurfaceSkeleton rows={3} />
                <SurfaceSkeleton rows={3} />
              </div>
            </div>
          ) : !compareWorkspaceReady ? (
            <SurfaceMessage
              title="Select laps to start comparing"
              message="Once you choose one or more same-track aligned laps, SlipStream will overlay the track map and telemetry traces here."
            />
          ) : (
            <div className="density-analysis-stack">
              <section className="density-analysis-panel rounded-[28px] border border-border/70 bg-surface-1/85">
                <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                  <div>
                    <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-text-muted">
                      X-Axis
                    </p>
                    <p className="mt-1 text-sm text-text-secondary">
                      Switch the overlay charts between shared track progress and actual elapsed lap time.
                    </p>
                  </div>
                  <div className="relative inline-grid grid-cols-2 rounded-full border border-border/70 bg-surface-2/88 p-1">
                    {([
                      { mode: "progress" as const, label: "Track Progress (%)" },
                      { mode: "time" as const, label: "Elapsed Time" },
                    ]).map((option) => {
                      const active = xAxisMode === option.mode;
                      return (
                        <button
                          key={option.mode}
                          type="button"
                          onClick={() => setXAxisMode(option.mode)}
                          className={`motion-safe-color relative inline-flex h-9 items-center justify-center rounded-full px-4 text-[10px] font-medium uppercase tracking-[0.14em] cursor-pointer ${
                            active
                              ? "border border-accent/20 bg-accent/12 text-accent"
                              : "text-text-secondary hover:text-text-primary"
                          }`}
                          aria-pressed={active}
                        >
                          {option.label}
                        </button>
                      );
                    })}
                  </div>
                </div>
              </section>

              <CompareTrackMap
                series={overlaySeries}
                activeMode={xAxisMode}
                activeProgressNorm={scrubState.progressNorm}
                activeElapsedTimeS={scrubState.elapsedTimeS}
                onActiveProgressChange={handleActiveProgressChange}
                corners={overlayData?.segmentation?.corners ?? null}
              />

              <MultiLapChart
                series={overlaySeries}
                yKey="SpeedKph"
                label="Speed (km/h)"
                syncId="lap-compare"
                xKey={chartXAxisKey}
                activeXValue={activeChartXValue}
                onActiveXValueChange={handleActiveChartValueChange}
                xTickFormatter={chartTickFormatter}
                xTooltipLabelFormatter={chartTooltipLabelFormatter}
              />

              <div className="grid gap-4 lg:grid-cols-2">
                <MultiLapChart
                  series={overlaySeries}
                  yKey="Brake"
                  label="Brake (%)"
                  syncId="lap-compare"
                  xKey={chartXAxisKey}
                  activeXValue={activeChartXValue}
                  onActiveXValueChange={handleActiveChartValueChange}
                  xTickFormatter={chartTickFormatter}
                  xTooltipLabelFormatter={chartTooltipLabelFormatter}
                  yValueFormatter={formatBrakeValue}
                />
                <MultiLapChart
                  series={overlaySeries}
                  yKey="Steering"
                  label="Steering"
                  syncId="lap-compare"
                  xKey={chartXAxisKey}
                  activeXValue={activeChartXValue}
                  onActiveXValueChange={handleActiveChartValueChange}
                  xTickFormatter={chartTickFormatter}
                  xTooltipLabelFormatter={chartTooltipLabelFormatter}
                />
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
