import { useEffect } from "react";
import {
  MapContainer,
  TileLayer,
  CircleMarker,
  Popup,
  Polyline,
  useMap,
  useMapEvents,
} from "react-leaflet";
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
  empty: "#db9157",
  off: "#aaa",
  chosen: "#174e40",
};
export function stationRisk(s: Station, layer: MapLayer, ageLimit: number) {
  const usable = layer === "bike" ? s.pickup : s.return;
  if (!usable || s.data_age_seconds > ageLimit) return "off";
  if ((layer === "bike" ? s.bikes : s.docks) === 0) return "empty";
  const f = s.forecast?.[RISK_HORIZON];
  const p = f ? (layer === "bike" ? f.p_bike : f.p_dock) : null;
  return p !== null && p !== undefined && p < RISK_THRESHOLD ? "risk" : "ok";
}
type Props = {
  layer?: MapLayer;
  ageLimit: number;
  stations: Station[];
  route: Route | null;
  origin: Endpoint;
  destination: Endpoint;
  selecting: "origin" | "destination" | null;
  onPick: (p: Point) => void;
  onStation: (s: Station) => void;
};
function Interaction({ stations, route, selecting, onPick }: Props) {
  const map = useMap();
  useMapEvents({
    click: (e) => {
      if (selecting) onPick({ lat: e.latlng.lat, lon: e.latlng.lng });
    },
  });
  useEffect(() => {
    if (route) {
      const stops = [route.pickup, route.dropoff].filter(
        Boolean,
      ) as NonNullable<Route["pickup"]>[];
      map.fitBounds(
        stops.map((s) => [s.lat, s.lon]) as LatLngBoundsExpression,
        { padding: [100, 100], maxZoom: 14 },
      );
    } else if (stations.length)
      map.fitBounds(
        stations.map((s) => [s.lat, s.lon]) as LatLngBoundsExpression,
        { padding: [35, 35], maxZoom: 13 },
      );
  }, [route, stations, map]);
  return null;
}
export default function RideMap(props: Props) {
  const { stations, route, origin, destination, selecting, onStation } = props;
  const layer = props.layer ?? "bike";
  const locate = (v: Endpoint) =>
    typeof v === "string" ? stations.find((s) => s.id === v) : v;
  const a = locate(origin),
    b = locate(destination);
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
      {stations.map((s) => {
        const chosen = s.id === route?.pickup?.id || s.id === route?.dropoff.id;
        return (
          <CircleMarker
            key={s.id}
            center={[s.lat, s.lon]}
            radius={chosen ? 11 : 7}
            bubblingMouseEvents={false}
            pathOptions={{
              color: chosen ? "#fff" : "#fff",
              weight: 2,
              fillColor: chosen
                ? COLORS.chosen
                : COLORS[stationRisk(s, layer, props.ageLimit)],
              fillOpacity: 1,
            }}
            eventHandlers={{
              click: () => {
                if (selecting) props.onPick({ lat: s.lat, lon: s.lon });
                else onStation(s);
              },
            }}
          >
            <Popup>
              <strong>{s.name}</strong>
              <br />
              {s.bikes} bikes · {s.docks} docks
              <br />
              {(() => {
                const f = s.forecast?.[RISK_HORIZON];
                const p = f ? (layer === "bike" ? f.p_bike : f.p_dock) : null;
                return p === null || p === undefined
                  ? null
                  : `${layer === "bike" ? "Bike" : "Open dock"} in ${RISK_HORIZON} min: ${Math.round(p * 100)}%`;
              })()}
              <br />
              Snapshot {s.data_age_seconds}s old
            </Popup>
          </CircleMarker>
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
      {[a, b].map(
        (p, i) =>
          p && (
            <CircleMarker
              key={i}
              interactive={false}
              center={[p.lat, p.lon]}
              radius={7}
              pathOptions={{
                color: "#fff",
                weight: 3,
                fillColor: i ? "#d78b54" : "#343e38",
                fillOpacity: 1,
              }}
            />
          ),
      )}
    </MapContainer>
  );
}
