# Divvy data audit

Audit date: 2026-10-30 (America/Los_Angeles). **Decision: NEED TO RESTRICT; not training-ready yet.**

## Sources and local storage

- CityBikes historical Divvy change records: model feature/label source under an explicitly revised observation policy.
- Official Divvy monthly trips: OD requests and training-only ride-time estimates.
- Official Divvy GBFS: live inference source; discovered from its official auto-discovery document.
- Downloaded **23 CityBikes months and matching trip months**, 624,711,946 bytes. Raw and processed files are outside the Git project, under the user-selected data root. Only code, manifests, source checks, and aggregate reports belong in BikeFlowAI.
- Full provenance: `download_manifest.json`; licenses and attribution: `licensing_and_overlap.md`.

## Actual historical data

- Date range: **2024-11-01T15:13:31Z → 2026-09-30T23:59:24Z** (698.37 calendar days).
- Raw records: **20,882,734**; deduplicated events: **20,882,734**; station identities: **2,233**.
- Duplicate rows removed: 0; conflicting station timestamps: 0, excluded from valid labels.
- Source `nuid` is retained as the publisher GBFS station ID; CityBikes' own hash ID is preserved separately.

**These are inventory-change events, not complete regular snapshots.** The upstream collector drops observations when bike/dock counts do not change. A quiet station may have constant inventory or may be unobserved. Status-flag-only changes can also be suppressed. We do not use unbounded forward-fill or interpret silence as empty/unchanged.
The collector timestamp is treated as UTC and the provider `extra.last_updated` is retained separately. Provider report age is checked; zero/missing dates are not fresh.

## Coverage and gaps

`coverage_by_station.csv` measures the fraction of fixed grid centers with a directly observed fresh event within tolerance. This is an observed-event coverage measure, **not an estimate of polling success**. It can penalize a perfectly functioning station whose inventory stayed constant.
The best station's training seven-minute / ±3.5-minute observed-event coverage is 51.08%. The old Bay Wheels 90% criterion cannot simply be carried over to this different record type.
`gap_summary.csv` reports station change intervals; `network_silences.csv` reports intervals with no network change records for >15 min. These are outage candidates, not confirmed collection outages.
Network change timestamp interval median / p90: 2.000 / 3.017 min; longest network silence: 1164.00 min.

## Chronological train / tune / calibrate / test

Complete UTC calendar weeks, cumulative 60/15/10/15 split, with 60-minute separation before later splits. No label search crosses a split. The purge must be reviewed if the final horizon/tolerance policy changes.

| Split | Start UTC | End UTC (exclusive) | Weeks |
|---|---|---|---:|
| train | 2024-11-04T00:00:00Z | 2025-12-22T00:00:00Z | 59.000 |
| tune | 2025-12-22T01:00:00Z | 2026-04-06T00:00:00Z | 14.994 |
| calibration | 2026-04-06T01:00:00Z | 2026-06-15T00:00:00Z | 9.994 |
| test | 2026-06-15T01:00:00Z | 2026-09-28T00:00:00Z | 14.994 |

These periods have enough calendar duration for 8 weeks training and 2 later weeks testing; observation support and rare events must still be checked per station/horizon. Splits are **provisional**, not certified training tables.

## Label retention and sampling comparison

Fresh base and target events require nonnegative bike/dock counts, known renting/returning flags, positive capacity, no explicit virtual-station flag, and provider report age 0–300 seconds. `is_installed` and disabled counts are not supplied by this historical schema and remain missing; they are not invented from today's GBFS.
Targets use **nearest valid events**, filtering validity before search, with deterministic earlier ties. Matched label observations must be strictly later than their request/base time, even when tolerance is wider than a short horizon. Base/target metadata epochs must match. Missing targets are dropped.

Training-only exploratory selection ranks a predeclared central-Chicago area by training observed-event coverage and excludes >50m training relocation. **20 candidates**, zero approved selections. Test outcomes do not choose stations.

For the exploratory candidates, original k=1…8 and ±3.5 min (whole archive diagnostics):

| k | Horizon (min) | Eligible fresh bases | Retained labels |
|---:|---:|---:|---:|
| 1 | 7 | 1,842,102 | 66.55% |
| 2 | 14 | 1,842,088 | 65.29% |
| 3 | 21 | 1,842,068 | 69.83% |
| 4 | 28 | 1,842,038 | 64.26% |
| 5 | 35 | 1,842,018 | 63.81% |
| 6 | 42 | 1,841,993 | 68.46% |
| 7 | 49 | 1,841,975 | 62.83% |
| 8 | 56 | 1,841,955 | 62.35% |

`label_retention.csv` also compares 15/30/45/60-minute horizons, 210/300/450-second tolerances, all stations versus training candidates, and every split. Wider tolerances improve retention at the cost of time precision; no setting is approved automatically.
Rates are **conditional on observing a change**, and are not evidence of uniform-time replay coverage or final lag-feature completeness. `class_balance.csv` is likewise event-weighted, not time-weighted occupancy.

## Field quality and station changes

Counts below overlap; denominator 20,882,734 deduplicated events:

- missing_or_negative_counts: 0 (0.00%).
- unknown_operating_flags: 0 (0.00%).
- capacity_zero_or_missing: 27 (0.00%).
- explicit_virtual: 0 (0.00%).
- virtual_flag_missing: 2,646,750 (12.67%).
- last_reported_zero_or_missing: 0 (0.00%).
- report_age_gt300s: 1,200,625 (5.75%).
- future_report_time: 0 (0.00%).
- not_renting: 20,480 (0.10%).
- not_returning: 20,480 (0.10%).
- is_installed_unavailable: 20,882,734 (100.00%).
- disabled_counts_unavailable: 20,882,734 (100.00%).
- usable_inventory_sum_ne_capacity: 17,661,755 (84.58%).

`station_changes.csv` contains 8,013 observed metadata changes. The Divvy `station_id_map.csv` contains 2,470 observed identity intervals. These intervals describe metadata provenance, not uninterrupted status reporting. Capacity-minus-bikes must not replace measured dock counts; disabled inventory is unavailable.

## Trips, timezones, and live inference

The official GBFS reports **America/Chicago**, not Pacific time. Historical collector epochs are UTC. Naive trip timestamps require America/Chicago localization with explicit ambiguous/nonexistent DST handling. Trip-date coverage, mapped endpoints, OD support, and training-only ride-time estimates are reported separately in `trip_overlap.json` / `trip_overlap.md` when the trip audit is complete.
The captured official GBFS has 2078 information stations and 2078 status stations. Historical identities with exact current publisher UID matches: 2062. A current UID match does not establish continuous historic station availability. See `live_gbfs_check.json`.
Live inference has a richer schema than the historical change archive; model features must use the historical/live intersection or explicitly handle missing fields. The current one-time live capture is not a feed-uptime audit.

## Decision and remaining acceptance

**NEED TO RESTRICT**: there is substantially more calendar history available, but event-only semantics, absent heartbeat/status-only changes, unapproved sampling thresholds, and missing historical GBFS fields prevent an unconditional PASS for the original complete-snapshot/replay architecture.
Use only directly observed, freshness-checked labels for an explicitly event-conditioned experiment, or obtain a historical polling/heartbeat source before claiming uniform-time replay. A new GBFS collector can extend history but cannot retroactively certify past silence.
Complete trip mapping/DST and frozen sampling rules before training. Preserve explicit exclusions, retain the held-out test, and do not call the provisional candidate list a final 20-station selection.
