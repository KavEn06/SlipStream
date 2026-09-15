import type { ExpectedInputProfile, ManualConditions } from "../types";

export type ExpectedMetric = "speed" | "brake" | "throttle" | "steering";
export type ExpectedBound = "expected" | "lower" | "upper";

const CONDITION_LIMITS: Record<
  keyof ManualConditions,
  readonly [number, number]
> = {
  wetness: [0, 1],
  air_temp_c: [-80, 80],
  track_temp_c: [-80, 100],
  tyre_wear: [0, 1],
};

export function interpolateExpectedMetric(
  profile: ExpectedInputProfile | null,
  progressNorm: number,
  key: ExpectedMetric,
  bound: ExpectedBound,
): number | undefined {
  if (!profile || profile.points.length === 0) return undefined;
  const points = profile.points;
  if (
    progressNorm < points[0].progress_norm ||
    progressNorm > points[points.length - 1].progress_norm
  ) {
    return undefined;
  }

  const firstValue = points[0][key][bound];
  if (progressNorm === points[0].progress_norm) {
    return firstValue === null ? undefined : firstValue;
  }

  for (let index = 1; index < points.length; index += 1) {
    const previous = points[index - 1];
    const current = points[index];
    if (
      progressNorm < previous.progress_norm ||
      progressNorm > current.progress_norm
    ) {
      continue;
    }
    const previousValue = previous[key][bound];
    const currentValue = current[key][bound];
    if (previousValue === null || currentValue === null) return undefined;
    const span = current.progress_norm - previous.progress_norm;
    if (span <= 0) return currentValue;
    const ratio = (progressNorm - previous.progress_norm) / span;
    return previousValue + (currentValue - previousValue) * ratio;
  }
  return undefined;
}

export function shapeManualConditionRequest(
  values: Partial<Record<keyof ManualConditions, string>>,
): ManualConditions {
  const supplied: ManualConditions = {};
  for (const key of Object.keys(CONDITION_LIMITS) as Array<
    keyof ManualConditions
  >) {
    const raw = values[key];
    if (raw === undefined || raw.trim() === "") continue;
    const value = Number(raw);
    if (!Number.isFinite(value)) {
      throw new Error("Enter valid numeric condition values.");
    }
    const [minimum, maximum] = CONDITION_LIMITS[key];
    if (value < minimum || value > maximum) {
      throw new Error(
        `${key} must be between ${minimum} and ${maximum}.`,
      );
    }
    supplied[key] = value;
  }
  if (Object.keys(supplied).length === 0) {
    throw new Error("Enter at least one override.");
  }
  return supplied;
}
