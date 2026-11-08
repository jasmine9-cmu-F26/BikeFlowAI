# Milestone 3 forecaster: preliminary results (tune split)

**Status: preliminary.** LightGBM + sigmoid calibration, B1, B1-cal and B2 are compared on the **tune** split only (2021-07-12 to 07-26, 14 service days, 384,582 station x request x horizon rows). The frozen **calibration** and **test** splits were not read by training or evaluation. Rows are dependent (32 stations x 10-minute grid x 6 horizons), so intervals use a paired **day-block bootstrap** (14 days, 2,000 resamples, seed 668).

Reproduce (about 40 s each on an M-series laptop CPU):

```bash
python scripts/model/train_forecaster.py --data-root EXTERNAL_2021_SAMPLE          # make train
python scripts/model/build_forward_predictions.py --data-root EXTERNAL_2021_SAMPLE # make forward
python scripts/model/replay_forecast.py --data-root EXTERNAL_2021_SAMPLE --time "2021-07-20 08:00" --reveal
```

## Task and protocol

- **Targets:** P(bike unavailable) and P(dock unavailable) at 10-60 minutes. A target is unavailable if its count is 0 or the station is not In Service. The app shows `1 - p` as availability.
- **Inputs:** only the 27 `model_feature_columns` in [feature_schema.json](../final_pipeline_audit/features/feature_schema.json). Native NaN is kept for cold-start lags. `station_id` is a categorical whose categories are fit on train.
- **Fit / early stopping / provisional calibration:** the model is fit on train rows whose target time is before `train_end - 14 days`. The last 14 train days are used for early stopping and a provisional Platt (sigmoid) fit. The final calibrator will be refit on the frozen calibration split, as the Milestone 2 protocol specifies.
- **Fixed settings:** `num_leaves=63`, `learning_rate=0.05`, `min_data_in_leaf=200`, `feature_fraction=0.9`, `bagging=0.8`, `L2=1`, seed 668, `deterministic=True`. Best iterations: 132 (bike) and 99 (dock). Two runs produced identical metrics.

## Baselines

| Name | Rule | Fit on |
|---|---|---|
| B1 persistence | Live-map behaviour: unavailable iff the current count is 0 (hard 0/1) | nothing |
| **B1-cal** calibrated persistence | Train empirical P(unavailable \| current count capped at 20, horizon) | all train |
| B2 historical rate | Station x weekday x hour rate at the **target** time; sparse cells fall back to the station rate | all train (pipeline table) |

B1-cal was added after the first results to answer an obvious question: does LightGBM win only because B1 outputs hard 0/1 values? It is a stronger, non-learned reference.

## Results (Brier, lower is better)

| Horizon | bike B1 | bike B1-cal | bike B2 | **bike LGBM** | dock B1 | dock B1-cal | dock B2 | **dock LGBM** |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 10 | 0.0679 | 0.0566 | 0.1306 | **0.0521** | 0.0075 | 0.0066 | 0.0280 | **0.0061** |
| 20 | 0.0996 | 0.0769 | 0.1306 | **0.0695** | 0.0117 | 0.0097 | 0.0280 | **0.0086** |
| 30 | 0.1182 | 0.0873 | 0.1307 | **0.0789** | 0.0143 | 0.0114 | 0.0280 | **0.0101** |
| 40 | 0.1323 | 0.0945 | 0.1308 | **0.0851** | 0.0162 | 0.0126 | 0.0281 | **0.0113** |
| 50 | 0.1417 | 0.0993 | 0.1308 | **0.0897** | 0.0180 | 0.0136 | 0.0281 | **0.0122** |
| 60 | 0.1507 | 0.1037 | 0.1309 | **0.0937** | 0.0193 | 0.0144 | 0.0281 | **0.0130** |
| all | 0.1184 | 0.0864 | 0.1307 | **0.0781** | 0.0145 | 0.0114 | 0.0281 | **0.0102** |

Relative Brier change of LightGBM, with 95% day-block CI ([bootstrap_vs_best_baseline.csv](bootstrap_vs_best_baseline.csv)):

| Comparison | bike (all horizons) | dock (all horizons) | Per-horizon range |
|---|---|---|---|
| Milestone 2 goal: vs better of B1/B2 | **-34.0%** [-34.9, -32.9] | **-29.5%** [-32.4, -25.9] | -19% to -35%; **>=10% goal met at every horizon** |
| vs stronger B1-cal | **-9.5%** [-10.3, -8.6] | **-10.3%** [-13.5, -7.0] | -8% to -11%; every CI excludes 0 |

**Calibration:** LightGBM + sigmoid ECE is 0.6-2.3 pp (bike) and 0.1-0.3 pp (dock) at every horizon, meeting the <=5 pp goal. The sigmoid halves bike ECE (2.9 pp raw → 1.4 pp). PR-AUC for the unavailable event across all horizons: bike 0.71 vs 0.62 (B1-cal) and 0.47 (B1); dock 0.74 vs 0.63 and 0.47.

**Slices** ([slice_metrics.csv](slice_metrics.csv)): LightGBM is best in weekday peak (7-10, 16-19), weekday off-peak and weekend slices for both targets. Weekday-peak bike Brier: 0.098 vs 0.110 (B1-cal) and 0.155 (B1). Per station at 30 minutes ([station_metrics_30min.csv](station_metrics_30min.csv)), LightGBM is worse than the best baseline at 4/32 stations for bikes (by at most 0.0012 Brier; these are rarely empty stations) and at 10/32 for docks (at most 0.0005; 5 of them never fill in tune, so every method scores ~0).

## What drives the model (ablations, tune Brier)

| Variant | features | bike | dock |
|---|---:|---:|---:|
| full model | 27 | **0.0781** | **0.0102** |
| no lag/delta features | 12 | 0.0784 | 0.0103 |
| no station_id | 26 | 0.0798 | 0.0104 |
| current state + calendar only | 6 | 0.0801 | 0.0105 |

Current count dominates (74% of bike split gain, 86% of dock). The 10/30/60-minute deltas add almost nothing at this 10-minute resolution, and station identity and hour add a little. Most of the gain over B1 comes from turning the count into a **calibrated, horizon-aware probability**, and the learned interactions add another ~10% over B1-cal. Weather, recent trip counts and neighbouring-station features remain untested candidates.

## Representative successes and failures (30-minute horizon)

- [Success](figures/example_bike_success.png), *chicago:46, 2021-07-25*: the station repeatedly empties and refills. B1 flips 0/1 one step late, while LightGBM holds 0.6-0.8 during the empty spells and 0.2-0.4 between them.
- [Failure](figures/example_bike_failure.png), *Clark St & Lake St, 2021-07-15*: at ~03:50 the station empties suddenly with no lead-up in counts or deltas (consistent with a rebalancing removal, which the features cannot see). The model only reacts after observing 0. In the evening, when the station oscillates between 0 and 1 bike, the model hovers near 0.5. That is honest uncertainty, but not a useful ranking.
- Dock examples: [success](figures/example_dock_success.png), [failure](figures/example_dock_failure.png).

## Data drift to watch

Unavailability is not stationary. The bike-unavailable rate is 7.6% in train but 16.3% in tune (dock 4.6% vs 2.3%). Calibrating on the most recent 14 train days absorbs part of this shift. The final calibrator on the later calibration split, and the separate 2026 GBFS validation, will show how much remains.

## Forward-chaining probabilities for RL

[forward_chaining_folds.csv](forward_chaining_folds.csv): for train week k >= 2, the model is fit on weeks < k-1, early-stopped and calibrated on week k-1, and predicts week k. This yields **1,543,088 of 1,929,788 train rows (80%)** with probabilities from models that never saw that week. Weeks 0-1 are cold start, so the planner uses B2/B1 there. LightGBM beats B1 in all 8 folds (for example, week 9 bike Brier 0.065 vs 0.098). Output: `EXTERNAL/models/forecaster_v0_m3/forward_train_predictions.parquet`.

## Serving behaviour (integration)

`ForecasterService` loads versioned model files once (hash-checked against `manifest.json`) and never trains.

- **Fallback chain:** LightGBM + sigmoid → B2 historical rate (model missing, corrupt, or schema mismatch) → `unavailable` (no B2).
- **Stale input:** if the causal base snapshot is older than the bound (900 s replay, 300 s live contract), the service suppresses every prediction, B2 included. Each response labels the method used per station.

The replay demo and a FastAPI wrapper (`/health`, `/forecast`) are in `scripts/model/`. Over 90 replay requests (32 stations x 6 horizons each), p50 latency was **59 ms** and p95 **62 ms**, including the Parquet as-of lookup. Invalid timestamps return a field-specific 422, and requests with no causal history return a 422 with an explanation. Fault behaviour is covered by `tests/test_forecaster.py` (synthetic, no network).

## Reproducibility check on a second machine

On a clean macOS checkout (Python 3.14.8, 2026-11-08), the bounded download returned the same **856,200** snapshots. **259 of 260 feature/label Parquet files are byte-identical** to the committed `generated_manifest.json` hashes (same 3,276,590 rows, same schema). The exception is `mapped_app32_requests.parquet`, which has identical row counts. All leakage checks returned 0. The rerun's current GBFS capture showed one live identity change: *Clark St & Lake St* (chicago:38) now publishes short name `CHI02436` instead of `CHI00761`. The frozen protocol files were left unchanged, and live serving must re-check identities.

## Limitations

- These are tune-split numbers used for development choices. Final claims must come from the untouched test split after refitting the calibrator on the calibration split.
- The 10-minute source resolution and historical recorded timestamps stand in for unmeasured publication latency.
- Labels describe station inventory, not whether a specific rider got a bike. Decision-level value (trip success, extra walking) needs the replay planner (B3/RL), which is not built yet.
