# Divvy source licensing and overlap audit

Checked 2026-10-30. Source URLs, fetched-page hashes, download sizes, and timestamps are in `download_manifest.json`; captured full terms are in the external data folder. This report distinguishes confirmed source declarations from limitations; no email permission or publisher clarification has been obtained.

| Source | Verified declaration | Project use / limits |
|---|---|---|
| [CityBikes history](https://data.citybik.es/) | ODbL 1.0 for its database/compilation; operator rights explicitly separate | Local historical audit and conditional modeling; attribution and applicable derivative-database obligations retained |
| [Official Divvy trips](https://divvybikes.com/system-data) | [Divvy Data License Agreement](https://divvybikes.com/data-license-agreement) | Download via linked S3 and analyze; do not rehost raw standalone trip datasets |
| [Official Divvy GBFS](https://gbfs.divvybikes.com/gbfs/2.3/gbfs.json) | Official source verified; [MobilityDatabase catalog](https://mobilitydatabase.org/feeds/gbfs/gbfs-lyft_chi) labels CC-BY-4.0 | Catalog license claim recorded; publisher `system_information` has no license URL, so independent publisher license confirmation remains pending |

## CityBikes attribution and share-alike

Bike-share data by CityBikes contributors and available from https://data.citybik.es.

Contains information from the CityBikes database, available under the [Open Database License 1.0](https://opendatacommons.org/licenses/odbl/1-0/).

The source's ODbL notice permits database reuse subject to conditions, while expressly excluding an operator-rights grant. Sections 4.3–4.6 distinguish produced works, publicly used derivative databases, internal use, and access to derivative databases or alteration methods. Keeping raw files off GitHub is not a blanket exemption for publicly used derivative outputs.
This repo supplies the selection/transformation methods and attribution. It does not assign ODbL to the independently licensed trip contents, promise all joined training tables can be published, or settle licensing of future trained models. Check the relevant public-use obligations and operator terms before distributing those artifacts.
The analytics repository's AGPL code license is separate from the ODbL dataset license; no upstream implementation was copied into the project's scripts.

## Local download and historical overlap

Downloaded **23 Divvy-only monthly history Parquets and 23 matching official trip ZIPs**, totaling **624,711,946 bytes**. No global CityBikes archive was downloaded. Raw/processed storage is outside `BikeFlowAI`, at the configured external data root.
CityBikes events cover **2024-11-01T15:13:31Z → 2026-09-30T23:59:24Z**, with **20,882,734** raw change records and **2,233** publisher identities.

The trip audit read **11,095,025** actual CSV rows. Unambiguous UTC starts within the history range: **11,088,338**. Chicago DST ambiguous/nonexistent start/end rows excluded: **947**.
Both endpoints mapped using exact normalized historical names, a unique publisher identity, observed metadata intervals, and <=50m geometry: **7,382,539** (**66.54%** of raw trips).
Training-only OD estimates use **3,949,228** eligible mapped trips. Of **220,354** OD pairs, **38,366** have at least 20 training trips. All **400** observed pairs among the 20 provisional candidates meet that support threshold.

These overlap/mapping counts are not claims that arrival inventory is observable for every trip. Change-only history cannot distinguish a station's unchanged inventory from collection silence. Historical installed and disabled fields are absent. See `data_audit.md` and `trip_overlap.md` for the resulting NEED TO RESTRICT decision.

## Official GBFS

Discovery and station information/status/system information were captured from the official endpoint, not from a historical mirror. `live_gbfs_check.json` reports schema, station IDs, and UTC capture time. The feed declares America/Chicago.
The catalog's CC-BY-4.0 label is not silently substituted for a missing publisher license field. The general Divvy data agreement and CityBikes' explicit underlying-rights caveat are retained in this review. Live-data rehosting clearance is therefore qualified rather than asserted as unconditional.

## Publication boundary

This change downloads and audits locally; it does not upload raw records, joined tables, or trained artifacts. Project files include code, source declarations, attribution, provisional metadata manifests, and aggregate non-commercial audit results. Source permissions and ODbL public-use obligations must remain attached when these results are published; a new project-code license must not overwrite third-party data terms.
