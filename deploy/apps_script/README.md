# Google Apps Script collector: no paid cloud plan

**Active in the user personal Google account. Initial scheduled collection is verified from supplied logs/screenshot; the Windows task is disabled. Raw Google files were not independently downloaded by the agent.** AWS was abandoned because the account signup/eligibility page requires a Paid plan, which the user does not authorize. No AWS resources were created by this project.

This alternative uses a Google account, Apps Script's built-in UrlFetch/Drive/trigger services and private Google Drive storage. It does not require a paid cloud billing account, payment card, Google One subscription, public web app or paid API. Quota/storage exhaustion causes failures, not an automatic subscription purchase by this script. School administrators may disable Apps Script or its permissions; do not bypass their restrictions.

## Cadence and limits

The proposed cloud cadence is **five minutes**, not the local collector's two minutes. Apps Script supports native minute-trigger intervals of 1, 5, 10, 15 or 30; two minutes is not a native choice. The existing historical data/model protocol is unchanged; cloud collection has separate timing/provenance and is supplementary current-data validation.

Personal-account quotas currently include 20,000 URL fetches/day and 90 minutes/day total trigger runtime. This implementation requests discovery, metadata and status each poll: nominally 288 polls/day and 864 requests/day. Average runtime must stay below about 18.75 seconds/poll if this were the only trigger workload. Other scripts share the account quotas; limits can change. A conservative 65-minute UTC-day script runtime guard stops this collector when reached, but it is not a measurement of the provider's rolling/shared quota. Inspect actual execution times after installation and after a full day.

Drive storage shares the account's available allowance (a personal account usually has 15 GB across Gmail, Photos and Drive). Each successful poll saves one gzip envelope containing the **full** discovery, metadata and station-status response text with hashes and timestamps. Actual size must be measured after the smoke run; storage/runtime are not guaranteed. Stop or download data if needed, never purchase storage automatically. A full account can also affect mail, so keep a comfortable reserve.

Official references checked 2026-10-30: [Apps Script quotas](https://developers.google.com/apps-script/guides/services/quotas), [allowed trigger intervals](https://developers.google.com/apps-script/reference/script/clock-trigger-builder#everyMinutes(Integer)), [Drive storage](https://support.google.com/drive/answer/6374270?hl=en).

## Install in your Google account

1. Open [Apps Script](https://script.google.com/home/start) and create a new project named `BikeFlowAI Divvy Collector`. Personal Google accounts avoid school administrator restrictions; use an account you control with enough free Drive space. No Google Cloud billing setup is needed.
2. Replace the default `Code.gs` content with all of [Code.gs](Code.gs). Save. These functions run in Google's cloud; your computer need not remain on after a trigger is installed.
3. Select **setupCollector** from the function menu and click **Run**. Review the Google permission screen: this project requests external URL fetch, Google Drive file/folder access, and management of its own Apps Script triggers. Drive permission is broad in the built-in service; the supplied code only works inside the new folder it creates. Do not approve a different/untrusted project. No passwords/tokens go into this repository or chat.
4. Confirm the execution completes and logs `status: ok`. It creates a new **private, unshared** `BikeFlowAI-Divvy-Full-Snapshots` folder in My Drive and one compressed smoke poll; it does **not** start scheduling yet. Keep this folder and its children unshared.
5. Select **startCollector** and click Run. This installs exactly one five-minute trigger for `captureDivvySnapshot`. No Deploy/Web App button is needed; do not publish a web endpoint.
6. After roughly 10–15 minutes, open **Executions** and verify **two distinct scheduled executions** completed. Check that the Drive gzip files contain `invocation: scheduled`, `status: ok`, `full_snapshot: true` and all station records; the status provider timestamps should be recent. A manual smoke run alone is not migration proof. Trigger timing is best-effort; it may be delayed or skip runs.
7. Run **collectorStatus** for folder/last-poll/runtime summary. Only after real scheduled cloud collection is verified should the Windows task be disabled:

```powershell
Disable-ScheduledTask -TaskName 'BikeFlowAI-Divvy-Full-GBFS-Collector'
```

The user completed Google authorization/setup/start, supplied successful scheduled-execution evidence, and the agent then disabled the local two-minute Windows task. The install steps above are for reproduction; do not create duplicate live triggers. Missing offline time remains missing; cloud collection cannot backfill it.

## Data and stopping

```text
Private Drive/BikeFlowAI-Divvy-Full-Snapshots/
  YYYY-MM-DD/
    timestamp_uuid.json.gz
```

The envelope includes collector version, manual/scheduled origin, actual UTC request/receipt times, provider last_updated/TTL, UTF-8 raw text hashes and full response texts. Identical counts are saved again on every successful poll. Original string station IDs are preserved; numeric/duplicate IDs are rejected. Known network/schema errors are error records, never empty inventory. Storage/quota failures can prevent an error file, so **Executions plus expected-slot gaps** must be monitored too. Google trigger execution does not provide exact expected poll times in this envelope; arrival receipt times are authoritative.

To inspect a downloaded file locally:

```python
import gzip, json
with gzip.open('downloaded_snapshot.json.gz', 'rt', encoding='utf-8') as stream:
    poll = json.load(stream)
status = json.loads(poll['sources']['station_status']['raw_json'])
print(poll['status'], len(status['data']['stations']))
```

Download only this collection folder to `Documents/BikeFlowAI-data/divvy/google_validation/`, outside Git. Drive may wrap folder downloads in ZIPs; extract locally. Do not overwrite historical data or mix local/cloud captures without their provenance.

Run **stopCollector** to remove only this collector's triggers while preserving files. Code removes its trigger on the first invocation at/after **2026-12-13 07:59 UTC** (December 12, 23:59 America/Los_Angeles); no later poll is captured. If quota/runtime guard stopped it earlier, review the cause before restarting with `startCollector`; a new `setupCollector` smoke capture may be needed. No file expiry/deletion is automated.

Source-specific terms and the City disclaimer remain in [DATA_SOURCES.md](../../DATA_SOURCES.md) and [NOTICE_CHICAGO.md](../../NOTICE_CHICAGO.md). Keeping Drive private does not grant additional redistribution rights.

## Local validation

Seven Node service-mock tests cover unchanged full captures/string IDs/hashes, separate setup/start/stop, error-vs-empty outcomes, untrusted redirects, numeric-ID rejection, overlap lock and the runtime guard:

```powershell
node --test tests/test_apps_script_collector.cjs
```

These are offline tests; they do not prove real Google authorization, quota headroom, external endpoint access or current cloud uptime. Real smoke and scheduled-run checks above remain required.
