# Data handoff: fixed 32-station Chicago protocol

**Version 1 data protocol is frozen and the bounded 32-station feasibility audit passed. Model-ready feature/label tables, fitted/calibrated models and the full replay evaluator remain pending.**

The [app manifest](../data/manifests/chicago/app_stations.csv) fixes 32 historical IDs and distinct live IDs using training qualification plus fixed current identity evidence. The original 42-station audit and failed 2022 sample remain separate evidence. No test labels/model scores selected this cohort.

## Frozen rules

See [data_protocol.json](../data/manifests/chicago/app32/data_protocol.json) for exact split timestamps/hashes. The 17-week 2021 window uses 10/2/2/3 calendar weeks train/tune/calibration/test, 60-minute separation, horizons 10/20/30/40/50/60 minutes, and ±5-minute nearest-valid future label matching within a split.

Feature inputs must use only recorded observations <= decision time, with maximum age 900 seconds. Stale/missing features or arrival observations exclude a request. Future labels/outcomes must be inaccessible to feature generation, the forecaster and planner. The shared `asof_index` helper is tested; no complete replay engine is claimed. Source publication latency is unmeasured, and ten-minute target quantization cannot prove exact stock before checkout.

OD estimates use mapped trips with both times in training, duration 60 seconds–6 hours, and >=20 rides per pair; unsupported pairs need the geometric fallback. Current identity is for serving/validation, never a substitute for historical features. Broad historical In Service and live installed/renting/returning semantics differ.

## Next implementation work

1. Build causal lag/features and label tables using the frozen schema/rules, with lineage and exclusions. Keep generated tables outside Git. Reject missing lags explicitly.
2. Fit a baseline and forecaster using train; use tune for choices, calibration for probability calibration, and frozen test for final reporting. No test-driven cohort/rule changes.
3. Implement replay with separate decision-time inputs and isolated future outcome access. Freeze request sampling and counterfactual inventory assumptions before policy comparisons; completed trips omit unmet demand.
4. Implement current station flag checks and a historical/live feature intersection. Review old/new capacity and service inconsistencies without inventing archived fields.
5. Assess 2021 summer to 2026 season/network shift with the ongoing full-GBFS collection once enough current observations exist. The app's 32-site scope is a deployable subset, not unbiased full-network evidence.

See [app results](../reports/chicago_historical_audit/app32/README.md), [source terms](../DATA_SOURCES.md), and [collector operations](gbfs_collector.md). Earlier source studies are retained under `legacy/`.

## Current collector handoff

Current collection uses Google Apps Script at a nominal five-minute cadence, independently of laptop uptime. Initial user-provided scheduled-run evidence was checked and the local Windows task disabled; existing local data remains intact. Raw cloud download, full-day quota/coverage review and historical/current domain-shift evaluation remain separate tasks. See [collector operations](gbfs_collector.md).

## Weather handoff

The [weather audit](../reports/weather_audit/weather_audit.md) covers five proposed variables, four requested model configurations and the fixed 2021 app32 snapshots. Coverage alone passes, but a stitched historical forecast valid_time cannot establish issued_at/available_at <= request_time. Weather remains optional/excluded from the certified causal baseline. Do not join t+h from a stitched archive and describe it as the forecast known at t. Require issuance-aware provenance or label a supplementary ablation with its assumptions. No collector, station, split or frozen model protocol was changed by this audit.
