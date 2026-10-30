"""Verify official license links, weather null rates, and real monthly trip dates.

Raw ZIPs stay in ignored data/raw. Does not assert permission for community
redistribution, infer DST folds, or claim that station-ID joins are complete.
"""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "BikeFlow-academic-data-audit/1.0"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return r.read()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--summary", type=Path, default=Path("reports/data_audit/audit_summary.json"))
    p.add_argument("--raw", type=Path, default=Path("data/raw/trips"))
    args = p.parse_args()
    summary = json.loads(args.summary.read_text())
    out = args.summary.parent
    start, end = summary["first_snapshot_utc"][:10], summary["last_snapshot_utc"][:10]
    result = dict(checked_at_utc=datetime.now(timezone.utc).isoformat(), archive_start=start, archive_end=end)
    urls = {
        "archive": "https://github.com/terinjokes/baywheels-history",
        "official_system_data": "https://lyftbikes.com/system-data",
        "lyft_license": "https://baywheels-assets.s3.amazonaws.com/data-license-agreement.html",
        "weather_docs": "https://open-meteo.com/en/docs/previous-runs-api",
        "weather_license": "https://open-meteo.com/en/licence",
    }
    result["sources"] = {}
    for key, url in urls.items():
        try:
            body = get(url)
            result["sources"][key] = dict(url=url, http_status=200,
                                           sha256=hashlib.sha256(body).hexdigest())
        except Exception as e:
            result["sources"][key] = dict(url=url, error=str(e))
    params = dict(latitude=37.7749, longitude=-122.4194, start_date=start, end_date=end,
        hourly="temperature_2m_previous_day1,precipitation_previous_day1,wind_speed_10m_previous_day1",
        models="gfs_seamless", timezone="UTC")
    weather_url = "https://previous-runs-api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(params)
    try:
        weather = json.loads(get(weather_url))
        counts = {k:dict(hours=len(v), nonnull=sum(x is not None for x in v),
                        nonnull_rate=sum(x is not None for x in v)/len(v))
                  for k,v in weather.get("hourly",{}).items() if k != "time"}
        result["weather"] = dict(url=weather_url, location="SF representative point only",
            model="gfs_seamless", lead_time="previous_day1, 24h before valid time", variables=counts,
            status="probe_only_no_complete_feature_join", raw_rows_redistributed=False)
    except Exception as e:
        result["weather"] = dict(url=weather_url, error=str(e))
    months = []
    year, month = map(int,start[:7].split("-"))
    while f"{year:04d}-{month:02d}" <= end[:7]:
        months.append(f"{year:04d}{month:02d}")
        year, month = (year+1,1) if month == 12 else (year,month+1)
    ns = {"s":"http://s3.amazonaws.com/doc/2006-03-01/"}
    args.raw.mkdir(parents=True,exist_ok=True)
    trips = []
    for m in months:
        row = dict(month=m)
        try:
            listing_url = "https://s3.amazonaws.com/baywheels-data?list-type=2&prefix="+m
            listing = ET.fromstring(get(listing_url))
            files = [x.find("s:Key",ns).text for x in listing.findall("s:Contents",ns)]
            key = next(k for k in files if k.endswith(".zip") and "tripdata" in k)
            url = "https://s3.amazonaws.com/baywheels-data/"+key
            local = args.raw / key
            if not local.exists():
                data = get(url)
                temporary = local.with_suffix(".tmp")
                temporary.write_bytes(data)
                temporary.replace(local)
            row.update(url=url, listing_url=listing_url, bytes=local.stat().st_size,
                       sha256=hashlib.sha256(local.read_bytes()).hexdigest())
            n, overlap, lo, hi, stations = 0, 0, None, None, set()
            with zipfile.ZipFile(local) as z:
                members = [x for x in z.namelist() if x.endswith(".csv") and not x.startswith("__MACOSX/")]
                for member in members:
                    with z.open(member) as stream:
                        reader = csv.DictReader(io.TextIOWrapper(stream, encoding="utf-8-sig"))
                        row["columns"] = reader.fieldnames
                        for r in reader:
                            ts = r.get("started_at") or r.get("start_time")
                            if not ts:
                                continue
                            # File dates are inspected as local strings; no ambiguous
                            # DST timestamp is silently assigned an absolute instant.
                            n += 1
                            lo = ts if lo is None or ts < lo else lo
                            hi = ts if hi is None or ts > hi else hi
                            overlap += start <= ts[:10] <= end
                            stations.add(r.get("start_station_id", ""))
                            stations.add(r.get("end_station_id", ""))
            stations.discard("")
            row.update(rows=n, min_started_at_local_unlocalized=lo,
                       max_started_at_local_unlocalized=hi,
                       rows_within_archive_calendar_dates=overlap,
                       unique_nonempty_trip_station_ids=len(stations),
                       station_id_examples=sorted(stations)[:5],
                       status="row_dates_verified_station_join_and_dst_pending")
            print(f"{m}: {n:,} trips; {lo} to {hi}",flush=True)
        except Exception as e:
            row["error"] = str(e)
        trips.append(row)
        result["trips"] = trips
        (out / "external_sources.json").write_text(json.dumps(result,indent=2)+"\n")
    result["trips"] = trips
    (out / "external_sources.json").write_text(json.dumps(result,indent=2)+"\n")


if __name__ == "__main__":
    main()
