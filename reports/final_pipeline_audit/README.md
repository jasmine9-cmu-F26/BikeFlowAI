# Final app32 pipeline audit

The weather audit was committed first as **6964cf5**. This audit uses only the existing fixed official Chicago historical/trip sources; no new database or model training.

1. [Final trip/OD](trip_od/README.md): 36,007 mapped app32 rides, 18,571 training OD rides, 229 supported pairs, explicit pair/request-weighted fallback.
2. [Replay freshness](freshness/README.md): compare 10/15/20 minutes, retain the existing 15-minute bound; live contract remains 5 minutes.
3. [Features/leakage](features/README.md): **3,276,590** separate feature and label rows, all audited invariants pass; training B2/OD versions are past-only.
4. [Collector health](collector_health/README.md): actual retired-local window audited; Google v2 initial health window confirmed from user output (2/2 successful scheduled slots); longer cloud uptime remains unmeasured.

The new [pipeline contract](../../data/manifests/chicago/final_pipeline_contract.json) extends the immutable original app32 protocol. Original cohort, split dates, original audits, weather decision and local raw data are preserved. The main model data lives externally under `chicago_historical_2021_sample/processed/final_pipeline_v1/`.

No full replay, OOF/policy probability table, trained model, publication-latency guarantee or weeks-long cloud uptime is certified by this data audit. Future test-time observed inputs are permitted causal covariates; final test labels/future information never fit statistics.
