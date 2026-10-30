# Data

Raw datasets are not committed. This repository contains extraction/audit code, aggregate reports, and provisional manifests.

## Sources and current result

1. [Historical Bay Wheels GBFS archive](https://github.com/terinjokes/baywheels-history): station-state history, 2022-08-07 to 2023-07-19.
2. [Official Bay Wheels / Lyft trip history](https://lyftbikes.com/system-data): historical requests and ride-time estimates; station-ID joins and DST handling are still pending.
3. Live Bay Wheels GBFS, linked from the official system-data page: planned inference source, separate from the historical archive.
4. [Optional archived weather forecasts](https://open-meteo.com/en/docs/previous-runs-api): availability must be verified per model, variable, and date. The initial SF probe found temperature values but no precipitation/wind values for the tested model and dates.

**Original proposal gate: FALLBACK.** Seven-minute slot coverage is 57.56%; no station reaches 90%. See [the full audit](../reports/data_audit/data_audit.md). No model has been trained.

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

## Provisional manifests

- `selected_stations.csv` is intentionally header-only: zero stations passed the gate. It is not a frozen training station list.
- `candidate_stations.csv` contains training-only exploratory candidates, not approved selections.
- `split_manifest.csv` has independent chronological train/tune/calibration/test intervals with 60-minute separation, but remains an audit proposal until the data gate passes.
- `station_id_map.csv` contains historical metadata intervals only. Current GBFS IDs remain blank; trip/current mappings are unverified. An open interval does not establish validity through today.

Coverage uses a fixed UTC seven-minute grid. Label retention uses nearest observed snapshots within 3.5 minutes, without filling missing observations with zeros. These diagnostic rates do not represent final training rows: freshness, causal metadata, lag features, trip joins, and weather require further work.

## Licensing

The archive has no identified repository license; official Lyft data has separate restrictions. Raw JSON, trip ZIP/CSV, Parquet, DuckDB, and the archive's Git history are not redistributed here. See [licensing_and_overlap.md](../reports/data_audit/licensing_and_overlap.md). The test fixture is entirely synthetic.

