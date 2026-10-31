"""Download Divvy-only CityBikes history, matching official trips, and live GBFS.

The data root must be OUTSIDE the project checkout. Downloads are atomic and
completed files are verified against the source listing and a local SHA-256.
No credentials, raw files, or third-party source code are put in the project.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

CITY = "https://data.citybik.es"
TRIPS = "https://divvy-tripdata.s3.amazonaws.com/"
DISCOVERY = "https://gbfs.divvybikes.com/gbfs/2.3/gbfs.json"
UA = "BikeFlowAI-academic-data-audit/1.0"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def request(url, **kwargs):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), **kwargs)


def get_json(url):
    with request(url, timeout=90) as r:
        return json.load(r)


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def download(url, destination, expected_bytes=None):
    destination.parent.mkdir(parents=True, exist_ok=True)
    sidecar = destination.with_suffix(destination.suffix + ".download.json")
    if destination.exists() and sidecar.exists():
        meta = json.loads(sidecar.read_text())
        size_ok = expected_bytes is None or destination.stat().st_size == expected_bytes
        if meta.get("url") == url and size_ok and sha256(destination) == meta.get("sha256"):
            print(f"Verified cached {destination.name}", flush=True)
            return meta
    temporary = destination.with_suffix(destination.suffix + ".part")
    error = None
    for attempt in range(3):
        try:
            start = time.monotonic()
            with request(url, timeout=120) as response:
                header_length = response.headers.get("Content-Length")
                etag, modified = response.headers.get("ETag"), response.headers.get("Last-Modified")
                with temporary.open("wb") as output:
                    while block := response.read(1024 * 1024):
                        output.write(block)
            actual = temporary.stat().st_size
            for expected in [expected_bytes, int(header_length) if header_length else None]:
                if expected is not None and actual != expected:
                    raise ValueError(f"Size mismatch {destination.name}: {actual} != {expected}")
            if destination.suffix == ".parquet":
                import pyarrow.parquet as pq
                pq.read_metadata(temporary)
            if destination.suffix == ".zip":
                with zipfile.ZipFile(temporary) as archive:
                    if not any(n.endswith(".csv") and not n.startswith("__MACOSX/") for n in archive.namelist()):
                        raise ValueError("No trip CSV in ZIP")
            meta = dict(url=url, bytes=actual, sha256=sha256(temporary), etag=etag,
                        source_last_modified=modified, downloaded_at_utc=utc_now())
            temporary.replace(destination)
            save_json(sidecar, meta)
            print(f"Downloaded {destination.name}: {actual:,} bytes ({time.monotonic()-start:.1f}s)", flush=True)
            return meta
        except (OSError, urllib.error.URLError, ValueError, zipfile.BadZipFile) as exc:
            error = exc
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Download failed after 3 attempts: {url}: {error}")


def discover():
    directories = get_json(CITY + "/dumps/by-network/")
    city = []
    for directory in directories:
        year = directory["name"]
        if directory["type"] != "directory" or not year.isdigit():
            continue
        listing_url = CITY + f"/dumps/by-network/{year}/"
        for item in get_json(listing_url):
            if item["name"].endswith("-divvy-stats.parquet"):
                city.append(dict(month=item["name"][:6], name=item["name"],
                    size=item["size"], url=listing_url+item["name"], listing_url=listing_url))
    city.sort(key=lambda x:x["month"])
    # S3 pagination is explicit rather than assuming one HTML index is complete.
    ns = {"s":"http://s3.amazonaws.com/doc/2006-03-01/"}
    trip_items, token = {}, None
    while True:
        url = TRIPS + "?list-type=2" + ("&continuation-token="+urllib.parse.quote(token) if token else "")
        with request(url, timeout=90) as response:
            root = ET.fromstring(response.read())
        for item in root.findall("s:Contents", ns):
            key = item.find("s:Key",ns).text
            if len(key) > 6 and key[:6].isdigit() and key.endswith("-divvy-tripdata.zip"):
                trip_items[key[:6]] = dict(month=key[:6], name=key,
                    size=int(item.find("s:Size",ns).text), url=TRIPS+key, listing_url=TRIPS+"?list-type=2")
        truncated = root.find("s:IsTruncated",ns)
        if truncated is None or truncated.text != "true":
            break
        token = root.find("s:NextContinuationToken",ns).text
    return city, trip_items


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data-root", type=Path, required=True)
    p.add_argument("--project-root", type=Path, default=Path.cwd())
    p.add_argument("--start-month", default="202411")
    p.add_argument("--end-month", default="202609")
    args = p.parse_args()
    root = args.data_root.resolve()
    if root.is_relative_to(args.project_root.resolve()):
        p.error("--data-root must be outside the project checkout")
    root.mkdir(parents=True, exist_ok=True)
    manifest_path = root / "download_manifest.json"
    manifest = dict(created_at_utc=utc_now(), citybikes_network="divvy",
        start_month=args.start_month, end_month=args.end_month,
        scope="All Divvy-only history and matching monthly trips in the declared interval; no world dumps",
        raw_data_redistributed=False, files=[], evidence=[], live=[])
    city, trips = discover()
    save_json(root / "catalog.json", dict(citybikes=city, official_trips=list(trips.values())))
    for entry in city:
        if not args.start_month <= entry["month"] <= args.end_month:
            continue
        for kind, item in [("citybikes",entry), ("trips",trips.get(entry["month"]))]:
            if item is None:
                manifest["files"].append(dict(kind=kind, month=entry["month"], error="No matching official trip month"))
                continue
            path = root / "raw" / kind / item["name"]
            record = download(item["url"],path,item["size"])
            manifest["files"].append(dict(kind=kind,month=item["month"],path=path.relative_to(root).as_posix(),**record))
            save_json(manifest_path,manifest)
    evidence = {
        "citybikes_terms.html": CITY+"/",
        "odbl_1_0.html":"https://opendatacommons.org/licenses/odbl/1-0/",
        "divvy_system_data.html":"https://divvybikes.com/system-data",
        "divvy_data_license.html":"https://divvybikes.com/data-license-agreement",
        "mobilitydatabase_divvy.html":"https://mobilitydatabase.org/feeds/gbfs/gbfs-lyft_chi",
        "citybikes_collector.py":"https://raw.githubusercontent.com/citybikes/analytics/master/collect.py",
        "citybikes_export.sh":"https://raw.githubusercontent.com/citybikes/analytics/master/export.sh",
    }
    for name,url in evidence.items():
        path = root / "evidence" / name
        record = download(url,path)
        manifest["evidence"].append(dict(path=path.relative_to(root).as_posix(),**record))
        save_json(manifest_path,manifest)
    discovery = get_json(DISCOVERY)
    captured = utc_now()
    save_json(root / "raw/live/gbfs.json",discovery)
    manifest["live"].append(dict(name="gbfs",url=DISCOVERY,path="raw/live/gbfs.json",captured_at_utc=captured))
    feeds = discovery["data"]["en"]["feeds"]
    for feed in feeds:
        if feed["name"] not in {"station_information","station_status","system_information"}:
            continue
        before = utc_now()
        data = get_json(feed["url"])
        path = root / "raw/live" / (feed["name"]+".json")
        save_json(path,data)
        manifest["live"].append(dict(name=feed["name"],url=feed["url"],path=path.relative_to(root).as_posix(),
            requested_at_utc=before,captured_at_utc=utc_now(),feed_last_updated=data.get("last_updated"),
            version=data.get("version"),sha256=sha256(path)))
        save_json(manifest_path,manifest)
    path = root / "raw/live/citybikes_network.json"
    record = download("https://api.citybik.es/v2/networks/divvy",path)
    manifest["live"].append(dict(name="citybikes_current_network",path=path.relative_to(root).as_posix(),**record))
    manifest["completed_at_utc"] = utc_now()
    manifest["total_raw_download_bytes"] = sum(r.get("bytes",0) for r in manifest["files"])
    manifest["download_script_sha256"] = sha256(Path(__file__))
    save_json(manifest_path,manifest)
    print(json.dumps(dict(files=len(manifest["files"]),bytes=manifest["total_raw_download_bytes"],
                          manifest=str(manifest_path)),indent=2),flush=True)


if __name__ == "__main__":
    main()
