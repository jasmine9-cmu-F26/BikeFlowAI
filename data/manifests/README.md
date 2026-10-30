# Manifest status

All current CSV files describe the initial archive audit. They are **provisional**, and their original contents are retained for traceability.

| File | Meaning | Still required before training |
|---|---|---|
| `candidate_stations.csv` | Exploratory SF candidates ranked using initial training-period coverage | Reselect under the approved revised rule, using training evidence only |
| `selected_stations.csv` | Header-only because no station passed the original seven-minute / 90% gate | Validate and freeze 20–50 stations under the revised rule |
| `station_id_map.csv` | Observed historical metadata intervals; current GBFS IDs blank | Reconcile trip IDs and archive identities across metadata changes; validate any current-ID mapping separately |
| `split_manifest.csv` | Proposed chronological training, tuning, calibration, and test periods | Recheck boundaries and purge requirements with the chosen horizons and look-back windows, then freeze |

An empty selection is an explicit outcome of the old gate, not an approved empty training set. An open-ended historical metadata interval does not prove validity through the present or uninterrupted station reporting.

Do not fill current IDs or merge stations by guessed name similarity. Record evidence, effective dates, ambiguous matches, and exclusions when implementing the revised mapping.

See the [data handoff checklist](../../docs/data_handoff.md) for the acceptance steps. CSV values and the original audit decision should change only after the revised analysis has been run and recorded.
