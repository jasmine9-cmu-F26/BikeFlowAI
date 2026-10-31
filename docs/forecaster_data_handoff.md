# Forecaster data handoff

Read [the final pipeline audit](../reports/final_pipeline_audit/README.md) and [feature schema](../reports/final_pipeline_audit/features/feature_schema.json) before loading data. The exact table hashes are in [generated_manifest.json](../reports/final_pipeline_audit/features/generated_manifest.json).

External root: `Documents/BikeFlowAI-data/divvy/chicago_historical_2021_sample/processed/final_pipeline_v1/`.

- `features/*.parquet`: model inputs, row ID/split and current/past lineage. Select only the schema's `model_feature_columns`.
- `labels/*.parquet`: future targets and lineage. Join on `row_id` only for supervised fitting/scoring; never expose this dataset to planner decision inputs.
- `mapped_app32_requests.parquet`: completed-trip request pool and explicit freshness/outcome/same-split retention flags; contains raw-level derived requests and stays outside Git.
- `B2/heldout_training_fit_rates.parquet`: final train-fit rates for later splits only.
- `B2/training_expanding_week_rates.parquet`: past-complete-week rates for within-training baseline/replay; first week requires B1 fallback.
- `OD/training_expanding_week_od.parquet`: past-only within-training OD medians/support; unsupported geometry requires metadata as-of request.

Train fits the forecaster; tune chooses settings; calibration fits final probability calibration; test is final reporting. Native missing lags and flags are intentional. Station categories and any learned preprocessing must fit train only. Weather, disabled-bike fields and separate historical renting/returning/installed flags are excluded. Future publication latency is not inferred from recorded timestamps.

The `policy` data pool is train, not a new time split. Before policy training, produce honest out-of-fold/forward training probabilities; this audit does not produce or certify them. Use final training OD/B2 only for later splits, and the past-week versions for within-training replay. Preserve all fit cutoffs and row exclusions.

Reproduce the scripts on a fresh external generated-output version, preserving the verified raw snapshot/ZIP inputs. `audit_final_trip_od.py --data-root EXTERNAL_2021_SAMPLE`, then `build_audited_features.py --data-root EXTERNAL_2021_SAMPLE`, then `audit_collector_health.py --data-root EXTERNAL_2021_SAMPLE`. Run from the project root. The feature builder intentionally refuses an existing features directory to avoid silently mixing versions; do not remove or overwrite generated artifacts without preserving their provenance.
