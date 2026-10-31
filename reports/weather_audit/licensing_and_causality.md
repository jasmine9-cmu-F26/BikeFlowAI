# Weather licence and request-time gate

Data source: [Open-Meteo Historical Forecast API](https://open-meteo.com/en/docs/historical-forecast-api), with [live Forecast schema](https://open-meteo.com/en/docs).

[API data licence](https://open-meteo.com/en/licence): CC BY 4.0. Credit Open-Meteo, link to the licence, and identify transformations (normalization/joins by BikeFlow AI); display a link beside displayed weather. No upstream AGPL server code was copied.

[Service terms](https://open-meteo.com/en/terms) separately restrict free API access to noncommercial use and published quotas (under 10,000 calls/day, 5,000/hour and 600/minute). This small audit uses no API key, paid account or commercial endpoint. Reuse rights do not grant unlimited/commercial free API service access. Future commercial deployment needs its own review.

Historical Forecast hourly times are **valid times** from stitched early run hours. The captured responses lack per-row issued_at/available_at; generationtime_ms is response processing duration. A backward join does not prove the source forecast was published before the request. Single Runs preserves initialization structure but its documented archive dates do not cover this 2021 window; initialization also needs a defensible publication delay. Do not fabricate release times from valid time or a fixed lag.

ERA5 and other reanalysis are excluded from the primary feature source. Retrospective weather analyses must be labeled separately. Required weather features need both low missingness and defensible availability provenance; the latter gate has not passed. Live inference should cache raw forecast responses with receipt timestamps and select received_at <= request_time, then the appropriate valid_time near ETA.
