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

import RideMap, { COLORS, fitWhenIdle, framePoints, tripBounds } from "../src/Map";

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

  it("keeps route lines and endpoint marks out of hit testing", () => {
    render();
    expect(layers.lines).toHaveLength(3);
    expect(layers.lines.every((p) => p.interactive === false)).toBe(true);
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

  it("labels an endpoint on a station without covering its status color", () => {
    render(null, { ...route, dropoff: stop(bystander) });
    const end = pin("endpoint-end").icon;
    expect(end.className).toContain("on-station");
    expect(end.html).toContain("Destination");
    // The destination station keeps its own colored marker under the label.
    expect(layers.markers.map((p) => p.center)).toContainEqual([
      destination.lat,
      destination.lon,
    ]);
  });

  it("draws a free map point as a labelled mark", () => {
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
    const start = pin("endpoint-start").icon;
    expect(start.className).not.toContain("on-station");
    expect(start.html).toContain("Start");
    expect(pin("endpoint-end").icon.className).toContain("on-station");
  });

  it("shows only the endpoints before a plan exists", () => {
    render(null, null);
    expect(layers.pins.filter((p) => p.eventHandlers)).toHaveLength(0);
    expect(layers.pins).toHaveLength(2);
    expect(layers.markers.every((p) => p.pathOptions.fillOpacity === 1)).toBe(
      true,
    );
  });

  it("greys stations beyond the walking limit once a trip is planned", () => {
    render();
    const [far] = layers.markers;
    expect(far.pathOptions.fillColor).toBe(COLORS.off);
    expect(far.pathOptions.fillOpacity).toBeLessThan(1);
  });

  it("needs no extra rings or circles to explain the trip", () => {
    render();
    expect(layers.circles).toHaveLength(0);
    expect(layers.markers.every((p) => p.pathOptions.color === "#fff")).toBe(
      true,
    );
  });

  it("keeps empty / full stations visually distinct from the destination", () => {
    expect(COLORS.empty.toLowerCase()).not.toEqual(COLORS.destination);
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

  it("reads the forecast at the horizon it is asked for", async () => {
    const { stationRisk } = await import("../src/Map");
    const draining: Station = {
      ...station,
      forecast: {
        10: { p_bike: 0.95, p_dock: 0.99 },
        30: { p_bike: 0.5, p_dock: 0.99 },
      },
    };
    expect(stationRisk(draining, "bike", 900, 10)).toBe("ok");
    expect(stationRisk(draining, "bike", 900, 30)).toBe("risk");
    // A horizon the forecaster does not publish falls back to the nearest one.
    expect(stationRisk(draining, "bike", 900, 25)).toBe("risk");
  });

  it("colors a planned trip by arrival time at each end, whatever the toggle says", () => {
    // 0.001 degrees of latitude is about 1.4 walking minutes.
    const nearStart: Station = {
      ...station,
      id: "near-start",
      lat: station.lat + 0.001,
      forecast: {
        10: { p_bike: 0.5, p_dock: 0.99 },
        30: { p_bike: 0.99, p_dock: 0.99 },
      },
    };
    const nearEnd: Station = {
      ...destination,
      id: "near-end",
      lat: destination.lat + 0.001,
      forecast: {
        20: { p_bike: 0.99, p_dock: 0.5 },
        30: { p_bike: 0.99, p_dock: 0.99 },
      },
    };
    reset();
    renderToStaticMarkup(
      <RideMap
        layer="dock"
        stations={[station, destination, bystander, nearStart, nearEnd]}
        route={{
          ...route,
          pickup: { ...stop(station), horizon_minutes: 10 },
          dropoff: { ...stop(destination), horizon_minutes: 20 },
        }}
        origin={station.id}
        destination={destination.id}
        walkLimit={5}
        ageLimit={900}
        selecting={null}
        onStation={vi.fn()}
        onPick={vi.fn()}
      />,
    );
    const fill = (s: Station) =>
      layers.markers.find((p) => p.center[0] === s.lat).pathOptions.fillColor;
    expect(fill(nearStart)).toBe(COLORS.risk); // bikes at +10, not docks at +30
    expect(fill(nearEnd)).toBe(COLORS.risk); // docks at +20
    expect(fill(bystander)).toBe(COLORS.off); // out of reach: greyed
  });

  it("colors the recommended stations by the same rule, not a fixed green", () => {
    const emptyStart = { ...station, bikes: 0 };
    reset();
    renderToStaticMarkup(
      <RideMap
        stations={[emptyStart, destination]}
        route={{ ...route, pickup: stop(emptyStart), wait_minutes: 20 }}
        origin={station.id}
        destination={destination.id}
        walkLimit={5}
        ageLimit={900}
        selecting={null}
        onStation={vi.fn()}
        onPick={vi.fn()}
      />,
    );
    expect(pin("pin-pickup").icon.className).toContain("status-empty");
    expect(pin("pin-return").icon.className).toContain("status-ok");
  });
});

describe("map framing", () => {
  const other: Route = {
    ...route,
    pickup: stop(bystander),
    dropoff: stop({ ...destination, id: "chicago:7", lat: 41.88, lon: -87.66 }),
  };

  it("frames every route it is given, so previewing one does not move the map", () => {
    const points = tripBounds([route, other], [station, destination]);
    expect(points).toContainEqual([bystander.lat, bystander.lon]);
    expect(points).toContainEqual([41.88, -87.66]);
    expect(points).toContainEqual([station.lat, station.lon]);
  });

  it("gives the same frame whichever route is shown inside it", () => {
    const a = tripBounds([route, other], [station, destination]);
    const b = tripBounds([route, other], [station, destination]);
    expect(JSON.stringify(a)).toBe(JSON.stringify(b));
  });

  it("skips a missing pickup and unknown endpoints", () => {
    const points = tripBounds([{ ...route, pickup: null }], [undefined, destination]);
    expect(points).toEqual([[destination.lat, destination.lon]]);
  });

  it("keeps every station within walking reach in view, not just the chosen two", () => {
    const nearEnd = { ...station, id: "chicago:60", lat: destination.lat - 0.003 };
    const points = framePoints(
      [{ ...route, pickup: null }],
      [station, destination],
      [station, destination, nearEnd, bystander],
      5,
    );
    expect(points).toContainEqual([nearEnd.lat, nearEnd.lon]);
    expect(points).not.toContainEqual([bystander.lat, bystander.lon]);
  });
});

describe("refitting the view", () => {
  const fakeMap = (animating: boolean) => {
    const handlers: Record<string, () => void> = {};
    return {
      _animatingZoom: animating,
      fitBounds: vi.fn(),
      once: vi.fn((event: string, fn: () => void) => {
        handlers[event] = fn;
      }),
      fire: (event: string) => handlers[event]?.(),
    };
  };

  it("fits right away when the map is idle", () => {
    const map = fakeMap(false);
    fitWhenIdle(map as any, [[41.9, -87.6]], {});
    expect(map.fitBounds).toHaveBeenCalledTimes(1);
  });

  it("waits for a running zoom to end instead of being dropped", () => {
    // Leaflet ignores a fitBounds that arrives mid zoom animation.
    const map = fakeMap(true);
    fitWhenIdle(map as any, [[41.9, -87.6]], {});
    expect(map.fitBounds).not.toHaveBeenCalled();
    map._animatingZoom = false;
    map.fire("zoomend");
    expect(map.fitBounds).toHaveBeenCalledTimes(1);
  });
});
