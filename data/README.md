# Data: official Chicago primary pipeline

Primary training/replay uses official City of Chicago historical Divvy snapshots, OD/ride times use matching official trips, live inference uses official GBFS, and current validation uses our full-GBFS collector. CityBikes change events are supplementary only.

## Storage

Raw and processed files stay outside the checkout, under `C:/Users/44604/Documents/BikeFlowAI-data/divvy/`:

```text
chicago_historical_2021_sample/  Active bounded source sample and source hashes
  raw/snapshots/               About 7.94 MB compressed, 856,200 full rows
  raw/trips/                   Four matching ZIPs, about 102.97 MB
  evidence/                    Source metadata, terms and required disclaimer
  processed/snapshots.parquet  Local normalized observations
chicago_historical_sample/     Preserved failed 2022 comparison
current_validation/            Ongoing full-GBFS snapshots, metadata, poll/error logs
raw/ and processed/            Earlier supplementary CityBikes audit data
```

No full 242-million-row export was downloaded. Full trip CSVs are streamed from ZIPs. The project stores code, configuration, aggregate reports, source notices, station manifests and synthetic tests.

## Reproduce

After installing root `requirements.txt` in a Python 3.14 environment:

```powershell
$DivvyRoot = "$env:USERPROFILE\Documents\BikeFlowAI-data\divvy"
$DataRoot = Join-Path $DivvyRoot 'chicago_historical_2021_sample'
.\.venv\Scripts\python.exe scripts/data/collect_divvy_gbfs.py --data-root "$DivvyRoot" --once
.\.venv\Scripts\python.exe scripts/data/download_chicago_sample.py --data-root "$DataRoot"
.\.venv\Scripts\python.exe scripts/data/build_app_cohort.py --data-root "$DataRoot"
```

The one-time collector call supplies current metadata on a new machine. Ongoing Windows scheduling is separate; see [collector operations](../docs/gbfs_collector.md). The downloader bounds the sample to 50 training-anchor stations / 18 weeks / one million rows, verifies TLS and cached-file SHA-256, and downloads only the four matching trip months.

`build_app_cohort.py` uses the preserved training-qualified cohort and fixed captured identity evidence, writes [app_stations.csv](manifests/chicago/app_stations.csv), reruns snapshots/trips into separate `app32/` outputs, and writes a versioned data protocol. It does not replace the original 42-station results. Protocol version 1 expects exactly 32 stations; changed selection evidence requires a reviewed new version.

`make data` runs bounded download then the app audit; `make audit-base` writes a separate reproduced base audit without replacing original evidence. Use explicit external roots and distinct report/manifest destinations for new samples.

## Cohorts and interpretation

The original 50 candidate / 42 training-qualified station audit remains in [the original report](../reports/chicago_historical_audit/data_audit.md). The **32-station app cohort** and its own coverage, labels, balance, trip mapping and training OD estimates are in [app32](../reports/chicago_historical_audit/app32/README.md). These have different trip denominators. The failed 2022 sample is retained for its ~50-day gap.

The [frozen protocol](manifests/chicago/app32/data_protocol.json) specifies 10–60-minute horizons, ±5-minute target matching, exact split dates, 60-minute separation, training-only OD, and causal feature freshness <=15 minutes. Features use only recorded snapshots <= decision time; future snapshots are label/outcome data only. Missing/stale inputs or outcomes exclude the request. Arbitrary filling and missing-as-zero are not permitted.

Historical floating timestamps and naive trip times use an explicit America/Chicago assumption; raw wall times are retained and DST folds/gaps excluded. Source schema does not independently annotate the historical timezone. GBFS Unix timestamps are UTC. Historical publication latency is unmeasured, so recorded timestamps are an availability assumption.

Historical `In Service` is a broad flag. Do not invent separate installed/renting/returning/disabled fields, add ebikes twice, or copy current metadata into historical features. Identity matches do not prove continuous operation or current service; live flags must be checked. No model-ready feature/label table, full replay or 2026 generalization is certified yet.

## Licenses and archived evidence

See [DATA_SOURCES.md](../DATA_SOURCES.md), [the primary license review](../reports/chicago_historical_audit/licensing_and_overlap.md), and [NOTICE_CHICAGO.md](../NOTICE_CHICAGO.md). Primary metadata says See Terms of Use. Official trip restrictions, live catalog/publisher qualifications and CityBikes ODbL remain source-specific.

Earlier code, numeric reports and manifests are archived under [legacy/baywheels](../legacy/baywheels/README.md) and [legacy/citybikes](../legacy/citybikes/README.md). Exact source bytes matching original Chicago audit hashes are in [legacy/official_chicago_audit_v1](../legacy/official_chicago_audit_v1/README.md). CSV/JSON results were preserved; navigation Markdown links were adjusted for relocation.


## Current collection handoff

Google Apps Script is now the active collector at a nominal **five-minute** cadence; the original Windows two-minute task is **disabled** and local files are preserved. Laptop uptime is no longer required. Cloud files stay in private personal Drive until explicitly downloaded to a separate external `google_validation/` folder. Google files contain gzip poll envelopes; their format differs from local status/metadata files. Initial verification uses user-supplied scheduled-run logs, not an independent audit of raw Google bytes. See [current operations](../docs/gbfs_collector.md).

## Weather data audit

Historical forecast responses, source evidence and normalized Parquet stay in external `weather_open_meteo_audit/`. The [small 2021 audit](../reports/weather_audit/weather_audit.md) checks hourly missingness, units, schema and backward valid-time matching to the fixed app32 cohort. Weather remains optional because forecast issue/publication provenance is unresolved; a successful timestamp join is not a certified causal feature. No ERA5 was requested or substituted. Reproduce with `python scripts/data/audit_weather_data.py --data-root EXTERNAL_DIVVY_ROOT/weather_open_meteo_audit`; add `--offline` to verify/re-audit saved responses without network. No weather calls were added to the live GBFS collector.
