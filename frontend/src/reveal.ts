import type { Route } from "./api";

// What /replay/reveal checks and returns: the recorded count at a station at
// the time the rider would have arrived there.
export type Phase = "pickup" | "return";
export type Attempt = {
  station_id: string;
  horizon_minutes: number;
  phase: Phase;
};
export type Outcome = Attempt & {
  observed: number | null;
  status: "available" | "unavailable" | "unobservable";
};

const attemptsFor = (r: Route): Attempt[] => [
  ...(r.pickup
    ? [
        {
          station_id: r.pickup.id,
          horizon_minutes: r.pickup.horizon_minutes,
          phase: "pickup" as const,
        },
      ]
    : []),
  {
    station_id: r.dropoff.id,
    horizon_minutes: r.dropoff.horizon_minutes,
    phase: "return",
  },
];

/**
 * Reveal attempts for our trip and for the stops where the current-count
 * baseline (B1) chose differently. Each list holds at most two attempts, the
 * most /replay/reveal accepts in one request.
 */
export function revealAttempts(ours: Route, b1: Route | null) {
  const mine = attemptsFor(ours);
  const key = (a: Attempt) => `${a.phase}|${a.station_id}|${a.horizon_minutes}`;
  const taken = new Set(mine.map(key));
  return {
    ours: mine,
    b1: b1 ? attemptsFor(b1).filter((a) => !taken.has(key(a))) : [],
  };
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

export function outcomeNote(o: Outcome) {
  if (o.status === "unobservable" || o.observed === null) return "Not observed";
  if (o.phase === "pickup")
    return o.status === "available"
      ? `At arrival: ${plural(o.observed, "bike")}`
      : "At arrival: no bike";
  return o.status === "available"
    ? `At arrival: ${plural(o.observed, "open dock")}`
    : "At arrival: full";
}
