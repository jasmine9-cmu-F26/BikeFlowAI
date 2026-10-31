# Matching-period official Divvy trips and OD audit

Streamed **2,887,990** actual rows from four official ZIPs; no full CSV was unpacked. **2,792,957** trip starts are inside the declared sample period.
The audit covers 50 historical candidate stations, not the entire network. Trips whose endpoints are outside that cohort are out of scope, not failed mappings.

- Trips with both endpoint names in the audited cohort and start inside the window: **111,891**.
- Both endpoints mapped by exact historical name, unique identity, <=50m geometry, and observed metadata interval: **104,609** (93.49% of the named-cohort denominator).
- Trips with both endpoints among the training-selected 42 stations: **79,320**.
- Those selected-cohort trips with pickup and return valid snapshots within ±5 min: **76,834** (96.87%).
- Eligible training-only rides for OD estimates: **42,356**.
- Observed OD pairs: **1,423**; pairs with >=20 training trips: **424**. Use the proposal's geometric fallback for unsupported pairs.

Source IDs, trip codes, and 2026 GBFS IDs remain separate string namespaces. Mapping does not copy current metadata into the past. Naive trip times follow the explicit America/Chicago policy; ambiguous/nonexistent local times are excluded (0 rows here).

The observation-support number reflects approximate 10-minute ground truth, not exact arrival stock before a real checkout/return. Trip events themselves change inventory, and completed rides omit unmet demand. Final replay timing, interpolation exclusions, and causal feature rules must be approved before reporting model/policy performance.

`trip_station_id_map.csv` records aggregate correspondence evidence. `od_ride_times.csv` uses only training rides (both endpoints in training, duration 60 seconds to 6 hours). No tuning/calibration/test trips estimate OD medians.
