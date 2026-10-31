# App cohort: 32 stations, protocol version 1

**PASS_BOUNDED_SNAPSHOT_FEASIBILITY** for the fixed 32-station cohort. This is separate from the original 42-station audit. Training tables and a full replay evaluator are not implemented/certified.

| Check | Result |
|---|---:|
| Historical sample | 2021-05-03 to 2021-08-30 (exclusive), 17 weeks |
| App stations | 32 distinct historical IDs and 32 distinct matched live IDs |
| Lowest per-station valid coverage across splits | 99.8010% |
| Lowest aggregated label retention across splits/horizons | 99.7997% |
| Bike / dock unavailable, selected sample | 12.21% / 3.60% |
| Both endpoints mapped among trips naming this app cohort | 93.74% |
| Mapped app trips with pickup/return observations within +/-5min | 96.80% |
| Mapped app trips with both station contexts as-of departure, <=15min old | 99.99% |
| Eligible training-only OD rides | 18,571 |
| Observed OD pairs / pairs with >=20 training rides | 806 / 229 |

| Horizon minutes | Sample label retention |
|---:|---:|
| 10 | 99.9298% |
| 20 | 99.9240% |
| 30 | 99.9181% |
| 40 | 99.9240% |
| 50 | 99.9240% |
| 60 | 99.9240% |

The mapping denominator above is restricted to the 32 app stations; the snapshot audit retains all 50 candidate diagnostics and marks the fixed 32 as its selected report cohort. No held-out label or performance metric selects/removes a station. The 2026 identity filter defines a deployable subset and must not be described as unbiased full-network performance.

Station IDs are strings. Current identity is serving/mapping evidence only; historical features use historical observations. Known broad historical closure is an unavailable label; current renting/returning/installed flags are checked separately in live serving.

Feature context uses the latest valid recorded snapshot <= decision time with maximum age 900 seconds. Future observations are permitted only for offline target labels/outcome scoring. Missing/stale features or outcomes exclude the request; exact source publication latency is unmeasured. The as-of support check is not a trained model, causal stock-before-checkout proof, or implemented full replay.

The frozen split dates are in [split_manifest.csv](../../../data/manifests/chicago/app32/split_manifest.csv). Whole-week rounding yields 10/2/2/3 calendar weeks with 60-minute separation before later splits, rather than exact percentage durations.

See [snapshot audit](data_audit.md), [trip/OD audit](trip_overlap.md), [protocol](../../../data/manifests/chicago/app32/data_protocol.json), and [app stations](../../../data/manifests/chicago/app_stations.csv). Raw data stays outside Git. Source terms and the required City notice remain applicable.
