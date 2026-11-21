# Dock-side results where docks are scarce

Open docks are missing only 2–3% of the time across the 32 stations, so network averages hide the dock forecast. This scores it where docks are actually scarce. **Every subset is chosen from decision-time information only, never from outcomes:**

- **Nearly full now:** ≤ 2 open docks in the base observation.
- **Busy dock hour / destination:** the training-period (B2) dock-unavailable rate for that station and hour is ≥ 10%.

## A. Dock forecast (target: no open dock at +10…60 min)

| Data | Subset | Share of rows | Full-dock rate | Brier B1 / B2 / **LGBM** | PR-AUC B1 / **LGBM** | LGBM vs B1 (95% CI) |
|---|---|---|---|---|---|---|
| 2021 tune | all | 100% | 2.3% | 0.014 / 0.028 / **0.010** | 0.47 / **0.74** | −30% (−32 to −26) |
| 2021 tune | nearly full now | 6% | 33% | 0.196 / 0.273 / **0.128** | 0.60 / **0.81** | **−35%** (−39 to −31) |
| 2021 tune | busy dock hour | 14% | 7.2% | 0.041 / 0.108 / **0.029** | 0.54 / **0.79** | −28% (−31 to −25) |
| 2026 live | all | 100% | 3.2% | 0.016 / 0.037 / **0.012** | 0.58 / **0.80** | −23% (−27 to −19) |
| 2026 live | nearly full now | 10% | 30% | 0.138 / 0.262 / **0.102** | 0.66 / **0.83** | **−26%** (−30 to −22) |
| 2026 live | busy dock hour | 15% | 8.0% | 0.028 / 0.112 / **0.023** | 0.69 / **0.87** | −18% (−23 to −10) |

When a destination has two or fewer open docks, about one in three will be full on arrival. Current counts cannot tell which; the forecaster separates them (PR-AUC 0.81–0.83 against 0.60–0.66) in both 2021 and 2026. B1 is the better baseline everywhere; B2's calendar rates are worst. Intervals are day-block bootstraps (14 days in 2021, 22 in 2026: 2026-10-31 to 11-21).

## B. Trip planner: arriving at a full dock

Replay of the 20,071 tune grid requests (λ = .02, f = .1; the [conditioned_f0.1](../rl_eval/conditioned_f0.1/README.md) setting). A **full-dock arrival** is a failed return attempt: the rider reaches a full station and rides on to a backup. It rarely fails the whole trip, so trip-level return failure (0.1–0.6%) hides it. "Busy destination" = destination at ≥ 10% B2 dock risk at checkout hour (1,835 riders). RL is the mean of three seeds.

| Walk limit | Riders | Full-dock arrivals per 100 riders: B1 / B2 / **B3** / RL | B3 − B1 (95% CI) |
|---|---|---|---|
| 5 min | all | 1.02 / 1.08 / **0.80** / 1.04 | −0.21 (−0.41 to −0.07) |
| 5 min | busy destination | 4.09 / 3.93 / **3.55** / 4.15 | **−0.55** (−1.20 to −0.12) |
| 10 min | all | 0.78 / 1.03 / **0.49** / 0.85 | −0.29 (−0.50 to −0.11) |
| 10 min | busy destination | 2.94 / 3.60 / **2.29** / 2.96 | **−0.65** (−1.52 to −0.11) |
| 15 min | all | 0.76 / 0.99 / **0.41** / 0.82 | −0.34 (−0.58 to −0.16) |
| 15 min | busy destination | 2.72 / 3.05 / **1.91** / 2.78 | **−0.82** (−1.79 to −0.21) |

- **The forecast-driven planner (B3) sends riders to full docks 13–30% less often at busy destinations** and 21–45% less often overall, with every interval excluding zero.
- **RL does not use the dock forecast on the return leg:** its full-dock arrivals match B1 (overall slightly more, e.g. +0.07 per 100 at 10 min). Its advantage is on the pickup side. The app already serves the return itinerary with B3 (`RL_pickup+B3_return`), which is the better choice here; giving RL a return-side signal is open work.
- Counting full-dock arrivals required a new counter in the replay environment (`return_failures`); outcomes are identical to the committed evaluation (checked).

Reproduce:

```bash
# A only (from the repo bundle; add --live-root for 2026):
.venv/bin/python scripts/model/dock_pressure.py --live-root <collector>/divvy/current_validation
# B: evaluate.py --lam 0.02 --f 0.1 --walk-limit {5,10,15} with the three f=0.1 seeds, then
#    --episodes <reports>/walk_*_lam_0.02/episodes.csv
```
