import { BrainCircuit, Footprints, Info } from "lucide-react";
import type { Plan, Route } from "./api";

export const WALK_CHOICES = [5, 10, 15];
const RISKY = 0.8;
const pct = (p: number) =>
  Math.min(Math.round(p * 100), p < 1 ? 99 : 100) + "%";
const weakest = (r: Route) =>
  Math.min(r.pickup?.probability ?? 1, r.dropoff.probability);

/** The plan is worth re-checking with a longer walk: nothing found, nothing to fall back on, or a risky end. */
export function needsWiderWalk(plan: Plan) {
  if (plan.status === "no_plan" || !plan.primary) return true;
  return plan.backups.length === 0 || weakest(plan.primary) < RISKY;
}

/** Only offer the longer walk when it clearly helps the rider. */
export function widerIsBetter(current: Plan, wider: Plan) {
  if (wider.status !== "ok" || !wider.primary) return false;
  if (current.status !== "ok" || !current.primary) return true;
  return (
    weakest(wider.primary) - weakest(current.primary) >= 0.05 ||
    (current.backups.length === 0 && wider.backups.length > 0)
  );
}

export function nextWalk(walk: number) {
  return WALK_CHOICES.find((w) => w > walk) ?? null;
}

/** What walking further buys, in one word for the walking switch. */
export function widerReason(current: Plan, wider: Plan) {
  const a = current.status === "ok" ? current.primary : null;
  if (!a) return "possible" as const;
  return weakest(wider.primary!) - weakest(a) >= 0.05
    ? ("safer" as const)
    : ("backup" as const);
}

/** The concrete trade-off of the longer walk against the current plan. */
export function widerRows(current: Plan, wider: Plan) {
  const a = current.status === "ok" ? current.primary : null;
  const b = wider.primary!;
  const extra = (r: Route) =>
    (r.pickup?.walk_minutes ?? 0) + r.dropoff.walk_minutes;
  const rows: string[] = [];
  if (b.pickup && (!a?.pickup || a.pickup.id !== b.pickup.id))
    rows.push(
      `Pick up at ${b.pickup.name} · ${pct(b.pickup.probability)} bike` +
        (a?.pickup ? ` (now ${pct(a.pickup.probability)})` : ""),
    );
  if (!a || a.dropoff.id !== b.dropoff.id)
    rows.push(
      `Return at ${b.dropoff.name} · ${pct(b.dropoff.probability)} dock` +
        (a ? ` (now ${pct(a.dropoff.probability)})` : ""),
    );
  if (wider.backups.length > (a ? current.backups.length : 0))
    rows.push(
      `${wider.backups.length} alternative${wider.backups.length > 1 ? "s" : ""} instead of ${a ? current.backups.length : 0}`,
    );
  rows.push(
    `${extra(b).toFixed(1)} min total walking` +
      (a ? ` (now ${extra(a).toFixed(1)})` : ""),
  );
  return rows;
}

const REASON_TAG = {
  possible: "makes it possible",
  safer: "safer",
  backup: "adds a backup",
};

/**
 * The walking limit, set on the result rather than in the form: each choice
 * replans in place, the longer walk is tagged when it clearly helps, and the
 * rider can always switch back.
 */
export function WalkChoice({
  walk,
  current,
  wider,
  onChange,
}: {
  walk: number;
  current: Plan;
  wider: { walk: number; plan: Plan } | null;
  onChange: (walk: number) => void;
}) {
  const reason = wider ? widerReason(current, wider.plan) : null;
  return (
    <section className="walk-choice" aria-label="Walking limit">
      <div className="walk-choice-row">
        <span className="walk-choice-label">
          <Footprints size={13} /> Walk at each end
        </span>
        <div className="walk-segments" role="radiogroup" aria-label="Walk up to">
          {WALK_CHOICES.map((n) => (
            <button
              key={n}
              role="radio"
              aria-checked={n === walk}
              className={
                (n === walk ? "selected" : "") +
                (wider?.walk === n ? " suggested" : "")
              }
              onClick={() => onChange(n)}
            >
              ≤ {n} min
              {wider?.walk === n && reason && <small>{REASON_TAG[reason]}</small>}
            </button>
          ))}
        </div>
      </div>
      {wider && (
        <p className="walk-choice-hint">
          <strong>{wider.walk} min:</strong>{" "}
          {widerRows(current, wider.plan).join(" · ")}
        </p>
      )}
    </section>
  );
}

/** Says plainly whether the RL policy made this decision, and why not if it did not. */
export function MethodNotice({ plan, walk }: { plan: Plan; walk: number }) {
  if (plan.requested_method !== "RL" || plan.status !== "ok") return null;
  if (plan.actual_method.startsWith("RL")) {
    return (
      <div className="method-notice rl">
        <BrainCircuit size={14} />
        <span>
          RL policy chose the{" "}
          {plan.actual_method === "RL_wait+B3_provisional" ? "wait" : "pickup"}{" "}
          for your {walk}-min walking limit. One policy adapts to 5, 10 or 15
          min.
        </span>
      </div>
    );
  }
  const reason = plan.warnings.find((w) => w.startsWith("RL unavailable"));
  return (
    <div className="method-notice fallback">
      <Info size={14} />
      <span>
        Planned with {plan.actual_method} instead of RL.
        {reason ? " " + reason.replace(/^RL unavailable; using \w+: /, "") : ""}
      </span>
    </div>
  );
}
