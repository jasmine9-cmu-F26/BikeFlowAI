# BikeFlow application demo

The application is local-first: React / TypeScript / Vite / Leaflet, with a FastAPI planning service. There are three deliberately separate data modes:

| Mode | Data | Needs model files? |
| --- | --- | --- |
| Example | Deterministic invented counts and probabilities, visibly labeled | No |
| Replay | Audited causal feature Parquet, development forecaster or B2 | Yes, or B2 rates for degraded serving |
| Live | Official GBFS, an independent 60-second in-memory cache and up to 75 minutes of look-back | Counts work without models; predictions require model/B2 files |

Missing replay data never silently switches to examples. The initial page selects Example so a fresh clone can demonstrate the interaction without redistributing historical data.

## Start on Windows

From the repository root (Node 22+, Python 3.14 for the existing pinned pipeline; application checks also exercised Python 3.12):

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
Push-Location frontend
npm.cmd ci
Pop-Location
.\scripts\start_demo.ps1
```

Open <http://127.0.0.1:3000>. Interactive API documentation is at <http://127.0.0.1:8000/docs>. The launcher starts hidden processes, checks both ports and writes local-only logs under `.local/`. Stop only those managed processes with:

```powershell
.\scripts\stop_demo.ps1
```

If this machine blocks `.ps1` files, use a process-scoped invocation (it does not change the saved execution policy), or use the two-terminal commands below:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/start_demo.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/stop_demo.ps1
```

For no outbound GBFS polling, start with `-NoLive`. Alternatively run each process in its own terminal:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --no-access-log
# In another terminal, from frontend/:
npm.cmd run dev
```

`--no-access-log` is intentional: the application's JSON logs exclude raw inputs and exact coordinates. Keep this flag if changing the launch command.

## Connect the team's trained artifacts

Set this environment variable **before** starting the API:

```powershell
$env:BIKEFLOW_DATA_ROOT='D:/data/chicago_historical_2021_sample'
```

The application expects the existing pipeline's layout, without copying files into Git:

```text
<data-root>/
  models/forecaster_v0_m3/
    manifest.json
    bike_lgbm.txt
    dock_lgbm.txt
  models/rl_dev/
    ppo.zip
    ppo.json
  processed/final_pipeline_v1/
    features/*.parquet
    labels/*.parquet
    B2/heldout_training_fit_rates.parquet
```

The LightGBM manifest embeds sigmoid calibration, feature order, station categories, hashes and library versions. `/health` exposes readiness. Model loading happens once at startup; supplying new files requires a restart. Raw data preparation and training never run on application startup. Labels are needed only for the separate outcome reveal action, never `/plan` or `/stations`.

Use a prepared **tune** timestamp such as `2021-07-20T08:06:00-05:00`, subject to the actual available feature rows. The feature grid has a six-minute phase: an 08:00 clock can legitimately use 07:56 features. Responses show the effective decision and prediction times. No more than 10 minutes is bridged to a prior feature-grid row, and source features retain the pipeline's 15-minute maximum observation age.

The app currently loads the development forecaster. Calibration and final-test dates (July 26 onward) are blocked from replay in this app; final evaluation stays in the existing evaluation pipeline. Outcome reveal is restricted to tune. Never use demo exploration to tune on the final test set.

## Planning behavior and current boundaries

- Coordinates or one of the 32 stable station IDs can be entered. Map clicks set coordinates; dropdowns select stations. The bounded service area is within 3 km of this cohort.
- Product default: **5 minutes walking at each endpoint**. Try 10 minutes for a richer alternative-station demo; the existing PPO was trained at 10 minutes by default.
- Up to three operational candidates per endpoint; at most two 10-minute waits; total decision-to-destination window at most 60 minutes. Effective horizons round up to 10/20/30/40/50/60 minutes.
- Walking uses straight-line distance / 1.3 m/s. Riding uses the committed training-only OD median when supported, otherwise 1.3 × straight-line distance / 4 m/s. All route lines are indicative.
- B1 ranks current availability; B2 uses training-only historical rates; B3 uses calibrated forecasts. The app's `decision-pair-v1` adapter scores **initial pickup/return pairs** with the existing greedy reward terms (λ=.02, μ=.01, c=.5). It is not the sequential evaluation policy in `scripts/rl/policies.py`; do not attach the evaluator's success rates to this adapter.
- Alternatives are feasible **initial plans**, not predictions that the primary will fail. `/replan` accepts the rider's current location/time, failed stations and pickup/return phase, excludes tried stations and recomputes a plan. The UI's failure buttons explicitly simulate a failed attempt and advance the replay clock. They do not claim to reveal an actual observed failure.
- PPO runs in an isolated CPU subprocess to avoid mixing torch and LightGBM OpenMP runtimes. Install `scripts/rl/requirements-ppo.txt` in the API environment to enable it. The bridge checks the 31-feature observation layout, walking limit and reward settings against `ppo.json`, and validates the action mask. It serves current station-anchored decisions at the decision-grid time. A current pickup action can be RL while the future return itinerary stays provisional B3; `actual_method` explicitly reports `RL_pickup+B3_return` or `RL_wait+B3_provisional`. A return-only current-state request can use `RL_return`. Arbitrary-location, offset-departure, missing/incompatible artifact and failure-history requests explicitly fall back to B3, then B2. There is no end-to-end online PPO performance claim.
- PPO worker cold-start can take seconds (15-second timeout). The proposal's cached p95 target should be measured separately for greedy serving; this process bridge is not a low-latency PPO deployment.
- Live polling discovers official feed URLs, validates station identities within 50 m, reads current capacity and installed/renting/returning flags, and applies two-second timeouts with one retry per feed. Requests read memory and never block on network. Poll frequency is 60 seconds; observation freshness must be ≤5 minutes. Stale counts remain visible but are excluded from planning and from **all** predictive methods.
- Live features use report timestamps for lag matching and keep missing history as missing. Restarting the app starts a cold history buffer. The external Google collector is independent and is never read by the app.
- `/replay/reveal` is an explicit post-plan operation: it reads future labels for the selected quantized horizons. Missing outcomes remain unobservable. Counts are approximate (±5 minutes), not exact arrival-time stock or a simulated rider's effect on stock.

## API

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | Artifact and replay readiness, live-cache state, active forecast method |
| `GET /registry` | Cohort metadata even when data/models are missing |
| `GET /stations?mode=...&historical_timestamp=...` | Mode-specific counts and six-horizon forecasts |
| `POST /plan` | Validated trip → primary, alternatives, times, probabilities, diagnostics |
| `POST /replan` | Fresh request after a failed pickup/return; excludes failed stations |
| `POST /replay/reveal` | Tune-only outcome lookup, separate from decisions |
| `GET /demo/scenarios` | Synthetic scenario descriptions |

Example request:

```json
{
  "mode": "replay",
  "origin": "chicago:14",
  "destination": "chicago:21",
  "historical_timestamp": "2021-07-20T08:06:00-05:00",
  "departure_time": "2021-07-20T08:06:00-05:00",
  "walk_limit_minutes": 10,
  "method": "B3"
}
```

Endpoints can also be `{"lat":41.858086,"lon":-87.651073}`. Live requests use an absolute departure time near the current clock and omit `historical_timestamp`. Naive API times are interpreted in America/Chicago; prefer explicit offsets. UI replay inputs are summer 2021 Chicago wall time; live departures use absolute UTC instants.

No-plan is a successful response with `status: "no_plan"` and an explanation. Malformed/unsupported inputs return field-specific 422 errors. `/health` can return HTTP 200 and `status: unavailable`: this means the API and examples work but forecast artifacts are absent.

## Docker Compose

```powershell
# Optional: copy .env.example to .env and set the data path.
docker compose up --build
```

Open <http://127.0.0.1:3000>. Default empty `demo-data/` supports examples; an external data directory is mounted **read-only** when configured. Only loopback ports are published. `docker compose down` stops the containers. Docker Desktop must be running. Image builds require internet; map tiles and live GBFS also need internet. Replay inference can run offline, but map tiles will be unavailable without a cache.

## Verification and demo rehearsal

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_app*.py' -v
Push-Location frontend
npm.cmd run build
Pop-Location
```

The repository's existing Python CI includes these app tests; a separate app workflow builds the frontend. Provider tests generate temporary Parquet and a tiny actual LightGBM bundle. They verify the serving plumbing, not the team's model quality. The tests corrupt outcome data and still require planning to succeed, and separately check reveal permissions, causal live lags, missing/stale data, field validation and PPO action masks.

For a reproducible synthetic cached-replay smoke benchmark, run `python scripts/benchmark_app.py` after installing the test/model dependencies. It records aggregate results in `reports/app_demo/synthetic_smoke.json`. See [recorded checks and remaining verification limits](../reports/app_demo/README.md).

Rehearse: Example normal → 10-minute walking limit → recommended plan → alternatives → failure replan → missing-model scenario → stale-data scenario. After installing real data: Replay tune date → plan → explicit historical reveal. Live: wait for cache → inspect real flags/counts → plan → check model/freshness warnings. The footer includes the City of Chicago disclaimer and map attribution.
