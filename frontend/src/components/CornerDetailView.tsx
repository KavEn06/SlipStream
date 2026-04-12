import { useEffect, useRef, useState } from "react";
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
import { TrackMap } from "./TrackMap";

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
  if (typeof rawIndex === "number" && rawIndex >= 0 && rawIndex < data.length) {
    return data[rawIndex];
  }

  return null;
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
              width={28}
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

  // Build merged chart data aligned on the 400-point NormalizedDistance grid
  const chartData: ChartRow[] = [];
  if (candLap && baseLap) {
    const baseByKey = new Map<number, Record<string, number | string>>();
    for (const r of baseLap.records) {
      const n = toNum(r.NormalizedDistance);
      baseByKey.set(Math.round(n * 100000), r);
    }
    for (const r of candLap.records) {
      const n = toNum(r.NormalizedDistance);
      if (n < approachNorm || n > endNorm) continue;
      const br = baseByKey.get(Math.round(n * 100000));
      chartData.push({
        progressNorm: n,
        distM: Math.round(n * referenceLengthM),
        candSpeed: toNum(r.SpeedKph),
        baseSpeed: br ? toNum(br.SpeedKph) : undefined,
        candBrake: toNum(r.Brake),
        baseBrake: br ? toNum(br.Brake) : undefined,
        candThrottle: getThrottle(r),
        baseThrottle: br ? getThrottle(br) : undefined,
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

  const showThrottle = finding.detector === "exit_phase_loss";

  return (
    <div className="flex flex-col gap-4">
      {/* Track map */}
      <div className="w-full overflow-hidden rounded-2xl border border-border/60 bg-surface-2/40">
        {loading && !candLap ? (
          <div className="flex h-[280px] items-center justify-center">
            <p className="text-xs text-text-muted">Loading track…</p>
          </div>
        ) : candLap ? (
          <TrackMap
            records={candLap.records}
            activeIndex={null}
            activeScrubValue={activeTrackProgressNorm}
            xKey="NormalizedDistance"
            height={280}
            corners={[cornerDef]}
            showCorners
          />
        ) : null}
      </div>

      {/* Telemetry charts */}
      <div className="flex min-w-0 flex-col gap-3">
        {loading && chartData.length === 0 ? (
          <p className="text-xs text-text-muted">Loading telemetry…</p>
        ) : chartData.length > 0 ? (
          <>
            <MiniChart
              data={chartData}
              candKey="candSpeed"
              baseKey="baseSpeed"
              label="Speed"
              formatter={(v) => `${v.toFixed(0)} kph`}
              eventDistances={eventDistances}
              candLapNumber={finding.lap_number}
              baseLapNumber={baselineLapNumber}
              syncId="corner-detail"
              onActiveProgressNormChange={setHoveredProgressNorm}
            />
            {showThrottle ? (
              <MiniChart
                data={chartData}
                candKey="candThrottle"
                baseKey="baseThrottle"
                label="Throttle"
                domain={[0, 1]}
                formatter={(v) => `${(v * 100).toFixed(0)}%`}
                eventDistances={eventDistances}
                candLapNumber={finding.lap_number}
                baseLapNumber={baselineLapNumber}
                syncId="corner-detail"
                onActiveProgressNormChange={setHoveredProgressNorm}
              />
            ) : (
              <MiniChart
                data={chartData}
                candKey="candBrake"
                baseKey="baseBrake"
                label="Brake"
                domain={[0, 1]}
                formatter={(v) => `${(v * 100).toFixed(0)}%`}
                eventDistances={eventDistances}
                candLapNumber={finding.lap_number}
                baseLapNumber={baselineLapNumber}
                syncId="corner-detail"
                onActiveProgressNormChange={setHoveredProgressNorm}
              />
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
