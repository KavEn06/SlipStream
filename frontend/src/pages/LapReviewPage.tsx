import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api/client";
import { LapChart } from "../components/LapChart";
import { SurfaceMessage, SurfaceSkeleton } from "../components/PageState";
import type { LapData } from "../types";

type LapDataType = "processed" | "raw";
type ChartKey = "speed" | "throttle" | "brake" | "steering";

const DEFAULT_VISIBLE_CHARTS: Record<ChartKey, boolean> = {
  speed: true,
  throttle: true,
  brake: true,
  steering: true,
};

const CHART_ORDER: ChartKey[] = ["speed", "throttle", "brake", "steering"];

function formatLapTime(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) {
    return "--";
  }

  const mins = Math.floor(seconds / 60);
  const secs = (seconds % 60).toFixed(3);
  return mins > 0 ? `${mins}:${secs.padStart(6, "0")}` : `${secs}s`;
}

function getNumericValue(
  record: Record<string, number | string> | undefined,
  key: string,
): number | undefined {
  const value = record?.[key];

  if (typeof value === "number") {
    return Number.isFinite(value) ? value : undefined;
  }

  if (typeof value === "string" && value.trim().length > 0) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : undefined;
  }

  return undefined;
}

function SummaryStat({
  label,
  value,
  mono = false,
  tone = "neutral",
}: {
  label: string;
  value: string;
  mono?: boolean;
  tone?: "neutral" | "accent" | "success" | "danger" | "warning";
}) {
  const toneClass =
    tone === "accent"
      ? "border-accent/24 bg-surface-2/80"
      : tone === "success"
        ? "border-success/28 bg-surface-2/80"
        : tone === "danger"
          ? "border-danger/30 bg-surface-2/80"
          : tone === "warning"
            ? "border-warning/28 bg-surface-2/80"
            : "border-border/70 bg-surface-2/80";
  const valueToneClass =
    tone === "accent"
      ? "text-accent"
      : tone === "success"
        ? "text-success"
        : tone === "danger"
          ? "text-danger"
          : tone === "warning"
            ? "text-warning"
            : "text-text-primary";

  return (
    <div
      className={`density-analysis-stat min-w-[120px] rounded-xl border ${toneClass}`}
    >
      <p className="text-[9px] uppercase tracking-[0.18em] text-text-muted">
        {label}
      </p>
      <p
        className={`mt-1.5 truncate text-sm font-medium ${valueToneClass} ${
          mono ? "font-mono" : ""
        }`}
      >
        {value}
      </p>
    </div>
  );
}

function StatusPill({
  children,
  tone = "neutral",
}: {
  children: string;
  tone?: "neutral" | "accent" | "success" | "danger" | "warning";
}) {
  const toneClass =
    tone === "accent"
      ? "border-accent/20 bg-accent/10 text-accent"
      : tone === "success"
        ? "border-success/18 bg-success/12 text-success"
        : tone === "danger"
          ? "border-danger/20 bg-danger/12 text-danger"
          : tone === "warning"
            ? "border-warning/20 bg-warning/12 text-warning"
          : "border-border/70 bg-surface-2/84 text-text-secondary";

  return (
    <span
      className={`inline-flex items-center rounded-full border px-3 py-1 text-[10px] font-medium uppercase tracking-[0.16em] ${toneClass}`}
    >
      {children}
    </span>
  );
}

export function LapReviewPage() {
  const { sessionId, lapNumber } = useParams<{
    sessionId: string;
    lapNumber: string;
  }>();
  const [requestedDataType, setRequestedDataType] =
    useState<LapDataType>("processed");
  const [resolvedDataType, setResolvedDataType] =
    useState<LapDataType>("processed");
  const [lapData, setLapData] = useState<LapData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const [visibleCharts, setVisibleCharts] = useState(DEFAULT_VISIBLE_CHARTS);
  const [focusedChart, setFocusedChart] = useState<ChartKey | null>(null);

  const parsedLapNumber = Number.parseInt(lapNumber ?? "", 10);
  const canLoad = Boolean(sessionId) && Number.isFinite(parsedLapNumber);

  useEffect(() => {
    if (!canLoad || !sessionId) {
      return;
    }

    let cancelled = false;

    const loadLapData = async () => {
      setLoading(true);
      setError(null);

      try {
        let result: LapData;
        let nextResolved: LapDataType = requestedDataType;

        if (requestedDataType === "processed") {
          try {
            result = await api.getLap(sessionId, parsedLapNumber, "processed");
          } catch {
            result = await api.getLap(sessionId, parsedLapNumber, "raw");
            nextResolved = "raw";
          }
        } else {
          result = await api.getLap(sessionId, parsedLapNumber, "raw");
        }

        if (!cancelled) {
          setLapData(result);
          setResolvedDataType(nextResolved);
        }
      } catch (err) {
        if (!cancelled) {
          setLapData(null);
          setResolvedDataType(requestedDataType);
          setError(err instanceof Error ? err.message : "Failed to load lap data");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    void loadLapData();

    return () => {
      cancelled = true;
    };
  }, [canLoad, parsedLapNumber, reloadToken, requestedDataType, sessionId]);

  const records = lapData?.records ?? [];
  const hasLapData = lapData !== null;
  const showBlockingLoad = loading && !hasLapData;
  const firstRecord = records[0];
  const lastRecord = records.length > 0 ? records[records.length - 1] : undefined;
  const isProcessed = resolvedDataType === "processed";
  const fallbackToRaw =
    !loading &&
    requestedDataType === "processed" &&
    resolvedDataType === "raw";

  const lapTimeS = isProcessed
    ? getNumericValue(firstRecord, "LapTimeS") ??
      getNumericValue(lastRecord, "LapTimeS")
    : getNumericValue(lastRecord, "CurrentLap") ??
      getNumericValue(lastRecord, "LapTimeS");
  const validFlag =
    getNumericValue(firstRecord, "LapIsValid") ??
    getNumericValue(lastRecord, "LapIsValid");
  const lapIsValid =
    validFlag === undefined ? null : validFlag > 0;

  const sourceBadgeTone =
    resolvedDataType === "processed" ? "accent" : "warning";
  const sourceBadgeLabel = fallbackToRaw
    ? "Raw Fallback"
    : resolvedDataType === "processed"
      ? "Processed"
      : "Raw";

  const xKey = isProcessed ? "NormalizedDistance" : "CurrentLap";
  const chartConfigs = useMemo(
    () => ({
      speed: {
        label: isProcessed ? "Speed (km/h)" : "Speed (m/s)",
        yKey: isProcessed ? "SpeedKph" : "Speed",
        color: "var(--app-chart-speed)",
      },
      throttle: {
        label: isProcessed ? "Throttle (0-1)" : "Throttle (0-255)",
        yKey: isProcessed ? "Throttle" : "Accel",
        color: "var(--app-chart-throttle)",
      },
      brake: {
        label: isProcessed ? "Brake (0-1)" : "Brake (0-255)",
        yKey: "Brake",
        color: "var(--app-chart-brake)",
      },
      steering: {
        label: "Steering",
        yKey: isProcessed ? "Steering" : "Steer",
        color: "var(--app-chart-steering)",
      },
    }),
    [isProcessed],
  );

  const visibleChartKeys = CHART_ORDER.filter((key) => visibleCharts[key]);
  const visibleMiddleCharts = (["throttle", "brake"] as ChartKey[]).filter(
    (key) => visibleCharts[key],
  );

  const toggleChartVisibility = (key: ChartKey) => {
    setVisibleCharts((current) => {
      const nextValue = !current[key];
      if (!nextValue) {
        setFocusedChart((focused) => (focused === key ? null : focused));
      }

      return { ...current, [key]: nextValue };
    });
  };

  const renderChart = (key: ChartKey, height?: number, className = "") => {
    const config = chartConfigs[key];
    const focused = focusedChart === key;

    return (
      <LapChart
        key={`${resolvedDataType}-${key}`}
        data={records}
        xKey={xKey}
        yKey={config.yKey}
        label={config.label}
        color={config.color}
        syncId="lap-review"
        height={height}
        className={className}
        action={
          <button
            type="button"
            onClick={() => setFocusedChart(focused ? null : key)}
            className={`motion-safe-color inline-flex h-8 items-center rounded-full border px-3 text-[10px] font-medium uppercase tracking-[0.14em] cursor-pointer ${
              focused
                ? "border-border-strong bg-surface-2/90 text-text-primary hover:bg-surface-3"
                : "border-accent/20 bg-accent/10 text-accent hover:bg-accent/16"
            }`}
          >
            {focused ? "Close Focus" : "Focus"}
          </button>
        }
        emptyMessage={`No ${config.label.toLowerCase()} data available for this lap.`}
      />
    );
  };

  if (!canLoad || !sessionId || !lapNumber) {
    return (
      <SurfaceMessage
        title="Lap not available"
        message="This lap route is missing the session or lap identifier."
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
                  Lap {lapNumber}
                </h2>
                <StatusPill tone={sourceBadgeTone}>{sourceBadgeLabel}</StatusPill>
                {lapIsValid !== null && (
                  <StatusPill tone={lapIsValid ? "success" : "danger"}>
                    {lapIsValid ? "Valid" : "Invalid"}
                  </StatusPill>
                )}
              </div>

              {fallbackToRaw && (
                <p className="mt-2 text-sm text-text-secondary">
                  Processed telemetry is unavailable for this lap. Showing raw data
                  instead.
                </p>
              )}
            </div>

            <div className="relative inline-grid min-w-[220px] grid-cols-2 rounded-full border border-border/70 bg-surface-2/88 p-1">
              <span
                aria-hidden="true"
                className="motion-safe-slide pointer-events-none absolute inset-y-1 left-1 rounded-full border border-accent/20 bg-accent/12 will-change-transform"
                style={{
                  width: "calc(50% - 0.25rem)",
                  transform:
                    requestedDataType === "raw"
                      ? "translateX(calc(100% + 0.25rem))"
                      : "translateX(0)",
                }}
              />
              {(["processed", "raw"] as const).map((value) => {
                const active = requestedDataType === value;

                return (
                  <button
                    key={value}
                    type="button"
                    onClick={() => setRequestedDataType(value)}
                    className={`motion-safe-color relative z-10 inline-flex h-9 items-center justify-center rounded-full px-4 text-sm font-medium capitalize cursor-pointer ${
                      active
                        ? "text-accent"
                        : "text-text-muted hover:text-text-primary"
                    }`}
                    aria-pressed={active}
                    disabled={loading}
                  >
                    {value}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="mt-4 flex flex-wrap gap-2">
            <SummaryStat label="Session" value={sessionId} mono />
            <SummaryStat label="Lap" value={`Lap ${lapNumber}`} />
            <SummaryStat label="Source" value={sourceBadgeLabel} />
            {isProcessed && (
              <SummaryStat
                label="Validity"
                value={
                  lapIsValid === null ? "Unknown" : lapIsValid ? "Valid" : "Invalid"
                }
                tone={
                  lapIsValid === null
                    ? "neutral"
                    : lapIsValid
                      ? "success"
                      : "danger"
                }
              />
            )}
            <SummaryStat label="Lap Time" value={formatLapTime(lapTimeS)} />
          </div>

          <div className="mt-4 flex flex-wrap items-center gap-2">
            {CHART_ORDER.map((key) => {
              const active = visibleCharts[key];

              return (
                <button
                  key={key}
                  type="button"
                  onClick={() => toggleChartVisibility(key)}
                  aria-pressed={active}
                  className={`motion-safe-color inline-flex h-9 items-center rounded-full border px-4 text-[11px] font-medium uppercase tracking-[0.16em] cursor-pointer ${
                    active
                      ? "border-accent/24 bg-accent/12 text-accent"
                      : "border-border/70 bg-surface-2/84 text-text-secondary hover:border-border-strong hover:bg-surface-3 hover:text-text-primary"
                  }`}
                >
                  {key}
                </button>
              );
            })}
          </div>
        </div>
      </section>

      {showBlockingLoad ? (
        <div className="density-analysis-stack">
          <SurfaceSkeleton rows={4} />
          <div className="grid gap-4 lg:grid-cols-2">
            <SurfaceSkeleton rows={3} />
            <SurfaceSkeleton rows={3} />
          </div>
          <SurfaceSkeleton rows={3} />
        </div>
      ) : error ? (
        <SurfaceMessage
          title="Could not load lap telemetry"
          message={error}
          actionLabel="Retry"
          onAction={() => setReloadToken((current) => current + 1)}
          tone="danger"
        />
      ) : !lapData ? (
        <SurfaceMessage
          title="No lap telemetry found"
          message="This lap does not have readable telemetry in the selected source."
        />
      ) : visibleChartKeys.length === 0 ? (
        <SurfaceMessage
          title="No charts selected"
          message="Turn on at least one telemetry series to continue reviewing this lap."
        />
      ) : focusedChart ? (
        renderChart(focusedChart, 420, "themed-shadow-lg")
      ) : (
        <div className="density-analysis-stack">
          {visibleCharts.speed && renderChart("speed", 260)}

          {visibleMiddleCharts.length > 0 && (
            <div
              className={`grid gap-4 ${
                visibleMiddleCharts.length > 1 ? "lg:grid-cols-2" : ""
              }`}
            >
              {visibleMiddleCharts.map((key) => renderChart(key))}
            </div>
          )}

          {visibleCharts.steering && renderChart("steering", 220)}
        </div>
      )}
    </div>
  );
}
