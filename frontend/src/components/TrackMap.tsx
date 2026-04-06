import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CornerDefinition } from "../types";

const MIN_POSITION_SAMPLES = 20;
const SVG_PADDING = 24;
const MARKER_RADIUS = 5;
const START_MARKER_RADIUS = 3.5;
const MIN_ZOOM = 0.5;
const MAX_ZOOM = 8;
const ZOOM_STEP = 1.15;
const PAN_NUDGE_STEP = 32;
const PAN_HOLD_DELAY_MS = 220;
const PAN_HOLD_INTERVAL_MS = 90;
const ROTATION_STEP = 0.008;
const MIN_PITCH = -1.35;
const MAX_PITCH = 1.35;
const THREE_D_OUTLINE_OUTER_WIDTH = 6.8;
const THREE_D_OUTLINE_INNER_WIDTH = 4.4;
const THREE_D_TRACK_WIDTH = 1.85;

const CORNER_ENTRY_COLOR = "rgba(59,130,246,0.55)";
const CORNER_CENTER_COLOR = "rgba(249,115,22,0.60)";
const CORNER_EXIT_COLOR = "rgba(34,197,94,0.55)";
const CORNER_STROKE_WIDTH = 4.5;
const CORNER_LABEL_FONT_SIZE = 9;

function clampZoom(value: number): number {
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, value));
}

function clampPitch(value: number): number {
  return Math.min(MAX_PITCH, Math.max(MIN_PITCH, value));
}

interface Props {
  records: Record<string, number | string>[];
  activeIndex: number | null;
  activeScrubValue?: number | string | null;
  xKey: string;
  height?: number;
  className?: string;
  corners?: CornerDefinition[];
  showCorners?: boolean;
}

type ViewMode = "2d" | "3d";

interface TrackPoint {
  x: number;
  y: number;
  z: number;
  scrub: number | null;
  progress: number | null;
}

interface ProjectedTrackPoint {
  sx: number;
  sy: number;
  scrub: number | null;
  progress: number | null;
}

interface WorldTrackPoint {
  x: number;
  y: number;
  scrub: number | null;
  progress: number | null;
}

function extractTrackPoints(
  records: Record<string, number | string>[],
  xKey: string,
): TrackPoint[] | null {
  const points: TrackPoint[] = [];

  for (const record of records) {
    const rawX = record.PositionX;
    const rawY = record.PositionY;
    const rawZ = record.PositionZ;

    if (rawX === undefined || rawZ === undefined) return null;

    const x = typeof rawX === "number" ? rawX : Number(rawX);
    const y =
      typeof rawY === "number" ? rawY : rawY === undefined ? 0 : Number(rawY);
    const z = typeof rawZ === "number" ? rawZ : Number(rawZ);
    const rawScrub = record[xKey];
    const scrub =
      typeof rawScrub === "number"
        ? rawScrub
        : typeof rawScrub === "string" && rawScrub.trim() !== ""
          ? Number(rawScrub)
          : Number.NaN;

    const rawProgress = record.NormalizedDistance;
    const progressVal =
      typeof rawProgress === "number"
        ? rawProgress
        : typeof rawProgress === "string" && rawProgress.trim() !== ""
          ? Number(rawProgress)
          : Number.NaN;

    if (!Number.isFinite(x) || !Number.isFinite(z)) continue;
    points.push({
      x,
      y: Number.isFinite(y) ? y : 0,
      z,
      scrub: Number.isFinite(scrub) ? scrub : null,
      progress: Number.isFinite(progressVal) ? progressVal : null,
    });
  }

  return points.length >= MIN_POSITION_SAMPLES ? points : null;
}

function smoothTrackPoints(points: TrackPoint[], radius = 2): TrackPoint[] {
  if (points.length <= 2) {
    return points;
  }

  return points.map((point, index) => {
    let totalWeight = 0;
    let sumX = 0;
    let sumY = 0;
    let sumZ = 0;

    for (
      let neighborIndex = Math.max(0, index - radius);
      neighborIndex <= Math.min(points.length - 1, index + radius);
      neighborIndex += 1
    ) {
      const neighbor = points[neighborIndex];
      const distance = Math.abs(index - neighborIndex);
      const weight = radius + 1 - distance;
      totalWeight += weight;
      sumX += neighbor.x * weight;
      sumY += neighbor.y * weight;
      sumZ += neighbor.z * weight;
    }

    return {
      x: sumX / totalWeight,
      y: sumY / totalWeight,
      z: sumZ / totalWeight,
      scrub: point.scrub,
      progress: point.progress,
    };
  });
}

function computeBounds(points: Array<{ x: number; y: number }>) {
  let minX = Infinity;
  let maxX = -Infinity;
  let minY = Infinity;
  let maxY = -Infinity;

  for (const p of points) {
    if (p.x < minX) minX = p.x;
    if (p.x > maxX) maxX = p.x;
    if (p.y < minY) minY = p.y;
    if (p.y > maxY) maxY = p.y;
  }

  return { minX, maxX, minY, maxY };
}

function buildSmoothPath(points: ProjectedTrackPoint[]): string {
  if (points.length === 0) {
    return "";
  }

  if (points.length === 1) {
    return `M ${points[0].sx} ${points[0].sy}`;
  }

  if (points.length === 2) {
    return `M ${points[0].sx} ${points[0].sy} L ${points[1].sx} ${points[1].sy}`;
  }

  let path = `M ${points[0].sx} ${points[0].sy}`;

  for (let index = 1; index < points.length - 1; index += 1) {
    const current = points[index];
    const next = points[index + 1];
    const midX = (current.sx + next.sx) / 2;
    const midY = (current.sy + next.sy) / 2;
    path += ` Q ${current.sx} ${current.sy} ${midX} ${midY}`;
  }

  const penultimate = points[points.length - 2];
  const last = points[points.length - 1];
  path += ` Q ${penultimate.sx} ${penultimate.sy} ${last.sx} ${last.sy}`;

  return path;
}

interface CornerSegment {
  cornerIndex: number;
  region: "entry" | "center" | "exit";
  path: string;
  color: string;
  labelX: number;
  labelY: number;
  cornerId: number;
  direction: string;
}

function buildSegmentPath(points: ProjectedTrackPoint[]): string {
  if (points.length === 0) return "";
  if (points.length === 1) return `M ${points[0].sx} ${points[0].sy}`;
  if (points.length === 2)
    return `M ${points[0].sx} ${points[0].sy} L ${points[1].sx} ${points[1].sy}`;

  let path = `M ${points[0].sx} ${points[0].sy}`;
  for (let i = 1; i < points.length - 1; i++) {
    const cur = points[i];
    const next = points[i + 1];
    const mx = (cur.sx + next.sx) / 2;
    const my = (cur.sy + next.sy) / 2;
    path += ` Q ${cur.sx} ${cur.sy} ${mx} ${my}`;
  }
  const pen = points[points.length - 2];
  const last = points[points.length - 1];
  path += ` Q ${pen.sx} ${pen.sy} ${last.sx} ${last.sy}`;
  return path;
}

function buildCornerSegments(
  corners: CornerDefinition[],
  projected: ProjectedTrackPoint[],
): CornerSegment[] {
  if (projected.length === 0 || corners.length === 0) return [];

  const hasProgress = projected.some((p) => p.progress !== null);
  if (!hasProgress) return [];

  const segments: CornerSegment[] = [];

  for (let ci = 0; ci < corners.length; ci++) {
    const c = corners[ci];

    const ranges: {
      region: "entry" | "center" | "exit";
      start: number;
      end: number;
      color: string;
    }[] = [
      { region: "entry", start: c.start_progress_norm, end: c.entry_end_progress_norm, color: CORNER_ENTRY_COLOR },
      { region: "center", start: c.entry_end_progress_norm, end: c.exit_start_progress_norm, color: CORNER_CENTER_COLOR },
      { region: "exit", start: c.exit_start_progress_norm, end: c.end_progress_norm, color: CORNER_EXIT_COLOR },
    ];

    for (const range of ranges) {
      const pts = projected.filter(
        (p) => p.progress !== null && p.progress >= range.start && p.progress <= range.end,
      );
      if (pts.length < 2) continue;

      const mid = pts[Math.floor(pts.length / 2)];
      segments.push({
        cornerIndex: ci,
        region: range.region,
        path: buildSegmentPath(pts),
        color: range.color,
        labelX: mid.sx,
        labelY: mid.sy,
        cornerId: c.corner_id,
        direction: c.direction,
      });
    }
  }

  return segments;
}

export function TrackMap({
  records,
  activeIndex,
  activeScrubValue = null,
  xKey,
  height = 320,
  className = "",
  corners,
  showCorners: showCornersProp,
}: Props) {
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [viewMode, setViewMode] = useState<ViewMode>("2d");
  const [rotation, setRotation] = useState({ yaw: -0.95, pitch: 0.82 });
  const panHoldDelayRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const panHoldRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const dragRef = useRef<
    | {
        mode: "pan";
        startX: number;
        startY: number;
        panX: number;
        panY: number;
      }
    | {
        mode: "orbit";
        startX: number;
        startY: number;
        yaw: number;
        pitch: number;
      }
    | null
  >(null);

  const points = useMemo(() => extractTrackPoints(records, xKey), [records, xKey]);

  const pathData = useMemo(() => {
    if (!points) return null;

    const smoothedPoints = smoothTrackPoints(points);
    const averageX =
      smoothedPoints.reduce((sum, point) => sum + point.x, 0) / smoothedPoints.length;
    const averageY =
      smoothedPoints.reduce((sum, point) => sum + point.y, 0) / smoothedPoints.length;
    const averageZ =
      smoothedPoints.reduce((sum, point) => sum + point.z, 0) / smoothedPoints.length;

    const centeredPoints = smoothedPoints.map((point) => ({
      x: point.x - averageX,
      y: point.y - averageY,
      z: point.z - averageZ,
      scrub: point.scrub,
      progress: point.progress,
    }));
    const xzBounds = computeBounds(
      centeredPoints.map((point) => ({ x: point.x, y: point.z })),
    );
    const xyBounds = computeBounds(
      centeredPoints.map((point) => ({ x: point.x, y: point.y })),
    );
    const rangeX = xzBounds.maxX - xzBounds.minX || 1;
    const rangeZ = xzBounds.maxY - xzBounds.minY || 1;
    const rangeY = xyBounds.maxY - xyBounds.minY || 1;
    const elevationScale = Math.max(rangeX, rangeZ) / Math.max(rangeY, 1);

    const worldPoints: WorldTrackPoint[] = centeredPoints.map((point) => {
      if (viewMode !== "3d") {
        return {
          x: point.x,
          y: point.z,
          scrub: point.scrub,
          progress: point.progress,
        };
      }

      const yScaled = point.y * Math.min(14, Math.max(3, elevationScale * 0.22));
      const cosYaw = Math.cos(rotation.yaw);
      const sinYaw = Math.sin(rotation.yaw);
      const yawX = point.x * cosYaw - point.z * sinYaw;
      const yawZ = point.x * sinYaw + point.z * cosYaw;

      const cosPitch = Math.cos(rotation.pitch);
      const sinPitch = Math.sin(rotation.pitch);
      const pitchY = yScaled * cosPitch - yawZ * sinPitch;

      return {
        x: yawX,
        y: -pitchY,
        scrub: point.scrub,
        progress: point.progress,
      };
    });

    const bounds = computeBounds(worldPoints);
    const worldRangeX = bounds.maxX - bounds.minX || 1;
    const worldRangeY = bounds.maxY - bounds.minY || 1;

    const aspect = worldRangeX / worldRangeY;
    const viewW = 500;
    const viewH = viewW / Math.max(aspect, 0.3);
    const drawW = viewW - SVG_PADDING * 2;
    const drawH = viewH - SVG_PADDING * 2;

    const scale = Math.min(drawW / worldRangeX, drawH / worldRangeY);
    const offsetX = SVG_PADDING + (drawW - worldRangeX * scale) / 2;
    const offsetY = SVG_PADDING + (drawH - worldRangeY * scale) / 2;

    const projected = worldPoints.map((point) => ({
      sx: offsetX + (point.x - bounds.minX) * scale,
      sy: offsetY + (point.y - bounds.minY) * scale,
      scrub: point.scrub,
      progress: point.progress,
    }));

    const smoothPath = buildSmoothPath(projected);

    return { projected, smoothPath, viewW, viewH };
  }, [points, rotation.pitch, rotation.yaw, viewMode]);

  const hasCorners = Boolean(corners && corners.length > 0);
  const [cornersVisible, setCornersVisible] = useState(true);
  const showCorners = (showCornersProp ?? cornersVisible) && hasCorners;

  const cornerSegments = useMemo(() => {
    if (!showCorners || !corners || !pathData) return [];
    return buildCornerSegments(corners, pathData.projected);
  }, [showCorners, corners, pathData]);

  const cornerLabels = useMemo(() => {
    if (!showCorners || !corners || cornerSegments.length === 0) return [];
    const seen = new Set<number>();
    const labels: { x: number; y: number; id: number; dir: string }[] = [];
    for (const seg of cornerSegments) {
      if (seg.region === "center" && !seen.has(seg.cornerId)) {
        seen.add(seg.cornerId);
        labels.push({ x: seg.labelX, y: seg.labelY, id: seg.cornerId, dir: seg.direction });
      }
    }
    return labels;
  }, [showCorners, corners, cornerSegments]);

  const handleWheel = useCallback(
    (e: React.WheelEvent<SVGSVGElement>) => {
      e.preventDefault();
      setZoom((prev) => clampZoom(e.deltaY < 0 ? prev * ZOOM_STEP : prev / ZOOM_STEP));
    },
    [],
  );

  const zoomIn = useCallback(() => {
    setZoom((prev) => clampZoom(prev * ZOOM_STEP));
  }, []);

  const zoomOut = useCallback(() => {
    setZoom((prev) => clampZoom(prev / ZOOM_STEP));
  }, []);

  const nudgePan = useCallback((dx: number, dy: number) => {
    setPan((prev) => ({
      x: prev.x + dx,
      y: prev.y + dy,
    }));
  }, []);

  const stopPanHold = useCallback(() => {
    if (panHoldDelayRef.current !== null) {
      clearTimeout(panHoldDelayRef.current);
      panHoldDelayRef.current = null;
    }
    if (panHoldRef.current !== null) {
      clearInterval(panHoldRef.current);
      panHoldRef.current = null;
    }
  }, []);

  const startPanHold = useCallback(
    (event: React.PointerEvent<HTMLButtonElement>, dx: number, dy: number) => {
      event.preventDefault();
      event.currentTarget.setPointerCapture?.(event.pointerId);
      stopPanHold();
      nudgePan(dx, dy);
      panHoldDelayRef.current = setTimeout(() => {
        panHoldRef.current = setInterval(() => {
          nudgePan(dx, dy);
        }, PAN_HOLD_INTERVAL_MS);
      }, PAN_HOLD_DELAY_MS);
    },
    [nudgePan, stopPanHold],
  );

  useEffect(() => stopPanHold, [stopPanHold]);

  const handlePointerDown = useCallback(
    (e: React.PointerEvent<SVGSVGElement>) => {
      const isPrimaryButton = e.button === 0;
      const isMiddleButton = e.button === 1;
      if (!isPrimaryButton && !isMiddleButton) return;

      e.preventDefault();
      (e.target as Element).setPointerCapture?.(e.pointerId);
      if (viewMode === "3d") {
        if (e.shiftKey || isMiddleButton) {
          dragRef.current = {
            mode: "pan",
            startX: e.clientX,
            startY: e.clientY,
            panX: pan.x,
            panY: pan.y,
          };
          return;
        }

        dragRef.current = {
          mode: "orbit",
          startX: e.clientX,
          startY: e.clientY,
          yaw: rotation.yaw,
          pitch: rotation.pitch,
        };
        return;
      }

      dragRef.current = {
        mode: "pan",
        startX: e.clientX,
        startY: e.clientY,
        panX: pan.x,
        panY: pan.y,
      };
    },
    [pan.x, pan.y, rotation.pitch, rotation.yaw, viewMode],
  );

  const handlePointerMove = useCallback(
    (e: React.PointerEvent<SVGSVGElement>) => {
      if (!dragRef.current) return;
      const dx = e.clientX - dragRef.current.startX;
      const dy = e.clientY - dragRef.current.startY;
      if (dragRef.current.mode === "orbit") {
        setRotation({
          yaw: dragRef.current.yaw + dx * ROTATION_STEP,
          pitch: clampPitch(dragRef.current.pitch - dy * ROTATION_STEP),
        });
        return;
      }

      setPan({
        x: dragRef.current.panX + dx,
        y: dragRef.current.panY + dy,
      });
    },
    [],
  );

  const handlePointerUp = useCallback(() => {
    dragRef.current = null;
  }, []);

  const resetView = useCallback(() => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
    setRotation({ yaw: -0.95, pitch: 0.82 });
  }, []);

  const interpolateActivePoint = useCallback((): ProjectedTrackPoint | null => {
    if (!pathData || pathData.projected.length === 0) {
      return null;
    }

    const projectedPoints = pathData.projected;
    const normalizedScrub =
      typeof activeScrubValue === "number"
        ? activeScrubValue
        : typeof activeScrubValue === "string" && activeScrubValue.trim() !== ""
          ? Number(activeScrubValue)
          : Number.NaN;

    if (Number.isFinite(normalizedScrub)) {
      const firstPoint = projectedPoints[0];
      const lastPoint = projectedPoints[projectedPoints.length - 1];
      const firstScrub = firstPoint.scrub;
      const lastScrub = lastPoint.scrub;

      if (firstScrub !== null && normalizedScrub <= firstScrub) {
        return firstPoint;
      }

      if (lastScrub !== null && normalizedScrub >= lastScrub) {
        return lastPoint;
      }

      for (let index = 1; index < projectedPoints.length; index += 1) {
        const previous = projectedPoints[index - 1];
        const current = projectedPoints[index];
        if (previous.scrub === null || current.scrub === null) {
          continue;
        }

        if (normalizedScrub >= previous.scrub && normalizedScrub <= current.scrub) {
          const scrubSpan = current.scrub - previous.scrub;
          const ratio = scrubSpan === 0 ? 1 : (normalizedScrub - previous.scrub) / scrubSpan;
          const prevProg = previous.progress;
          const curProg = current.progress;
          const interpProgress =
            prevProg !== null && curProg !== null
              ? prevProg + (curProg - prevProg) * ratio
              : null;
          return {
            sx: previous.sx + (current.sx - previous.sx) * ratio,
            sy: previous.sy + (current.sy - previous.sy) * ratio,
            scrub: normalizedScrub,
            progress: interpProgress,
          };
        }
      }
    }

    if (
      activeIndex !== null &&
      activeIndex >= 0 &&
      activeIndex < projectedPoints.length
    ) {
      return projectedPoints[activeIndex];
    }

    return projectedPoints[0] ?? null;
  }, [activeIndex, activeScrubValue, pathData]);

  if (!points || !pathData) {
    return (
      <div
        className={`density-analysis-chart rounded-3xl border border-border/70 bg-surface-1/85 ${className}`.trim()}
      >
        <div className="mb-3 flex items-start justify-between gap-3">
          <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-text-muted">
            Track Map
          </p>
        </div>
        <div className="flex items-center justify-center rounded-2xl border border-dashed border-border/70 bg-surface-2/72 p-4 text-sm text-text-muted"
          style={{ height: height - 40 }}
        >
          No position data available for this lap.
        </div>
      </div>
    );
  }

  const activePoint = interpolateActivePoint();

  const startPoint = pathData.projected[0];
  const isZoomedOrPanned = zoom !== 1 || pan.x !== 0 || pan.y !== 0;

  return (
    <div
      className={`density-analysis-chart rounded-3xl border border-border/70 bg-surface-1/85 ${className}`.trim()}
    >
      <div className="mb-3 flex items-start justify-between gap-3">
        <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-text-muted">
          Track Map
        </p>
        <div className="flex items-center gap-2">
          <div className="relative inline-grid grid-cols-2 rounded-full border border-border/70 bg-surface-2/88 p-1">
            {(["2d", "3d"] as const).map((mode) => {
              const active = viewMode === mode;
              return (
                <button
                  key={mode}
                  type="button"
                  onClick={() => setViewMode(mode)}
                  className={`motion-safe-color relative inline-flex h-7 items-center justify-center rounded-full px-3 text-[10px] font-medium uppercase tracking-[0.14em] cursor-pointer ${
                    active
                      ? "border border-accent/20 bg-accent/12 text-accent"
                      : "text-text-secondary hover:text-text-primary"
                  }`}
                  aria-pressed={active}
                >
                  {mode}
                </button>
              );
            })}
          </div>
          {hasCorners && (
            <button
              type="button"
              onClick={() => setCornersVisible((v) => !v)}
              className={`motion-safe-color inline-flex h-7 items-center rounded-full border px-3 text-[10px] font-medium uppercase tracking-[0.14em] cursor-pointer ${
                showCorners
                  ? "border-accent/20 bg-accent/12 text-accent"
                  : "border-border/70 bg-surface-2/84 text-text-secondary hover:border-border-strong hover:bg-surface-3 hover:text-text-primary"
              }`}
              aria-pressed={showCorners}
            >
              Corners
            </button>
          )}
          {isZoomedOrPanned && (
            <button
              type="button"
              onClick={resetView}
              className="motion-safe-color inline-flex h-7 items-center rounded-full border border-border/70 bg-surface-2/84 px-3 text-[10px] font-medium uppercase tracking-[0.14em] text-text-secondary hover:border-border-strong hover:bg-surface-3 hover:text-text-primary cursor-pointer"
            >
              Reset
            </button>
          )}
          <button
            type="button"
            onClick={zoomOut}
            aria-label="Zoom out"
            className="motion-safe-color inline-flex h-7 w-7 items-center justify-center rounded-full border border-border/70 bg-surface-2/84 text-sm font-semibold text-text-secondary hover:border-border-strong hover:bg-surface-3 hover:text-text-primary cursor-pointer"
          >
            -
          </button>
          <button
            type="button"
            onClick={zoomIn}
            aria-label="Zoom in"
            className="motion-safe-color inline-flex h-7 w-7 items-center justify-center rounded-full border border-border/70 bg-surface-2/84 text-sm font-semibold text-text-secondary hover:border-border-strong hover:bg-surface-3 hover:text-text-primary cursor-pointer"
          >
            +
          </button>
        </div>
      </div>

      <div
        className="relative overflow-hidden rounded-2xl border border-border/70 bg-surface-2/72"
        style={{ height }}
      >
        <svg
          viewBox={`0 0 ${pathData.viewW} ${pathData.viewH}`}
          width="100%"
          height="100%"
          preserveAspectRatio="xMidYMid meet"
          className="cursor-grab active:cursor-grabbing"
          onWheel={handleWheel}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onPointerLeave={handlePointerUp}
          onContextMenu={(event) => event.preventDefault()}
        >
          <g
            transform={`translate(${pan.x / (zoom > 0 ? zoom : 1)}, ${pan.y / (zoom > 0 ? zoom : 1)}) scale(${zoom})`}
            style={{ transformOrigin: `${pathData.viewW / 2}px ${pathData.viewH / 2}px` }}
          >
            {viewMode === "3d" && (
              <>
                <path
                  d={pathData.smoothPath}
                  fill="none"
                  stroke="var(--app-surface-0)"
                  strokeWidth={THREE_D_OUTLINE_OUTER_WIDTH}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  vectorEffect="non-scaling-stroke"
                  opacity={0.5}
                />
                <path
                  d={pathData.smoothPath}
                  fill="none"
                  stroke="var(--app-border-strong)"
                  strokeWidth={THREE_D_OUTLINE_INNER_WIDTH}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  vectorEffect="non-scaling-stroke"
                  opacity={0.78}
                />
              </>
            )}
            <path
              d={pathData.smoothPath}
              fill="none"
              stroke="var(--app-text-primary)"
              strokeWidth={viewMode === "3d" ? THREE_D_TRACK_WIDTH : 2.1}
              strokeLinecap="round"
              strokeLinejoin="round"
              vectorEffect="non-scaling-stroke"
              opacity={showCorners ? 0.3 : 0.96}
            />

            {showCorners && cornerSegments.map((seg, i) => (
              <path
                key={`corner-${seg.cornerId}-${seg.region}-${i}`}
                d={seg.path}
                fill="none"
                stroke={seg.color}
                strokeWidth={CORNER_STROKE_WIDTH}
                strokeLinecap="round"
                strokeLinejoin="round"
                vectorEffect="non-scaling-stroke"
              />
            ))}

            {showCorners && cornerLabels.map((label) => (
              <g key={`label-${label.id}`}>
                <circle
                  cx={label.x}
                  cy={label.y}
                  r={10 / zoom}
                  fill="var(--app-surface-0)"
                  opacity={0.85}
                />
                <text
                  x={label.x}
                  y={label.y}
                  textAnchor="middle"
                  dominantBaseline="central"
                  fill="var(--app-text-primary)"
                  fontSize={CORNER_LABEL_FONT_SIZE / zoom}
                  fontWeight={600}
                >
                  {`T${label.id}`}
                </text>
              </g>
            ))}

            {startPoint && (
              <circle
                cx={startPoint.sx}
                cy={startPoint.sy}
                r={START_MARKER_RADIUS / zoom}
                fill="var(--app-text-muted)"
                opacity={0.7}
              />
            )}

            {activePoint && (
              <circle
                cx={activePoint.sx}
                cy={activePoint.sy}
                r={MARKER_RADIUS / zoom}
                fill="var(--app-accent)"
                stroke="var(--app-surface-0)"
                strokeWidth={2 / zoom}
              />
            )}
          </g>
        </svg>
        {viewMode === "2d" && (
          <div className="pointer-events-none absolute bottom-3 right-3">
            <div className="pointer-events-auto grid grid-cols-3 gap-1 rounded-2xl border border-border/70 bg-surface-1/88 p-2 shadow-lg backdrop-blur-sm">
              <div />
              <button
                type="button"
                onPointerDown={(event) => startPanHold(event, 0, PAN_NUDGE_STEP)}
                onPointerUp={stopPanHold}
                onPointerLeave={stopPanHold}
                onPointerCancel={stopPanHold}
                onLostPointerCapture={stopPanHold}
                aria-label="Pan up"
                className="motion-safe-color inline-flex h-8 w-8 items-center justify-center rounded-full border border-border/70 bg-surface-2/84 text-sm font-semibold text-text-secondary hover:border-border-strong hover:bg-surface-3 hover:text-text-primary cursor-pointer"
              >
                ↑
              </button>
              <div />
              <button
                type="button"
                onPointerDown={(event) => startPanHold(event, PAN_NUDGE_STEP, 0)}
                onPointerUp={stopPanHold}
                onPointerLeave={stopPanHold}
                onPointerCancel={stopPanHold}
                onLostPointerCapture={stopPanHold}
                aria-label="Pan left"
                className="motion-safe-color inline-flex h-8 w-8 items-center justify-center rounded-full border border-border/70 bg-surface-2/84 text-sm font-semibold text-text-secondary hover:border-border-strong hover:bg-surface-3 hover:text-text-primary cursor-pointer"
              >
                ←
              </button>
              <button
                type="button"
                onClick={resetView}
                aria-label="Reset view"
                className="motion-safe-color inline-flex h-8 w-8 items-center justify-center rounded-full border border-accent/18 bg-accent/10 text-[10px] font-medium uppercase tracking-[0.12em] text-accent hover:bg-accent/16 cursor-pointer"
              >
                C
              </button>
              <button
                type="button"
                onPointerDown={(event) => startPanHold(event, -PAN_NUDGE_STEP, 0)}
                onPointerUp={stopPanHold}
                onPointerLeave={stopPanHold}
                onPointerCancel={stopPanHold}
                onLostPointerCapture={stopPanHold}
                aria-label="Pan right"
                className="motion-safe-color inline-flex h-8 w-8 items-center justify-center rounded-full border border-border/70 bg-surface-2/84 text-sm font-semibold text-text-secondary hover:border-border-strong hover:bg-surface-3 hover:text-text-primary cursor-pointer"
              >
                →
              </button>
              <div />
              <button
                type="button"
                onPointerDown={(event) => startPanHold(event, 0, -PAN_NUDGE_STEP)}
                onPointerUp={stopPanHold}
                onPointerLeave={stopPanHold}
                onPointerCancel={stopPanHold}
                onLostPointerCapture={stopPanHold}
                aria-label="Pan down"
                className="motion-safe-color inline-flex h-8 w-8 items-center justify-center rounded-full border border-border/70 bg-surface-2/84 text-sm font-semibold text-text-secondary hover:border-border-strong hover:bg-surface-3 hover:text-text-primary cursor-pointer"
              >
                ↓
              </button>
              <div />
            </div>
          </div>
        )}
      </div>
      {showCorners && (
        <div className="mt-3 flex items-center gap-4">
          <div className="flex items-center gap-1.5">
            <span className="inline-block h-2 w-5 rounded-full" style={{ background: CORNER_ENTRY_COLOR }} />
            <span className="text-[10px] uppercase tracking-[0.12em] text-text-muted">Entry</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="inline-block h-2 w-5 rounded-full" style={{ background: CORNER_CENTER_COLOR }} />
            <span className="text-[10px] uppercase tracking-[0.12em] text-text-muted">Center</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="inline-block h-2 w-5 rounded-full" style={{ background: CORNER_EXIT_COLOR }} />
            <span className="text-[10px] uppercase tracking-[0.12em] text-text-muted">Exit</span>
          </div>
          <span className="text-[10px] text-text-subtle">
            {corners?.length ?? 0} corner{(corners?.length ?? 0) !== 1 ? "s" : ""} detected
          </span>
        </div>
      )}
      {viewMode === "3d" && (
        <p className="mt-3 text-[11px] text-text-muted">
          Drag to orbit. Hold Shift and drag, or use middle-drag, to pan. Scroll to zoom.
        </p>
      )}
    </div>
  );
}
