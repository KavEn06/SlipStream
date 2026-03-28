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
}

export function LapChart({
  data,
  xKey,
  yKey,
  label,
  color,
  height = 200,
}: Props) {
  if (!data.length || !(yKey in data[0])) {
    return (
      <div className="flex h-48 items-center justify-center rounded-3xl border border-border/70 bg-surface-1/85 p-4 text-sm text-text-muted">
        No data for {label}
      </div>
    );
  }

  return (
    <div className="rounded-3xl border border-border/70 bg-surface-1/85 p-5">
      <p className="mb-3 text-[11px] font-medium uppercase tracking-[0.16em] text-text-muted">
        {label}
      </p>
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={data}>
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
