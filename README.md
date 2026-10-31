# BikeFlow AI

Divvy / Chicago trip planning with predicted pickup/return availability and backup stations. Project repository: [jasmine9-cmu-F26/BikeFlowAI](https://github.com/jasmine9-cmu-F26/BikeFlowAI).

**The 32-station app data protocol is frozen as version 1 and passes bounded source feasibility.** Model-ready tables, trained/calibrated models, UI/API and a full replay evaluator remain to be implemented.

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
