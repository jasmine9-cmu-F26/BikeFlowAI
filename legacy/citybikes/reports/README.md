# Supplementary recent CityBikes audit

The source is no longer the primary training/replay dataset. Its original quantitative audit and provenance are preserved below as feasibility/identity evidence. Change-event silence is not arbitrary-time ground truth. The primary official snapshot audit is [../chicago_historical_audit/](../../../reports/chicago_historical_audit/README.md).

# Original CityBikes audit context

Start with [data_audit.md](data_audit.md), [trip_overlap.md](trip_overlap.md), and [licensing_and_overlap.md](licensing_and_overlap.md).

The new source design is CityBikes historical Divvy for observed model inputs/labels, official trips for OD/ride times, and official GBFS for live inference. Current decision: **NEED TO RESTRICT**, not a certified training dataset.

`coverage_by_station.csv` describes observed change-event coverage, not polling uptime. `gap_summary.csv` and `network_silences.csv` cannot prove whether silence means constant inventory or an outage. `class_balance.csv` is event-weighted. `label_retention.csv` filters validity before nearest matching, checks report age and station epochs, and keeps splits separate.

The candidate cohort is selected using training evidence only; all split/horizon results remain diagnostics. `candidate_od_ride_times.csv` uses training trips only. Its candidate mappings and OD aggregates do not create a final approved station list or certify uniform-time replay coverage.

Raw Parquet/ZIP/CSV, captured live JSON/pages, normalized events, complete mappings, and full OD tables are stored in the external data root, not here. `download_manifest.json` records their provenance. Scripts allow different report/manifest destinations for repeat experiments.

Bike-share data by CityBikes contributors and available from https://data.citybik.es. Contains information from the CityBikes database, available under [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/). Official trip terms and the live catalog/publisher license distinction are explained in the licensing review and [DATA_SOURCES.md](../../../DATA_SOURCES.md).
