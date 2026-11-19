import { ArrowRight, Layers, RefreshCw, TriangleAlert } from "lucide-react";
import {
  clock,
  type Endpoint,
  type Plan,
  type Route,
  type Station,
} from "./api";
import { RISK_THRESHOLD } from "./Map";

const HORIZONS = [10, 20, 30, 40, 50, 60];
// Never round a probability up to a certainty.
const pct = (p: number) =>
  Math.min(Math.round(p * 100), p < 1 ? 99 : 100) + "%";

function pDock(s: Station | undefined, h: number) {
  const v = s?.forecast?.[h]?.p_dock;
  return v === undefined ? null : v;
}

/** Station a rider would naturally return at: the destination station, or the nearest one. */
export function destinationStation(destination: Endpoint, stations: Station[]) {
  if (typeof destination === "string")
    return stations.find((s) => s.id === destination);
  let best: Station | undefined;
  let bestD = Infinity;
  for (const s of stations) {
    const dy = s.lat - destination.lat;
    const dx = (s.lon - destination.lon) * Math.cos((s.lat * Math.PI) / 180);
    const d = dx * dx + dy * dy;
    if (d < bestD) {
      bestD = d;
      best = s;
    }
  }
  return best;
}

/**
 * Makes the dock side of the forecaster visible: the destination's open-dock
 * forecast over the next hour, whether the plan rerouted the return, and what a
 * current-count planner (B1) would have chosen instead.
 */
export default function DockInsight({
  route,
  plan,
  destination,
  stations,
  baseline,
  comparing,
  onCompare,
}: {
  route: Route;
  plan: Plan;
  destination: Endpoint;
  stations: Station[];
  baseline: Plan | null;
  comparing: boolean;
  onCompare: (() => void) | null;
}) {
  const dest = destinationStation(destination, stations);
  if (!dest) return null;
  // Horizon at which the rider reaches the return area (same quantization as the planner).
  const sameStop = [plan.primary, ...plan.backups].find(
    (r) => r?.dropoff.id === dest.id,
  )?.dropoff;
  const h = sameStop?.horizon_minutes ?? route.dropoff.horizon_minutes;
  const at =
    sameStop?.effective_prediction_time ??
    route.dropoff.effective_prediction_time;
  const pDest = pDock(dest, h);
  if (pDest === null) return null;
  const chosen = stations.find((s) => s.id === route.dropoff.id);
  const pChosen = pDock(chosen, route.dropoff.horizon_minutes);
  const rerouted = route.dropoff.id !== dest.id;
  const risky = pDest < RISK_THRESHOLD;
  const b1 = baseline?.primary?.dropoff;
  return (
    <section
      className={
        "dock-insight " + (rerouted ? "rerouted" : risky ? "risk" : "ok")
      }
      aria-label="Return dock forecast"
    >
      <span className="eyebrow">
        <Layers size={12} /> RETURN CHECK · DOCK FORECAST
      </span>
      {rerouted ? (
        <>
          <strong>Return moved to {route.dropoff.name}</strong>
          <p>
            {dest.name} shows <b>{dest.docks} open docks</b> right now, but the
            forecast gives only <b>{pct(pDest)}</b> chance of an open dock by{" "}
            {clock(at)}.
            {pChosen !== null && (
              <>
                {" "}
                {route.dropoff.name} is a {route.dropoff.walk_minutes} min walk
                away at <b>{pct(pChosen)}</b>.
              </>
            )}
          </p>
        </>
      ) : (
        <>
          <strong>
            {risky ? "This dock may fill up" : "Open dock expected"}
          </strong>
          <p>
            {dest.name}: <b>{dest.docks} open docks</b> now →{" "}
            <b>{pct(pDest)}</b> chance by {clock(at)}.
            {risky && " Keep an alternative in reach."}
          </p>
        </>
      )}
      <div
        className="dock-trend"
        aria-label={`Open-dock forecast at ${dest.name}`}
      >
        {HORIZONS.map((hh) => {
          const p = pDock(dest, hh);
          return (
            <span
              key={hh}
              className={
                (p !== null && p < RISK_THRESHOLD ? "low " : "") +
                (hh === h ? "arrival" : "")
              }
            >
              <i style={{ height: `${Math.max(3, (p ?? 0) * 38)}px` }} />
              <b>{p === null ? "—" : pct(p)}</b>
              <small>+{hh}</small>
            </span>
          );
        })}
      </div>
      <small className="dock-trend-caption">
        Open-dock chance at {dest.name} · minutes from now · outlined = your
        arrival
      </small>
      {onCompare && !b1 && (
        <button
          className="compare-btn"
          disabled={comparing}
          onClick={onCompare}
        >
          {comparing ? (
            <RefreshCw size={13} className="spin" />
          ) : (
            <TriangleAlert size={13} />
          )}
          What would a current-count app do?
          <ArrowRight size={13} />
        </button>
      )}
      {b1 && (
        <div className="baseline-line">
          <b>B1 · current counts only</b> → returns at <b>{b1.name}</b> (
          {b1.docks} open docks now)
          {b1.id === route.dropoff.id
            ? " — same choice as this plan."
            : ` — ignores the ${pct(
                pDock(
                  stations.find((s) => s.id === b1.id),
                  b1.horizon_minutes,
                ) ?? 1,
              )} forecast.`}
        </div>
      )}
    </section>
  );
}
