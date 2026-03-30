import type { ReactNode } from "react";
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

interface Props {
  data: Record<string, number | string>[];
  xKey?: string;
  yKey: string;
  label: string;
  color: string;
  height?: number;
  syncId?: string;
  badge?: ReactNode;
  action?: ReactNode;
  className?: string;
  emptyMessage?: string;
}

export function LapChart({
  data,
  xKey,
  yKey,
  label,
  color,
  height = 200,
  syncId,
  badge,
  action,
  className = "",
  emptyMessage,
}: Props) {
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
        <LineChart data={data} syncId={syncId}>
          <CartesianGrid stroke={COLORS.grid} strokeDasharray="2 6" />
          <XAxis
            dataKey={xKey}
            tick={{ fill: COLORS.tick, fontSize: 10 }}
            stroke={COLORS.axis}
            tickFormatter={(v: number) =>
              typeof v === "number" ? v.toFixed(2) : String(v)
            }
          />
          <YAxis
            tick={{ fill: COLORS.tick, fontSize: 10 }}
            stroke={COLORS.axis}
            width={55}
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
