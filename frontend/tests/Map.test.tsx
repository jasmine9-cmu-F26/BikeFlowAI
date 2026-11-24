import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import type { ReactNode } from "react";
import type { Route, Station } from "../src/api";

// Capture the options passed to Leaflet: decorative layers must never
// participate in hit testing above the station markers.
const layers = vi.hoisted(() => ({
  markers: [] as any[],
  pins: [] as any[],
  lines: [] as any[],
  circles: [] as any[],
  popups: [] as any[],
  events: null as any,
}));
vi.mock("leaflet", () => ({ divIcon: (options: any) => options }));
vi.mock("react-leaflet", () => ({
  MapContainer: ({ children }: { children: ReactNode }) => (
    <div>{children}</div>
  ),
  TileLayer: () => null,
  CircleMarker: (props: any) => {
    layers.markers.push(props);
    return <div>{props.children}</div>;
  },
  Marker: (props: any) => {
    layers.pins.push(props);
    return <div>{props.children}</div>;
  },
  Circle: (props: any) => {
    layers.circles.push(props);
    return null;
  },
  Polyline: (props: any) => {
    layers.lines.push(props);
    return null;
  },
  Popup: (props: any) => {
    layers.popups.push(props);
    return <div>{props.children}</div>;
  },
  useMap: () => ({ fitBounds: vi.fn() }),
  useMapEvents: (handlers: any) => {
    layers.events = handlers;
    return null;
  },
}));

import RideMap, { COLORS, tripCandidates, WALK_SPEED } from "../src/Map";

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
const bystander: Station = {
  ...station,
  id: "chicago:99",
  name: "Far away",
  lat: 41.95,
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

function reset() {
  layers.markers.length = 0;
  layers.pins.length = 0;
  layers.lines.length = 0;
  layers.circles.length = 0;
  layers.popups.length = 0;
  layers.events = null;
}

function render(
  selecting: "origin" | "destination" | null = null,
  currentRoute: Route | null = route,
) {
  const onStation = vi.fn(),
    onPick = vi.fn(),
    onBackground = vi.fn();
  renderToStaticMarkup(
    <RideMap
      stations={[station, destination, bystander]}
      route={currentRoute}
      origin={station.id}
      destination={destination.id}
      walkLimit={5}
      ageLimit={900}
      selecting={selecting}
      onStation={onStation}
      onPick={onPick}
      onBackground={onBackground}
    />,
  );
  return { onStation, onPick, onBackground };
}

const pin = (kind: string) =>
  layers.pins.find((p) => p.icon.className.includes(kind));

describe("station map interaction", () => {
  beforeEach(reset);

  it("keeps route lines, walking ranges and endpoint marks out of hit testing", () => {
    render();
    expect(layers.lines).toHaveLength(3);
    expect(layers.lines.every((p) => p.interactive === false)).toBe(true);
    expect(layers.circles).toHaveLength(2);
    expect(layers.circles.every((p) => p.interactive === false)).toBe(true);
    reset();
    render(null, null);
    expect(layers.pins).toHaveLength(2);
    expect(layers.pins.every((p) => p.interactive === false)).toBe(true);
  });

  it("opens station details from a recommended station's pin", () => {
    const { onStation, onPick } = render();
    const marker = pin("pin-pickup");
    marker.eventHandlers.click();
    expect(onStation).toHaveBeenCalledExactlyOnceWith(station);
    expect(onPick).not.toHaveBeenCalled();
    expect(marker.bubblingMouseEvents).toBe(false);
  });

  it("sets a location instead of opening details while picking an endpoint", () => {
    const { onStation, onPick } = render("origin");
    pin("pin-pickup").eventHandlers.click();
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

  it("leaves station details to one panel instead of a second map popup", () => {
    render();
    expect(layers.popups).toHaveLength(0);
  });

  it("closes station details when the empty map is clicked", () => {
    const { onBackground, onPick } = render();
    layers.events.click({ latlng: { lat: 41.9, lng: -87.6 } });
    expect(onBackground).toHaveBeenCalledOnce();
    expect(onPick).not.toHaveBeenCalled();
  });

  it("sets the endpoint, not closes details, when the map is clicked while picking", () => {
    const { onBackground, onPick } = render("destination");
    layers.events.click({ latlng: { lat: 41.9, lng: -87.6 } });
    expect(onPick).toHaveBeenCalledExactlyOnceWith({ lat: 41.9, lon: -87.6 });
    expect(onBackground).not.toHaveBeenCalled();
  });
});

describe("trip markers", () => {
  beforeEach(reset);

  it("draws the recommended pickup and return as different pins", () => {
    render();
    expect(pin("pin-pickup")).toBeTruthy();
    expect(pin("pin-return")).toBeTruthy();
    expect(pin("pin-pickup").icon.html).not.toEqual(
      pin("pin-return").icon.html,
    );
    // The recommended stations are pins, not plain dots.
    expect(layers.markers.map((p) => p.center)).toEqual([
      [bystander.lat, bystander.lon],
    ]);
  });

  it("labels the recommended stations with plain text, not icons", () => {
    render(null, { ...route, dropoff: stop(bystander) });
    const pickup = pin("pin-pickup").icon.html,
      ret = pin("pin-return").icon.html;
    expect(pickup).toContain("Pick up");
    expect(pickup).toContain("3 bikes");
    expect(ret).toContain("Return");
    expect(ret).toContain("5 docks");
    expect(pickup + ret).not.toContain("<svg");
  });

  it("names your start and destination in the pin they coincide with", () => {
    render();
    // No extra ring stacked on the pins: the label says it instead.
    expect(pin("endpoint-start")).toBeUndefined();
    expect(pin("endpoint-end")).toBeUndefined();
    expect(pin("pin-pickup").icon.html).toContain("at start");
    expect(pin("pin-return").icon.html).toContain("at destination");
  });

  it("says when the plan waits at the pickup for a bike", () => {
    render(null, { ...route, wait_minutes: 20 });
    const label = pin("pin-pickup").icon.html;
    expect(label).toContain("Wait 20 min");
    expect(label).toContain("3 bikes now");
  });

  it("frames an endpoint station without covering its status color", () => {
    render(null, { ...route, dropoff: stop(bystander) });
    expect(pin("endpoint-end").icon.className).toContain("framed");
    // The destination station keeps its own colored marker inside the frame.
    expect(layers.markers.map((p) => p.center)).toContainEqual([
      destination.lat,
      destination.lon,
    ]);
  });

  it("draws a free map point as a plain endpoint mark", () => {
    reset();
    renderToStaticMarkup(
      <RideMap
        stations={[station, destination]}
        route={null}
        origin={{ lat: 41.86, lon: -87.66 }}
        destination={destination.id}
        ageLimit={900}
        selecting={null}
        onStation={vi.fn()}
        onPick={vi.fn()}
      />,
    );
    expect(pin("endpoint-start").icon.className).not.toMatch(/framed|ringed/);
    expect(pin("endpoint-end").icon.className).toContain("framed");
  });

  it("shows only the endpoints before a plan exists", () => {
    render(null, null);
    expect(layers.pins.filter((p) => p.eventHandlers)).toHaveLength(0);
    expect(layers.pins).toHaveLength(2);
    expect(layers.circles).toHaveLength(0);
    expect(layers.markers.every((p) => p.pathOptions.fillOpacity === 1)).toBe(
      true,
    );
  });

  it("fades stations the planner could not consider", () => {
    render();
    const [far] = layers.markers;
    expect(far.pathOptions.fillOpacity).toBeLessThan(1);
  });

  it("draws the walking range at the planner's walking speed", () => {
    render();
    expect(layers.circles[0].radius).toBeCloseTo(5 * 60 * WALK_SPEED);
  });

  it("keeps empty / full stations visually distinct from the destination", () => {
    expect(COLORS.empty.toLowerCase()).not.toEqual(COLORS.destination);
  });
});

describe("planner candidates", () => {
  // 0.001 degrees of latitude is about 111 m, i.e. 1.4 walking minutes.
  const at = (id: string, dLat: number, extra: Partial<Station> = {}) => ({
    ...station,
    id,
    lat: station.lat + dLat,
    ...extra,
  });

  it("mirrors the backend: usable, fresh, within the limit, nearest three", () => {
    const stations = [
      at("far", 0.004),
      at("c", 0.002),
      at("closed", 0.0005, { pickup: false }),
      at("stale", 0.0007, { data_age_seconds: 1000 }),
      at("d", 0.0025),
      at("a", 0),
      at("b", 0.001),
    ];
    const ids = tripCandidates(stations, station, "pickup", 5, 900).map(
      (s) => s.id,
    );
    expect(ids).toEqual(["a", "b", "c"]);
  });

  it("uses dock availability flags for the return side", () => {
    const stations = [at("a", 0, { return: false }), at("b", 0.001)];
    expect(
      tripCandidates(stations, station, "return", 5, 900).map((s) => s.id),
    ).toEqual(["b"]);
  });
});

describe("bike / dock risk layer", () => {
  it("colors stations by open docks in the return view", async () => {
    const { stationRisk } = await import("../src/Map");
    const filling: Station = {
      ...station,
      docks: 8,
      forecast: { 30: { p_bike: 0.99, p_dock: 0.76 } },
    };
    expect(stationRisk(filling, "bike", 900)).toBe("ok");
    expect(stationRisk(filling, "dock", 900)).toBe("risk");
    expect(stationRisk({ ...filling, docks: 0 }, "dock", 900)).toBe("empty");
    expect(stationRisk({ ...filling, return: false }, "dock", 900)).toBe("off");
    expect(
      stationRisk({ ...filling, data_age_seconds: 1000 }, "dock", 900),
    ).toBe("off");
  });
});
