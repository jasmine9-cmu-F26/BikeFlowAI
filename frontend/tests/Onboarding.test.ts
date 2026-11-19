import { afterEach, describe, expect, it, vi } from "vitest";
import { markOnboardingSeen, shouldShowOnboarding } from "../src/Onboarding";

function fakeStorage() {
  const data = new Map<string, string>();
  return {
    getItem: (k: string) => data.get(k) ?? null,
    setItem: (k: string, v: string) => void data.set(k, v),
  };
}

describe("first-visit guide", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("shows once, then stays closed", () => {
    vi.stubGlobal("localStorage", fakeStorage());
    expect(shouldShowOnboarding()).toBe(true);
    markOnboardingSeen();
    expect(shouldShowOnboarding()).toBe(false);
  });

  it("never breaks the page when storage is blocked", () => {
    vi.stubGlobal("localStorage", {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      },
    });
    expect(shouldShowOnboarding()).toBe(true);
    expect(() => markOnboardingSeen()).not.toThrow();
  });
});
