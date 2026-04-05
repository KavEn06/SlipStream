import { useCallback, type ReactNode } from "react";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
} from "recharts";

const COLORS = {
  grid: "var(--app-chart-grid)",
  axis: "var(--app-chart-axis)",
  tick: "var(--app-chart-tick)",
  tooltipBg: "var(--app-chart-tooltip-bg)",
  tooltipBorder: "var(--app-chart-tooltip-border)",
};

function resolveActiveIndex(
  state: Record<string, unknown>,
  data: Record<string, number | string>[],
  xKey?: string,
): number | null {
  const rawTooltipIndex = state.activeTooltipIndex;
  if (typeof rawTooltipIndex === "number" && rawTooltipIndex >= 0) {
    return rawTooltipIndex;
  }

  if (!xKey) {
    return null;
  }

  const activeLabel = state.activeLabel;
  if (activeLabel === undefined || activeLabel === null) {
    return null;
  }

  const normalizedLabel =
    typeof activeLabel === "number"
      ? activeLabel
      : typeof activeLabel === "string" && activeLabel.trim() !== ""
        ? Number(activeLabel)
        : activeLabel;

  return (
    data.findIndex((row) => {
      const rowValue = row[xKey];
      if (typeof normalizedLabel === "number") {
        const numericRowValue =
          typeof rowValue === "number"
            ? rowValue
            : typeof rowValue === "string" && rowValue.trim() !== ""
              ? Number(rowValue)
              : Number.NaN;
        return Number.isFinite(numericRowValue) && Math.abs(numericRowValue - normalizedLabel) < 1e-6;
      }

      return rowValue === normalizedLabel;
    }) ?? -1
  );
}

function formatTooltipNumber(value: number): string {
  if (!Number.isFinite(value)) {
    return String(value);
  }

  if (value === 0) {
    return "0";
  }

  return Number.parseFloat(value.toPrecision(3)).toString();
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
    return formatTooltipNumber(value);
  }

  if (typeof value === "string") {
    const numericValue = Number(value);
    if (!Number.isNaN(numericValue) && value.trim() !== "") {
      return formatTooltipNumber(numericValue);
    }

    return value;
  }

  return String(value);
}

interface Props {
  data: Record<string, number | string>[];
  xKey?: string;
  yKey: string;
  label: string;
  color: string;
  xTickFormatter?: (value: number | string) => string;
  xValueFormatter?: (
    value: number | string | readonly (number | string)[] | undefined,
  ) => string;
  yValueFormatter?: (
    value: number | string | readonly (number | string)[] | undefined,
  ) => string;
  height?: number;
  syncId?: string;
  badge?: ReactNode;
  action?: ReactNode;
  className?: string;
  emptyMessage?: string;
  onActiveIndexChange?: (index: number | null) => void;
  onActiveScrubValueChange?: (value: number | string | null) => void;
}

export function LapChart({
  data,
  xKey,
  yKey,
  label,
  color,
  xTickFormatter,
  xValueFormatter,
  yValueFormatter,
  height = 200,
  syncId,
  badge,
  action,
  className = "",
  emptyMessage,
  onActiveIndexChange,
  onActiveScrubValueChange,
}: Props) {
  const handleMouseMove = useCallback(
    (state: Record<string, unknown>) => {
      if (!state?.isTooltipActive) {
        return;
      }

      const activeLabel = state.activeLabel;
      if (
        onActiveScrubValueChange &&
        (typeof activeLabel === "number" || typeof activeLabel === "string")
      ) {
        onActiveScrubValueChange(activeLabel);
      }

      if (!onActiveIndexChange) {
        return;
      }

      const idx = resolveActiveIndex(state, data, xKey);
      if (idx !== null && idx >= 0) {
        onActiveIndexChange(idx);
      }
    },
    [data, onActiveIndexChange, onActiveScrubValueChange, xKey],
  );

  const handleMouseLeave = useCallback(() => {
    onActiveIndexChange?.(null);
    onActiveScrubValueChange?.(null);
  }, [onActiveIndexChange, onActiveScrubValueChange]);
  if (!data.length || !(yKey in data[0])) {
    return (
      <div
        className={`density-analysis-chart rounded-3xl border border-border/70 bg-surface-1/85 ${className}`.trim()}
      >
        <div className="mb-3 flex items-start justify-between gap-3">
          <div className="flex min-w-0 items-center gap-2">
            <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-text-muted">
              {label}
            </p>
            {badge}
          </div>
          {action}
        </div>
        <div className="flex h-40 items-center justify-center rounded-2xl border border-dashed border-border/70 bg-surface-2/72 p-4 text-sm text-text-muted">
          {emptyMessage ?? `No data for ${label}`}
        </div>
      </div>
    );
  }

  return (
    <div
      className={`density-analysis-chart rounded-3xl border border-border/70 bg-surface-1/85 ${className}`.trim()}
    >
      <div className="mb-3 flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-text-muted">
            {label}
          </p>
          {badge}
        </div>
        {action}
      </div>
      <ResponsiveContainer width="100%" height={height}>
        <LineChart
          data={data}
          syncId={syncId}
          onMouseMove={handleMouseMove}
          onMouseLeave={handleMouseLeave}
        >
          <CartesianGrid stroke={COLORS.grid} strokeDasharray="2 6" />
          <XAxis
            dataKey={xKey}
            tick={{ fill: COLORS.tick, fontSize: 10 }}
            stroke={COLORS.axis}
            tickFormatter={(value: number | string) =>
              xTickFormatter
                ? xTickFormatter(value)
                : typeof value === "number"
                  ? value.toFixed(2)
                  : String(value)
            }
          />
          <YAxis
            tick={{ fill: COLORS.tick, fontSize: 10 }}
            stroke={COLORS.axis}
            width={55}
            tickFormatter={(value: number | string) =>
              yValueFormatter ? yValueFormatter(value) : formatTooltipValue(value)
            }
          />
          <Tooltip
            cursor={{ stroke: COLORS.axis, strokeDasharray: "3 6" }}
            contentStyle={{
              backgroundColor: COLORS.tooltipBg,
              border: `1px solid ${COLORS.tooltipBorder}`,
              borderRadius: 14,
              fontSize: 12,
            }}
            labelStyle={{ color: COLORS.tick }}
            formatter={(value) => [
              yValueFormatter ? yValueFormatter(value) : formatTooltipValue(value),
              label,
            ]}
            labelFormatter={(label) =>
              typeof label === "number" || typeof label === "string"
                ? xValueFormatter
                  ? xValueFormatter(label)
                  : formatTooltipValue(label)
                : String(label)
            }
          />
          <Line
            type="monotone"
            dataKey={yKey}
            stroke={color}
            dot={false}
            strokeWidth={1.5}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
