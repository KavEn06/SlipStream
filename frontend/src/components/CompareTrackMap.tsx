import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CornerDefinition, TrackOutline } from "../types";

const MIN_POSITION_SAMPLES = 20;
const SVG_PADDING = 24;
const MARKER_RADIUS = 5;
const START_MARKER_RADIUS = 3.5;
const MIN_ZOOM = 0.5;
const MAX_ZOOM = 16;
const ZOOM_STEP = 1.15;
const PAN_NUDGE_STEP = 32;
const PAN_HOLD_DELAY_MS = 220;
const PAN_HOLD_INTERVAL_MS = 90;
const ROTATION_STEP = 0.008;
const MIN_PITCH = -1.35;
const MAX_PITCH = 1.35;
const THREE_D_OUTLINE_OUTER_WIDTH = 6.8;
const THREE_D_OUTLINE_INNER_WIDTH = 4.4;
// Fallback envelope sizing when no persisted track outline is available.
const MIN_TRACK_OUTER_WIDTH = 9;
const MAX_TRACK_OUTER_WIDTH = 34;
const TRACK_EDGE_THICKNESS = 1.6; // visible white rail thickness on each side
const TRACK_EDGE_PADDING = 4; // breathing room between racing line and rail
const REFERENCE_LINE_WIDTH = 1.8;
const OTHER_LINE_WIDTH = 3.0;
const REFERENCE_LINE_DASH = "10 8";
const MAP_HOVER_SNAP_PX = 28;
const FOCUS_PADDING_PX = 4;
const MIN_FOCUS_SPAN_PX = 24;

const CORNER_ENTRY_COLOR = "rgba(59,130,246,0.70)";
const CORNER_CENTER_COLOR = "rgba(249,115,22,0.75)";
const CORNER_EXIT_COLOR = "rgba(34,197,94,0.70)";
const CORNER_LABEL_FONT_SIZE = 9;

type ViewMode = "2d" | "3d";
type ActiveMode = "progress" | "time";

export interface CompareTrackSeries {
  id: string;
  label: string;
  color: string;
  isReference: boolean;
  records: Record<string, number | string>[];
  // Invisible series still contribute to track-envelope sizing and viewport
  // bounds, but are not drawn as a racing line, marker, or legend entry.
  invisible?: boolean;
}

interface Props {
  series: CompareTrackSeries[];
  trackOutline?: TrackOutline | null;
  activeProgressNorm?: number | null;
  activeElapsedTimeS?: number | null;
  activeMode?: ActiveMode;
  onActiveProgressChange?: (value: number | null) => void;
  height?: number;
  className?: string;
  corners?: CornerDefinition[] | null;
  focusStartProgressNorm?: number | null;
  focusEndProgressNorm?: number | null;
  autoFocusKey?: string | number | null;
  showTrackEnvelope?: boolean;
}

interface TrackPoint {
  x: number;
  y: number;
  z: number;
  progress: number | null;
  elapsedTimeS: number | null;
}

interface ProjectedTrackPoint {
  sx: number;
  sy: number;
  progress: number | null;
  elapsedTimeS: number | null;
}

const CORNER_LABEL_OFFSET = 20;

interface CornerSegment {
  cornerIndex: number;
  region: "entry" | "center" | "exit";
  path: string;
  color: string;
  labelX: number;
  labelY: number;
  labelOffsetX: number;
  labelOffsetY: number;
  cornerId: number;
  direction: string;
}

interface CornerRegionOverlay {
  key: string;
  cornerIndex: number;
  region: "entry" | "center" | "exit";
  color: string;
  polygonPath: string;
  startCapPath: string;
  endCapPath: string;
}

function clampZoom(value: number): number {
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, value));
}

function clampPitch(value: number): number {
  return Math.min(MAX_PITCH, Math.max(MIN_PITCH, value));
}

function extractTrackPoints(records: Record<string, number | string>[]): TrackPoint[] | null {
  const points: TrackPoint[] = [];

  for (const record of records) {
    const rawX = record.PositionX;
    const rawY = record.PositionY;
    const rawZ = record.PositionZ;
    const rawProgress = record.TrackProgressNorm;
    const rawElapsedTimeS = record.ElapsedTimeS;

    const x = typeof rawX === "number" ? rawX : Number(rawX);
    const y =
      typeof rawY === "number" ? rawY : rawY === undefined ? 0 : Number(rawY);
    const z = typeof rawZ === "number" ? rawZ : Number(rawZ);
    const progress =
      typeof rawProgress === "number"
        ? rawProgress
        : typeof rawProgress === "string" && rawProgress.trim() !== ""
          ? Number(rawProgress)
          : Number.NaN;
    const elapsedTimeS =
      typeof rawElapsedTimeS === "number"
        ? rawElapsedTimeS
        : typeof rawElapsedTimeS === "string" && rawElapsedTimeS.trim() !== ""
          ? Number(rawElapsedTimeS)
          : Number.NaN;

    if (!Number.isFinite(x) || !Number.isFinite(z)) {
      continue;
    }

    points.push({
      x,
      y: Number.isFinite(y) ? y : 0,
      z,
      progress: Number.isFinite(progress) ? progress : null,
      elapsedTimeS: Number.isFinite(elapsedTimeS) ? elapsedTimeS : null,
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
      progress: point.progress,
      elapsedTimeS: point.elapsedTimeS,
    };
  });
}

function extractOutlineTrackPoints(trackOutline: TrackOutline | null | undefined) {
  if (!trackOutline?.points?.length) {
    return null;
  }

  const leftPoints: TrackPoint[] = [];
  const rightPoints: TrackPoint[] = [];
  const centerPoints: TrackPoint[] = [];

  for (const point of trackOutline.points) {
    const progress =
      typeof point.progress_norm === "number" ? point.progress_norm : Number(point.progress_norm);
    const distance =
      typeof point.distance_m === "number" ? point.distance_m : Number(point.distance_m);
    const centerX = typeof point.center_x === "number" ? point.center_x : Number(point.center_x);
    const centerZ = typeof point.center_z === "number" ? point.center_z : Number(point.center_z);
    const leftX = typeof point.left_x === "number" ? point.left_x : Number(point.left_x);
    const leftZ = typeof point.left_z === "number" ? point.left_z : Number(point.left_z);
    const rightX = typeof point.right_x === "number" ? point.right_x : Number(point.right_x);
    const rightZ = typeof point.right_z === "number" ? point.right_z : Number(point.right_z);

    if (
      !Number.isFinite(progress) ||
      !Number.isFinite(distance) ||
      !Number.isFinite(centerX) ||
      !Number.isFinite(centerZ) ||
      !Number.isFinite(leftX) ||
      !Number.isFinite(leftZ) ||
      !Number.isFinite(rightX) ||
      !Number.isFinite(rightZ)
    ) {
      continue;
    }

    const basePoint = {
      y: 0,
      elapsedTimeS: null,
    };
    leftPoints.push({ x: leftX, z: leftZ, progress, ...basePoint });
    rightPoints.push({ x: rightX, z: rightZ, progress, ...basePoint });
    centerPoints.push({ x: centerX, z: centerZ, progress, ...basePoint });
  }

  if (leftPoints.length < 2 || rightPoints.length < 2 || centerPoints.length < 2) {
    return null;
  }

  return { leftPoints, rightPoints, centerPoints };
}

function computeBounds(points: Array<{ x: number; y: number }>) {
  let minX = Infinity;
  let maxX = -Infinity;
  let minY = Infinity;
  let maxY = -Infinity;

  for (const point of points) {
    minX = Math.min(minX, point.x);
    maxX = Math.max(maxX, point.x);
    minY = Math.min(minY, point.y);
    maxY = Math.max(maxY, point.y);
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

function buildSegmentPath(points: ProjectedTrackPoint[]): string {
  return buildSmoothPath(points);
}

function buildLinePath(start: ProjectedTrackPoint, end: ProjectedTrackPoint): string {
  return `M ${start.sx} ${start.sy} L ${end.sx} ${end.sy}`;
}

function buildClosedPolygonPath(
  leftPoints: ProjectedTrackPoint[],
  rightPoints: ProjectedTrackPoint[],
): string {
  if (leftPoints.length < 2 || rightPoints.length < 2) {
    return "";
  }

  const commands = [`M ${leftPoints[0].sx} ${leftPoints[0].sy}`];
  for (let index = 1; index < leftPoints.length; index += 1) {
    commands.push(`L ${leftPoints[index].sx} ${leftPoints[index].sy}`);
  }
  for (let index = rightPoints.length - 1; index >= 0; index -= 1) {
    commands.push(`L ${rightPoints[index].sx} ${rightPoints[index].sy}`);
  }
  commands.push("Z");
  return commands.join(" ");
}

function getRangePoints(
  points: ProjectedTrackPoint[],
  start: number,
  end: number,
): ProjectedTrackPoint[] {
  const withProgress = points.filter((point) => point.progress !== null);
  if (start <= end) {
    return withProgress.filter(
      (point) => point.progress !== null && point.progress >= start && point.progress <= end,
    );
  }

  const tail = withProgress.filter(
    (point) => point.progress !== null && point.progress >= start,
  );
  const head = withProgress.filter(
    (point) => point.progress !== null && point.progress <= end,
  );
  return [...tail, ...head];
}

function buildCornerSegments(
  corners: CornerDefinition[],
  projected: ProjectedTrackPoint[],
): CornerSegment[] {
  if (!projected.length || !corners.length) {
    return [];
  }

  const hasProgress = projected.some((point) => point.progress !== null);
  if (!hasProgress) {
    return [];
  }

  const segments: CornerSegment[] = [];
  for (let cornerIndex = 0; cornerIndex < corners.length; cornerIndex += 1) {
    const corner = corners[cornerIndex];
    const ranges = [
      {
        region: "entry" as const,
        start: corner.start_progress_norm,
        end: corner.entry_end_progress_norm,
        color: CORNER_ENTRY_COLOR,
      },
      {
        region: "center" as const,
        start: corner.entry_end_progress_norm,
        end: corner.exit_start_progress_norm,
        color: CORNER_CENTER_COLOR,
      },
      {
        region: "exit" as const,
        start: corner.exit_start_progress_norm,
        end: corner.end_progress_norm,
        color: CORNER_EXIT_COLOR,
      },
    ];

    for (const range of ranges) {
      const points = getRangePoints(projected, range.start, range.end);
      if (points.length < 2) {
        continue;
      }

      const middlePoint = points[Math.floor(points.length / 2)];
      const firstPt = points[0];
      const lastPt = points[points.length - 1];
      const dx = lastPt.sx - firstPt.sx;
      const dy = lastPt.sy - firstPt.sy;
      const segLen = Math.sqrt(dx * dx + dy * dy) || 1;
      const labelOffsetX = (dy / segLen) * CORNER_LABEL_OFFSET;
      const labelOffsetY = (-dx / segLen) * CORNER_LABEL_OFFSET;
      segments.push({
        cornerIndex,
        region: range.region,
        path: buildSegmentPath(points),
        color: range.color,
        labelX: middlePoint.sx,
        labelY: middlePoint.sy,
        labelOffsetX,
        labelOffsetY,
        cornerId: corner.corner_id,
        direction: corner.direction,
      });
    }
  }

  return segments;
}

function buildCornerRegionOverlays(
  corners: CornerDefinition[],
  leftPoints: ProjectedTrackPoint[],
  rightPoints: ProjectedTrackPoint[],
): CornerRegionOverlay[] {
  if (!corners.length || leftPoints.length < 2 || rightPoints.length < 2) {
    return [];
  }

  const overlays: CornerRegionOverlay[] = [];
  for (let cornerIndex = 0; cornerIndex < corners.length; cornerIndex += 1) {
    const corner = corners[cornerIndex];
    const ranges = [
      {
        region: "entry" as const,
        start: corner.start_progress_norm,
        end: corner.entry_end_progress_norm,
        color: CORNER_ENTRY_COLOR,
      },
      {
        region: "center" as const,
        start: corner.entry_end_progress_norm,
        end: corner.exit_start_progress_norm,
        color: CORNER_CENTER_COLOR,
      },
      {
        region: "exit" as const,
        start: corner.exit_start_progress_norm,
        end: corner.end_progress_norm,
        color: CORNER_EXIT_COLOR,
      },
    ];

    for (const range of ranges) {
      const leftRange = getRangePoints(leftPoints, range.start, range.end);
      const rightRange = getRangePoints(rightPoints, range.start, range.end);
      const sampleCount = Math.min(leftRange.length, rightRange.length);
      if (sampleCount < 2) {
        continue;
      }

      const clippedLeft = leftRange.slice(0, sampleCount);
      const clippedRight = rightRange.slice(0, sampleCount);
      overlays.push({
        key: `${corner.corner_id}-${range.region}`,
        cornerIndex,
        region: range.region,
        color: range.color,
        polygonPath: buildClosedPolygonPath(clippedLeft, clippedRight),
        startCapPath: buildLinePath(clippedLeft[0], clippedRight[0]),
        endCapPath: buildLinePath(
          clippedLeft[clippedLeft.length - 1],
          clippedRight[clippedRight.length - 1],
        ),
      });
    }
  }

  return overlays;
}

function progressInRange(
  progress: number | null,
  start: number,
  end: number,
): boolean {
  if (progress === null) {
    return false;
  }
  if (start <= end) {
    return progress >= start && progress <= end;
  }
  return progress >= start || progress <= end;
}

function interpolateTrackPoint(
  points: ProjectedTrackPoint[],
  targetValue: number | null | undefined,
  key: "progress" | "elapsedTimeS",
): ProjectedTrackPoint | null {
  const EDGE_EPSILON = 1e-9;
  if (!points.length || targetValue === null || targetValue === undefined) {
    return null;
  }

  const keyedPoints = points.filter(
    (point): point is ProjectedTrackPoint & { [K in typeof key]: number } =>
      point[key] !== null,
  );
  if (!keyedPoints.length) {
    return null;
  }

  if (targetValue < keyedPoints[0][key] - EDGE_EPSILON) {
    return null;
  }

  if (targetValue <= keyedPoints[0][key] + EDGE_EPSILON) {
    return keyedPoints[0];
  }

  const lastPoint = keyedPoints[keyedPoints.length - 1];
  if (targetValue > lastPoint[key] + EDGE_EPSILON) {
    return null;
  }

  if (lastPoint[key] - EDGE_EPSILON <= targetValue) {
    return lastPoint;
  }

  for (let index = 1; index < keyedPoints.length; index += 1) {
    const previous = keyedPoints[index - 1];
    const current = keyedPoints[index];
    if (targetValue > current[key]) {
      continue;
    }
    const denominator = current[key] - previous[key];
    if (Math.abs(denominator) < 1e-9) {
      return current;
    }
    const ratio = (targetValue - previous[key]) / denominator;
    return {
      sx: previous.sx + ((current.sx - previous.sx) * ratio),
      sy: previous.sy + ((current.sy - previous.sy) * ratio),
      progress:
        previous.progress !== null && current.progress !== null
          ? previous.progress + ((current.progress - previous.progress) * ratio)
          : previous.progress ?? current.progress,
      elapsedTimeS:
        previous.elapsedTimeS !== null && current.elapsedTimeS !== null
          ? previous.elapsedTimeS + ((current.elapsedTimeS - previous.elapsedTimeS) * ratio)
          : previous.elapsedTimeS ?? current.elapsedTimeS,
    };
  }

  return lastPoint;
}

function applyViewportTransform(
  points: ProjectedTrackPoint[],
  zoom: number,
  pan: { x: number; y: number },
  centerX: number,
  centerY: number,
): ProjectedTrackPoint[] {
  return points.map((point) => ({
    sx: ((point.sx - centerX) * zoom) + centerX + pan.x,
    sy: ((point.sy - centerY) * zoom) + centerY + pan.y,
    progress: point.progress,
    elapsedTimeS: point.elapsedTimeS,
  }));
}

export function CompareTrackMap({
  series,
  trackOutline = null,
  activeProgressNorm = null,
  activeElapsedTimeS = null,
  activeMode = "progress",
  onActiveProgressChange,
  height = 340,
  className = "",
  corners,
  focusStartProgressNorm = null,
  focusEndProgressNorm = null,
  autoFocusKey = null,
  showTrackEnvelope = false,
}: Props) {
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [viewMode, setViewMode] = useState<ViewMode>("2d");
  const [rotation, setRotation] = useState({ yaw: -0.95, pitch: 0.82 });
  const [cornersVisible, setCornersVisible] = useState(true);
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
  const panHoldDelayRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const panHoldRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const lastAutoFocusKeyRef = useRef<string | number | null>(null);
  const preparedSeries = useMemo(() => {
    const extracted = series
      .map((lap) => {
        const points = extractTrackPoints(lap.records);
        return points
          ? {
              ...lap,
              points: smoothTrackPoints(points),
            }
          : null;
      })
      .filter((lap): lap is CompareTrackSeries & { points: TrackPoint[] } => Boolean(lap));

    if (!extracted.length) {
      return null;
    }

    const allPoints = extracted.flatMap((lap) => lap.points);
    const averageX = allPoints.reduce((sum, point) => sum + point.x, 0) / allPoints.length;
    const averageY = allPoints.reduce((sum, point) => sum + point.y, 0) / allPoints.length;
    const averageZ = allPoints.reduce((sum, point) => sum + point.z, 0) / allPoints.length;
    const outlineTrackPoints = viewMode !== "3d" ? extractOutlineTrackPoints(trackOutline) : null;

    const centeredSeries = extracted.map((lap) => ({
      ...lap,
      centeredPoints: lap.points.map((point) => ({
        x: point.x - averageX,
        y: point.y - averageY,
        z: point.z - averageZ,
        progress: point.progress,
        elapsedTimeS: point.elapsedTimeS,
      })),
    }));

    const centeredOutline = outlineTrackPoints
      ? {
          leftPoints: outlineTrackPoints.leftPoints.map((point) => ({
            x: point.x - averageX,
            y: 0,
            z: point.z - averageZ,
            progress: point.progress,
            elapsedTimeS: null,
          })),
          rightPoints: outlineTrackPoints.rightPoints.map((point) => ({
            x: point.x - averageX,
            y: 0,
            z: point.z - averageZ,
            progress: point.progress,
            elapsedTimeS: null,
          })),
          centerPoints: outlineTrackPoints.centerPoints.map((point) => ({
            x: point.x - averageX,
            y: 0,
            z: point.z - averageZ,
            progress: point.progress,
            elapsedTimeS: null,
          })),
        }
      : null;

    const xzBounds = computeBounds(
      [
        ...centeredSeries.flatMap((lap) => lap.centeredPoints.map((point) => ({ x: point.x, y: point.z }))),
        ...(centeredOutline
          ? [
              ...centeredOutline.leftPoints.map((point) => ({ x: point.x, y: point.z })),
              ...centeredOutline.rightPoints.map((point) => ({ x: point.x, y: point.z })),
            ]
          : []),
      ],
    );
    const xyBounds = computeBounds(
      centeredSeries.flatMap((lap) => lap.centeredPoints.map((point) => ({ x: point.x, y: point.y }))),
    );
    const rangeX = xzBounds.maxX - xzBounds.minX || 1;
    const rangeZ = xzBounds.maxY - xzBounds.minY || 1;
    const rangeY = xyBounds.maxY - xyBounds.minY || 1;
    const elevationScale = Math.max(rangeX, rangeZ) / Math.max(rangeY, 1);

    const worldSeries = centeredSeries.map((lap) => ({
      ...lap,
      worldPoints: lap.centeredPoints.map((point) => {
        if (viewMode !== "3d") {
          return {
            x: point.x,
            y: point.z,
            progress: point.progress,
            elapsedTimeS: point.elapsedTimeS,
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
          progress: point.progress,
          elapsedTimeS: point.elapsedTimeS,
        };
      }),
    }));

    const worldBounds = computeBounds(
      [
        ...worldSeries.flatMap((lap) => lap.worldPoints.map((point) => ({ x: point.x, y: point.y }))),
        ...(centeredOutline && viewMode !== "3d"
          ? [
              ...centeredOutline.leftPoints.map((point) => ({ x: point.x, y: point.z })),
              ...centeredOutline.rightPoints.map((point) => ({ x: point.x, y: point.z })),
            ]
          : []),
      ],
    );
    const worldRangeX = worldBounds.maxX - worldBounds.minX || 1;
    const worldRangeY = worldBounds.maxY - worldBounds.minY || 1;

    const aspect = worldRangeX / worldRangeY;
    const viewW = 500;
    const viewH = viewW / Math.max(aspect, 0.3);
    const drawW = viewW - SVG_PADDING * 2;
    const drawH = viewH - SVG_PADDING * 2;
    const scale = Math.min(drawW / worldRangeX, drawH / worldRangeY);
    const offsetX = SVG_PADDING + ((drawW - (worldRangeX * scale)) / 2);
    const offsetY = SVG_PADDING + ((drawH - (worldRangeY * scale)) / 2);

    return {
      viewW,
      viewH,
      centerX: viewW / 2,
      centerY: viewH / 2,
      laps: worldSeries.map((lap) => ({
        ...lap,
        projected: lap.worldPoints.map((point) => ({
          sx: offsetX + ((point.x - worldBounds.minX) * scale),
          sy: offsetY + ((point.y - worldBounds.minY) * scale),
          progress: point.progress,
          elapsedTimeS: point.elapsedTimeS,
        })),
      })),
      outline:
        centeredOutline && viewMode !== "3d"
          ? {
              leftProjected: centeredOutline.leftPoints.map((point) => ({
                sx: offsetX + ((point.x - worldBounds.minX) * scale),
                sy: offsetY + ((point.z - worldBounds.minY) * scale),
                progress: point.progress,
                elapsedTimeS: null,
              })),
              rightProjected: centeredOutline.rightPoints.map((point) => ({
                sx: offsetX + ((point.x - worldBounds.minX) * scale),
                sy: offsetY + ((point.z - worldBounds.minY) * scale),
                progress: point.progress,
                elapsedTimeS: null,
              })),
              centerProjected: centeredOutline.centerPoints.map((point) => ({
                sx: offsetX + ((point.x - worldBounds.minX) * scale),
                sy: offsetY + ((point.z - worldBounds.minY) * scale),
                progress: point.progress,
                elapsedTimeS: null,
              })),
              maxWidthPx: centeredOutline.leftPoints.reduce((maxWidth, _point, index) => {
                const leftPoint = centeredOutline.leftPoints[index];
                const rightPoint = centeredOutline.rightPoints[index];
                const widthPx = Math.hypot(
                  (rightPoint.x - leftPoint.x) * scale,
                  (rightPoint.z - leftPoint.z) * scale,
                );
                return Math.max(maxWidth, widthPx);
              }, 0),
            }
          : null,
    };
  }, [rotation.pitch, rotation.yaw, series, trackOutline, viewMode]);

  // When a persisted outline is available, derive the paint width from it.
  // Otherwise fall back to the old reference-vs-lap spread heuristic.
  const trackWidths = useMemo(() => {
    const fallback = {
      outer: MIN_TRACK_OUTER_WIDTH,
      inner: Math.max(2, MIN_TRACK_OUTER_WIDTH - 2 * TRACK_EDGE_THICKNESS),
    };
    if (!preparedSeries) {
      return fallback;
    }
    if (preparedSeries.outline) {
      const outer = Math.min(
        MAX_TRACK_OUTER_WIDTH,
        Math.max(MIN_TRACK_OUTER_WIDTH, preparedSeries.outline.maxWidthPx),
      );
      return {
        outer,
        inner: Math.max(2, outer - 2 * TRACK_EDGE_THICKNESS),
      };
    }
    const referencePreparedLap = preparedSeries.laps.find((lap) => lap.isReference);
    if (!referencePreparedLap) {
      return fallback;
    }

    let maxLateralPx = 0;
    // Sample every 12th point to keep envelope sizing O(n) rather than O(n²).
    const STRIDE = 12;
    for (const lap of preparedSeries.laps) {
      if (lap.isReference) continue;
      for (let i = 0; i < lap.projected.length; i += STRIDE) {
        const point = lap.projected[i];
        if (point.progress === null) continue;
        const referencePoint = interpolateTrackPoint(
          referencePreparedLap.projected,
          point.progress,
          "progress",
        );
        if (!referencePoint) continue;
        const dx = point.sx - referencePoint.sx;
        const dy = point.sy - referencePoint.sy;
        const distance = Math.sqrt(dx * dx + dy * dy);
        if (distance > maxLateralPx) {
          maxLateralPx = distance;
        }
      }
    }

    const outer = Math.min(
      MAX_TRACK_OUTER_WIDTH,
      Math.max(MIN_TRACK_OUTER_WIDTH, 2 * maxLateralPx + 2 * TRACK_EDGE_PADDING),
    );
    const inner = Math.max(2, outer - 2 * TRACK_EDGE_THICKNESS);
    return { outer, inner };
  }, [preparedSeries]);

  const displayData = useMemo(() => {
    if (!preparedSeries) {
      return null;
    }

    const laps = preparedSeries.laps.map((lap) => {
      const transformedPoints = applyViewportTransform(
        lap.projected,
        zoom,
        pan,
        preparedSeries.centerX,
        preparedSeries.centerY,
      );
      return {
        ...lap,
        transformedPoints,
        path: buildSmoothPath(transformedPoints),
      };
    });

    return {
      ...preparedSeries,
      laps,
      outline: preparedSeries.outline
        ? (() => {
            const leftPoints = applyViewportTransform(
              preparedSeries.outline.leftProjected,
              zoom,
              pan,
              preparedSeries.centerX,
              preparedSeries.centerY,
            );
            const rightPoints = applyViewportTransform(
              preparedSeries.outline.rightProjected,
              zoom,
              pan,
              preparedSeries.centerX,
              preparedSeries.centerY,
            );
            const centerPoints = applyViewportTransform(
              preparedSeries.outline.centerProjected,
              zoom,
              pan,
              preparedSeries.centerX,
              preparedSeries.centerY,
            );
            return {
              leftPoints,
              rightPoints,
              centerPoints,
              leftPath: buildSmoothPath(leftPoints),
              rightPath: buildSmoothPath(rightPoints),
              polygonPath: buildClosedPolygonPath(leftPoints, rightPoints),
              maxWidthPx: preparedSeries.outline.maxWidthPx,
            };
          })()
        : null,
    };
  }, [pan, preparedSeries, zoom]);

  const referenceLap = displayData?.laps.find((lap) => lap.isReference) ?? null;
  const displayOutline = displayData?.outline ?? null;
  const hasCorners = Boolean(corners && corners.length > 0 && referenceLap);
  const showCorners = cornersVisible && hasCorners;

  const cornerSegments = useMemo(() => {
    if (!showCorners || !corners || !referenceLap) {
      return [];
    }
    return buildCornerSegments(corners, referenceLap.transformedPoints);
  }, [corners, referenceLap, showCorners]);

  const cornerRegionOverlays = useMemo(() => {
    if (!showCorners || !corners || !displayOutline) {
      return [];
    }
    return buildCornerRegionOverlays(
      corners,
      displayOutline.leftPoints,
      displayOutline.rightPoints,
    );
  }, [corners, displayOutline, showCorners]);

  const cornerLabels = useMemo(() => {
    if (!showCorners || !cornerSegments.length) {
      return [];
    }
    const seen = new Set<number>();
    return cornerSegments
      .filter((segment) => {
        if (segment.region !== "center" || seen.has(segment.cornerId)) {
          return false;
        }
        seen.add(segment.cornerId);
        return true;
      })
      .map((segment) => ({
        x: segment.labelX,
        y: segment.labelY,
        offsetX: segment.labelOffsetX,
        offsetY: segment.labelOffsetY,
        id: segment.cornerId,
      }));
  }, [cornerSegments, showCorners]);

  const activeMarkerKey = activeMode === "time" ? "elapsedTimeS" : "progress";
  const activeMarkerValue = activeMode === "time" ? activeElapsedTimeS : activeProgressNorm;
  const activeMarkers = useMemo(
    () =>
      displayData?.laps
        .filter((lap) => !lap.invisible)
        .map((lap) => ({
          ...lap,
          marker: interpolateTrackPoint(lap.transformedPoints, activeMarkerValue, activeMarkerKey),
        }))
        .filter((lap) => lap.marker !== null) ?? [],
    [activeMarkerKey, activeMarkerValue, displayData],
  );

  const handleWheel = useCallback((event: React.WheelEvent<SVGSVGElement>) => {
    event.preventDefault();
    setZoom((current) => clampZoom(event.deltaY < 0 ? current * ZOOM_STEP : current / ZOOM_STEP));
  }, []);

  const zoomIn = useCallback(() => {
    setZoom((current) => clampZoom(current * ZOOM_STEP));
  }, []);

  const zoomOut = useCallback(() => {
    setZoom((current) => clampZoom(current / ZOOM_STEP));
  }, []);

  const nudgePan = useCallback((dx: number, dy: number) => {
    setPan((current) => ({ x: current.x + dx, y: current.y + dy }));
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
    (event: React.PointerEvent<SVGSVGElement>) => {
      const isPrimaryButton = event.button === 0;
      const isMiddleButton = event.button === 1;
      if (!isPrimaryButton && !isMiddleButton) {
        return;
      }

      event.preventDefault();
      (event.target as Element).setPointerCapture?.(event.pointerId);

      if (viewMode === "3d") {
        if (event.shiftKey || isMiddleButton) {
          dragRef.current = {
            mode: "pan",
            startX: event.clientX,
            startY: event.clientY,
            panX: pan.x,
            panY: pan.y,
          };
          return;
        }

        dragRef.current = {
          mode: "orbit",
          startX: event.clientX,
          startY: event.clientY,
          yaw: rotation.yaw,
          pitch: rotation.pitch,
        };
        return;
      }

      dragRef.current = {
        mode: "pan",
        startX: event.clientX,
        startY: event.clientY,
        panX: pan.x,
        panY: pan.y,
      };
    },
    [pan.x, pan.y, rotation.pitch, rotation.yaw, viewMode],
  );

  const handlePointerMove = useCallback(
    (event: React.PointerEvent<SVGSVGElement>) => {
      if (dragRef.current) {
        const dx = event.clientX - dragRef.current.startX;
        const dy = event.clientY - dragRef.current.startY;
        if (dragRef.current.mode === "orbit") {
          setRotation({
            yaw: dragRef.current.yaw + (dx * ROTATION_STEP),
            pitch: clampPitch(dragRef.current.pitch - (dy * ROTATION_STEP)),
          });
          return;
        }

        setPan({
          x: dragRef.current.panX + dx,
          y: dragRef.current.panY + dy,
        });
        return;
      }

      if (!onActiveProgressChange || !referenceLap || !displayData) {
        return;
      }

      const rect = event.currentTarget.getBoundingClientRect();
      const cursorX = ((event.clientX - rect.left) / rect.width) * displayData.viewW;
      const cursorY = ((event.clientY - rect.top) / rect.height) * displayData.viewH;

      let bestDistanceSq = Infinity;
      let bestProgress: number | null = null;
      for (const point of referenceLap.transformedPoints) {
        if (point.progress === null) {
          continue;
        }
        const dx = point.sx - cursorX;
        const dy = point.sy - cursorY;
        const distanceSq = (dx * dx) + (dy * dy);
        if (distanceSq < bestDistanceSq) {
          bestDistanceSq = distanceSq;
          bestProgress = point.progress;
        }
      }

      if (bestProgress !== null && Math.sqrt(bestDistanceSq) <= MAP_HOVER_SNAP_PX) {
        onActiveProgressChange(bestProgress);
      } else {
        onActiveProgressChange(null);
      }
    },
    [displayData, onActiveProgressChange, referenceLap],
  );

  const handlePointerUp = useCallback(() => {
    dragRef.current = null;
  }, []);

  useEffect(() => {
    if (
      viewMode !== "2d" ||
      !preparedSeries ||
      focusStartProgressNorm === null ||
      focusEndProgressNorm === null ||
      autoFocusKey === null
    ) {
      return;
    }
    if (lastAutoFocusKeyRef.current === autoFocusKey) {
      return;
    }

    const focusPoints = preparedSeries.laps.flatMap((lap) =>
      lap.projected.filter((point) =>
        progressInRange(point.progress, focusStartProgressNorm, focusEndProgressNorm),
      ),
    );
    if (focusPoints.length < 2) {
      return;
    }

    const bounds = computeBounds(
      focusPoints.map((point) => ({ x: point.sx, y: point.sy })),
    );
    const spanX = Math.max(bounds.maxX - bounds.minX, MIN_FOCUS_SPAN_PX);
    const spanY = Math.max(bounds.maxY - bounds.minY, MIN_FOCUS_SPAN_PX);
    const zoomX = (preparedSeries.viewW - (FOCUS_PADDING_PX * 2)) / spanX;
    const zoomY = (preparedSeries.viewH - (FOCUS_PADDING_PX * 2)) / spanY;
    const nextZoom = clampZoom(Math.max(1, Math.min(zoomX, zoomY)));
    const boundsCenterX = (bounds.minX + bounds.maxX) / 2;
    const boundsCenterY = (bounds.minY + bounds.maxY) / 2;

    setZoom(nextZoom);
    setPan({
      x: (preparedSeries.centerX - boundsCenterX) * nextZoom,
      y: (preparedSeries.centerY - boundsCenterY) * nextZoom,
    });
    lastAutoFocusKeyRef.current = autoFocusKey;
  }, [
    autoFocusKey,
    focusEndProgressNorm,
    focusStartProgressNorm,
    preparedSeries,
    viewMode,
  ]);

  const resetView = useCallback(() => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
    setRotation({ yaw: -0.95, pitch: 0.82 });
  }, []);

  if (!displayData || !displayData.laps.length) {
    return (
      <div
        className={`density-analysis-chart rounded-3xl border border-border/70 bg-surface-1/85 ${className}`.trim()}
      >
        <div className="mb-3 flex items-start justify-between gap-3">
          <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-text-muted">
            Track Overlay
          </p>
        </div>
        <div
          className="flex items-center justify-center rounded-2xl border border-dashed border-border/70 bg-surface-2/72 p-4 text-sm text-text-muted"
          style={{ height: height - 40 }}
        >
          No aligned position data available for the selected laps.
        </div>
      </div>
    );
  }

  const isZoomedOrPanned = zoom !== 1 || pan.x !== 0 || pan.y !== 0;

  return (
    <div
      className={`density-analysis-chart rounded-3xl border border-border/70 bg-surface-1/85 ${className}`.trim()}
    >
      <div className="mb-3 flex items-start justify-between gap-3">
        <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-text-muted">
          Track Overlay
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
              onClick={() => setCornersVisible((current) => !current)}
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
          viewBox={`0 0 ${displayData.viewW} ${displayData.viewH}`}
          width="100%"
          height="100%"
          preserveAspectRatio="xMidYMid meet"
          className="cursor-grab active:cursor-grabbing"
          onWheel={handleWheel}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onPointerLeave={() => {
            handlePointerUp();
            onActiveProgressChange?.(null);
          }}
          onContextMenu={(event) => event.preventDefault()}
        >
          {viewMode === "3d" && referenceLap && (
            <>
              <path
                d={referenceLap.path}
                fill="none"
                stroke="var(--app-surface-0)"
                strokeWidth={THREE_D_OUTLINE_OUTER_WIDTH}
                strokeLinecap="round"
                strokeLinejoin="round"
                opacity={0.5}
              />
              <path
                d={referenceLap.path}
                fill="none"
                stroke="var(--app-border-strong)"
                strokeWidth={THREE_D_OUTLINE_INNER_WIDTH}
                strokeLinecap="round"
                strokeLinejoin="round"
                opacity={0.78}
              />
            </>
          )}

          {showTrackEnvelope && viewMode !== "3d" && displayOutline?.polygonPath ? (
            <>
              <path
                d={displayOutline.polygonPath}
                fill="rgba(8,10,16,0.82)"
                opacity={0.92}
              />
              {showCorners &&
                cornerRegionOverlays.map((overlay) => (
                  <path
                    key={`corner-fill-${overlay.key}`}
                    d={overlay.polygonPath}
                    fill={overlay.color}
                    opacity={0.82}
                  />
                ))}
              <path
                d={displayOutline.leftPath}
                fill="none"
                stroke="rgba(255,255,255,0.55)"
                strokeWidth={TRACK_EDGE_THICKNESS}
                strokeLinecap="round"
                strokeLinejoin="round"
                opacity={0.95}
              />
              <path
                d={displayOutline.rightPath}
                fill="none"
                stroke="rgba(255,255,255,0.55)"
                strokeWidth={TRACK_EDGE_THICKNESS}
                strokeLinecap="round"
                strokeLinejoin="round"
                opacity={0.95}
              />
              {showCorners &&
                cornerRegionOverlays.map((overlay) => (
                  <g key={`corner-caps-${overlay.key}`}>
                    <path
                      d={overlay.startCapPath}
                      fill="none"
                      stroke={overlay.color}
                      strokeWidth={2.2}
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      opacity={0.95}
                    />
                    <path
                      d={overlay.endCapPath}
                      fill="none"
                      stroke={overlay.color}
                      strokeWidth={2.2}
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      opacity={0.95}
                    />
                  </g>
                ))}
            </>
          ) : (
            <>
              {/* Corner fills drawn first so track edges render on top of them */}
              {showCorners &&
                cornerSegments.map((segment, index) => (
                  <path
                    key={`corner-${segment.cornerId}-${segment.region}-${index}`}
                    d={segment.path}
                    fill="none"
                    stroke={segment.color}
                    strokeWidth={trackWidths.outer}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                ))}

              {showTrackEnvelope && referenceLap && (
                <>
                  <path
                    d={referenceLap.path}
                    fill="none"
                    stroke="rgba(255,255,255,0.55)"
                    strokeWidth={trackWidths.outer}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    opacity={0.95}
                  />
                  <path
                    d={referenceLap.path}
                    fill="none"
                    stroke="rgba(8,10,16,0.82)"
                    strokeWidth={trackWidths.inner}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    opacity={0.92}
                  />
                </>
              )}
            </>
          )}

          {displayData.laps
            .filter((lap) => !lap.invisible)
            .map((lap) => (
              <g key={lap.id}>
                <path
                  d={lap.path}
                  fill="none"
                  stroke={lap.color}
                  strokeWidth={lap.isReference ? REFERENCE_LINE_WIDTH : OTHER_LINE_WIDTH}
                  strokeDasharray={lap.isReference ? REFERENCE_LINE_DASH : undefined}
                  strokeLinecap="butt"
                  strokeLinejoin="round"
                  opacity={lap.isReference ? 0.85 : 1}
                />
              </g>
            ))}

          {showCorners &&
            cornerLabels.map((label) => {
              const lx = label.x + label.offsetX;
              const ly = label.y + label.offsetY;
              return (
                <g key={`label-${label.id}`}>
                  <line
                    x1={label.x}
                    y1={label.y}
                    x2={lx}
                    y2={ly}
                    stroke="var(--app-text-muted)"
                    strokeWidth={0.8}
                    opacity={0.5}
                  />
                  <circle
                    cx={label.x}
                    cy={label.y}
                    r={2}
                    fill="var(--app-text-muted)"
                    opacity={0.6}
                  />
                  <circle
                    cx={lx}
                    cy={ly}
                    r={9}
                    fill="var(--app-surface-0)"
                    opacity={0.9}
                  />
                  <text
                    x={lx}
                    y={ly}
                    textAnchor="middle"
                    dominantBaseline="central"
                    fill="var(--app-text-primary)"
                    fontSize={CORNER_LABEL_FONT_SIZE}
                    fontWeight={600}
                  >
                    {`T${label.id}`}
                  </text>
                </g>
              );
            })}

          {referenceLap?.transformedPoints[0] && (
            <circle
              cx={referenceLap.transformedPoints[0].sx}
              cy={referenceLap.transformedPoints[0].sy}
              r={START_MARKER_RADIUS}
              fill="var(--app-text-muted)"
              opacity={0.7}
            />
          )}

          {activeMarkers.map((lap) => (
            <circle
              key={`marker-${lap.id}`}
              cx={lap.marker?.sx}
              cy={lap.marker?.sy}
              r={lap.isReference ? MARKER_RADIUS + 0.75 : MARKER_RADIUS}
              fill={lap.color}
              stroke="var(--app-surface-0)"
              strokeWidth={2}
              opacity={lap.isReference ? 1 : 0.92}
            />
          ))}
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

      <div className="mt-3 flex flex-wrap items-center gap-3">
        {displayData.laps
          .filter((lap) => !lap.invisible)
          .map((lap) => (
            <div key={`legend-${lap.id}`} className="flex items-center gap-2">
              <span
                className="inline-block h-2.5 w-6 rounded-full"
                style={{ backgroundColor: lap.color, opacity: lap.isReference ? 1 : 0.72 }}
              />
              <span className="text-[10px] uppercase tracking-[0.12em] text-text-muted">
                {lap.label}
                {lap.isReference ? " · ref" : ""}
              </span>
            </div>
          ))}
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
