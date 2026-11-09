import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import type { ReactNode } from "react";
import type { Route, Station } from "../src/api";

// Capture the options passed to Leaflet: decorative SVG paths must never
// participate in hit testing above the station paths.
const layers = vi.hoisted(() => ({ markers: [] as any[], lines: [] as any[] }));
vi.mock("react-leaflet", () => ({
  MapContainer: ({ children }: { children: ReactNode }) => (
    <div>{children}</div>
  ),
  TileLayer: () => null,
  CircleMarker: (props: any) => {
    layers.markers.push(props);
    return <div>{props.children}</div>;
  },
  Polyline: (props: any) => {
    layers.lines.push(props);
    return null;
  },
  Popup: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  useMap: () => ({ fitBounds: vi.fn() }),
  useMapEvents: () => null,
}));

import RideMap from "../src/Map";

const station: Station = {
  id: "chicago:14",
  name: "Morgan St & 18th St",
  lat: 41.858,
  lon: -87.651,
  bikes: 3,
  docks: 5,
  pickup: true,
  return: true,
  data_age_seconds: 30,
  forecast: {},
};
const destination: Station = {
  ...station,
  id: "chicago:21",
  name: "Destination",
  lat: 41.877,
};
const stop = (s: Station) => ({
  ...s,
  walk_minutes: 0,
  probability: 0.8,
  horizon_minutes: 10,
  estimated_arrival_time: "2021-07-20T08:10:00-05:00",
  effective_prediction_time: "2021-07-20T08:10:00-05:00",
});
const route: Route = {
  pickup: stop(station),
  dropoff: stop(destination),
  wait_minutes: 0,
  ride_minutes: 10,
  ride_method: "geometric_estimate",
  total_minutes: 10,
};

describe("station map interaction", () => {
  beforeEach(() => {
    layers.markers.length = 0;
    layers.lines.length = 0;
  });

  function render(
    selecting: "origin" | "destination" | null = null,
    currentRoute: Route = route,
  ) {
    const onStation = vi.fn(),
      onPick = vi.fn();
    renderToStaticMarkup(
      <RideMap
        stations={[station, destination]}
        route={currentRoute}
        origin={station.id}
        destination={destination.id}
        ageLimit={900}
        selecting={selecting}
        onStation={onStation}
        onPick={onPick}
      />,
    );
    return { onStation, onPick };
  }

  it("keeps all route lines and endpoint decorations out of hit testing", () => {
    render();
    expect(layers.lines).toHaveLength(3);
    expect(layers.lines.every((p) => p.interactive === false)).toBe(true);
    const decorations = layers.markers.filter((p) => !p.eventHandlers);
    expect(decorations).toHaveLength(2);
    expect(decorations.every((p) => p.interactive === false)).toBe(true);
  });

  it("opens station details for a station underneath a recommended endpoint", () => {
    const { onStation, onPick } = render();
    const marker = layers.markers.find((p) => p.eventHandlers);
    marker.eventHandlers.click();
    expect(onStation).toHaveBeenCalledExactlyOnceWith(station);
    expect(onPick).not.toHaveBeenCalled();
    expect(marker.bubblingMouseEvents).toBe(false);
    expect(marker.radius).toBeGreaterThanOrEqual(7);
  });

  it("sets a location instead of opening details while picking an endpoint", () => {
    const { onStation, onPick } = render("origin");
    layers.markers.find((p) => p.eventHandlers).eventHandlers.click();
    expect(onPick).toHaveBeenCalledExactlyOnceWith({
      lat: station.lat,
      lon: station.lon,
    });
    expect(onStation).not.toHaveBeenCalled();
  });

  it("keeps return-only replanning lines noninteractive as well", () => {
    render(null, { ...route, pickup: null });
    expect(layers.lines).toHaveLength(2);
    expect(layers.lines.every((p) => p.interactive === false)).toBe(true);
  });
});
