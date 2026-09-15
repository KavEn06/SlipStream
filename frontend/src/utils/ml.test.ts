import { describe, expect, it } from "vitest";
import type { ExpectedInputProfile } from "../types";
import {
  interpolateExpectedMetric,
  shapeManualConditionRequest,
} from "./ml";

const profile: ExpectedInputProfile = {
  lap_number: 1,
  support: 0.9,
  points: [
    {
      progress_norm: 0.2,
      throttle: { expected: 0.2, lower: 0.1, upper: 0.3 },
      brake: { expected: 0.8, lower: 0.7, upper: 0.9 },
      steering: { expected: -0.2, lower: -0.3, upper: -0.1 },
      speed: { expected: 100, lower: 95, upper: 105 },
    },
    {
      progress_norm: 0.6,
      throttle: { expected: 0.6, lower: 0.5, upper: 0.7 },
      brake: { expected: 0.0, lower: null, upper: 0.1 },
      steering: { expected: 0.2, lower: 0.1, upper: 0.3 },
      speed: { expected: 140, lower: 135, upper: 145 },
    },
  ],
};

describe("expected profile interpolation", () => {
  it("interpolates expected values and interval bounds on aligned progress", () => {
    expect(interpolateExpectedMetric(profile, 0.4, "speed", "expected")).toBeCloseTo(120);
    expect(interpolateExpectedMetric(profile, 0.4, "throttle", "lower")).toBeCloseTo(0.3);
    expect(interpolateExpectedMetric(profile, 0.2, "steering", "expected")).toBeCloseTo(-0.2);
  });

  it("does not extrapolate or bridge a missing calibrated bound", () => {
    expect(interpolateExpectedMetric(profile, 0.1, "speed", "expected")).toBeUndefined();
    expect(interpolateExpectedMetric(profile, 0.4, "brake", "lower")).toBeUndefined();
    expect(interpolateExpectedMetric(null, 0.4, "speed", "expected")).toBeUndefined();
  });
});

describe("manual condition request shaping", () => {
  it("omits blank inputs and converts supplied values to numbers", () => {
    expect(
      shapeManualConditionRequest({
        wetness: " 0.25 ",
        air_temp_c: "",
        track_temp_c: "31.5",
        tyre_wear: "0",
      }),
    ).toEqual({ wetness: 0.25, track_temp_c: 31.5, tyre_wear: 0 });
  });

  it("rejects empty, non-numeric, and out-of-contract requests", () => {
    expect(() => shapeManualConditionRequest({ wetness: "" })).toThrow(
      "Enter at least one override.",
    );
    expect(() => shapeManualConditionRequest({ wetness: "wet" })).toThrow(
      "Enter valid numeric condition values.",
    );
    expect(() => shapeManualConditionRequest({ tyre_wear: "1.1" })).toThrow(
      "tyre_wear must be between 0 and 1.",
    );
  });
});
