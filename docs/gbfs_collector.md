# Own full-GBFS collector: Google cloud active

**Current state:** Google Apps Script saves complete official Divvy snapshots to private Google Drive every **nominal five minutes**. Initial cloud handoff is verified from the user's `collectorStatus` JSON and successful Time-Driven execution screenshot. The Windows task `BikeFlowAI-Divvy-Full-GBFS-Collector` was disabled and queried directly after that evidence arrived. All existing local files were preserved.

The laptop may now be shut down. No browser tab or local Python process is needed for the Google trigger. This is best-effort collection under shared Apps Script runtime/fetch quotas and available Drive storage; check execution history regularly.

## Evidence and scope

- Six successful Time-Driven captures were shown, with the latest status response received at `2026-10-31T02:01:29.771Z` (October 30, 19:01:29 America/Los_Angeles).
- One matching trigger, `last_poll.status: ok`, `invocation: scheduled`, 2,078 stations, and no recorded last error.
- Latest gzip size: 136,471 bytes. At 288 nominal captures/day, this single-size estimate is about 39.3 MB/day or 1.18 GB/30 days. Real sizes/rates vary; confirm actual Drive space.
- The agent did not log in to Google or independently download raw cloud files. This initial evidence does not certify every stored byte, a full day of quota headroom, weeks of coverage or model accuracy.

See [handoff evidence](../reports/chicago_historical_audit/cloud_collector_handoff.json) and [status](../reports/chicago_historical_audit/collector_status.json). Private Drive folder/file IDs remain outside committed reports.

## Active Google operations

Open your existing Apps Script project with the personal account used during setup. Do not create a duplicate project/trigger. Run `collectorStatus` to inspect the last successful poll, last error and runtime summary; view **Executions** for each Time-Driven run. A successful old poll does not rule out later failures, so compare its timestamp with the current time and inspect errors.

Raw captures are in private Drive folder `BikeFlowAI-Divvy-Full-Snapshots`, under daily UTC subfolders. Unchanged inventory is saved on every successful poll. Download the data into `Documents/BikeFlowAI-data/divvy/google_validation/`, outside the repo; it is not automatically synced to this computer. Keep local and Google records with their separate formats/provenance.

Run `stopCollector` in Google Apps Script to stop only this collector's cloud triggers without deleting data. Code stops capture at **2026-12-13 07:59 UTC** (December 12, 23:59 America/Los_Angeles). No paid subscription/storage upgrade or automatic data expiry is configured. Quota/storage exhaustion can cause missing captures; do not backfill missing intervals with empty or unchanged state.

The [Google deployment/operation guide](../deploy/apps_script/README.md) contains setup, permissions, quotas, format and validation details. AWS was abandoned due account Paid-plan requirements; do not run its deployment commands.

## Preserved local collector (disabled)

Existing local raw files remain at `Documents/BikeFlowAI-data/divvy/current_validation/`, including full statuses, immutable metadata, poll/error heartbeat logs and state. The old local cadence was two minutes. This evidence is retained rather than mixed silently with the five-minute Google collection.

```powershell
Get-ScheduledTask -TaskName 'BikeFlowAI-Divvy-Full-GBFS-Collector'
# Expected state: Disabled
```

The standard-library [local collector](../scripts/data/collect_divvy_gbfs.py) and [installer](../scripts/data/install_divvy_collector.ps1) remain available for a deliberate fallback. Re-enabling/installing it would require this computer to stay logged in, awake and online. Do not run parallel collectors accidentally.

Historical training data, station selection, splits and model timing rules are unchanged. Raw source terms remain documented in [DATA_SOURCES.md](../DATA_SOURCES.md).
