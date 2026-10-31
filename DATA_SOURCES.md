# Data sources, attribution and terms

## Primary historical training/replay

City of Chicago, **Divvy Bicycle Stations – Historical**, dataset [eq45-8inv](https://data.cityofchicago.org/d/eq45-8inv). It is historical-only. Metadata says **See Terms of Use**, not a standard CC0/CC-BY/ODbL grant.

Follow the [City Data Terms of Use](https://www.chicago.gov/city/en/narr/foia/data_disclaimer.html), including its exact required application disclaimer in [NOTICE_CHICAGO.md](NOTICE_CHICAGO.md), any agency-specific terms, warranty exclusions and reserved rights. The City notice must accompany an application access/download site. Raw/processed data remains external; this does not remove the applicable terms.

The active sample uses the official source only for historical states/metadata. Source, trip and current IDs are string namespaces. Primary records are not joined with CityBikes change data or relabeled under the supplementary source's ODbL.

## Official Divvy trips and live GBFS

Official trips: [system data](https://divvybikes.com/system-data), [Divvy Data License Agreement](https://divvybikes.com/data-license-agreement). Analysis/use is subject to those terms, including standalone dataset redistribution limits and non-commercial report/study conditions. Raw trips are not rehosted. Completed trips do not represent unmet demand.

Live/own-collector source: [official GBFS discovery](https://gbfs.divvybikes.com/gbfs/2.3/gbfs.json). The system timezone is America/Chicago. [MobilityDatabase](https://mobilitydatabase.org/feeds/gbfs/gbfs-lyft_chi) lists CC-BY-4.0, while captured publisher metadata lacks `license_url`. The audit records that catalog evidence and the general official terms separately; it does not assert independently confirmed unrestricted live-data redistribution rights.

## Supplementary CityBikes recent data

Bike-share data by CityBikes contributors and available from [https://data.citybik.es](https://data.citybik.es/). Contains information from the CityBikes database, available under [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/).

Requested paper citation: CityBikes contributors. (2026) Bike-share data retrieved from https://data.citybik.es.

The ODbL notice covers CityBikes' compilation and explicitly reserves operator rights. Applicable attribution/share-alike and derivative-database access obligations remain attached to its supplementary outputs. Keeping raw files off Git is not a blanket exemption for public derivative outputs/models. Its analytics code has a separate AGPL license; none of that program was incorporated here. The primary snapshot audit uses our generic utilities, not CityBikes data.

See the [primary source review](reports/chicago_historical_audit/licensing_and_overlap.md), the preserved [supplementary CityBikes review](legacy/citybikes/reports/licensing_and_overlap.md), and the [legacy Bay Wheels review](legacy/baywheels/reports/licensing_and_overlap.md). No new project-code license has been chosen and no raw/joined database is publicly rehosted by this change.
