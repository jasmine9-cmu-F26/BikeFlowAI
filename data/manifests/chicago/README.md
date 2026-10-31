# Primary Chicago sample manifests

The active 2021 sample qualifies **42 historical stations using training data only**. Their selection is a bounded data-feasibility result, not final model-protocol approval or proof of 2026 accuracy.

- `candidate_stations.csv`: 50 initially sampled central-Chicago stations selected from one predeclared training-anchor poll, not from test outcomes.
- `selected_stations.csv`: training-stable sample cohort (coverage >=90%, name/capacity stable, <=50m training movement, >=80% training In Service). Test results do not remove stations from this list.
- `split_manifest.csv`: provisional 10/2/2/3-week chronological split, with separation before later splits.
- `station_id_map.csv`: observed historical metadata intervals, split at changes and >30-minute gaps; current evidence is separate from past features.
- `trip_station_id_map.csv`: aggregate exact-name/geometry/time evidence for same-period trip codes and historical IDs.
- `failed_2022/`: preserved failed May–August 2022 comparison; it has no training-qualified cohort under the same rule.

Historical IDs use a `chicago:` namespace. Trip codes and current GBFS IDs must not be joined directly to that namespace or parsed as floats. The live comparison is in `reports/chicago_historical_audit/live_station_overlap.csv`. A nearby renamed site is a candidate for review, not a confirmed match; an unconfirmed site is not automatically declared removed.

The primary metadata comes from the official City snapshot source, not CityBikes. Review [City terms and the required application notice](../../../NOTICE_CHICAGO.md), [source terms](../../../DATA_SOURCES.md), and [handoff](../../../docs/data_handoff.md).

## App cohort version 1

The fixed 32-station subset is in [app_stations.csv](app_stations.csv), with its own [protocol and manifests](app32/README.md). The original 42-station `selected_stations.csv` and original split manifest remain unchanged.
