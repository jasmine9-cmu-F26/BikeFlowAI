# Collector health: local audited, initial cloud health confirmed

The retired local collector was audited from actual JSONL attempts and raw snapshot hashes. For the installation-start to disable-time window:

| Metric | Local result |
|---|---:|
| Expected nominal two-minute slots | 69 |
| Successful / failed attempts | 69 / 0 |
| Missing attempt slots | 0 |
| Median / p90 interval | 120.0 / 121.0 seconds |
| Longest success gap, including window boundaries | 124.0 seconds |
| Duplicate capture timestamps | 0 |
| Station-count min / max | 2078 / 2078 |
| Feed-age median / p90 | 70.0 / 94.0 seconds |

This measures only that bounded retired local window. [local_health.json](local_health.json) exposes the window/phase, raw integrity checks, source repetition and extra-attempt caveats. Earlier manual probes are outside the scheduled window; local logs do not independently tag invocation origin.

**Google cloud uptime is not yet independently measured from raw exports.** The current cloud trigger is nominally **five minutes**, not two. Initial user-supplied successful runs prove startup, not weeks of uptime. [google_health.json](google_health.json) explicitly records the remaining gate.

Active `apps-script-v2-health` records bounded rolling hourly metadata automatically on each capture and exposes `collectorHealth()`: expected/attempted/successful/failed slots, gaps, median/p90 cadence, duplicates, source timestamp repetition, station count, feed age and stale-feed counts. It stores metadata only in the same script's Properties; no new URL fetches, paid services, Drive scans or duplicate triggers. Last 48 UTC hour buckets are retained; a report covers the observed indexed portion of the last 24 hours. It cannot retroactively reconstruct earlier v1 attempts. Trigger timing is best-effort; slot assignment tolerates sub-cadence jitter.

**Current action:** keep the existing five-minute cloud trigger. The user has saved v2 and supplied a successful scheduled-health report. Do not rerun setup/start. The Windows task stays disabled. Periodically preserve health reports; the rolling index does not retain the entire project history.

For a complete retrospective cloud-window audit, download the private Drive folder into external `google_validation/` and run `audit_collector_health.py --data-root EXTERNAL_2021_SAMPLE --google-root EXPORTED_FOLDER`. Raw response hashes and station counts are validated; storage/termination/quota gaps remain gaps. Do not describe absence of an error file as proof of a successful capture.

## Latest user confirmation

At October 30, 20:07:09 America/Los_Angeles, the user supplied the real v2 collectorHealth output. The earlier WAITING result preceded the first indexed scheduled attempt.

| Metric | User-reported cloud result |
|---|---:|
| Observed UTC window (October 31) | 03:01:27.486–03:07:09.208 |
| Expected / successful slots | 2 / 2 |
| Failed / missing attempt slots | 0 / 0 |
| Median / p90 interval | 298.934 / 298.934 seconds |
| Station-count min / max | 2078 / 2078 |
| Feed-age median / maximum | 38.268 / 38.801 seconds |
| Duplicate capture / repeated provider timestamps | 0 / 0 |
| Stale-feed polls over five minutes | 0 |

Exact output and verification scope are in [google_health.json](google_health.json). This initial observed window confirms operation from user-supplied logs, without independent authenticated cloud access or raw-file hash checks. It does not establish full-day or weeks-long uptime. No computer uptime or trigger reinstallation is needed for continued cloud collection.
