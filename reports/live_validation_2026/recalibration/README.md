# Live-mode recalibration on 2026 data

[The 2026 validation](../README.md) found the 2021 forecaster still ranks risk well but under-predicts in the middle range. This refits **only the sigmoid calibrator** (two numbers per target, as in training) on raw LightGBM output from recent live data. The LightGBM trees are unchanged, and Replay keeps the 2021 calibration.

- **Fit:** service days 2026-10-31 to 11-09 (265,680 rows). Fit rows whose 60-minute horizon would reach the held-out period are dropped.
- **Held out:** 2026-11-10 to 11-18 (227,835 rows, 9 days). The decision to serve it was made on these days only: it had to beat the 2021 calibration on both Brier and ECE for both targets.

| Held-out, all horizons | Brier B1 / 2021 cal / **2026 cal** | ECE 2021 cal / **2026 cal** | PR-AUC (unchanged) |
|---|---|---|---|
| Bike | 0.042 / 0.0329 / **0.0323** | 1.36 / **0.43** pp | 0.75 |
| Dock | 0.018 / 0.0139 / **0.0136** | 0.51 / **0.27** pp | 0.80 |

Brier change from recalibration (paired 9-day bootstrap): bike −1.7% (−3.1 to −0.8), dock −1.9% (−4.0 to −0.1); at 60 minutes the dock interval includes zero. Mid-range reliability at 30 minutes: bike forecasts near 45% were observed 63% of the time before and 57% after; dock forecasts near 46% went from 60% to 50% observed.

| Target | 2021 sigmoid (a, b) | 2026 sigmoid (a, b) |
|---|---|---|
| Bike | 0.959, 0.204 | 1.199, 0.472 |
| Dock | 0.985, −0.080 | 1.122, 0.090 |

The parameters are in [artifacts/live_calibration.json](../../../artifacts/live_calibration.json). The app's Live mode applies them when the model version matches and says so in its warnings; `/health` reports `live_calibration`. Only nine held-out late-autumn days support this; it should be refit as collection continues.

Reproduce: `.venv/bin/python scripts/model/recalibrate_live_2026.py --live-root <collector>/divvy/current_validation --write-artifact artifacts/live_calibration.json`
