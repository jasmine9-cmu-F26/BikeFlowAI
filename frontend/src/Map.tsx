import { useEffect, useMemo } from "react";
import {
  MapContainer,
  TileLayer,
  Circle,
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
// The stations the planner may choose from at one end of the trip: usable for
// that phase, fresh, within the walking limit, nearest three (ties by id).
export function tripCandidates(
  stations: Station[],
  point: Point,
  phase: "pickup" | "return",
  limit: number,
  ageLimit: number,
) {
  return stations
    .filter((s) => s[phase] && s.data_age_seconds <= ageLimit)
    .map((s) => ({ s, walk: walkMinutes(point, s) }))
    .filter((c) => c.walk <= limit + 1e-9)
    .sort((x, y) => x.walk - y.walk || x.s.id.localeCompare(y.s.id))
    .slice(0, 3)
    .map((c) => c.s);
}
export function stationRisk(s: Station, layer: MapLayer, ageLimit: number) {
  const usable = layer === "bike" ? s.pickup : s.return;
  if (!usable || s.data_age_seconds > ageLimit) return "off";
  if ((layer === "bike" ? s.bikes : s.docks) === 0) return "empty";
  const f = s.forecast?.[RISK_HORIZON];
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
// Your start / destination. On a station it is a hollow frame around that
// station's dot, so the station keeps showing its availability color.
const endpointIcon = (kind: "start" | "end", framed: boolean) => {
  const size = framed ? 24 : 14;
  return divIcon({
    className: `trip-endpoint endpoint-${kind}${framed ? " framed" : ""}`,
    html: "",
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  });
};
// Built once: react-leaflet calls setIcon whenever the icon object changes.
const ICONS = {
  start: endpointIcon("start", false),
  startFramed: endpointIcon("start", true),
  end: endpointIcon("end", false),
  endFramed: endpointIcon("end", true),
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
type Props = {
  layer?: MapLayer;
  ageLimit: number;
  // The walking limit the shown plan used; draws the candidate range.
  walkLimit?: number;
  stations: Station[];
  route: Route | null;
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
  useEffect(() => {
    if (route) {
      // Frame the whole trip, endpoints included, clear of the top chips and the legend.
      const ends = [origin, destination].map((v) =>
        typeof v === "string" ? stations.find((s) => s.id === v) : v,
      );
      const points = [route.pickup, route.dropoff, ...ends].filter(
        Boolean,
      ) as Point[];
      map.fitBounds(
        points.map((s) => [s.lat, s.lon]) as LatLngBoundsExpression,
        {
          paddingTopLeft: [70, 100],
          paddingBottomRight: [70, 140],
          maxZoom: 15,
        },
      );
    } else if (stations.length)
      map.fitBounds(
        stations.map((s) => [s.lat, s.lon]) as LatLngBoundsExpression,
        { padding: [35, 35], maxZoom: 13 },
      );
  }, [route, stations, origin, destination, map]);
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
  // With a plan on screen, outline what the planner could choose from and fade the rest.
  const candidates = new Set<string>();
  if (route && props.walkLimit !== undefined) {
    const ends: [Point | undefined, "pickup" | "return"][] = [
      [route.pickup ? a : undefined, "pickup"],
      [b, "return"],
    ];
    for (const [point, phase] of ends)
      if (point)
        for (const s of tripCandidates(
          stations,
          point,
          phase,
          props.walkLimit,
          props.ageLimit,
        ))
          candidates.add(s.id);
  }
  const range = (props.walkLimit ?? 0) * 60 * WALK_SPEED;
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
      {route && props.walkLimit !== undefined && (
        <>
          {route.pickup && a && (
            <Circle
              interactive={false}
              center={[a.lat, a.lon]}
              radius={range}
              pathOptions={{
                color: COLORS.origin,
                weight: 1.5,
                dashArray: "4 6",
                fillColor: COLORS.origin,
                fillOpacity: 0.05,
              }}
            />
          )}
          {b && (
            <Circle
              interactive={false}
              center={[b.lat, b.lon]}
              radius={range}
              pathOptions={{
                color: COLORS.destination,
                weight: 1.5,
                dashArray: "4 6",
                fillColor: COLORS.destination,
                fillOpacity: 0.06,
              }}
            />
          )}
        </>
      )}
      {stations
        .filter((s) => s.id !== pickupId && s.id !== returnId)
        .map((s) => {
          const candidate = candidates.has(s.id);
          const faded = route && !candidate;
          return (
            <CircleMarker
              key={s.id}
              center={[s.lat, s.lon]}
              radius={candidate ? 8 : faded ? 6 : 7}
              bubblingMouseEvents={false}
              pathOptions={{
                color: candidate ? COLORS.chosen : "#fff",
                weight: candidate ? 3 : faded ? 1.5 : 2,
                opacity: faded ? 0.7 : 1,
                fillColor: COLORS[stationRisk(s, layer, props.ageLimit)],
                fillOpacity: faded ? 0.35 : 1,
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
          icon={isStation(a) ? ICONS.startFramed : ICONS.start}
        />
      )}
      {b && !endAtReturn && (
        <Marker
          interactive={false}
          position={[b.lat, b.lon]}
          zIndexOffset={500}
          icon={isStation(b) ? ICONS.endFramed : ICONS.end}
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
