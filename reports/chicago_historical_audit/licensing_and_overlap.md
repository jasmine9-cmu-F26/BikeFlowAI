# Official historical Divvy: source terms and bounded overlap

Checked 2026-10-30. Dataset metadata, exact API requests, source terms, hashes and dates are preserved in the external sample evidence and `download_manifest.json`.

## Primary historical source

[Official City dataset eq45-8inv](https://data.cityofchicago.org/d/eq45-8inv) declares **SEE_TERMS_OF_USE / See Terms of Use**, with attribution City of Chicago. Do not label it CC0, ODbL, or automatically apply the official-trip agreement to it.
The [City Data Terms of Use](https://www.chicago.gov/city/en/narr/foia/data_disclaimer.html) provide the data as-is, reserve rights and the ability to discontinue/restrict use, and require the specified application disclaimer plus any additional agency terms. The publisher-required disclaimer is reproduced in [NOTICE_CHICAGO.md](../../NOTICE_CHICAGO.md); do not omit it from an application download/access site. This is source-term documentation, not a blanket grant of rights beyond those terms.

The metadata's historical coverage says: `2013 to 9/10/2022, except for 7/7/2019 - 12/9/2019 and 2/28/2022 - 4/20/2022`. Metadata updated in 2026 does not mean observations extend to 2026. [Data.gov](https://catalog.data.gov/dataset/divvy-bicycle-stations-historical) explicitly identifies the source as historical-only.

## Bounded availability findings

The first 2022 May–August sample found a shared ~50-day May–July gap not listed in the brief catalog description. It failed coverage and is retained under `failed_2022/`; no missing period was filled as zero or compressed away.
The separate 2021 May–August window was checked for data availability before model tuning. It contains **856,200** full snapshots for 50 initial stations; the fixed training-only rule qualifies **42**. This is a bounded sample result, not an audit of every 2021–2022 station/date.

## Official trips and current identity

Four same-period ZIPs were downloaded from the [official Divvy trip interface](https://divvybikes.com/system-data), subject to the [Divvy Data License Agreement](https://divvybikes.com/data-license-agreement). Raw datasets are not rehosted; the agreement's standalone-distribution restrictions and non-commercial report/study conditions remain applicable.
The streaming audit read **2,887,990** rows. Among trips naming both sampled endpoints, **93.49%** mapped by exact historical name, <=50m geometry, unique identity and observed time interval. Trips outside the cohort are not classified as mapping failures.
Mapped trips at selected stations have pickup/return observations within ±5 min for **96.87%** of requests. This is approximate snapshot support, not exact causal stock before a completed ride. Training-only OD medians use **42,356** eligible rides; **424** pairs meet >=20 training trips.
Current direct official GBFS metadata yields **32** unique exact-name/geometry matches among the historical selected cohort. Current identifiers are not copied into historical features or equated with legacy IDs.

## Live and supplementary sources

Official GBFS is the live inference and own-collector source. MobilityDatabase's catalog lists CC-BY-4.0, but the captured publisher system-information document lacks a license URL; the catalog declaration is not presented as independent publisher confirmation. Keep the general official Divvy terms and this qualification attached.
Current collection has moved to Google Apps Script with nominal five-minute full polls in private Drive. Initial scheduled-run evidence was supplied and checked; the Windows task is disabled with its data preserved. Cloud collection runs independently of laptop uptime but remains subject to Google quotas, storage and scheduler delays. It does not grant redistribution rights, certify continuous uptime, or retroactively fill historical gaps.

CityBikes recent change events remain supplementary only. Its compilation has separate ODbL 1.0 attribution/public-use obligations; they are not a license for the official City source. No CityBikes data is joined into these primary historical labels or trip mappings. Its old reports/attribution remain under `legacy/citybikes/reports/` and [DATA_SOURCES.md](../../DATA_SOURCES.md).

## Separate 32-station app audit

The original figures above refer to the initial 42-station feasibility cohort / 50-station mapping scope. The [32-station app report](app32/README.md) reports its own denominators: 93.74% mapping, 96.80% pickup/return observation support, 18,571 training OD rides and 229 pairs with >=20 training rides. Source terms remain unchanged.
