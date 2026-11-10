import { useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  ArrowUpDown,
  Bike,
  Check,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Footprints,
  Info,
  Layers,
  LocateFixed,
  MapPin,
  RefreshCw,
  ShieldCheck,
  TriangleAlert,
  X,
} from "lucide-react";
import RideMap from "./Map";
import {
  api,
  clock,
  historical,
  type Endpoint,
  type Health,
  type Method,
  type Mode,
  type Plan,
  type Request,
  type Route,
  type Snapshot,
  type Station,
} from "./api";

const HIST = "2021-07-20T08:06";
const pct = (p: number | null) =>
  p === null ? "Unavailable" : Math.round(p * 100) + "%";
const labels: Record<Mode, string> = {
  fixture: "Example",
  replay: "Replay",
  live: "Live",
};
const methods: Record<Method, string> = {
  B1: "Current availability",
  B2: "Historical patterns",
  B3: "Forecast + greedy",
  RL: "RL policy (with fallback)",
};

function Journey({ route }: { route: Route }) {
  return (
    <div className="journey">
      {route.wait_minutes > 0 && (
        <div className="journey-row">
          <span className="step-icon">
            <Clock3 size={17} />
          </span>
          <div>
            <strong>Wait {route.wait_minutes} min before leaving</strong>
            <small>Availability improves at a later horizon</small>
          </div>
        </div>
      )}
      {route.pickup && (
        <>
          <div className="journey-row">
            <span className="step-icon">
              <Footprints size={17} />
            </span>
            <div>
              <strong>Walk {route.pickup.walk_minutes} min</strong>
              <small>To {route.pickup.name}</small>
            </div>
          </div>
          <div className="journey-row station-step">
            <span className="step-dot" />
            <div>
              <div className="step-title">
                <strong>Pick up a bike</strong>
                <time>{clock(route.pickup.estimated_arrival_time)}</time>
              </div>
              <small>{route.pickup.bikes} bikes in latest snapshot</small>
              <span className="probability">
                <Check size={13} />
                {pct(route.pickup.probability)} estimated bike availability
              </span>
              <small>
                Forecast for {clock(route.pickup.effective_prediction_time)} ·{" "}
                {route.pickup.horizon_minutes}m horizon
              </small>
            </div>
          </div>
        </>
      )}
      <div className="journey-row">
        <span className="step-icon">
          <Bike size={18} />
        </span>
        <div>
          <strong>Ride about {route.ride_minutes} min</strong>
          <small>
            {route.ride_method === "training_median"
              ? "Based on historical rides"
              : "Estimated from straight-line distance"}
          </small>
        </div>
      </div>
      <div className="journey-row station-step">
        <span className="step-dot destination-dot" />
        <div>
          <div className="step-title">
            <strong>Return your bike</strong>
            <time>{clock(route.dropoff.estimated_arrival_time)}</time>
          </div>
          <small>{route.dropoff.name}</small>
          <span className="probability">
            <Check size={13} />
            {pct(route.dropoff.probability)} estimated dock availability
          </span>
          <small>
            Forecast for {clock(route.dropoff.effective_prediction_time)} ·{" "}
            {route.dropoff.horizon_minutes}m horizon
          </small>
        </div>
      </div>
      <div className="journey-row">
        <span className="step-icon">
          <Footprints size={17} />
        </span>
        <div>
          <strong>Walk {route.dropoff.walk_minutes} min</strong>
          <small>Arrive at your destination</small>
        </div>
      </div>
    </div>
  );
}

function RouteDetails({
  route,
  plan,
  loading,
  label = "ESTIMATED JOURNEY",
  onReplan,
}: {
  route: Route;
  plan: Plan;
  loading: boolean;
  label?: string;
  onReplan: (phase: "pickup" | "return") => void;
}) {
  return (
    <>
      <div className="route-summary">
        <div>
          <span className="eyebrow">{label}</span>
          <strong>
            {route.total_minutes}
            <small> min</small>
          </strong>
        </div>
        <span className="method-badge">
          {plan.mode === "fixture" ? "Example · " : ""}
          {plan.actual_method}
        </span>
      </div>
      <Journey route={route} />
      <details className="failure-controls">
        <summary>Attempt failed? Find the next option</summary>
        <p>
          For replay, this advances the decision clock to the attempted arrival.
          It is a hypothetical failure, not a revealed outcome.
        </p>
        {route.pickup && (
          <button disabled={loading} onClick={() => onReplan("pickup")}>
            No bike at pickup <ChevronRight size={14} />
          </button>
        )}
        <button disabled={loading} onClick={() => onReplan("return")}>
          No dock at return <ChevronRight size={14} />
        </button>
      </details>
    </>
  );
}

export default function App() {
  const [mode, setMode] = useState<Mode>("fixture");
  const [method, setMethod] = useState<Method>("B3");
  const [origin, setOrigin] = useState<Endpoint>("chicago:14");
  const [destination, setDestination] = useState<Endpoint>("chicago:21");
  const [when, setWhen] = useState(HIST);
  const [offset, setOffset] = useState(0);
  const [walk, setWalk] = useState(5);
  const [scenario, setScenario] = useState("normal");
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [registry, setRegistry] = useState<Station[]>([]);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadingMap, setLoadingMap] = useState(false);
  const [selected, setSelected] = useState<Station | null>(null);
  const [selecting, setSelecting] = useState<"origin" | "destination" | null>(
    null,
  );
  const [tab, setTab] = useState<"recommended" | "alternatives">("recommended");
  const [shownRoute, setShownRoute] = useState<Route | null>(null);
  const [selectedAlternativeIndex, setSelectedAlternativeIndex] = useState<
    number | null
  >(null);
  const [reload, setReload] = useState(0);
  const [failed, setFailed] = useState<string[]>([]);
  const [routeOrigin, setRouteOrigin] = useState<Endpoint>(origin);
  const [revealed, setRevealed] = useState<{
    outcomes: { phase: string; observed: number | null; status: string }[];
    warning: string;
  } | null>(null);
  const requestRef = useRef<AbortController | null>(null);
  const [didPlan, setDidPlan] = useState(false);
  const initialModeSelected = useRef(false);
  useEffect(() => {
    api<Health>("/health")
      .then((status) => {
        setHealth(status);
        if (!initialModeSelected.current) {
          initialModeSelected.current = true;
          if (status.status === "ready" && status.replay_data_ready) {
            setMode("replay");
            setWhen(
              (status.default_replay_time || "2021-07-20T08:06").slice(0, 16),
            );
          }
        }
      })
      .catch(() => {});
    api<{ stations: Station[] }>("/registry")
      .then((d) => setRegistry(d.stations))
      .catch(() => {});
  }, [reload]);
  useEffect(() => {
    const ctrl = new AbortController();
    setLoadingMap(true);
    setError("");
    setSnap(null);
    setSelected(null);
    const query = new URLSearchParams({ mode, scenario });
    if (mode !== "live") query.set("historical_timestamp", historical(when));
    api<Snapshot>("/stations?" + query, undefined, ctrl.signal)
      .then(setSnap)
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      })
      .finally(() => {
        if (!ctrl.signal.aborted) setLoadingMap(false);
      });
    return () => ctrl.abort();
  }, [mode, when, scenario, reload]);
  useEffect(() => {
    requestRef.current?.abort();
    setLoading(false);
    setPlan(null);
    setShownRoute(null);
    setSelectedAlternativeIndex(null);
    setFailed([]);
    setDidPlan(false);
    setRouteOrigin(origin);
    setRevealed(null);
  }, [mode, when, offset, walk, method, origin, destination, scenario, reload]);
  useEffect(() => setRevealed(null), [shownRoute]);
  useEffect(() => () => requestRef.current?.abort(), []);
  const stations = snap?.stations.length ? snap.stations : registry;
  const body = (): Request => {
    const now = mode === "live" ? new Date() : new Date(historical(when));
    return {
      origin,
      destination,
      mode,
      method,
      scenario,
      walk_limit_minutes: walk,
      departure_time: new Date(now.getTime() + offset * 60000).toISOString(),
      ...(mode === "live" ? {} : { historical_timestamp: historical(when) }),
    };
  };
  async function submit() {
    requestRef.current?.abort();
    const ctrl = new AbortController();
    requestRef.current = ctrl;
    setLoading(true);
    setError("");
    setDidPlan(true);
    setFailed([]);
    setRevealed(null);
    setRouteOrigin(origin);
    try {
      const p = await api<Plan>("/plan", body(), ctrl.signal);
      setPlan(p);
      setShownRoute(p.primary);
      setSelectedAlternativeIndex(null);
      setTab("recommended");
    } catch (e) {
      if (!ctrl.signal.aborted) {
        setError((e as Error).message);
        setPlan(null);
        setShownRoute(null);
        setSelectedAlternativeIndex(null);
      }
    } finally {
      if (!ctrl.signal.aborted) setLoading(false);
    }
  }
  async function replan(phase: "pickup" | "return") {
    if (!shownRoute) return;
    const station = phase === "pickup" ? shownRoute.pickup : shownRoute.dropoff;
    if (!station) return;
    const failedIds = [...failed, station.id];
    // Explicit hypothetical failure clock. A future snapshot is read only after the
    // user confirms the attempt failed, never while producing the initial plan.
    const nextClock = new Date(station.estimated_arrival_time);
    const ctrl = new AbortController();
    requestRef.current?.abort();
    requestRef.current = ctrl;
    setLoading(true);
    setError("");
    const request = {
      ...body(),
      origin: station.id,
      ...(mode === "live"
        ? { departure_time: new Date().toISOString() }
        : {
            departure_time: nextClock.toISOString(),
            historical_timestamp: nextClock.toISOString(),
          }),
      failed_station_ids: failedIds,
      phase,
    };
    try {
      const p = await api<Plan>("/replan", request, ctrl.signal);
      setPlan(p);
      setShownRoute(p.primary);
      setSelectedAlternativeIndex(null);
      setRouteOrigin(station.id);
      setFailed(failedIds);
      setTab("recommended");
      const params = new URLSearchParams({
        mode,
        scenario,
        historical_timestamp: request.departure_time,
      });
      api<Snapshot>("/stations?" + params, undefined, ctrl.signal)
        .then(setSnap)
        .catch(() => {});
    } catch (e) {
      if (!ctrl.signal.aborted) setError((e as Error).message);
    } finally {
      if (!ctrl.signal.aborted) setLoading(false);
    }
  }
  async function reveal() {
    if (!plan || !shownRoute) return;
    const attempts = [
      ...(shownRoute.pickup
        ? [
            {
              station_id: shownRoute.pickup.id,
              horizon_minutes: shownRoute.pickup.horizon_minutes,
              phase: "pickup",
            },
          ]
        : []),
      {
        station_id: shownRoute.dropoff.id,
        horizon_minutes: shownRoute.dropoff.horizon_minutes,
        phase: "return",
      },
    ];
    try {
      setError("");
      setRevealed(
        await api("/replay/reveal", {
          historical_timestamp: plan.decision_time,
          attempts,
        }),
      );
    } catch (e) {
      setError((e as Error).message);
    }
  }
  function endpointInput(
    field: "origin" | "destination",
    value: Endpoint,
    set: (v: Endpoint) => void,
  ) {
    return (
      <div className="endpoint-field">
        <label htmlFor={field}>{field === "origin" ? "From" : "To"}</label>
        <div className="endpoint-control">
          <span
            className={"endpoint-dot " + (field === "destination" ? "end" : "")}
          />
          <select
            id={field}
            value={typeof value === "string" ? value : "custom"}
            onChange={(e) => set(e.target.value)}
          >
            {typeof value !== "string" && (
              <option value="custom">
                Map location · {value.lat.toFixed(3)}, {value.lon.toFixed(3)}
              </option>
            )}
            {stations.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
          <button
            type="button"
            className={selecting === field ? "icon-btn active" : "icon-btn"}
            aria-label={`Choose ${field} on map`}
            title="Choose on map"
            onClick={() => setSelecting(selecting === field ? null : field)}
          >
            <LocateFixed size={16} />
          </button>
        </div>
      </div>
    );
  }
  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="/" aria-label="BikeFlow home">
          <span className="brand-symbol">
            <Bike size={24} />
          </span>
          BikeFlow<span className="ai-tag">AI</span>
        </a>
        <nav>
          <span className="nav-active">Trip planner</span>
          <a
            href="https://github.com/jasmine9-cmu-F26/BikeFlowAI"
            target="_blank"
            rel="noreferrer"
          >
            About the project <ArrowRight size={13} />
          </a>
        </nav>
        <span className="city-label">
          <MapPin size={14} /> Chicago, IL
        </span>
      </header>
      <main className="workspace">
        <aside className="planner-panel">
          <div className="eyebrow">LESS GUESSWORK. MORE RIDING.</div>
          <h1>
            A better
            <br />
            way there<span>.</span>
          </h1>
          <p className="intro">
            Find a bike now.
            <br />A place to dock when you arrive.
          </p>
          <div className="mode-switch" aria-label="Data mode">
            {(["fixture", "replay", "live"] as Mode[]).map((m) => (
              <button
                key={m}
                className={mode === m ? "selected" : ""}
                onClick={() => {
                  initialModeSelected.current = true;
                  setMode(m);
                }}
              >
                {m === "live" && <span className="live-dot" />}
                {labels[m]}
              </button>
            ))}
          </div>
          <div className="mode-note">
            {mode === "fixture" ? (
              <>
                <Info size={14} /> Synthetic examples · not model results
              </>
            ) : mode === "replay" ? (
              <>
                <Clock3 size={14} /> Historical data · summer 2021
              </>
            ) : (
              <>
                <RefreshCw size={14} /> Current GBFS · experimental predictions
              </>
            )}
          </div>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              submit();
            }}
          >
            <div className="endpoints">
              {endpointInput("origin", origin, setOrigin)}
              <button
                className="swap"
                type="button"
                aria-label="Swap origin and destination"
                onClick={() => {
                  setOrigin(destination);
                  setDestination(origin);
                }}
              >
                <ArrowUpDown size={15} />
              </button>
              {endpointInput("destination", destination, setDestination)}
            </div>
            {mode !== "live" && (
              <label className="field-label">
                Replay clock <span>Chicago time</span>
                <input
                  type="datetime-local"
                  value={when}
                  min={
                    mode === "replay" &&
                    health?.data_source === "bundled_m3_tune"
                      ? "2021-07-12T01:00"
                      : "2021-05-03T00:00"
                  }
                  max="2021-07-25T23:59"
                  required
                  onChange={(e) => setWhen(e.target.value)}
                />
              </label>
            )}
            <div className="form-two">
              <label className="field-label">
                Departure
                <select
                  value={offset}
                  onChange={(e) => setOffset(+e.target.value)}
                >
                  <option value={0}>
                    {mode === "live" ? "Now" : "At replay clock"}
                  </option>
                  <option value={10}>In 10 minutes</option>
                  <option value={20}>In 20 minutes</option>
                </select>
              </label>
              <label className="field-label">
                Extra walking
                <select value={walk} onChange={(e) => setWalk(+e.target.value)}>
                  {[0, 5, 10, 15, 20].map((n) => (
                    <option key={n} value={n}>
                      {n} min max
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <label className="field-label">
              Planning method
              <select
                value={method}
                onChange={(e) => setMethod(e.target.value as Method)}
              >
                {Object.entries(methods).map(([k, v]) => (
                  <option key={k} value={k}>
                    {k} · {v}
                  </option>
                ))}
              </select>
            </label>
            <button
              className="primary-btn"
              disabled={loading || loadingMap || !stations.length}
              type="submit"
            >
              {loading ? (
                <>
                  <RefreshCw size={18} className="spin" />
                  Finding your way…
                </>
              ) : (
                <>
                  Find my ride <ArrowRight size={18} />
                </>
              )}
            </button>
          </form>
          <div className="walk-note">
            <Footprints size={16} />
            <span>
              Limit applies at each end. The 32-station area is sparse; try 10
              min for more alternatives.
            </span>
          </div>
          {mode === "fixture" && (
            <div className="demo-controls">
              <label className="field-label">
                Demo scenario
                <select
                  value={scenario}
                  onChange={(e) => setScenario(e.target.value)}
                >
                  <option value="normal">Morning commute</option>
                  <option value="model-missing">Missing model → B2</option>
                  <option value="stale">Stale station data</option>
                </select>
              </label>
            </div>
          )}
          <div className="panel-footer">
            <ShieldCheck size={16} />
            <span>
              Estimates, never a reservation.
              <br />
              Check station availability before riding.
            </span>
          </div>
        </aside>
        <section className="map-panel" aria-label="Chicago station map">
          <RideMap
            ageLimit={mode === "live" ? 300 : 900}
            stations={snap?.stations || []}
            route={shownRoute}
            origin={shownRoute ? routeOrigin : origin}
            destination={destination}
            selecting={selecting}
            onPick={(p) => {
              if (selecting === "origin") setOrigin(p);
              else setDestination(p);
              setSelecting(null);
            }}
            onStation={setSelected}
          />
          <div className="map-top">
            <span className="map-chip">
              <span className="live-dot" />
              {mode === "fixture"
                ? "EXAMPLE DATA"
                : mode === "replay"
                  ? "HISTORICAL REPLAY"
                  : "LIVE STATIONS"}
            </span>
            <button
              className="map-refresh"
              aria-label="Refresh station data"
              onClick={() => {
                setPlan(null);
                setShownRoute(null);
                setReload((r) => r + 1);
              }}
            >
              <RefreshCw size={16} className={loadingMap ? "spin" : ""} />
            </button>
          </div>
          {selecting && (
            <div className="select-toast">
              Click the map to set your {selecting}
              <button
                className="icon-btn"
                onClick={() => setSelecting(null)}
                aria-label="Cancel map selection"
              >
                <X size={16} />
              </button>
            </div>
          )}
          {mode === "fixture" && (
            <div className="example-watermark">
              EXAMPLE
              <br />
              <small>Synthetic station data</small>
            </div>
          )}
          {selected && (
            <div className="station-card">
              <div className="station-card-title">
                <span className="eyebrow">STATION FORECAST</span>
                <button
                  className="icon-btn"
                  aria-label="Close station details"
                  onClick={() => setSelected(null)}
                >
                  <X size={16} />
                </button>
              </div>
              <h3>{selected.name}</h3>
              <div className="counts">
                <span>
                  <Bike size={17} />
                  <b>{selected.bikes}</b> bikes
                </span>
                <span>
                  <Layers size={17} />
                  <b>{selected.docks}</b> docks
                </span>
              </div>
              <table>
                <thead>
                  <tr>
                    <th>Horizon</th>
                    <th>Bike</th>
                    <th>Dock</th>
                  </tr>
                </thead>
                <tbody>
                  {[10, 20, 30, 40, 50, 60].map((h) => (
                    <tr key={h}>
                      <td>+{h} min</td>
                      <td>{pct(selected.forecast[h]?.p_bike ?? null)}</td>
                      <td>{pct(selected.forecast[h]?.p_dock ?? null)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <small>
                Snapshot age: {selected.data_age_seconds}s · availability
                estimates
              </small>
            </div>
          )}
          <div className="map-bottom">
            <div className="map-legend">
              <span>
                <i />
                Station
              </span>
              <span>
                <i className="orange" />
                Empty
              </span>
              <span>
                <i className="dark" />
                Recommended
              </span>
            </div>
            <span className="route-note">
              Route lines are indicative · not turn-by-turn directions
            </span>
          </div>
        </section>
        <aside
          className="results-panel"
          aria-label="Trip results"
          aria-live="polite"
        >
          <div className="results-heading">
            <span className="eyebrow">YOUR NEXT RIDE</span>
            <span className="station-count">
              {snap?.stations.length || 32} stations
            </span>
          </div>
          <h2>
            {plan?.primary
              ? "A little planning.\nA smoother ride."
              : "Good rides start\nwith a plan."}
          </h2>
          {error && (
            <div className="error-box" role="alert">
              <TriangleAlert size={18} />
              <div>
                <strong>Let’s adjust that</strong>
                <p>{error}</p>
              </div>
            </div>
          )}
          {!plan && !loading && (
            <div className="empty-state">
              <div className="empty-illustration">
                <Bike size={48} strokeWidth={1.15} />
                <span className="illustration-path" />
                <MapPin size={26} strokeWidth={1.2} />
              </div>
              <h3>Your ride, one step ahead.</h3>
              <p>
                We look beyond today’s bike count to help you find a bike and an
                open dock at arrival.
              </p>
              <div className="how-row">
                <span>01</span>Choose where you’re going
              </div>
              <div className="how-row">
                <span>02</span>Compare expected availability
              </div>
              <div className="how-row">
                <span>03</span>Keep an alternative in reach
              </div>
            </div>
          )}
          {loading && (
            <div className="loading-state">
              <RefreshCw size={24} className="spin" />
              <p>Checking stations and arrival horizons…</p>
            </div>
          )}
          {plan && !loading && (
            <>
              <div className="result-tabs">
                <button
                  className={tab === "recommended" ? "active" : ""}
                  onClick={() => {
                    setTab("recommended");
                    setSelectedAlternativeIndex(null);
                    setShownRoute(plan.primary);
                  }}
                >
                  Recommended
                </button>
                <button
                  className={tab === "alternatives" ? "active" : ""}
                  onClick={() => {
                    setTab("alternatives");
                    setSelectedAlternativeIndex(null);
                    setShownRoute(null);
                  }}
                >
                  Alternatives <span>{plan.backups.length}</span>
                </button>
              </div>
              {plan.status === "no_plan" ? (
                <div className="no-plan">
                  <TriangleAlert size={30} />
                  <h3>No feasible ride yet</h3>
                  <p>{plan.no_plan_reason}</p>
                  <p>
                    Try another endpoint, a shorter departure offset, or a
                    larger walking limit.
                  </p>
                </div>
              ) : tab === "recommended" && shownRoute ? (
                <RouteDetails
                  route={shownRoute}
                  plan={plan}
                  loading={loading}
                  onReplan={replan}
                />
              ) : (
                <div className="alternatives">
                  {selectedAlternativeIndex !== null && shownRoute ? (
                    <>
                      <button
                        className="alternative-back"
                        onClick={() => {
                          setSelectedAlternativeIndex(null);
                          setShownRoute(null);
                        }}
                      >
                        <ChevronLeft size={15} /> Back to alternatives
                      </button>
                      <RouteDetails
                        route={shownRoute}
                        plan={plan}
                        loading={loading}
                        label={`ALTERNATIVE OPTION ${selectedAlternativeIndex + 2}`}
                        onReplan={replan}
                      />
                    </>
                  ) : (
                    <>
                      <p>
                        Other plans available at the initial decision time.
                        Replan after an actual failed attempt.
                      </p>
                      {plan.backups.map((r, i) => (
                        <button
                          className="alternative"
                          key={i}
                          onClick={() => {
                            setSelectedAlternativeIndex(i);
                            setShownRoute(r);
                          }}
                        >
                          <div>
                            <span className="eyebrow">
                              OPTION {i + 2} · {r.total_minutes} MIN
                            </span>
                            <strong>
                              {r.pickup?.name || "Continue riding"}
                            </strong>
                            <small>to {r.dropoff.name}</small>
                            <span>
                              {r.pickup
                                ? `${pct(r.pickup.probability)} bike · `
                                : ""}
                              {pct(r.dropoff.probability)} dock
                            </span>
                          </div>
                          <ArrowRight size={18} />
                        </button>
                      ))}
                      {!plan.backups.length && (
                        <p>No additional station pairs fit your limits.</p>
                      )}
                    </>
                  )}
                </div>
              )}
              {mode === "replay" &&
                shownRoute &&
                (tab === "recommended" ||
                  selectedAlternativeIndex !== null) && (
                  <div className="failure-controls">
                    <button onClick={reveal}>
                      Reveal historical outcomes <ChevronRight size={14} />
                    </button>
                    {revealed && (
                      <>
                        <p>
                          {revealed.outcomes
                            .map(
                              (o) =>
                                `${o.phase}: ${o.status}${o.observed === null ? "" : ` (${o.observed})`}`,
                            )
                            .join(" · ")}
                        </p>
                        <p>{revealed.warning}</p>
                      </>
                    )}
                  </div>
                )}
              <div className="warnings">
                {plan.warnings.map((w, i) => (
                  <div key={i}>
                    <Info size={14} />
                    <span>{w}</span>
                  </div>
                ))}
              </div>
              <details className="diagnostics">
                <summary>Plan details</summary>
                <dl>
                  <dt>Decision clock</dt>
                  <dd>{clock(plan.decision_time)} Chicago</dd>
                  <dt>Requested / used</dt>
                  <dd>
                    {plan.requested_method} / {plan.actual_method}
                  </dd>
                  <dt>Model</dt>
                  <dd>{plan.model_version || "No model loaded"}</dd>
                  <dt>Data age</dt>
                  <dd>{plan.data_age_seconds ?? "—"} seconds</dd>
                  <dt>API time</dt>
                  <dd>{plan.latency_ms} ms</dd>
                  <dt>Request</dt>
                  <dd>{plan.request_id}</dd>
                </dl>
              </details>
            </>
          )}
          {!didPlan &&
            snap?.warnings.map((w, i) => (
              <div className="initial-warning" key={i}>
                <Info size={14} />
                {w}
              </div>
            ))}
          <div className="service-status">
            <i className={health?.status === "ready" ? "ready" : ""} />
            {health
              ? `Model service ${health.status}`
              : "Connecting to local API…"}
            {health && !health.replay_data_ready && (
              <span>Replay data not prepared</span>
            )}
          </div>
        </aside>
      </main>
      <footer className="site-footer">
        <span>
          BIKEFLOW AI <b> / </b> DIVVY · CHICAGO
        </span>
        <details>
          <summary>Data sources &amp; important information</summary>
          <p>
            City of Chicago historical station data · Official Divvy trips and
            GBFS · OpenStreetMap contributors. Probabilities are estimates from
            summer 2021 models. Example mode uses synthetic data. Availability
            is not guaranteed.
          </p>
          <p>
            This site provides applications using data that has been modified
            for use from its original source, www.cityofchicago.org, the
            official website of the City of Chicago. The City of Chicago makes
            no claims as to the content, accuracy, timeliness, or completeness
            of any of the data provided at this site. The data provided at this
            site is subject to change at any time. It is understood that the
            data provided at this site is being used at one’s own risk.
          </p>
        </details>
        <span>Built for the ride ahead.</span>
      </footer>
    </div>
  );
}
