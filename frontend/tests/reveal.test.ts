import { describe, expect, it } from "vitest";
import type { Route } from "../src/api";
import {
  outcomeNote,
  revealAttempts,
  type Outcome,
} from "../src/reveal";

const stop = (id: string, horizon_minutes = 10) => ({
  id,
  name: id,
  lat: 41.88,
  lon: -87.63,
  walk_minutes: 2,
  probability: 0.9,
  bikes: 3,
  docks: 3,
  horizon_minutes,
  estimated_arrival_time: "2021-07-20T08:10:00-05:00",
  effective_prediction_time: "2021-07-20T08:10:00-05:00",
  data_age_seconds: 30,
});
const route = (pickup: string | null, dropoff: string, ride = 20): Route => ({
  pickup: pickup ? stop(pickup) : null,
  dropoff: stop(dropoff, ride),
  wait_minutes: 0,
  ride_minutes: 10,
  ride_method: "training_median",
  total_minutes: 14,
});

describe("revealing what happened", () => {
  it("checks both ends of our trip, pickup first", () => {
    const { ours, b1 } = revealAttempts(route("a", "b"), null);
    expect(ours).toEqual([
      { station_id: "a", horizon_minutes: 10, phase: "pickup" },
      { station_id: "b", horizon_minutes: 20, phase: "return" },
    ]);
    expect(b1).toEqual([]);
    expect(revealAttempts(route(null, "b"), null).ours).toHaveLength(1);
  });

  it("adds only the stops where the current-count app chose differently", () => {
    // The reveal endpoint takes at most two attempts, so the baseline's go in
    // a request of their own.
    expect(revealAttempts(route("a", "b"), route("a", "c")).b1).toEqual([
      { station_id: "c", horizon_minutes: 20, phase: "return" },
    ]);
    expect(revealAttempts(route("a", "b"), route("a", "b")).b1).toEqual([]);
  });

  it("says what was there at arrival in plain words", () => {
    const o = (
      phase: "pickup" | "return",
      status: Outcome["status"],
      observed: number | null,
    ): Outcome => ({
      station_id: "a",
      horizon_minutes: 10,
      phase,
      observed,
      status,
    });
    expect(outcomeNote(o("pickup", "available", 7))).toBe(
      "At arrival: 7 bikes",
    );
    expect(outcomeNote(o("pickup", "unavailable", 0))).toBe(
      "At arrival: no bike",
    );
    expect(outcomeNote(o("return", "available", 1))).toBe(
      "At arrival: 1 open dock",
    );
    expect(outcomeNote(o("return", "unavailable", 0))).toBe("At arrival: full");
    expect(outcomeNote(o("return", "unobservable", null))).toBe("Not observed");
  });
});
