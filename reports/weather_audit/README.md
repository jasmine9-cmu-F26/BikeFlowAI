# Weather source feasibility and causal availability

Read [weather_audit.md](weather_audit.md). **Coverage passes; strict request-time availability remains unverified. Weather is not promoted to required.**

- `missingness_by_variable.csv`, `missingness_by_month.csv`: four requested model configurations, five proposal variables and three diagnostics.
- `timestamp_quality.csv`, `schema_alignment.csv`: hourly UTC cadence, live/historical keys and units.
- `snapshot_join_summary.csv`, `join_coverage_by_station.csv`: backward valid-time alignment for 547,968 snapshots / 32 stations. This is not forecast publication-time provenance.
- `value_quality.csv`, `requested_model_comparison.csv`: bounds checks and model alias equality.
- `download_manifest.json`, `source_inventory.json`, `audit_summary.json`: exact queries/hashes, licence and decision.
- `proposal_revision.json`: original/revised Word hashes; [reference update](../../docs/proposal_references.md).

The external data root is `Documents/BikeFlowAI-data/divvy/weather_open_meteo_audit/`; no raw weather/reanalysis is committed. Weather data by [Open-Meteo.com](https://open-meteo.com/), CC BY 4.0. API service access terms are separate.
