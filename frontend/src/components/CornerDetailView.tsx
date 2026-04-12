import { useEffect, useMemo, useRef, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "../api/client";
import type { AnalysisFinding, CornerDefinition, LapData } from "../types";
import { CompareTrackMap } from "./CompareTrackMap";

// Module-level cache: persists across component mounts within the page session.
const _lapCache = new Map<string, LapData>();

function lapCacheKey(sessionId: string, lapNumber: number) {
  return `${sessionId}/${lapNumber}`;
}

async function fetchLapCached(sessionId: string, lapNumber: number): Promise<LapData> {
  const key = lapCacheKey(sessionId, lapNumber);
  if (_lapCache.has(key)) return _lapCache.get(key)!;
  const data = await api.getLap(sessionId, lapNumber);
  _lapCache.set(key, data);
  return data;
}

function toNum(v: number | string | undefined | null): number {
  if (v === undefined || v === null) return 0;
  return typeof v === "number" ? v : parseFloat(v as string) || 0;
}

function getThrottle(r: Record<string, number | string>): number {
  return r.Throttle !== undefined ? toNum(r.Throttle) : toNum(r.Accel);
}

interface ChartRow {
  progressNorm: number;
  distM: number;
  candSpeed: number;
  baseSpeed?: number;
  candBrake: number;
  baseBrake?: number;
  candThrottle: number;
  baseThrottle?: number;
  candSteering: number;
  baseSteering?: number;
}

const CAND_COLOR = "#f97316"; // orange-500 — driver's lap
const BASE_COLOR = "#60a5fa"; // blue-400  — reference lap

const CHART_TOOLTIP_STYLE = {
  background: "rgba(14,14,20,0.92)",
  border: "1px solid rgba(255,255,255,0.09)",
  borderRadius: 8,
  fontSize: 11,
  color: "rgba(255,255,255,0.8)",
};

const AXIS_TICK_STYLE = { fontSize: 9, fill: "rgba(255,255,255,0.35)" };
const GRID_STROKE = "rgba(255,255,255,0.05)";
const CHART_SAMPLE_COUNT = 220;

interface LapMetricSample {
  progressNorm: number;
  speed: number;
  brake: number;
  throttle: number;
  steering: number;
}

type DetailChartKey = "speed" | "throttle" | "brake" | "steering";

const DETAIL_CHART_ORDER: DetailChartKey[] = ["speed", "throttle", "brake", "steering"];
const DEFAULT_VISIBLE_CHARTS: Record<DetailChartKey, boolean> = {
  speed: true,
  throttle: true,
  brake: true,
  steering: true,
};

function resolveActiveChartRow(
  state: Record<string, unknown>,
  data: ChartRow[],
): ChartRow | null {
  const activePayload = state.activePayload;
  if (Array.isArray(activePayload) && activePayload.length > 0) {
    const payloadCandidate = activePayload[0];
    if (
      payloadCandidate &&
      typeof payloadCandidate === "object" &&
      "payload" in payloadCandidate
    ) {
      const row = (payloadCandidate as { payload?: unknown }).payload;
      if (row && typeof row === "object" && "progressNorm" in row) {
        return row as ChartRow;
      }
    }
  }

  const rawIndex = state.activeTooltipIndex;
  const tooltipIndex =
    typeof rawIndex === "number"
      ? rawIndex
      : typeof rawIndex === "string" && rawIndex.trim() !== ""
        ? Number(rawIndex)
        : Number.NaN;
  if (Number.isFinite(tooltipIndex) && tooltipIndex >= 0 && tooltipIndex < data.length) {
    return data[tooltipIndex];
  }

  return null;
}

function getRecordProgressNorm(record: Record<string, number | string>): number | null {
  const alignedProgress = toNum(record.TrackProgressNorm);
  if (Number.isFinite(alignedProgress)) {
    return alignedProgress;
  }

  const normalizedDistance = toNum(record.NormalizedDistance);
  return Number.isFinite(normalizedDistance) ? normalizedDistance : null;
}

function buildLapMetricSamples(
  records: Record<string, number | string>[],
): LapMetricSample[] {
  return records
    .map((record) => {
      const progressNorm = getRecordProgressNorm(record);
      if (progressNorm === null) {
        return null;
      }

      return {
        progressNorm,
        speed: toNum(record.SpeedKph),
        brake: toNum(record.Brake),
        throttle: getThrottle(record),
        steering: toNum(record.Steering),
      };
    })
    .filter((sample): sample is LapMetricSample => sample !== null)
    .sort((left, right) => left.progressNorm - right.progressNorm);
}

function interpolateLapMetric(
  samples: LapMetricSample[],
  progressNorm: number,
  key: "speed" | "brake" | "throttle" | "steering",
): number | undefined {
  if (samples.length === 0) {
    return undefined;
  }

  const first = samples[0];
  const last = samples[samples.length - 1];
  if (progressNorm < first.progressNorm || progressNorm > last.progressNorm) {
    return undefined;
  }
  if (progressNorm === first.progressNorm) {
    return first[key];
  }
  if (progressNorm === last.progressNorm) {
    return last[key];
  }

  for (let index = 1; index < samples.length; index += 1) {
    const previous = samples[index - 1];
    const current = samples[index];
    if (progressNorm < previous.progressNorm || progressNorm > current.progressNorm) {
      continue;
    }

    const progressSpan = current.progressNorm - previous.progressNorm;
    if (progressSpan <= 0) {
      return current[key];
    }

    const ratio = (progressNorm - previous.progressNorm) / progressSpan;
    return previous[key] + (current[key] - previous[key]) * ratio;
  }

  return undefined;
}

function buildChartGrid(startNorm: number, endNorm: number): number[] {
  if (endNorm <= startNorm) {
    return [startNorm];
  }

  const points: number[] = [];
  const step = (endNorm - startNorm) / (CHART_SAMPLE_COUNT - 1);
  for (let index = 0; index < CHART_SAMPLE_COUNT; index += 1) {
    points.push(startNorm + step * index);
  }
  return points;
}

interface MiniChartProps {
  data: ChartRow[];
  candKey: keyof ChartRow;
  baseKey: keyof ChartRow;
  label: string;
  domain?: [number | string, number | string];
  formatter: (v: number) => string;
  eventDistances: number[];
  candLapNumber: number;
  baseLapNumber: number;
  syncId?: string;
  onActiveProgressNormChange?: (value: number | null) => void;
}

function MiniChart({
  data,
  candKey,
  baseKey,
  label,
  domain,
  formatter,
  eventDistances,
  candLapNumber,
  baseLapNumber,
  syncId,
  onActiveProgressNormChange,
}: MiniChartProps) {
  return (
    <div>
      <div className="mb-1 flex items-center gap-2">
        <span className="text-[10px] uppercase tracking-[0.14em] text-text-muted">{label}</span>
        <span className="flex items-center gap-1 text-[9px] text-text-muted">
          <span className="inline-block h-[2px] w-3 rounded" style={{ background: CAND_COLOR }} />
          Lap {candLapNumber}
        </span>
        <span className="flex items-center gap-1 text-[9px] text-text-muted">
          <span className="inline-block h-[2px] w-3 rounded" style={{ background: BASE_COLOR }} />
          Lap {baseLapNumber} (ref)
        </span>
      </div>
      <div className="h-[88px]">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart
            data={data}
            syncId={syncId}
            margin={{ top: 2, right: 4, left: 0, bottom: 0 }}
            onMouseMove={(state) => {
              if (!state?.isTooltipActive) {
                return;
              }

              const row = resolveActiveChartRow(state as Record<string, unknown>, data);
              onActiveProgressNormChange?.(row?.progressNorm ?? null);
            }}
            onMouseLeave={() => {
              onActiveProgressNormChange?.(null);
            }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke={GRID_STROKE} vertical={false} />
            <XAxis
              dataKey="distM"
              tick={false}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              width={44}
              tick={AXIS_TICK_STYLE}
              axisLine={false}
              tickLine={false}
              domain={domain}
              tickFormatter={(v: number) => formatter(v)}
            />
            <Tooltip
              contentStyle={CHART_TOOLTIP_STYLE}
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              formatter={(v: any, name: any) => [
                typeof v === "number" ? formatter(v) : String(v),
                typeof name === "string" && name.startsWith("base")
                  ? `Lap ${baseLapNumber} (ref)`
                  : `Lap ${candLapNumber}`,
              ]}
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              labelFormatter={(l: any) => `${l} m`}
              itemStyle={{ color: "rgba(255,255,255,0.8)" }}
            />
            {eventDistances.map((d) => (
              <ReferenceLine
                key={d}
                x={d}
                stroke="rgba(255,255,255,0.18)"
                strokeWidth={1}
              />
            ))}
            <Line
              dataKey={baseKey as string}
              stroke={BASE_COLOR}
              dot={false}
              strokeWidth={1.5}
              strokeOpacity={0.75}
              isAnimationActive={false}
            />
            <Line
              dataKey={candKey as string}
              stroke={CAND_COLOR}
              dot={false}
              strokeWidth={2}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

interface Props {
  finding: AnalysisFinding;
  cornerDef: CornerDefinition;
  sessionId: string;
  baselineLapNumber: number;
  referenceLengthM: number;
}

export function CornerDetailView({
  finding,
  cornerDef,
  sessionId,
  baselineLapNumber,
  referenceLengthM,
}: Props) {
  const [candLap, setCandLap] = useState<LapData | null>(null);
  const [baseLap, setBaseLap] = useState<LapData | null>(null);
  const [loading, setLoading] = useState(false);
  const [hoveredProgressNorm, setHoveredProgressNorm] = useState<number | null>(null);
  const [visibleCharts, setVisibleCharts] = useState(DEFAULT_VISIBLE_CHARTS);
  const abortRef = useRef(false);

  useEffect(() => {
    abortRef.current = false;
    setLoading(true);
    setCandLap(null);
    setBaseLap(null);
    setHoveredProgressNorm(null);

    Promise.all([
      fetchLapCached(sessionId, finding.lap_number),
      fetchLapCached(sessionId, baselineLapNumber),
    ])
      .then(([cand, base]) => {
        if (abortRef.current) return;
        setCandLap(cand);
        setBaseLap(base);
      })
      .catch(() => {
        // silent — the loading spinner disappears and charts stay empty
      })
      .finally(() => {
        if (!abortRef.current) setLoading(false);
      });

    return () => {
      abortRef.current = true;
    };
  }, [sessionId, finding.lap_number, baselineLapNumber]);

  // Window bounds: approach start → corner end (with a tiny exit buffer)
  const approachNorm = Math.max(
    0,
    cornerDef.approach_start_distance_m / referenceLengthM,
  );
  const endNorm = Math.min(1, cornerDef.end_progress_norm + 0.004);

  // Build merged chart data on a shared aligned-progress grid so the
  // candidate and reference traces render continuously across the corner.
  const chartData: ChartRow[] = [];
  if (candLap && baseLap) {
    const candidateSamples = buildLapMetricSamples(candLap.records);
    const baselineSamples = buildLapMetricSamples(baseLap.records);

    for (const progressNorm of buildChartGrid(approachNorm, endNorm)) {
      const candSpeed = interpolateLapMetric(candidateSamples, progressNorm, "speed");
      const candBrake = interpolateLapMetric(candidateSamples, progressNorm, "brake");
      const candThrottle = interpolateLapMetric(candidateSamples, progressNorm, "throttle");
      const candSteering = interpolateLapMetric(candidateSamples, progressNorm, "steering");
      const baseSpeed = interpolateLapMetric(baselineSamples, progressNorm, "speed");
      const baseBrake = interpolateLapMetric(baselineSamples, progressNorm, "brake");
      const baseThrottle = interpolateLapMetric(baselineSamples, progressNorm, "throttle");
      const baseSteering = interpolateLapMetric(baselineSamples, progressNorm, "steering");

      if (
        candSpeed === undefined &&
        candBrake === undefined &&
        candThrottle === undefined &&
        candSteering === undefined &&
        baseSpeed === undefined &&
        baseBrake === undefined &&
        baseThrottle === undefined &&
        baseSteering === undefined
      ) {
        continue;
      }

      chartData.push({
        progressNorm,
        distM: Math.round(progressNorm * referenceLengthM),
        candSpeed: candSpeed ?? 0,
        baseSpeed,
        candBrake: candBrake ?? 0,
        baseBrake,
        candThrottle: candThrottle ?? 0,
        baseThrottle,
        candSteering: candSteering ?? 0,
        baseSteering,
      });
    }
  }

  // Event marker distances (from evidence_refs progress_start values)
  const eventDistances = finding.evidence_refs
    .filter((e) => e.progress_start !== undefined)
    .map((e) => Math.round((e.progress_start as number) * referenceLengthM));

  // Active marker on track map: first evidence ref progress_start
  const primaryEventNorm =
    (finding.evidence_refs[0]?.progress_start as number | undefined) ?? null;
  const activeTrackProgressNorm = hoveredProgressNorm ?? primaryEventNorm ?? null;
  const trackSeries = useMemo(
    () =>
      candLap && baseLap
        ? [
            {
              id: `candidate-${sessionId}-${finding.lap_number}`,
              label: `Lap ${finding.lap_number}`,
              color: CAND_COLOR,
              isReference: false,
              records: candLap.records,
            },
            {
              id: `reference-${sessionId}-${baselineLapNumber}`,
              label: `Lap ${baselineLapNumber} (ref)`,
              color: BASE_COLOR,
              isReference: true,
              records: baseLap.records,
            },
          ]
        : null,
    [baseLap, baselineLapNumber, candLap, finding.lap_number, sessionId],
  );
  const visibleChartKeys = DETAIL_CHART_ORDER.filter((key) => visibleCharts[key]);

  const toggleChartVisibility = (key: DetailChartKey) => {
    setVisibleCharts((current) => ({ ...current, [key]: !current[key] }));
  };

  const chartConfigs: Record<
    DetailChartKey,
    {
      candKey: keyof ChartRow;
      baseKey: keyof ChartRow;
      label: string;
      domain?: [number | string, number | string];
      formatter: (v: number) => string;
    }
  > = {
    speed: {
      candKey: "candSpeed",
      baseKey: "baseSpeed",
      label: "Speed",
      formatter: (v) => `${v.toFixed(0)} kph`,
    },
    throttle: {
      candKey: "candThrottle",
      baseKey: "baseThrottle",
      label: "Throttle",
      domain: [0, 1],
      formatter: (v) => `${(v * 100).toFixed(0)}%`,
    },
    brake: {
      candKey: "candBrake",
      baseKey: "baseBrake",
      label: "Brake",
      domain: [0, 1],
      formatter: (v) => `${(v * 100).toFixed(0)}%`,
    },
    steering: {
      candKey: "candSteering",
      baseKey: "baseSteering",
      label: "Steering",
      formatter: (v) => v.toFixed(2),
    },
  };

  return (
    <div className="flex flex-col gap-4">
      {/* Track map */}
      <div className="w-full overflow-hidden rounded-2xl border border-border/60 bg-surface-2/40">
        {loading && !candLap ? (
          <div className="flex h-[280px] items-center justify-center">
            <p className="text-xs text-text-muted">Loading track…</p>
          </div>
        ) : trackSeries ? (
          <CompareTrackMap
            series={trackSeries}
            activeProgressNorm={activeTrackProgressNorm}
            activeMode="progress"
            height={280}
            corners={[cornerDef]}
            focusStartProgressNorm={approachNorm}
            focusEndProgressNorm={endNorm}
            autoFocusKey={finding.finding_id}
            showTrackEnvelope
          />
        ) : null}
      </div>

      {/* Telemetry charts */}
      <div className="flex min-w-0 flex-col gap-3">
        {loading && chartData.length === 0 ? (
          <p className="text-xs text-text-muted">Loading telemetry…</p>
        ) : chartData.length > 0 ? (
          <>
            <div className="flex flex-wrap items-center gap-2">
              {DETAIL_CHART_ORDER.map((key) => {
                const active = visibleCharts[key];
                return (
                  <button
                    key={key}
                    type="button"
                    onClick={() => toggleChartVisibility(key)}
                    aria-pressed={active}
                    className={`motion-safe-color inline-flex h-8 items-center rounded-full border px-3 text-[10px] font-medium uppercase tracking-[0.14em] cursor-pointer ${
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
            {visibleChartKeys.length > 0 ? (
              <div className={`grid gap-3 ${visibleChartKeys.length > 1 ? "xl:grid-cols-2" : ""}`}>
                {visibleChartKeys.map((key) => {
                  const config = chartConfigs[key];
                  return (
                    <MiniChart
                      key={key}
                      data={chartData}
                      candKey={config.candKey}
                      baseKey={config.baseKey}
                      label={config.label}
                      domain={config.domain}
                      formatter={config.formatter}
                      eventDistances={eventDistances}
                      candLapNumber={finding.lap_number}
                      baseLapNumber={baselineLapNumber}
                      syncId="corner-detail"
                      onActiveProgressNormChange={setHoveredProgressNorm}
                    />
                  );
                })}
              </div>
            ) : (
              <p className="text-xs text-text-muted">
                Select at least one graph to compare this corner.
              </p>
            )}
            <p className="text-right text-[9px] text-text-muted">
              {Math.round(approachNorm * referenceLengthM)}m –{" "}
              {Math.round(cornerDef.end_progress_norm * referenceLengthM)}m along track
              {eventDistances.length > 0 && " · markers = key events"}
            </p>
          </>
        ) : null}
      </div>
    </div>
  );
}
