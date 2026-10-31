# App cohort and repository cleanup validation

The fixed 32-station cohort was audited separately against the already downloaded official snapshots and all four matching trip ZIPs. No new source dataset was downloaded. Snapshot/label and trip/OD outputs have their own cohort denominators and source/helper hashes.

- **25 offline synthetic regression tests passed** in both the staged and installed BikeFlowAI project, including active causal as-of selection, future-label isolation, Chicago DST folds/gaps, duplicate identity rejection, historical extraction and collector full-poll/error/locking behavior.
- Original Bay Wheels/CityBikes CSV/JSON and frozen Python bytes were preserved when archived. Original 42-station Chicago and failed 2022 numeric artifacts were unchanged. Navigation Markdown links were updated.
- Active scripts import shared utilities from `scripts/data/bikeflow_data/`, with no dependency on archived CityBikes entry points. Exact source bytes for the original Chicago script hashes are retained under `legacy/official_chicago_audit_v1/`.
- Fixed cohort and unique live IDs, selected manifests, label tolerances/counts, same-split bounds, training-only OD totals, protocol/code hashes, Python syntax, relative Markdown links and external raw-data placement were checked. Historical/live semantics and source publication-latency assumptions remain explicit.

Machine-readable checks and the final installed-project verification are recorded in [validation_results.json](validation_results.json). This audit validation preceded the requested local commit sequence. Hosted CI has not run; no model training or push was performed.

Installed project checks: `pip check` found no broken requirements; `git diff --check` passed. Old file paths were removed only after archived destinations were copied and SHA-256 verified. The collector code and task were not changed.
