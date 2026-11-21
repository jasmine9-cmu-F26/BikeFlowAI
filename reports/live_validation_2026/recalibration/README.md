# Live-mode recalibration on 2026 data

[The 2026 validation](../README.md) found the 2021 forecaster still ranks risk well but under-predicts in the middle range. This refits **only the sigmoid calibrator** (two numbers per target, as in training) on raw LightGBM output from recent live data. The LightGBM trees are unchanged, and Replay keeps the 2021 calibration.

- **Fit:** service days 2026-10-31 to 11-09 (265,680 rows). Fit rows whose 60-minute horizon would reach the held-out period are dropped.
- **Held out:** 2026-11-10 to 11-21 (309,117 rows, 12 days; 9 days in the first run on 2026-11-18). The decision to serve it was made on these days only: it had to beat the 2021 calibration on both Brier and ECE for both targets.

| Held-out, all horizons | Brier B1 / 2021 cal / **2026 cal** | ECE 2021 cal / **2026 cal** | PR-AUC (unchanged) |
|---|---|---|---|
| Bike | 0.045 / 0.0337 / **0.0333** | 1.22 / **0.33** pp | 0.74 |
| Dock | 0.018 / 0.0137 / **0.0135** | 0.47 / **0.23** pp | 0.80 |

Brier change from recalibration (paired 12-day bootstrap): bike −1.3% (−2.4 to −0.5); dock −1.4% (−3.1 to +0.2), so **for docks the Brier gain is no longer significant overall** with the longer hold-out (it is at 30 minutes: −1.8%, −3.6 to −0.1). The calibration gain is the robust part. Mid-range reliability at 30 minutes: bike forecasts near 45% were observed 61% of the time before and 55% after; dock forecasts near 45% went from 63% to 55% observed.

| Target | 2021 sigmoid (a, b) | 2026 sigmoid (a, b) |
|---|---|---|
| Bike | 0.959, 0.204 | 1.199, 0.472 |
| Dock | 0.985, −0.080 | 1.122, 0.090 |

The parameters are in [artifacts/live_calibration.json](../../../artifacts/live_calibration.json). The app's Live mode applies them when the model version matches and says so in its warnings; `/health` reports `live_calibration`. Refitting on the same ten days with the longer data reproduces the served parameters (bike within 0.0005 in each parameter, at most 0.02 pp in probability; dock identical), so the served file was not changed. Twelve held-out late-autumn days support this; refit as collection continues.

Reproduce: `.venv/bin/python scripts/model/recalibrate_live_2026.py --live-root <collector>/divvy/current_validation --write-artifact artifacts/live_calibration.json`
