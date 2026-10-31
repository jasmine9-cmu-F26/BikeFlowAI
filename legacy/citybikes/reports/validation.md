# Divvy audit validation

This records the scope of the new audit. Local unit/integration results are checked before handoff; a GitHub-hosted CI run is separate and requires commit/push.

- Downloaded 46 listed data objects (23 Divvy-only monthly history Parquets + 23 official trip ZIPs), with expected lengths, local SHA-256, HTTP metadata, and captured license/source evidence.
- Normalized every downloaded historical month and audited all 20,882,734 change records across 2,233 publisher station identities. No count changes were interpreted as complete polling heartbeat.
- Read all 11,095,025 actual official trip CSV rows; applied Chicago timezone handling with explicit ambiguous/nonexistent exclusions, historical exact-name/geometry/time endpoint matching, and training-only ride-time estimation.
- Synthetic tests cover validity filtering before nearest matching, deterministic ties, no cross-split target search, no filling through silence, historical/live schema differences, Chicago DST folds/gaps, and a complete toy extraction→audit→trip mapping→training-OD pipeline.
- Original Bay Wheels audit numeric artifacts and legacy manifests remain separate and unchanged. New raw/processed files and full joined databases are outside the Git checkout. No model was trained and no raw data was uploaded.

The result is NEED TO RESTRICT. These checks do not certify the unobserved state between inventory changes, approve final station/rule selection, or clear unrestricted publication of derivative training/model artifacts.

## Final local verification

- **13 tests passed**, including a regression preventing current observations from becoming future labels under wide tolerances.
- The synthetic OD test includes a held-out ride and a far-away coordinate: neither enters the training OD median.
- `pip check`, Python syntax, local Markdown links, the external data-root configuration, all 46 raw SHA-256/size values, all 23 normalized part hashes/row counts, and recorded script hashes were checked.
- CSV row counts, empty approved selection, label count/error bounds, and >=20-trip support for all 400 candidate OD pairs were checked.
- See `validation_results.json` for the machine-readable result. Hosted Ubuntu/Windows CI has not been run in this session.
