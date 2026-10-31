# Supplementary CityBikes Divvy manifests

These historical files are retained as recent change-event feasibility/identity evidence. They are **not** the primary Chicago snapshot manifests or complete replay ground truth. Active primary files are [../chicago/](../../../data/manifests/chicago/README.md).

# Original CityBikes audit context — provisional

| File | Meaning |
|---|---|
| `candidate_stations.csv` | 20 central-Chicago exploratory identities ranked by training observed-event coverage, excluding >50m training movement |
| `selected_stations.csv` | Header-only: no stations have been approved under a frozen final sampling rule |
| `station_id_map.csv` | Publisher UID and observed historical name/location intervals, plus separate current UID/short-code evidence |
| `trip_station_id_map.csv` | Candidate-only trip/archive matches with exact normalized name, <=50m geometry, unique identity, and observed historical time interval |
| `split_manifest.csv` | Proposed UTC train/tune/calibration/test periods with separation; not final training acceptance |

CityBikes hash IDs are not substituted for publisher GBFS UUIDs. A current UID/short-name match is separate evidence, not metadata that was known at a past request time. Observed identity intervals do not certify continuous station-status reporting.

No station selection or rule was chosen using test results. Candidate-only outputs are supplied for this non-commercial audit; the full mapping remains in external local storage. Do not mix these files with the legacy Bay Wheels CSVs in the parent directory.

Bike-share data by CityBikes contributors and available from https://data.citybik.es; its compilation is available under [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/). See [source terms](../../../DATA_SOURCES.md) and [handoff](../../../docs/data_handoff.md) before freezing or publicly redistributing derivative artifacts.
