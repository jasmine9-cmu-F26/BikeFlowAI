import { describe, expect, it } from "vitest";
import type { Plan, Route } from "../src/api";
import {
  needsWiderWalk,
  nextWalk,
  widerIsBetter,
  widerReason,
  widerRows,
} from "../src/PlanNotices";

const stop = (id: string, probability: number) => ({
  id,
  name: id,
  lat: 41.88,
  lon: -87.63,
  walk_minutes: 2,
  probability,
  bikes: 3,
  docks: 3,
  horizon_minutes: 10,
  estimated_arrival_time: "2021-07-20T08:10:00-05:00",
  effective_prediction_time: "2021-07-20T08:10:00-05:00",
  data_age_seconds: 30,
});
const route = (pb: number, pd: number, a = "a", b = "b"): Route => ({
  pickup: stop(a, pb),
  dropoff: stop(b, pd),
  wait_minutes: 0,
  ride_minutes: 10,
  ride_method: "training_median",
  total_minutes: 14,
});
const plan = (primary: Route | null, backups: Route[] = []): Plan => ({
  status: primary ? "ok" : "no_plan",
  requested_method: "B3",
  actual_method: "B3",
  mode: "replay",
  primary,
  backups,
  warnings: [],
  no_plan_reason: primary ? null : "none",
  request_id: "r",
  decision_time: "2021-07-20T08:06:00-05:00",
  latency_ms: 1,
  model_version: "m",
  data_age_seconds: 30,
});

describe("walking-limit suggestion", () => {
  it("re-checks only sparse, risky or empty plans", () => {
    expect(needsWiderWalk(plan(null))).toBe(true);
    expect(needsWiderWalk(plan(route(0.95, 0.95)))).toBe(true); // no alternatives
    expect(needsWiderWalk(plan(route(0.7, 0.95), [route(0.9, 0.9)]))).toBe(
      true,
    );
    expect(needsWiderWalk(plan(route(0.95, 0.95), [route(0.9, 0.9)]))).toBe(
      false,
    );
  });

  it("offers the longer walk only when it clearly helps", () => {
    const risky = plan(route(0.7, 0.95), [route(0.6, 0.9)]);
    expect(widerIsBetter(risky, plan(route(0.95, 0.95, "c")))).toBe(true);
    expect(widerIsBetter(risky, plan(route(0.72, 0.95, "c")))).toBe(false);
    expect(widerIsBetter(plan(null), plan(route(0.8, 0.9)))).toBe(true);
    expect(
      widerIsBetter(
        plan(route(0.95, 0.95)),
        plan(route(0.95, 0.95), [route(0.9, 0.9)]),
      ),
    ).toBe(true);
    expect(widerIsBetter(risky, plan(null))).toBe(false);
  });

  it("steps through the walking limits the RL policy supports", () => {
    expect(nextWalk(5)).toBe(10);
    expect(nextWalk(10)).toBe(15);
    expect(nextWalk(15)).toBeNull();
  });

  it("names what the longer walk buys, in a word for the switch", () => {
    const risky = plan(route(0.7, 0.95), [route(0.6, 0.9)]);
    expect(widerReason(plan(null), plan(route(0.9, 0.9)))).toBe("possible");
    expect(widerReason(risky, plan(route(0.95, 0.95, "c")))).toBe("safer");
    expect(
      widerReason(plan(route(0.95, 0.95)), plan(route(0.95, 0.95), [route(0.9, 0.9)])),
    ).toBe("backup");
  });

  it("spells out the trade-off against the current plan", () => {
    const current = plan(route(0.38, 0.99, "start", "end"));
    const wider = plan(route(0.99, 0.99, "north", "end"), [route(0.9, 0.9)]);
    expect(widerRows(current, wider)).toEqual([
      "Pick up at north · 99% bike (now 38%)",
      "1 alternative instead of 0",
      "4.0 min total walking (now 4.0)",
    ]);
  });
});
