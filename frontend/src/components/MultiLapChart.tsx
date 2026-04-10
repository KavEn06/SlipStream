import { useCallback, useMemo } from "react";
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

const COLORS = {
  grid: "var(--app-chart-grid)",
  axis: "var(--app-chart-axis)",
  tick: "var(--app-chart-tick)",
  tooltipBg: "var(--app-chart-tooltip-bg)",
  tooltipBorder: "var(--app-chart-tooltip-border)",
};

const CHART_GRID_POINTS = 400;

export interface MultiLapSeries {
  id: string;
  label: string;
  color: string;
  isReference: boolean;
  records: Record<string, number | string>[];
}

interface Props {
  series: MultiLapSeries[];
  yKey: string;
  label: string;
  height?: number;
  className?: string;
  syncId?: string;
  xKey?: string;
  activeXValue?: number | null;
  onActiveXValueChange?: (value: number | null) => void;
  xTickFormatter?: (value: number | string) => string;
  xTooltipLabelFormatter?: (value: number | string) => string;
  yValueFormatter?: (
    value: number | string | readonly (number | string)[] | undefined,
  ) => string;
}

function formatProgressTick(value: number | string): string {
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

function formatNumber(value: number): string {
  if (!Number.isFinite(value)) {
    return String(value);
  }
  if (value === 0) {
    return "0";
  }
  return Number.parseFloat(value.toPrecision(4)).toString();
}

function formatTooltipValue(
  value: number | string | readonly (number | string)[] | undefined,
): string {
  if (value === undefined) {
    return "";
  }
  if (Array.isArray(value)) {
    return value.map((entry) => formatTooltipValue(entry)).join(" - ");
  }
  if (typeof value === "number") {
    return formatNumber(value);
  }
  if (typeof value === "string") {
    const numeric = Number(value);
    return Number.isFinite(numeric) && value.trim() !== "" ? formatNumber(numeric) : value;
  }
  return String(value);
}

function buildAxisGrid(series: MultiLapSeries[], points: number, xKey: string): number[] {
  let minX = Infinity;
  let maxX = -Infinity;

  for (const lap of series) {
    for (const record of lap.records) {
      const rawValue = record[xKey];
      const axisValue =
        typeof rawValue === "number"
          ? rawValue
          : typeof rawValue === "string" && rawValue.trim() !== ""
            ? Number(rawValue)
            : Number.NaN;
      if (!Number.isFinite(axisValue)) {
        continue;
      }
      minX = Math.min(minX, axisValue);
      maxX = Math.max(maxX, axisValue);
    }
  }

  if (!Number.isFinite(minX) || !Number.isFinite(maxX)) {
    return [];
  }

  if (Math.abs(maxX - minX) < 1e-9) {
    return [minX];
  }

  return Array.from(
    { length: points },
    (_, index) => minX + ((maxX - minX) * index) / (points - 1),
  );
}

function interpolateSeriesValue(
  records: Record<string, number | string>[],
  xKey: string,
  yKey: string,
  targetX: number,
): number | null {
  const EDGE_EPSILON = 1e-9;
  const points = records
    .map((record) => {
      const rawX = record[xKey];
      const rawValue = record[yKey];
      const axisValue =
        typeof rawX === "number"
          ? rawX
          : typeof rawX === "string" && rawX.trim() !== ""
            ? Number(rawX)
            : Number.NaN;
      const value =
        typeof rawValue === "number"
          ? rawValue
          : typeof rawValue === "string" && rawValue.trim() !== ""
            ? Number(rawValue)
            : Number.NaN;
      return {
        axisValue,
        value,
      };
    })
    .filter((point) => Number.isFinite(point.axisValue) && Number.isFinite(point.value))
    .sort((left, right) => left.axisValue - right.axisValue);

  if (!points.length) {
    return null;
  }

  if (targetX < points[0].axisValue - EDGE_EPSILON) {
    return null;
  }

  if (targetX <= points[0].axisValue + EDGE_EPSILON) {
    return points[0].value;
  }

  const lastPoint = points[points.length - 1];
  if (targetX > lastPoint.axisValue + EDGE_EPSILON) {
    return null;
  }

  if (targetX >= lastPoint.axisValue - EDGE_EPSILON) {
    return lastPoint.value;
  }

  for (let index = 1; index < points.length; index += 1) {
    const previous = points[index - 1];
    const current = points[index];
    if (targetX > current.axisValue) {
      continue;
    }
    if (Math.abs(current.axisValue - previous.axisValue) < 1e-9) {
      return current.value;
    }
    const ratio = (targetX - previous.axisValue) / (current.axisValue - previous.axisValue);
    return previous.value + ((current.value - previous.value) * ratio);
  }

  return lastPoint.value;
}

export function MultiLapChart({
  series,
  yKey,
  label,
  height = 240,
  className = "",
  syncId,
  xKey = "TrackProgressNorm",
  activeXValue = null,
  onActiveXValueChange,
  xTickFormatter,
  xTooltipLabelFormatter,
  yValueFormatter,
}: Props) {
  const activeSeries = useMemo(
    () =>
      series.filter((lap) =>
        lap.records.some((record) => record[yKey] !== undefined && record[xKey] !== undefined),
      ),
    [series, xKey, yKey],
  );

  const chartData = useMemo(() => {
    const axisGrid = buildAxisGrid(activeSeries, CHART_GRID_POINTS, xKey);
    return axisGrid.map((axisValue) => {
      const row: Record<string, number | string | null> = { [xKey]: axisValue };
      for (const lap of activeSeries) {
        row[lap.id] = interpolateSeriesValue(lap.records, xKey, yKey, axisValue);
      }
      return row;
    });
  }, [activeSeries, xKey, yKey]);

  const handleMouseMove = useCallback(
    (state: Record<string, unknown>) => {
      if (!state?.isTooltipActive || !onActiveXValueChange) {
        return;
      }
      const activeLabel = state.activeLabel;
      const axisValue =
        typeof activeLabel === "number"
          ? activeLabel
          : typeof activeLabel === "string" && activeLabel.trim() !== ""
            ? Number(activeLabel)
            : Number.NaN;
      if (Number.isFinite(axisValue)) {
        onActiveXValueChange(axisValue);
      }
    },
    [onActiveXValueChange],
  );

  const handleMouseLeave = useCallback(() => {
    onActiveXValueChange?.(null);
  }, [onActiveXValueChange]);

  if (!chartData.length || !activeSeries.length) {
    return (
      <div
        className={`density-analysis-chart rounded-3xl border border-border/70 bg-surface-1/85 ${className}`.trim()}
      >
        <div className="mb-3 flex items-start justify-between gap-3">
          <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-text-muted">
            {label}
          </p>
        </div>
        <div className="flex h-40 items-center justify-center rounded-2xl border border-dashed border-border/70 bg-surface-2/72 p-4 text-sm text-text-muted">
          No {label.toLowerCase()} data available for the selected laps.
        </div>
      </div>
    );
  }

  return (
    <div
      className={`density-analysis-chart rounded-3xl border border-border/70 bg-surface-1/85 ${className}`.trim()}
    >
      <div className="mb-3 flex items-start justify-between gap-3">
        <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-text-muted">
          {label}
        </p>
      </div>
      <ResponsiveContainer width="100%" height={height}>
        <LineChart
          data={chartData}
          syncId={syncId}
          onMouseMove={handleMouseMove}
          onMouseLeave={handleMouseLeave}
        >
          <CartesianGrid stroke={COLORS.grid} strokeDasharray="2 6" />
          <XAxis
            dataKey={xKey}
            tick={{ fill: COLORS.tick, fontSize: 10 }}
            stroke={COLORS.axis}
            tickFormatter={xTickFormatter ?? formatTooltipValue}
          />
          <YAxis
            tick={{ fill: COLORS.tick, fontSize: 10 }}
            stroke={COLORS.axis}
            width={55}
            tickFormatter={(value: number | string) =>
              yValueFormatter ? yValueFormatter(value) : formatTooltipValue(value)
            }
          />
          {activeXValue !== null && Number.isFinite(activeXValue) && (
            <ReferenceLine
              x={activeXValue}
              stroke={COLORS.axis}
              strokeDasharray="3 6"
            />
          )}
          <Tooltip
            cursor={{ stroke: COLORS.axis, strokeDasharray: "3 6" }}
            contentStyle={{
              backgroundColor: COLORS.tooltipBg,
              border: `1px solid ${COLORS.tooltipBorder}`,
              borderRadius: 14,
              fontSize: 12,
            }}
            labelStyle={{ color: COLORS.tick }}
            labelFormatter={(value) =>
              xTooltipLabelFormatter
                ? xTooltipLabelFormatter(value as number | string)
                : formatTooltipValue(value as number | string)
            }
            formatter={(value, name) => [
              yValueFormatter ? yValueFormatter(value) : formatTooltipValue(value),
              activeSeries.find((lap) => lap.id === name)?.label ?? String(name),
            ]}
          />
          {activeSeries.map((lap) => (
            <Line
              key={lap.id}
              type="monotone"
              dataKey={lap.id}
              stroke={lap.color}
              dot={false}
              strokeWidth={lap.isReference ? 2.6 : 1.7}
              opacity={lap.isReference ? 1 : 0.66}
              isAnimationActive={false}
              connectNulls
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
