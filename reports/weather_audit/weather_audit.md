# Open-Meteo weather audit: bounded 2021 Chicago cohort

**NEED_TO_RESTRICT_NOT_REQUIRED**. Coverage and time-of-availability are separate gates. Weather remains **optional / excluded from the certified causal baseline**; this audit does not promote it to required.

## Source, scope and licence

Preferred candidate: [9] [Historical Forecast API](https://open-meteo.com/en/docs/historical-forecast-api); live schema and source: [10] [Open-Meteo Forecast API and data licence](https://open-meteo.com/). Maskable PPO moves to [11] in the proposal reference update.

The fixed app32 historical window is 2021-05-03 00:00 through 2021-08-30 00:00 America/Chicago (exclusive), 2,856 hours, 547,968 recorded station snapshots. UTC/Unix requests include a preceding context day. One weather point at median historical app-station coordinates is used; this does not audit spatial variation at every station.

Explicit GFS Global, GFS Seamless and HRRR models plus Best Match diagnostic were fetched by month, not the full weather archive. Model columns record requested API IDs, not confirmed per-row run lineage; Seamless and Best Match may share an effective model. A present-day two-day live forecast control checks keys/units only; it is not evidence of 2021 information availability. Documentation, raw JSON, URLs, HTTP status, hashes and local processed Parquet are external to Git. Exact provenance is in download_manifest.json.

Weather data by [Open-Meteo.com](https://open-meteo.com/) under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/): attribution, licence link and indication of transformations are required. Free API access is independently limited to noncommercial use and published request quotas; commercial data reuse rights do not make the free API commercial service access free. No upstream AGPL server code was copied. See [licence](https://open-meteo.com/en/licence) and [terms](https://open-meteo.com/en/terms).

## Missingness and schema

The latest proposal enumerates five weather features: temperature_2m, relative_humidity_2m, precipitation amount, wind_speed_10m and weather_code. Apparent temperature, cloud cover and precipitation probability are separate diagnostics; do not silently replace probability with precipitation amount. Per-variable and per-month counts include missing timestamps in the denominator. Threshold <=1% is a source-feasibility diagnostic, not a trained-model acceptance rule.

| Model | Variable | Missing hours / expected | Missing % |
|---|---|---:|---:|
| gfs_global | temperature_2m | 0 / 2856 | 0.00% |
| gfs_global | relative_humidity_2m | 0 / 2856 | 0.00% |
| gfs_global | precipitation | 0 / 2856 | 0.00% |
| gfs_global | wind_speed_10m | 0 / 2856 | 0.00% |
| gfs_global | apparent_temperature | 0 / 2856 | 0.00% |
| gfs_global | weather_code | 2 / 2856 | 0.07% |
| gfs_global | cloud_cover | 0 / 2856 | 0.00% |
| gfs_global | precipitation_probability | 2856 / 2856 | 100.00% |
| gfs_seamless | temperature_2m | 0 / 2856 | 0.00% |
| gfs_seamless | relative_humidity_2m | 0 / 2856 | 0.00% |
| gfs_seamless | precipitation | 0 / 2856 | 0.00% |
| gfs_seamless | wind_speed_10m | 0 / 2856 | 0.00% |
| gfs_seamless | apparent_temperature | 0 / 2856 | 0.00% |
| gfs_seamless | weather_code | 0 / 2856 | 0.00% |
| gfs_seamless | cloud_cover | 0 / 2856 | 0.00% |
| gfs_seamless | precipitation_probability | 2856 / 2856 | 100.00% |
| gfs_hrrr | temperature_2m | 0 / 2856 | 0.00% |
| gfs_hrrr | relative_humidity_2m | 0 / 2856 | 0.00% |
| gfs_hrrr | precipitation | 0 / 2856 | 0.00% |
| gfs_hrrr | wind_speed_10m | 0 / 2856 | 0.00% |
| gfs_hrrr | apparent_temperature | 0 / 2856 | 0.00% |
| gfs_hrrr | weather_code | 0 / 2856 | 0.00% |
| gfs_hrrr | cloud_cover | 0 / 2856 | 0.00% |
| gfs_hrrr | precipitation_probability | 2856 / 2856 | 100.00% |
| best_match | temperature_2m | 0 / 2856 | 0.00% |
| best_match | relative_humidity_2m | 0 / 2856 | 0.00% |
| best_match | precipitation | 0 / 2856 | 0.00% |
| best_match | wind_speed_10m | 0 / 2856 | 0.00% |
| best_match | apparent_temperature | 0 / 2856 | 0.00% |
| best_match | weather_code | 0 / 2856 | 0.00% |
| best_match | cloud_cover | 0 / 2856 | 0.00% |
| best_match | precipitation_probability | 2856 / 2856 | 100.00% |

See missingness_by_variable.csv, missingness_by_month.csv, timestamp_quality.csv and schema_alignment.csv. Hourly keys/units do not prove identical numerical models between 2021 and current forecasts. Model versions, spatial resolution and current availability can change. Wind is requested in m/s, temperature °C and precipitation mm. Precipitation is a preceding-hour total, not a probability.

Use the explicit GFS Global control to review any missing weather-code hours and core calendar-join exclusions. Precipitation probability is a separate diagnostic, not an interchangeable precipitation-amount field. Out-of-range values are reported in value_quality.csv without clipping. Requested aliases that return identical arrays (requested_model_comparison.csv) must not be counted as independent model-replication evidence.

## Temporal alignment versus causal availability

Hourly UTC valid times can be matched backward to snapshot request times with a <=1-hour age bound. This diagnostic never nearest-matches a future valid time and does not interpolate across missing hours. It is **calendar alignment only**, not an authorization to use the result as a feature. See snapshot_join_summary.csv and join_coverage_by_station.csv for all fixed splits and each of 32 stations.

Historical Forecast stitches early forecast hours from successive runs. The responses tested expose hourly valid times, not per-row issued_at / published_at / available_at. generationtime_ms is API processing duration. A row with valid_time <= request_time does not imply its originating run was already published at request time. Likewise a t+h row may come from a newer run than the t request could have seen.

Thus certified request-time-available joins are **unknown/not certifiable**, not a measured 100% and not evidence that every forecast was actually late. Synthetic issuance-gate tests reject rows without available_at and reject runs published after request, even when their initialization or valid time is earlier. Do not fabricate issuance metadata by flooring, delaying one hour or subtracting a model-cycle length.

The [Single Runs API](https://open-meteo.com/en/docs/single-runs-api) preserves initialization/run structure but currently documents later archive starts (IFS from March 2024, other models from April 2026), so it does not automatically solve this 2021 cohort. Initialization alone also needs a defensible publication/ingestion delay. The generic Historical Forecast page contains broad 2022 coverage text while its model table lists earlier GFS/HRRR starts; actual responses, pinned model IDs and per-variable results are used here.

ERA5/reanalysis was **not downloaded or substituted** as primary features. It is valid as a separately labeled retrospective-weather analysis, not as proof of what a request-time forecaster knew.

## Decision and next work

Keep the current historical period, app cohort and frozen model protocol unchanged. Freeze an exact subset/model only after all feature variables and issuance/publication semantics pass. Until then the causal baseline omits weather; a stitched-archive weather ablation must be explicitly labeled with its unverified availability assumption, not presented as leakage-free causal replay.

For future current-data use, archive the live forecast response at receipt time and keep forecast_received_at <= request_time plus valid_time near ETA. That establishes a prospective provenance trail; it cannot retroactively repair 2021. This audit does not silently add weather calls to the running GBFS collector or use its quotas.
