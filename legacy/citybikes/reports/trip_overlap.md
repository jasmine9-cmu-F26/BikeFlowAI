# Official Divvy trips: overlap and OD audit

Read **11,095,025** actual trip rows in **23** monthly CSV inputs, not just filenames.
Raw ZIP/CSV and full joined/OD tables stay outside the repository.

- Valid, unambiguous UTC starts within the historical event range: **11,088,338**.
- DST ambiguous/nonexistent start or end timestamps excluded: **947**; policy uses IANA America/Chicago, never Pacific or a fixed offset. See `dst_exclusions.csv`.
- Both endpoints conservatively mapped to historical archive identities: **7,382,539** (66.54% of all raw trips).
- Mapped, duration-filtered trips in the exact UTC overlap: **7,301,138**.
- Training-only eligible trips for ride-time estimates: **3,949,228**; OD pairs: **220,354**; pairs with >=20 training trips: **38,366**.
- Among the provisional training-area candidates: **400** observed OD pairs; **400** have >=20 training trips. Others must use the proposal's documented geometric fallback.

Mapping requires an exact whitespace/case-normalized name, <=50m endpoint coordinates, a compatible observed historical metadata interval, and a unique publisher station identity. It does not assume trip codes equal GBFS UUIDs or use today's metadata as historical truth.
The CSV's timestamps have no timezone annotation. Chicago localization is an explicit policy based on the service area and official GBFS timezone, not a claim that the CSV schema independently certifies that convention.
The candidate-only mapping and OD aggregates are available in the repository; full tables stay in external local storage. Mapping remains provisional pending final station/rule approval.

OD medians use only training trips, with both start/end inside training and UTC ride duration from 60 seconds to 6 hours. Tuning, calibration, and test rides do not estimate ride times.
These overlap counts do **not** mean all trips have observable pickup/return inventory: the change-event archive's heartbeat and arrival-label limitations still apply. Completed-trip sampling also misses unmet demand.

See `trip_overlap_by_month.csv`, `trip_overlap.json`, and `licensing_and_overlap.md` for details and source restrictions.
