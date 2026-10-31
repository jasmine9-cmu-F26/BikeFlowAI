# Feature-table feasibility and leakage audit

**PASS_FEATURE_TABLE_INVARIANTS_UNDER_RECORDED_TIME_ASSUMPTION**. **3,276,590 feature rows and equal separate label rows** are ready for forecaster data handoff. No forecaster, calibration model, OOF probabilities, policy model or full replay evaluator was trained.

| Chronological split | Feature/label rows across six horizons |
|---|---:|
| train | 1,929,788 |
| tune | 384,582 |
| calibration | 383,970 |
| test | 578,250 |

There is no fifth chronological policy split. The **1,929,788 training rows** are the future policy-training data pool; policy-ready forecaster predictions must be out-of-fold/forward-generated from training only. Tuning is for model/planner/policy choices; calibration remains reserved for final probability calibration; final test does not fit statistics. No policy probability table is claimed here.

Requests use the frozen ten-minute grid at phase 360 seconds learned from training. Features use the latest valid open base <= request and <=15 minutes old. Capacity/service metadata comes from that exact source snapshot. Lags query <= request−10/30/60 minutes, with a 15-minute as-of age bound and <=50m geometry consistency. Missing lags remain native NaN/null with explicit flags; no imputation, scaling or learned encoder is fit on held-out data. The first training hours retain legitimate cold-start missingness. Do not interpret a lag delta as an exactly spaced observation without its age/lineage.

**Features and future outcomes are physically separate Parquet datasets.** Use only `model_feature_columns` from [feature_schema.json](feature_schema.json) as inputs. Row IDs, split labels, lineage timestamps and all target/outcome columns are not model features. Labels require a strictly future valid snapshot within ±5 minutes of the horizon target, same split, and <=50m base/target displacement. Known closed target status is unavailable; unknown/missing outcomes are excluded. Weather and unavailable historical GBFS fields are omitted.

[leakage_checks.json](leakage_checks.json) records zero violations of future base/metadata/features/lags, stale base/lags, target-not-future, target tolerance/split boundaries, duplicate keys, feature/label joins, nontraining OD fits, B2 fit cutoffs or target columns in the model feature allowlist. Synthetic tests mutate future counts/metadata while holding current features fixed and inject a future base into a real table to ensure the auditor rejects it.

The final B2 table uses valid training snapshots at station/weekday/hour, with >=20 cell observations or a station-overall fallback from that same fit period. It is for tune/calibration/test only. External training-week B2 versions use only prior complete training weeks; first week lacks B2 and requires B1 fallback. B2 is **not** silently attached as a training feature. See [B2_fit_manifest.csv](B2_fit_manifest.csv) and [B2_heldout_rates.csv](B2_heldout_rates.csv).

Reports: [feature missingness](feature_missingness.csv), [lag completeness](lag_completeness.csv), [rows/class balance by split/horizon](rows_and_class_balance.csv), [station counts](station_rows.csv), [target offset distribution](target_offset_distribution.csv), and [generated hashes](generated_manifest.json).

Held-out **covariates already observed before a request** may be causal inputs; held-out labels/future values never fit station selection, transformations, OD or B2. The fixed 2026 identity intersection is an external deployment-scope filter, not held-out outcome selection. All certification is under the documented historical recorded-time assumption; actual publication latency is unmeasured.
