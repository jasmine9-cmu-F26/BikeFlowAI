# Replay input freshness

**Keep replay <=15 minutes; live serving <=5 minutes.** Fifteen minutes was already frozen; this comparison does not choose a new threshold using held-out outcomes.

| Max age (min) | Mapped app32 requests | Both station contexts fresh | Input retention | Input exclusions | Full restricted replay-request support |
|---:|---:|---:|---:|---:|---:|
| 10 | 36,007 | 35,438 | 98.4198% | 569 | 31,734 |
| 15 | 36,007 | 36,003 | 99.9889% | 4 | 32,246 |
| 20 | 36,007 | 36,007 | 100.0000% | 0 | 32,250 |

Current inputs read only the latest valid recorded snapshot <= departure time for **both** requested stations. Future arrivals are separate outcome reads within ±5 minutes. The final support column additionally requires open current endpoints, duration 60s..6h, arrival within the same chronological split, and observable pickup/return snapshots. It is not model/policy performance and does not account for every counterfactual station that a learned policy might consider.

[freshness_comparison.csv](freshness_comparison.csv) contains split-specific trip-time checks and a fixed ten-minute station grid. Their denominators differ; fixed grid rows describe individual station contexts, whereas trip-time rows require both endpoint contexts. Twelve mapped starts fall in purge intervals and cannot enter the restricted replay pool. External mapped request rows include the explicit 15-minute retention flag.

Live 5-minute freshness is a future serving cache/provider timestamp contract. The prospective five-minute Google validation collector is **not** the live serving cache and does not guarantee that a live request will always be fresh. Current GBFS flags still govern usability. Historical publication latency is unmeasured; no claim of exact continuous-time state is made.
