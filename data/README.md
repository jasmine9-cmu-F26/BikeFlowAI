# Data

Raw datasets are not committed. This repository contains extraction/audit code, aggregate reports, and provisional manifests.

## Sources and current result

1. [Historical Bay Wheels GBFS archive](https://github.com/terinjokes/baywheels-history): station-state history, 2022-08-07 to 2023-07-19.
2. [Official Bay Wheels / Lyft trip history](https://lyftbikes.com/system-data): historical requests and ride-time estimates; station-ID joins and DST handling are still pending.
3. Live Bay Wheels GBFS, linked from the official system-data page: planned inference source, separate from the historical archive.
4. [Optional archived weather forecasts](https://open-meteo.com/en/docs/previous-runs-api): availability must be verified per model, variable, and date. The initial SF probe found temperature values but no precipitation/wind values for the tested model and dates.

**Initial archive audit complete; revised data rules pending validation.** The original seven-minute / 90% gate returned FALLBACK (57.56% coverage). The revised proposal treats the archive as irregularly sampled and makes weather optional; the original result does not establish that the revised project is infeasible. See [the original audit](../reports/data_audit/data_audit.md) and its [interpretation notes](../reports/data_audit/README.md). No model has been trained.

The current scripts reproduce the original-rule audit. They still use seven-minute slots and a 3.5-minute tolerance; a revised feature/label builder and rule comparison are not implemented yet. See the [data handoff checklist](../docs/data_handoff.md) for the next deliverables.

## Reproduce the audit

Run commands from the BikeFlowAI project root with Git and the audit Python environment installed:

```powershell
git clone https://github.com/terinjokes/baywheels-history.git ../baywheels-history
git -C ../baywheels-history checkout b409260cc6a4a38b5d9c5336e32f132d1d8b71ac
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r scripts/data/requirements.txt
.\.venv\Scripts\python.exe scripts/data/extract_baywheels_history.py --repo ../baywheels-history --output data/processed/baywheels_history
.\.venv\Scripts\python.exe scripts/data/audit_baywheels_data.py --repo ../baywheels-history --input data/processed/baywheels_history
```

Skip `git clone` if a complete archive checkout already exists. On this machine the sibling `../baywheels-history` is that original checkout; retain its local files and do not clone over it. Use `--repo` with another path if necessary.

To repeat the external checks after the audit:

```powershell
.\.venv\Scripts\python.exe scripts/data/check_external_sources.py
```

This downloads monthly trip ZIPs into ignored `data/raw/trips/`, scans their actual dates, and probes the weather API. It uses the network; results can change. It does not complete trip-ID mapping, localize ambiguous Pacific timestamps, or build a weather feature table.

The extractor writes atomic parts every 500 commits and resumes completed parts only for the same source revision, extractor hash, and options. Use a new output directory if those change. `--limit` is a smoke run; a full audit refuses incomplete extraction.

## Local output and committed artifacts

| Path | Contents | Git status |
|---|---|---|
| `processed/baywheels_history/` | Extracted parts, snapshot inventory, consolidated Parquet, temporary DuckDB files | Ignored |
| `raw/`, `external/`, `generated/` | Downloaded or generated local data | Ignored |
| `manifests/` | Candidate stations and provisional station/split manifests | Included |
| `../reports/data_audit/` | Aggregate audit results, source checks, validation | Included |

The initial aggregate reports were copied unchanged from the original archive audit. Their source commit and script/data hashes remain in `audit_summary.json`. Existing raw ZIPs and Parquet remain in the sibling archive checkout; they were not copied into this project.

The script defaults overwrite the report and manifest directories when rerun. To preserve the initial results during experiments, pass separate destinations, for example `--reports reports/sampling_revision --manifests data/manifests/sampling_revision`. This separates output locations only; it does not change the current script's fixed sampling rule.

## Provisional manifests

- `selected_stations.csv` is intentionally header-only: zero stations passed the original seven-minute / 90% gate. Selection under the revised rule is still pending; this is not a frozen training station list.
- `candidate_stations.csv` contains training-only exploratory candidates, not approved selections.
- `split_manifest.csv` has independent chronological train/tune/calibration/test intervals with 60-minute separation. It remains an audit proposal until the revised rule and split-boundary checks pass.
- `station_id_map.csv` contains historical metadata intervals only. Current GBFS IDs remain blank; trip/current mappings are unverified. An open interval does not establish validity through today.

The initial diagnostic coverage uses a fixed UTC seven-minute grid. Initial label retention uses the nearest observed snapshot within 3.5 minutes, then checks validity; it does not yet implement the revised proposal's nearest-valid matching rule. These diagnostic rates do not represent final training rows. Freshness, causal metadata, lag features, trip joins, and split-boundary checks require further work; weather is optional. Missing or non-reporting observations must never become zero-inventory labels.

The [manifest status notes](manifests/README.md) define what each provisional file can be used for.

## Licensing

The archive has no identified repository license; official Lyft data has separate restrictions. Raw JSON, trip ZIP/CSV, Parquet, DuckDB, and the archive's Git history are not redistributed here. See [licensing_and_overlap.md](../reports/data_audit/licensing_and_overlap.md). The test fixture is entirely synthetic.

