import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AUTO_REPLAN_MS, debounced } from "../src/autoReplan";

describe("auto replan", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("plans once after a burst of input changes settles", () => {
    const run = vi.fn();
    const auto = debounced(run);
    auto.schedule();
    vi.advanceTimersByTime(AUTO_REPLAN_MS - 50);
    auto.schedule();
    vi.advanceTimersByTime(AUTO_REPLAN_MS - 50);
    expect(run).not.toHaveBeenCalled();
    vi.advanceTimersByTime(50);
    expect(run).toHaveBeenCalledTimes(1);
  });

  it("drops a pending replan when a plan is requested directly", () => {
    const run = vi.fn();
    const auto = debounced(run);
    auto.schedule();
    auto.cancel();
    vi.advanceTimersByTime(AUTO_REPLAN_MS * 2);
    expect(run).not.toHaveBeenCalled();
  });

  it("waits about a quarter second", () => {
    expect(AUTO_REPLAN_MS).toBeGreaterThanOrEqual(200);
    expect(AUTO_REPLAN_MS).toBeLessThanOrEqual(400);
  });
});
