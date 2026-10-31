# Fixed 32-station app cohort

`data_protocol.json` freezes version 1 cohort, exact split dates, horizons, matching, causal feature freshness and training-only OD policy. `selected_stations.csv` contains the same 32 historical IDs as [../app_stations.csv](../app_stations.csv). Original 42-station manifests remain one directory above and are not overwritten.

These are audited data-protocol artifacts; model-ready tables and a full replay evaluator remain pending. See [32-station report](../../../../reports/chicago_historical_audit/app32/README.md).
