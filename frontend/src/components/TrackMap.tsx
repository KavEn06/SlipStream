import { useCallback, useMemo, useRef, useState } from "react";

const MIN_POSITION_SAMPLES = 20;
const SVG_PADDING = 24;
const MARKER_RADIUS = 5;
const START_MARKER_RADIUS = 3.5;
const MIN_ZOOM = 0.5;
const MAX_ZOOM = 8;
const ZOOM_STEP = 1.15;
const ROTATION_STEP = 0.008;
const MIN_PITCH = -1.35;
const MAX_PITCH = 1.35;

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
}

type ViewMode = "2d" | "3d";

interface TrackPoint {
  x: number;
  y: number;
  z: number;
  scrub: number | null;
}

interface ProjectedTrackPoint {
  sx: number;
  sy: number;
  scrub: number | null;
}

interface WorldTrackPoint {
  x: number;
  y: number;
  scrub: number | null;
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

    if (!Number.isFinite(x) || !Number.isFinite(z)) continue;
    points.push({
      x,
      y: Number.isFinite(y) ? y : 0,
      z,
      scrub: Number.isFinite(scrub) ? scrub : null,
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

export function TrackMap({
  records,
  activeIndex,
  activeScrubValue = null,
  xKey,
  height = 320,
  className = "",
}: Props) {
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [viewMode, setViewMode] = useState<ViewMode>("2d");
  const [rotation, setRotation] = useState({ yaw: -0.95, pitch: 0.82 });
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
    }));

    const smoothPath = buildSmoothPath(projected);

    return { projected, smoothPath, viewW, viewH };
  }, [points, rotation.pitch, rotation.yaw, viewMode]);

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

  const handlePointerDown = useCallback(
    (e: React.PointerEvent<SVGSVGElement>) => {
      if (e.button !== 0) return;
      (e.target as Element).setPointerCapture?.(e.pointerId);
      if (viewMode === "3d") {
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
          return {
            sx: previous.sx + (current.sx - previous.sx) * ratio,
            sy: previous.sy + (current.sy - previous.sy) * ratio,
            scrub: normalizedScrub,
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
        className="overflow-hidden rounded-2xl border border-border/70 bg-surface-2/72"
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
        >
          <g
            transform={`translate(${pan.x / (zoom > 0 ? zoom : 1)}, ${pan.y / (zoom > 0 ? zoom : 1)}) scale(${zoom})`}
            style={{ transformOrigin: `${pathData.viewW / 2}px ${pathData.viewH / 2}px` }}
          >
            {viewMode === "3d" && (
              <path
                d={pathData.smoothPath}
                fill="none"
                stroke="rgb(var(--app-accent-rgb) / 0.16)"
                strokeWidth={8 / zoom}
                strokeLinecap="round"
                strokeLinejoin="round"
                opacity={0.85}
              />
            )}
            <path
              d={pathData.smoothPath}
              fill="none"
              stroke="var(--app-text-primary)"
              strokeWidth={2.6 / zoom}
              strokeLinecap="round"
              strokeLinejoin="round"
              opacity={0.95}
            />

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
      </div>
      {viewMode === "3d" && (
        <p className="mt-3 text-[11px] text-text-muted">
          Drag to rotate. Scroll to zoom.
        </p>
      )}
    </div>
  );
}
