import { describe, expect, it } from "vitest";
import { routeOnMap } from "../src/routeOnMap";
import type { Plan, Route } from "../src/api";

const route = (name: string) =>
  ({ pickup: null, dropoff: { name } }) as unknown as Route;
const primary = route("primary");
const backups = [route("option 2"), route("option 3")];
const plan = { primary, backups } as unknown as Plan;

describe("route on the map", () => {
  it("shows nothing before a plan exists", () => {
    expect(routeOnMap(null, null, null)).toBeNull();
  });

  it("follows the route whose details are open", () => {
    expect(routeOnMap(plan, backups[1], null)).toBe(backups[1]);
  });

  it("keeps the recommended trip on the map while browsing alternatives", () => {
    expect(routeOnMap(plan, null, null)).toBe(primary);
  });

  it("previews the alternative under the pointer", () => {
    expect(routeOnMap(plan, null, 0)).toBe(backups[0]);
  });

  it("shows nothing when the plan found no ride", () => {
    const none = { primary: null, backups: [] } as unknown as Plan;
    expect(routeOnMap(none, null, null)).toBeNull();
  });
});
