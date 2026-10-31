# Own full-GBFS collector

Started 2026-10-30. The local Windows task `BikeFlowAI-Divvy-Full-GBFS-Collector` captures official Divvy station status every **2 minutes**, through **2026-12-12 23:59 America/Los_Angeles** (2026-12-13 07:59 UTC).

It uses a windowless Python process with limited interactive-user permissions. It continues independently of this chat, but the user must be logged in and the computer awake/online. It does not wake the machine, store passwords, or change power settings. Time missed while asleep/offline stays missing; `StartWhenAvailable` is not historical backfill.

## Stored outside the project

```text
BikeFlowAI-data/divvy/current_validation/
  status/YYYY/MM/DD/*.json.gz  Every successful complete station_status response
  metadata/<hash>.json.gz     Immutable station_information content versions
  discovery/                 Captured official discovery responses
  polls.jsonl                Success/error heartbeat for each attempted poll
  last_poll.json             Last attempt and any failure/stale-feed warning
  state.json                 Last successful poll and counters
  installation.json          Last checked local task configuration
```

Unchanged inventories are **not suppressed**. Only metadata content is deduplicated. Metadata is fetched before status and its reference/capture times are logged. Successful polls retain raw response hash, provider last_updated/TTL/version, receipt times, count of stations, code hash, and a stale-feed warning. Failed fetches write error heartbeats and never empty station snapshots. A process lock prevents overlapping captures and releases on process exit.

## Run or install

```powershell
$DivvyRoot = "$env:USERPROFILE\Documents\BikeFlowAI-data\divvy"
# One full poll; uses the audit environment or any installed Python 3.14.
.\.venv\Scripts\python.exe scripts/data/collect_divvy_gbfs.py --data-root "$DivvyRoot" --once

# Foreground loop (Ctrl+C stops this loop only):
.\.venv\Scripts\python.exe scripts/data/collect_divvy_gbfs.py --data-root "$DivvyRoot" --interval-seconds 120

# Install/update only this project's Windows task; prefer a stable interpreter.
.\scripts\data\install_divvy_collector.ps1 -PythonExe "$env:LOCALAPPDATA\Python\pythoncore-3.14-64\python.exe" -DataRoot "$DivvyRoot"
```

Do not delete/move the installed interpreter or collector script while the task is in use. The installer uses `pythonw.exe` if available, so no console window appears every poll. The script uses only the standard library; data/model packages are not needed by the scheduled process.

```powershell
Get-ScheduledTask -TaskName 'BikeFlowAI-Divvy-Full-GBFS-Collector'
Get-ScheduledTaskInfo -TaskName 'BikeFlowAI-Divvy-Full-GBFS-Collector'
# Stop future scheduled attempts when the project ends early:
Disable-ScheduledTask -TaskName 'BikeFlowAI-Divvy-Full-GBFS-Collector'
# Resume before the configured end:
Enable-ScheduledTask -TaskName 'BikeFlowAI-Divvy-Full-GBFS-Collector'
```

These current snapshots are a future sanity/supplemental-evaluation source. A few initial polls do not establish weeks of coverage, validate a 2021 model in 2026, or erase vintage/season differences. Freeze any current evaluation period before using it to tune a model. Keep raw snapshots outside Git and preserve source-specific terms in [DATA_SOURCES.md](../DATA_SOURCES.md).
