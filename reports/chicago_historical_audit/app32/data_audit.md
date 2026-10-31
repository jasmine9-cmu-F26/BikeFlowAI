# Official Chicago Divvy snapshot feasibility audit

Audit date: 2026-10-30. **PASS_BOUNDED_SNAPSHOT_FEASIBILITY**. This is a bounded source/cohort feasibility result, not certification of a complete model or arbitrary exact-time truth.

## Sample and provenance

- Source: [Chicago official dataset eq45-8inv](https://data.cityofchicago.org/d/eq45-8inv), classified historical-only; [Data.gov description](https://catalog.data.gov/dataset/divvy-bicycle-stations-historical).
- Declared local window: **2021-05-03T00:00:00 → 2021-08-30T00:00:00**. The source's floating times are explicitly interpreted as America/Chicago; raw wall times are retained. The API schema itself provides no timezone offset.
- **856,200** downloaded rows, **856,200** normalized rows, **50** sampled stations. The full ~242-million-row dataset was not exported or independently recounted.
- Initial candidates came only from a predeclared central-Chicago training anchor, sorted by exact station ID. Final eligibility uses training coverage, service fraction, capacity/name stability, and <=50m training movement; test outcomes do not select stations.
- Raw compressed snapshot bytes: 7,943,527; matching-month official trip ZIP bytes: 102,965,549. Raw/processed files stay outside Git. `download_manifest.json` records query URLs, bounds, hashes and source metadata.
- Source station IDs and current GBFS IDs remain strings; no floating-point conversion of long identifiers.

## Cadence, coverage, missingness

- Unique cohort poll interval median / p90: **10.000 / 10.583 min**.
- Longest gap in the sampled network timestamps: **38.33 min**; see `network_gaps.csv` and per-station `gap_summary.csv`.
- Grid: 10 minutes, phase 360 seconds (learned from training only), ±5 min observation tolerance. Denominators use the entire declared split, not each station's lifetime. Presence and valid-state coverage are separate.
- Training-qualified stations in this report cohort: **32** stations. Lowest selected valid coverage across all four splits: **99.80%**.
- Unchanged consecutive inventory fraction: **66.81%**. These repeated full observations are retained, unlike change-event-only archives.
- Source metadata documents: `2013 to 9/10/2022, except for 7/7/2019 - 12/9/2019 and 2/28/2022 - 4/20/2022`. Additional gaps found by a sample must be reported rather than hidden by compressing calendar time.

## Chronological splits

The requested window is divided into whole local calendar weeks using nominal 60/15/10/15 proportions rounded to whole-week cumulative boundaries (actual 10/2/2/3 weeks in this 17-week sample), with 60-minute separation before later splits. Source/feature timestamps are UTC after documented localization; targets and matched observations cannot cross splits.

| Split | Start UTC | End UTC (exclusive) | Weeks |
|---|---|---|---:|
| train | 2021-05-03T05:00:00Z | 2021-07-12T05:00:00Z | 10.000 |
| tune | 2021-07-12T06:00:00Z | 2021-07-26T05:00:00Z | 1.994 |
| calibration | 2021-07-26T06:00:00Z | 2021-08-09T05:00:00Z | 1.994 |
| test | 2021-08-09T06:00:00Z | 2021-08-30T05:00:00Z | 2.994 |

## Availability labels

For each open, valid base snapshot, the target is t+h. Search valid snapshots first, choose the nearest strictly future observation within ±5 min, break ties earlier, and reject >50m base/target relocation. No filling across missing intervals is performed.
Bike availability requires source `In Service` and available_bikes>0; dock availability requires `In Service` and available_docks>0. Known closed status is a negative availability outcome. Missing counts/status are exclusions, never empty labels.
The old archive does not expose separate current GBFS installed/renting/returning or disabled-bike flags. The broad status-based historical label and historical/live feature intersection need explicit model-design review.

| Horizon (min) | Eligible bases | Sample label retention |
|---:|---:|---:|
| 10 | 547,180 | 99.93% |
| 20 | 547,148 | 99.92% |
| 30 | 547,116 | 99.92% |
| 40 | 547,084 | 99.92% |
| 50 | 547,052 | 99.92% |
| 60 | 547,020 | 99.92% |

Lowest selected retention over each split/horizon: **99.80%**. `label_retention.csv` and `class_balance.csv` include all sampled versus training-selected cohorts. Selected sample bike/dock unavailable fractions: **12.21% / 3.60%**.
Labels have 10-minute resolution with a documented matching error; this is not exact continuous-time ground truth. Full lag-feature completeness and end-to-end replay are not implemented by this feasibility audit.

## Historical trip and 2026 live identity

`station_id_map.csv` versions observed historical names/coordinates/capacities and splits intervals at >30-minute observation gaps. `live_station_overlap.csv` compares current official GBFS by exact normalized name and <=50m coordinates, requiring uniqueness; name-changed spatial candidates remain unconfirmed.
Current exact name+geometry matches among the selected cohort: **32**. Current UID/short-code evidence is not copied into past features or treated as proof of continuous operation since the sample year.
Same-period official trip mapping, training-only OD medians, and pickup/return observation support are reported separately in `trip_overlap.md` after the trip audit. Historical IDs, trip station codes, and 2026 GBFS station IDs must not be assumed identical.

## License and acceptance

The publisher labels the dataset **SEE_TERMS_OF_USE / See Terms of Use**, not CC0 or the CityBikes ODbL. Follow the City's [Data Terms of Use](https://www.chicago.gov/city/en/narr/foia/data_disclaimer.html), including the required application disclaimer and any additional agency terms. Official trips and live GBFS have separate source-specific terms.

Diagnostic feasibility thresholds are >=20 training-stable stations, >=90% valid coverage in every split, and >=90% label retention per horizon/split. A passing small audit establishes only this sampled source/period/cohort. The fixed app cohort, exact splits and timing rules are frozen in data_protocol.json version 1. Feature generation, historical/live feature semantics, model evaluation, and old-to-2026 domain shift remain separate tasks.
CityBikes recent records remain supplementary feasibility/identity evidence and are not arbitrary-time ground truth. The new full-GBFS collector provides future current-data sanity checks, not retroactive repairs to old gaps.
