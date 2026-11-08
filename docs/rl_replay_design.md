# RL planner on causal replay: design

Status: implemented 2026-11-08 in `scripts/rl/`, on top of the forecaster in `scripts/model/` (`train_forecaster.py`, `build_forward_predictions.py`); tested on synthetic tables and run on the real tune split. Owner role C (RL) with E (evaluation).

## Intent

The proposal adds a MaskablePPO policy on top of the forecaster and evaluates it against greedy ranking (B3) on identical requests. RL can only add value through sequential choices: waiting, backups after a failure, and keeping a near alternative in reserve. This design builds the replay environment, the greedy baselines and the PPO policy so that the whole chain runs as soon as the audited tables exist locally.

Non-goals for this version: crowd effects (many riders sent to one station), road routing, live serving, the API/UI.

## Decision view and outcome view

The environment reuses the audited tables instead of re-reading raw snapshots.

- **Decision view**, keyed by `(station_id, request_time, horizon_minutes)`: current bikes/docks/capacity from `features/`, the calibrated forecaster probabilities for that row, and B2 rates for the arrival hour. This is everything a policy may see.
- **Outcome view**, same key: `bike_unavailable` / `dock_unavailable` from `labels/`. The environment reads it only after an action is fixed, to decide success or failure. Policies and observations never receive it.

Forecaster probabilities come from models that never saw the scored week:

- training weeks 2 to 9: forward-chaining (`make forward`), week *w* is scored by a model fitted on rows whose target time is before week *w*−1, early-stopped and provisionally calibrated on week *w*−1. Weeks 0 and 1 have no scores and are not used for policy training.
- tune: the calibrated `LGBM` columns of `tune_predictions.parquet` from `make train` (provisional calibration on the last 14 training days). Test: the final forecaster only, with its calibrator refit on the calibration split; nothing writes `forecaster_final/predictions_test.parquet` yet, so `make rl-eval-final` cannot run.

B2 and ride times follow the same rule: `train_week_k` versions for training weeks, held-out versions for tune and later.

## Episode

Each request is an origin station, a destination station and a checkout time *T*. There are two request sets (`--requests`):

- **`grid`** (default, the main evaluation): at every decision time *q* and every station, a Poisson number of riders with mean `demand_scale` × (training departures per hour from that station at that Chicago hour, weekday or weekend) / 6, each checking out at *T* = *q* + 10 minutes, with a destination drawn from that station's training destination shares. Rates and shares come from training trips only: all of them for tune and test, and only the weeks before week *k* for training week *k*. Nothing conditions on whether a bike was there, which is the situation of a rider who opens the app. `demand_scale` (default 5) only multiplies the number of draws; `--request-seed` fixes them.
- **`trips`** (secondary): completed trips from `mapped_app32_requests.parquet` with `replay_15min_request_retained`, origin the start station, destination the end station. This is the real-trip replay the proposal promised, but it is conditional on the trip having succeeded (see Known limits).

On tune, the origin is empty at the first pickup horizon for 18.3% of grid requests and 3.4% of trip requests.

- First decision time *q0*: the last 10-minute grid point (phase 360 s) at least 10 minutes before *T*.
- Pickup candidates: the origin station plus stations within **10 minutes** of extra walking (straight line at 1.3 m/s), nearest first, at most 3. The proposal's product default is 5 minutes; with only 15 of 32 stations having any alternative within 5 minutes, replay uses 10 minutes and reports say so.
- Return candidates: the destination station plus stations within 10 minutes' walk of it, at most 3.
- Arrival horizon for a pickup slot: walking time rounded up to 10 minutes, at least 10. For a return slot: ride time from the pickup station, rounded up, at least 10. Ride time is the training median (≥20 trips) else 1.3 × haversine / 4 m/s.
- Actions: `0..2` choose slot, `3` wait 10 minutes. Waiting is allowed only in the pickup phase, at most twice.
- After a failed pickup the rider stands at the failed station; remaining candidates are re-measured from there. After a failed return the rider rides on to a remaining return candidate.
- Mask: empty slot, station already tried, horizon above 60 minutes, decision row (or its forecaster score) missing, or a third wait.
- The trip fails (`−c`) once every candidate of the current phase has been tried. If actions are all masked before that, or a chosen action's outcome row is missing, the episode ends as unobservable with no failure penalty; evaluation reports the count per policy.
- A masked action ends the episode as `invalid` with `−c`, so the environment accepts any action as the Gymnasium API requires. MaskablePPO never samples one, and the evaluator raises if a policy does.
- Station geometry (walking and the ride-time fallback) uses the fixed `historical_lat/lon` in `app_stations.csv` for every split.

Reward: `+1` for a completed pickup and return, `−λ` per extra walking minute, `−μ` per waiting minute, `−c` on failure. Pickup walking is charged on every attempt (the rider really walked to a failed station); the walk from the return station to the destination is charged once, on success. Defaults λ = 0.02, μ = 0.01, c = 0.5; evaluation sweeps λ.

## Policies

- **Greedy family** (one rule, three probability sources): score each valid slot by its expected one-step reward `1 − (1 + c)·p_fail − λ·walk`; score waiting by the best slot's value with `p_fail` at horizon + 10, minus `μ·10`; take the best. B1 uses hard current emptiness (so waiting never helps), B2 uses historical rates, B3 uses the calibrated forecaster.
- **RL**: MaskablePPO (sb3-contrib) on a 31-number observation: per slot (valid, walk, horizon, current count share, currently empty, forecaster p_fail at horizon and at horizon + 10, B2 p_fail, tried) plus phase, waits used, minutes elapsed, failures so far.

## Evaluation

All policies run the same tune requests with the same λ, μ, c. Report trip success, pickup and return failure, failed attempts, extra walk (mean, median, p90), waiting, mean reward, and unobservable episodes. Paired differences (RL − B3, RL − B1, B3 − B1, B3 − B2) on success, reward, walk and wait use requests observed under both policies, with Chicago-day bootstrap intervals; `comparisons.csv` lists the number of days, because an interval over a handful of days means little. Test is used once, with frozen settings (`make rl-eval-final`).

### λ sweep

Mean reward ranks policies only for one λ, and λ is a product choice, not a fact. `make rl-sweep` ([`sweep.py`](../scripts/rl/sweep.py)) therefore retrains PPO with seeds 0, 1, 2 for each λ in {0, 0.005, 0.01, 0.02, 0.04, 0.08, 0.16, 0.32}, reruns B1/B2/B3 with the same λ on the same grid requests, and plots failed trips against walking and against walking plus waiting (`reports/rl_eval/lambda_sweep/frontier.png`). Seeded runs reproduce exactly. On tune (20,071 grid requests, μ = 0.01, c = 0.5):

- B3 fails 3.89% to 3.94% of trips for every λ up to 0.08, while its mean walk falls from 6.4 to 1.2 minutes; walking beyond that buys nothing. At λ = 0.08 it walks as much as B1 (−0.03 minutes, interval −0.06 to 0.00), fails 1.0 point less (0.67 to 1.34), i.e. 21% fewer failed trips (interval 14% to 27%), and waits 1.1 minutes more. Above 0.08 it trades walking for waiting and starts to fail more (4.38% at 0.32).
- RL fails 3.94% to 4.22% across λ (seed spread up to 0.2 points), walks 0.8 to 1.1 minutes for λ ≥ 0.005, and has a higher mean reward than B3 for every seed at λ from 0.005 to 0.08 (two of three seeds at 0.16, none at 0 or 0.32). Its best points sit next to B3 at λ = 0.08 on both plots, so RL beats a greedy rule tuned for the same λ but not B3 at its best λ. RL−B3 success differences below about 0.3 points change sign or significance with the seed.

## Known limits

Replay snapshots already contain the real rider's own checkout and other riders' unmet demand is invisible; one simulated rider cannot change station stock. Ten-minute quantization of walking and riding. A row whose label is missing stays in the decision view, so a policy can choose it and end unobservable; at the audited 99.8% retention this is a small effect, reported per policy. The trip/OD audit asks for fallback geometry from metadata as of each request; replay uses the fixed historical coordinates of the 32-station manifest instead, which do not move with time but are summaries over the whole window.

Trip requests are completed trips, so the rider did find a bike at the origin. On tune, the origin was empty at the first pickup horizon for 3.4% of them, against 16.3% over all station-times, and the forecaster (calibrated on all station-times) gives these origins 9.1% on average. Greedy rules that trust the forecaster therefore walk to alternatives more than this request set rewards, and policies that stay at the origin look better than they would for a rider who opens the app without knowing. Results on trip requests answer "does the planner hurt riders who would have succeeded?", not "how many failures does it prevent?"; grid requests answer the second question.

Grid requests are synthetic. Their departure rates come from completed trips, so demand at stations that were often empty is undercounted; grid riders are independent episodes and do not compete for the same bike; and destinations follow the origin's average shares, not the hour's.

LightGBM/sklearn and torch each bundle libomp, and two OpenMP runtimes in one macOS process crash or deadlock. Forecasting and RL therefore run in separate processes (`make pipeline` already does), the replay modules never import lightgbm or sklearn, and tests that train PPO do so in a child process.

## Commands

```
make train             # tune probabilities  -> $DATA_ROOT/models/forecaster_v0_m3/tune_predictions.parquet
make forward           # training weeks 2+   -> .../forward_train_predictions.parquet
make rl-train          # MaskablePPO         -> $DATA_ROOT/models/rl_dev/ppo.zip (+ .json manifest)
make rl-eval           # B1/B2/B3/RL on tune -> reports/rl_eval/tune/
make pipeline          # the four steps above in order
make rl-sweep          # 8 λ x 3 PPO seeds   -> reports/rl_eval/lambda_sweep/ (about 10 minutes, 8 jobs)
```

`rl-train` needs `pip install -r scripts/rl/requirements-ppo.txt` (torch); CI installs only `requirements.txt` and skips the PPO tests.
