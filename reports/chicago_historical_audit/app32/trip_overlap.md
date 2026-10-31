# Matching-period official Divvy trips and OD audit

Streamed **2,887,990** actual rows from four official ZIPs; no full CSV was unpacked. **2,792,957** trip starts are inside the declared sample period.
The audit covers 32 historical stations in its mapping cohort, not the entire network. Trips whose endpoints are outside that cohort are out of scope, not failed mappings.

- Trips with both endpoint names in the audited cohort and start inside the window: **38,413**.
- Both endpoints mapped by exact historical name, unique identity, <=50m geometry, and observed metadata interval: **36,007** (93.74% of the named-cohort denominator).
- Trips with both endpoints among the training-selected 32 stations: **36,007**.
- Those selected-cohort trips with pickup and return valid snapshots within ±5 min: **34,854** (96.80%).
- Trips with both station contexts available as-of departure (<=15 min old, no future snapshot inputs): **36,003**.
- Trips with both causal contexts and pickup/return observation support: **34,850**. Source publication latency is not measured; this is a feasibility check, not an implemented replay evaluator.
- Eligible training-only rides for OD estimates: **18,571**.
- Observed OD pairs: **806**; pairs with >=20 training trips: **229**. Use the proposal's geometric fallback for unsupported pairs.

Source IDs, trip codes, and 2026 GBFS IDs remain separate string namespaces. Mapping does not copy current metadata into the past. Naive trip times follow the explicit America/Chicago policy; ambiguous/nonexistent local times are excluded (0 rows here).

The observation-support number reflects approximate 10-minute ground truth, not exact arrival stock before a real checkout/return. Trip events themselves change inventory, and completed rides omit unmet demand. Final replay timing, interpolation exclusions, and causal feature rules must be approved before reporting model/policy performance.

`trip_station_id_map.csv` records aggregate correspondence evidence. `od_ride_times.csv` uses only training rides (both endpoints in training, duration 60 seconds to 6 hours). No tuning/calibration/test trips estimate OD medians.
