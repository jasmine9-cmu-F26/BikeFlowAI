import { useEffect, useMemo } from "react";
import {
  MapContainer,
  TileLayer,
  CircleMarker,
  Marker,
  Polyline,
  useMap,
  useMapEvents,
} from "react-leaflet";
import { divIcon } from "leaflet";
import type { LatLngBoundsExpression } from "leaflet";
import type { Endpoint, Route, Station, Point } from "./api";
export type MapLayer = "bike" | "dock";
// Stations are colored by what matters for the chosen trip end: bikes for
// pickup, open docks for return, using the calibrated +30 min forecast.
export const RISK_HORIZON = 30;
export const RISK_THRESHOLD = 0.8;
export const COLORS = {
  ok: "#538b78",
  risk: "#d9b14e",
  // Red, not orange: orange marks the destination everywhere in the app.
  empty: "#c4513f",
  off: "#aaa",
  chosen: "#174e40",
  origin: "#174e40",
  destination: "#cb8253",
};
// Same walking model as backend/core.py `candidates`: straight line at 1.3 m/s.
export const WALK_SPEED = 1.3;
export function walkMinutes(a: Point, b: Point) {
  const r = Math.PI / 180,
    lat1 = a.lat * r,
    lat2 = b.lat * r;
  const v =
    Math.sin((lat2 - lat1) / 2) ** 2 +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin(((b.lon - a.lon) * r) / 2) ** 2;
  return (6371000 * 2 * Math.asin(Math.sqrt(Math.min(1, v)))) / WALK_SPEED / 60;
}
// The forecaster publishes +10 … +60 min; an arrival in between reads the nearest.
function forecastAt(s: Station, horizon: number) {
  const f = s.forecast ?? {};
  if (f[horizon]) return f[horizon];
  const keys = Object.keys(f).map(Number);
  if (!keys.length) return undefined;
  const near = keys.reduce((x, y) =>
    Math.abs(y - horizon) < Math.abs(x - horizon) ? y : x,
  );
  return f[near];
}
export function stationRisk(
  s: Station,
  layer: MapLayer,
  ageLimit: number,
  horizon = RISK_HORIZON,
) {
  const usable = layer === "bike" ? s.pickup : s.return;
  if (!usable || s.data_age_seconds > ageLimit) return "off";
  if ((layer === "bike" ? s.bikes : s.docks) === 0) return "empty";
  const f = forecastAt(s, horizon);
  const p = f ? (layer === "bike" ? f.p_bike : f.p_dock) : null;
  return p !== null && p !== undefined && p < RISK_THRESHOLD ? "risk" : "ok";
}
// Recommended stations: a plain dot (pickup) or square (return), as in the
// form, with a text tag that says what to do there and what is there now.
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;
export function pinLabel(
  kind: "pickup" | "return",
  s: Station,
  atEnd: boolean,
  waitMinutes = 0,
) {
  if (kind === "return")
    return `Return${atEnd ? " at destination" : ""} · ${plural(s.docks, "dock")}`;
  // A plan that waits at an empty dock must not read like "pick up · 0 bikes".
  const wait = Math.round(waitMinutes);
  return wait > 0
    ? `Wait ${wait} min, then pick up${atEnd ? " at start" : ""} · ${plural(s.bikes, "bike")} now`
    : `Pick up${atEnd ? " at start" : ""} · ${plural(s.bikes, "bike")}`;
}
const pinIcon = (kind: "pickup" | "return", label: string) =>
  divIcon({
    className: `trip-pin pin-${kind}`,
    html: `<span class="pin-label">${label}</span>`,
    iconSize: [14, 14],
    iconAnchor: [7, 7],
  });
// Your start / destination: a text tag. On a station the tag sits on that
// station's own dot, so it keeps showing its availability color; a free map
// point also gets a small hollow mark.
const endpointIcon = (kind: "start" | "end", onStation: boolean) =>
  divIcon({
    className: `trip-endpoint endpoint-${kind}${onStation ? " on-station" : ""}`,
    html: `<span class="pin-label endpoint-label">${kind === "start" ? "Start" : "Destination"}</span>`,
    iconSize: [14, 14],
    iconAnchor: [7, 7],
  });
// Built once: react-leaflet calls setIcon whenever the icon object changes.
const ICONS = {
  start: endpointIcon("start", false),
  startOnStation: endpointIcon("start", true),
  end: endpointIcon("end", false),
  endOnStation: endpointIcon("end", true),
};
const samePlace = (a: Point, b: Point) =>
  Math.abs(a.lat - b.lat) < 1e-6 && Math.abs(a.lon - b.lon) < 1e-6;
function TripPin({
  kind,
  s,
  atEnd,
  waitMinutes,
  onClick,
}: {
  kind: "pickup" | "return";
  s: Station;
  atEnd: boolean;
  waitMinutes?: number;
  onClick: () => void;
}) {
  const label = pinLabel(kind, s, atEnd, waitMinutes);
  const icon = useMemo(() => pinIcon(kind, label), [kind, label]);
  return (
    <Marker
      position={[s.lat, s.lon]}
      icon={icon}
      zIndexOffset={1000}
      bubblingMouseEvents={false}
      eventHandlers={{ click: onClick }}
    />
  );
}
// Every station of the given routes plus the trip's endpoints, once each.
export function tripBounds(routes: Route[], ends: (Point | undefined)[]) {
  const seen = new Map<string, [number, number]>();
  for (const p of [...routes.flatMap((r) => [r.pickup, r.dropoff]), ...ends])
    if (p) seen.set(`${p.lat},${p.lon}`, [p.lat, p.lon]);
  return [...seen.values()];
}
// What the view must show: the routes, the endpoints, and every station within
// walking reach of either end (the pickup end only when a route picks up), so
// no station the trip colors ends up off screen or under the legend.
export function framePoints(
  routes: Route[],
  [start, end]: (Point | undefined)[],
  stations: Station[],
  reach?: number,
) {
  const pickup = routes.some((r) => r.pickup);
  const near = (p: Point | undefined, s: Station) =>
    !!p && reach !== undefined && walkMinutes(p, s) <= reach;
  const nearby = stations.filter(
    (s) => (pickup && near(start, s)) || near(end, s),
  );
  return tripBounds(routes, [start, end, ...nearby]);
}
type Props = {
  layer?: MapLayer;
  ageLimit: number;
  // The walking limit the shown plan used; stations beyond it are greyed.
  walkLimit?: number;
  stations: Station[];
  route: Route | null;
  // Routes the view should frame; defaults to the shown route. Framing all of
  // a plan's options keeps the map still while one of them is previewed.
  frame?: Route[];
  origin: Endpoint;
  destination: Endpoint;
  selecting: "origin" | "destination" | null;
  onPick: (p: Point) => void;
  onStation: (s: Station) => void;
  // A click on the map itself (not a station, not while picking): closes details.
  onBackground?: () => void;
};
function Interaction({
  stations,
  route,
  origin,
  destination,
  frame,
  walkLimit,
  selecting,
  onPick,
  onBackground,
}: Props) {
  const map = useMap();
  useMapEvents({
    click: (e) => {
      if (selecting) onPick({ lat: e.latlng.lat, lon: e.latlng.lng });
      else onBackground?.();
    },
  });
  // Frame the whole trip, endpoints included, clear of the top chips and the
  // legend. Keyed on the points themselves, so a re-render that shows another
  // route inside the same frame leaves the view alone.
  const ends = [origin, destination].map((v) =>
    typeof v === "string" ? stations.find((s) => s.id === v) : v,
  );
  const routes = frame?.length ? frame : route ? [route] : [];
  const points = routes.length
    ? framePoints(routes, ends, stations, walkLimit)
    : [];
  const key = JSON.stringify(points);
  useEffect(() => {
    if (points.length)
      map.fitBounds(points as LatLngBoundsExpression, {
        paddingTopLeft: [70, 100],
        paddingBottomRight: [70, 140],
        maxZoom: 15,
      });
    else if (stations.length)
      map.fitBounds(
        stations.map((s) => [s.lat, s.lon]) as LatLngBoundsExpression,
        { padding: [35, 35], maxZoom: 13 },
      );
  }, [key, stations.length, map]);
  return null;
}
export default function RideMap(props: Props) {
  const { stations, route, origin, destination, selecting, onStation } = props;
  const layer = props.layer ?? "bike";
  const locate = (v: Endpoint) =>
    typeof v === "string" ? stations.find((s) => s.id === v) : v;
  const a = locate(origin),
    b = locate(destination);
  const click = (s: Station) => () => {
    if (selecting) props.onPick({ lat: s.lat, lon: s.lon });
    else onStation(s);
  };
  const pickupId = route?.pickup?.id,
    returnId = route?.dropoff.id;
  const pickupStation = stations.find((s) => s.id === pickupId),
    returnStation = stations.find((s) => s.id === returnId);
  const startAtPickup = !!(a && pickupStation && samePlace(a, pickupStation)),
    endAtReturn = !!(b && returnStation && samePlace(b, returnStation));
  const isStation = (p: Point) => stations.some((s) => samePlace(s, p));
  // With a plan on screen, color each station for the end of the trip it can
  // serve, at the time the rider would get there: bikes within walking reach of
  // the start, open docks within reach of the destination. The rest are greyed.
  const reach = props.walkLimit;
  const tripRisk = (s: Station) => {
    if (!route || reach === undefined)
      return stationRisk(s, layer, props.ageLimit);
    if (route.pickup && a && walkMinutes(a, s) <= reach)
      return stationRisk(s, "bike", props.ageLimit, route.pickup.horizon_minutes);
    if (b && walkMinutes(b, s) <= reach)
      return stationRisk(s, "dock", props.ageLimit, route.dropoff.horizon_minutes);
    return null;
  };
  return (
    <MapContainer
      center={[41.89, -87.65]}
      zoom={12}
      className={selecting ? "ride-map picking" : "ride-map"}
      scrollWheelZoom
    >
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      <Interaction {...props} />
      {stations
        .filter((s) => s.id !== pickupId && s.id !== returnId)
        .map((s) => {
          const risk = tripRisk(s);
          return (
            <CircleMarker
              key={s.id}
              center={[s.lat, s.lon]}
              radius={risk ? 7 : 5}
              bubblingMouseEvents={false}
              pathOptions={{
                color: "#fff",
                weight: risk ? 2 : 1,
                fillColor: COLORS[risk ?? "off"],
                fillOpacity: risk ? 1 : 0.55,
              }}
              eventHandlers={{ click: click(s) }}
            />
          );
        })}
      {route && (
        <>
          {route.pickup && a && (
            <Polyline
              interactive={false}
              positions={[
                [a.lat, a.lon],
                [route.pickup.lat, route.pickup.lon],
              ]}
              pathOptions={{ color: "#538b78", dashArray: "5 7", weight: 3 }}
            />
          )}
          {route.pickup && (
            <Polyline
              interactive={false}
              positions={[
                [route.pickup.lat, route.pickup.lon],
                [route.dropoff.lat, route.dropoff.lon],
              ]}
              pathOptions={{ color: "#174e40", weight: 5, opacity: 0.85 }}
            />
          )}
          {!route.pickup && a && (
            <Polyline
              interactive={false}
              positions={[
                [a.lat, a.lon],
                [route.dropoff.lat, route.dropoff.lon],
              ]}
              pathOptions={{ color: "#174e40", weight: 5, opacity: 0.85 }}
            />
          )}
          {b && (
            <Polyline
              interactive={false}
              positions={[
                [route.dropoff.lat, route.dropoff.lon],
                [b.lat, b.lon],
              ]}
              pathOptions={{ color: "#538b78", dashArray: "5 7", weight: 3 }}
            />
          )}
        </>
      )}
      {a && !startAtPickup && (
        <Marker
          interactive={false}
          position={[a.lat, a.lon]}
          zIndexOffset={500}
          icon={isStation(a) ? ICONS.startOnStation : ICONS.start}
        />
      )}
      {b && !endAtReturn && (
        <Marker
          interactive={false}
          position={[b.lat, b.lon]}
          zIndexOffset={500}
          icon={isStation(b) ? ICONS.endOnStation : ICONS.end}
        />
      )}
      {pickupStation && (
        <TripPin
          kind="pickup"
          s={pickupStation}
          atEnd={startAtPickup}
          waitMinutes={route?.wait_minutes}
          onClick={click(pickupStation)}
        />
      )}
      {returnStation && (
        <TripPin
          kind="return"
          s={returnStation}
          atEnd={endAtReturn}
          onClick={click(returnStation)}
        />
      )}
    </MapContainer>
  );
}
