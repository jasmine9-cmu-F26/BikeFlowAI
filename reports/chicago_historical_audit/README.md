# Primary official Chicago snapshot feasibility audit

Read [data_audit.md](data_audit.md), [trip_overlap.md](trip_overlap.md), [licensing_and_overlap.md](licensing_and_overlap.md), and [collector_status.json](collector_status.json).

The active bounded 2021 sample passes snapshot feasibility for a training-qualified cohort; it does not certify exact continuous-time truth, a trained model, or 2026 performance. The failed 2022 sample is retained in [failed_2022/data_audit.md](failed_2022/data_audit.md), including the observed May–July gap.

The full ~242-million-row dataset was not exported or independently recounted, and the entire 2021–2022 interval was not audited. Station selection uses only the declared window's training data. Sample labels use 10–60-minute horizons and ±5-minute nearest valid observations; missing data stays missing.

`coverage_by_station.csv`, `gap_summary.csv`, `network_gaps.csv`, `label_retention.csv`, `class_balance.csv`, `station_changes.csv`, and `live_station_overlap.csv` contain the requested checks. Same-period trip evidence and training-only OD support are separate from snapshot coverage and model quality.

Source: City of Chicago, Divvy Bicycle Stations – Historical, eq45-8inv. The source license metadata is See Terms of Use, not CC0 or CityBikes ODbL. See [the required application notice](../../NOTICE_CHICAGO.md) and source-specific review. Raw snapshots/ZIPs, normalized data and full collector polls stay outside Git.

## Fixed app cohort

Current app/model/replay data scope is the [separate 32-station version 1 audit](app32/README.md). Original 42-station numbers above remain historical feasibility evidence and must not be reused as 32-station metrics. Exact original source bytes are retained under [legacy/official_chicago_audit_v1](../../legacy/official_chicago_audit_v1/README.md).
