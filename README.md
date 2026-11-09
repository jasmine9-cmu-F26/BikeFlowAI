# BikeFlow AI

Divvy / Chicago trip planning with predicted pickup/return availability and backup stations. Project repository: [jasmine9-cmu-F26/BikeFlowAI](https://github.com/jasmine9-cmu-F26/BikeFlowAI).

**The 32-station app data protocol is frozen as version 1 and passes bounded source feasibility.** Audited feature/label tables, the preliminary forecaster, forward-chained policy probabilities and replay evaluator are implemented. A local React/FastAPI trip planner now supports clearly separated synthetic examples, historical replay and live station data; see [app setup and limitations](docs/app_demo.md).

## Run the application

After installing `backend/requirements.txt` into `.venv` and running `npm ci` in `frontend`, run `./scripts/start_demo.ps1` on Windows, or `docker compose up --build` with Docker Desktop running. Open **http://127.0.0.1:3000**. The initial Example mode uses visibly labeled synthetic data; real replay and predictive live serving require the team's external data/model package via `BIKEFLOW_DATA_ROOT`. See [the full startup guide, API contract and demo rehearsal](docs/app_demo.md).

| Source | Role |
|---|---|
| City of Chicago Divvy Bicycle Stations – Historical (`eq45-8inv`) | Primary historical training/labels and approximate replay observations |
| Official Divvy trips from the same months | OD requests and training-only ride-time estimates |
| Official Divvy GBFS | Live inference and our own full-snapshot collector |
| CityBikes recent change records | Supplementary evidence only; not arbitrary-time ground truth |

## Audited scope

The declared historical window is **2021-05-03 to 2021-08-30 (exclusive)**, 17 weeks. The original source audit examined **856,200 snapshots / 50 stations**, qualified **42 using training data only**, and then matched **32** to unique current GBFS identities. That fixed identity intersection defines the app cohort; no held-out labels/model performance choose stations.

| Check | Fixed 32-station app cohort |
|---|---:|
| Source poll interval median / p90 | 10.00 / 10.58 min |
| Lowest per-station valid coverage across splits | 99.80% |
| Lowest aggregate label retention across splits/horizons | 99.80% |
| Trip mapping among trips naming both app-cohort endpoints | 93.74% |
| Mapped trips with pickup/return observations within ±5min | 96.80% |
| Training-only OD rides / pairs with >=20 rides | 18,571 / 229 |

The original **42-station** results remain separate: trip mapping **93.49%** over the original 50-station mapping scope, selected-trip observation support **96.87%**, and **42,356** training OD rides. Do not mix these denominators with app results. The failed 2022 comparison retains its observed ~50-day May–July gap.

Read the [32-station report](reports/chicago_historical_audit/app32/README.md), [frozen protocol](data/manifests/chicago/app32/data_protocol.json), [app station manifest](data/manifests/chicago/app_stations.csv), [original 42-station audit](reports/chicago_historical_audit/data_audit.md), and [source terms](DATA_SOURCES.md).

## Frozen timing rules

- Horizons: **10/20/30/40/50/60 minutes**; future labels use nearest valid observations within **±5 minutes**, inside the same split. Missing observations are excluded.
- Exact split dates are in [split_manifest.csv](data/manifests/chicago/app32/split_manifest.csv). Whole-week rounding gives **10/2/2/3 weeks**, with **60-minute separation** before later splits; 60/15/10/15 is the nominal ratio.
- Features/planner inputs use only the latest valid recorded snapshot **at or before decision time**, at most **15 minutes old**. Future snapshots are available only to offline labels/outcome scoring. Stale/missing context excludes the request.
- OD estimates use both trip times inside training, durations 60 seconds–6 hours, and at least 20 rides per pair; unsupported pairs need geometric fallback.

The source has ten-minute resolution, broad historical `In Service` flags and unmeasured historical publication latency. It does not certify exact stock before checkout, continuous-time truth or 2026 performance. Live serving must check current installed/renting/returning flags separately. See [data handoff](docs/data_handoff.md).

## Repository

```text
scripts/data/                         Active Chicago pipeline and collector
scripts/data/bikeflow_data/           Shared time-matching and download utilities
data/manifests/chicago/app_stations.csv  Fixed app identity cohort
data/manifests/chicago/app32/         Frozen app protocol, splits and mapping
reports/chicago_historical_audit/app32/  App-specific audit and training-only OD
reports/chicago_historical_audit/     Original feasibility evidence; failed_2022/
legacy/baywheels/                    Retired code/reports/manifests
legacy/citybikes/                    Supplementary code/reports/manifests
legacy/official_chicago_audit_v1/     Exact source bytes for original audit hashes
tests/                              Active and clearly named legacy regression tests
docs/                               Handoff and collector operations
```

## Reproduce and test

Use Python 3.14 and an isolated environment:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$DivvyRoot = "$env:USERPROFILE\Documents\BikeFlowAI-data\divvy"
$DataRoot = Join-Path $DivvyRoot 'chicago_historical_2021_sample'
.\.venv\Scripts\python.exe scripts/data/collect_divvy_gbfs.py --data-root "$DivvyRoot" --once
.\.venv\Scripts\python.exe scripts/data/download_chicago_sample.py --data-root "$DataRoot"
.\.venv\Scripts\python.exe scripts/data/build_app_cohort.py --data-root "$DataRoot"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

`make data PYTHON=.venv/Scripts/python.exe` downloads/reuses the bounded sample and rebuilds the app audit. Raw/processed data stays outside Git. See [data setup](data/README.md) and [cleanup validation](reports/chicago_historical_audit/app32/validation.md). No model training/evaluation targets exist yet.

Current full-GBFS collection runs in **Google Apps Script every nominal 5 minutes**, saving complete polls to private Google Drive through **2026-12-12 23:59 America/Los_Angeles**. Initial scheduled execution evidence was supplied and checked; the Windows two-minute task is now **disabled**, with its existing data preserved. Laptop uptime is no longer required. Shared quotas, storage limits and best-effort scheduling still apply. See [collector operations](docs/gbfs_collector.md).

## Team and source terms

Feifan Yang, Jasmine Zhang, Liye Fu, Xiaohan Zhou, Zhouheng Tao.

City of Chicago primary data is labeled **See Terms of Use**, not CC0. Retain [NOTICE_CHICAGO.md](NOTICE_CHICAGO.md). Official trips and live GBFS have separate terms; CityBikes ODbL attribution stays with its supplementary outputs. No project code license has been selected. Raw data is not rehosted.


## Current cloud collection

Google Apps Script is active with a nominal five-minute trigger. [Handoff evidence](reports/chicago_historical_audit/cloud_collector_handoff.json) distinguishes user-provided cloud execution evidence from directly verified local task state; cloud raw files were not independently downloaded/validated. Check [current status](deploy/apps_script/deployment_status.json) and [operations](deploy/apps_script/README.md).

AWS was abandoned after account eligibility required a Paid plan. No AWS resources were created; the AWS implementation is inactive evidence only. The active Google script requires no cloud billing setup. These initial captures do not constitute weeks of current-data validation or prove old-to-current model generalization.

## Weather audit

The [2021 weather audit](reports/weather_audit/weather_audit.md) uses the Historical Forecast API [9] and live Forecast schema/licence [10], with ERA5 excluded from primary features. Five proposal variables have good coverage; GFS Global weather code has two missing hours (0.07%), while Seamless/HRRR/Best Match have no missing core values. Strict historical request-time availability cannot be certified from stitched hourly valid times alone, so weather remains **optional / excluded from the certified causal baseline**. See [reference update](docs/proposal_references.md) and [methodology](reports/weather_audit/licensing_and_causality.md).


## Final pipeline audit and model handoff

The [final app32 pipeline audit](reports/final_pipeline_audit/README.md) includes planner OD fallback, 10/15/20-minute freshness, **3,276,590 separate feature and label rows**, train-only/past-week B2 and OD lineage, and collector health. See [forecaster handoff](docs/forecaster_data_handoff.md) and [pipeline contract](data/manifests/chicago/final_pipeline_contract.json). Weather remains optional/excluded from the causal baseline.

Google v2 health is active: the user-supplied initial report shows 2/2 scheduled slots successful, zero failures/missing slots, 298.934-second cadence and 2,078 stations. This short window is not a full-day uptime measurement; see [health evidence](reports/final_pipeline_audit/collector_health/google_health.json). The five-minute cloud trigger and disabled local task are not reinstalled by this audit.


## Milestone 3 forecaster (preliminary, tune split)

[Forecaster results](reports/forecaster_m3/README.md): LightGBM + sigmoid calibration predicts bike/dock unavailability at 10–60 minutes from the audited causal features. On the **tune** split (calibration/test untouched), Brier is **34% (bike) / 30% (dock)** lower than the better of B1/B2, meeting the proposal's 10% goal at every horizon, and **~10%** lower than a stronger calibrated-persistence baseline (B1-cal); 95% day-block bootstrap intervals exclude zero at every horizon. ECE is ≤2.3 pp. Forward-chaining train-pool probabilities for RL, a replay demo, and a FastAPI `/health` + `/forecast` wrapper with LightGBM → B2 → unavailable fallbacks are in `scripts/model/`. Reproduce with `make train`, `make forward`, `make replay-demo` (set `DATA_ROOT`). B3/RL planning is in the next section.

## Replay, greedy baselines and RL (preliminary, tune split)

The planner is evaluated by replaying riders against the audited outcome labels; see the [design](docs/rl_replay_design.md). By default riders are drawn at every station and 10-minute slot from training departure rates and destination shares (`--requests grid`), so whether a bike was there is not filtered; `--requests trips` replays completed trips instead, which conditions on the trip having succeeded. Each episode is one rider: up to three pickup candidates within a 10-minute walk (the product default is 5; at 5 minutes only 15 of 32 stations have any alternative), wait up to twice, then up to three return candidates, with backups after a failed attempt. The environment reads a station's outcome only after the action is fixed. Policies read the forecaster's outputs: forward-chained scores from `make forward` for training weeks 2 to 9, and the calibrated tune probabilities from `make train`.

- `make rl-train`: MaskablePPO on the training-week replay ([`train_ppo.py`](scripts/rl/train_ppo.py)); needs `pip install -r scripts/rl/requirements-ppo.txt`.
- `make rl-eval`: B1, B2 and B3 (one greedy rule over current emptiness, historical rates or the forecaster) and RL on identical tune requests, with paired Chicago-day bootstrap differences, into `reports/rl_eval/tune/`. `make rl-eval-final` repeats it on test once, after settings are frozen and the final forecaster has written test probabilities.
- `make pipeline`: `train`, `forward`, `rl-train`, `rl-eval` in order, each in its own process.

On 20,071 grid requests over the 14 tune days (origin empty at arrival for 18.3%), B1 fails 4.9% of trips. B3 cuts that to 3.9% (success +0.96 points, 95% interval 0.70 to 1.23), about 20% fewer failed trips, at 0.59 more walking minutes and about one minute of waiting on average. RL fails 4.2%: more often than B3 (−0.27 points, −0.39 to −0.13) but less than B1 (+0.69 points, 0.45 to 0.98), and it walks 0.82 minutes less than B3, so its mean reward is the highest (+0.014 over B3, 0.011 to 0.016). These numbers use the walking penalty λ = 0.02 per minute.

`make rl-sweep` repeats the comparison for λ from 0 to 0.32 with three PPO seeds each ([frontier](reports/rl_eval/lambda_sweep/frontier.png), [details](docs/rl_replay_design.md#λ-sweep)). B3's failure rate stays at 3.9% for every λ up to 0.08 while its walking falls from 6.4 to 1.2 minutes; at λ = 0.08 it walks as much as B1 and fails 21% less often (interval 14% to 27%), waiting 1.1 minutes more. RL beats B3 on mean reward when both use the same λ from 0.005 to 0.08, but its best points match B3 at λ = 0.08 rather than improving on it, so the preliminary evidence is that the forecaster carries the gain and PPO matches a well-tuned greedy rule. Completed-trip replay (`--requests trips`) is kept as a check on riders who would have succeeded anyway. The local UI and plan API are implemented with a separately versioned initial-pair adapter; see [application setup and boundaries](docs/app_demo.md). Evaluator results above do not measure this application adapter.
