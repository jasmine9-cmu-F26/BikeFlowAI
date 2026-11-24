import type { Plan, Route } from "./api";

// The map keeps showing a trip for as long as a plan is on screen: the route
// whose details are open, else the alternative under the pointer, else the
// recommended one (so browsing the alternatives list keeps the trip in view).
export function routeOnMap(
  plan: Plan | null,
  open: Route | null,
  preview: number | null,
): Route | null {
  if (open) return open;
  if (!plan) return null;
  return (preview !== null ? plan.backups[preview] : null) ?? plan.primary;
}
