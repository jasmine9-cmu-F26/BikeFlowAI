"""Normalize CityBikes Divvy change events, preserving missing GBFS fields.

Counts/flags come from the historical record, never from today's live feed.
Collector timestamps are UTC; provider report times are separately retained.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import duckdb


def file_hash(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f,"sha256").hexdigest()


def normalize_sql():
    return """
    SELECT
      cast(epoch(timestamp) AS BIGINT) AS timestamp,
      coalesce(nullif(nuid,''),'citybikes:'||id) AS station_id,
      id AS citybikes_id, nullif(nuid,'') AS gbfs_station_id,
      name, latitude AS lat, longitude AS lon,
      bikes AS num_bikes_available, free AS num_docks_available,
      try_cast(json_extract_string(extra,'$.slots') AS INTEGER) AS capacity,
      try_cast(json_extract_string(extra,'$.renting') AS BOOLEAN) AS is_renting,
      try_cast(json_extract_string(extra,'$.returning') AS BOOLEAN) AS is_returning,
      cast(NULL AS BOOLEAN) AS is_installed,
      try_cast(json_extract_string(extra,'$.virtual') AS BOOLEAN) AS is_virtual,
      cast(NULL AS INTEGER) AS num_bikes_disabled,
      cast(NULL AS INTEGER) AS num_docks_disabled,
      try_cast(json_extract_string(extra,'$.ebikes') AS INTEGER) AS num_ebikes_available,
      coalesce(try_cast(json_extract_string(extra,'$.last_updated') AS BIGINT),
        cast(epoch(try_cast(json_extract_string(extra,'$.last_updated') AS TIMESTAMP)) AS BIGINT)) AS last_reported,
      ?::VARCHAR AS source_month, ?::VARCHAR AS source_file, ?::VARCHAR AS source_sha256,
      'inventory_change_event' AS record_type
    FROM read_parquet(?) WHERE tag='divvy'
    """


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data-root",type=Path,required=True)
    args=p.parse_args()
    root=args.data_root.resolve()
    downloads=json.loads((root/"download_manifest.json").read_text())
    if not downloads.get("completed_at_utc"):
        p.error("Download manifest is incomplete")
    out=root/"processed/events"
    out.mkdir(parents=True,exist_ok=True)
    manifest_path=root/"processed/extraction_manifest.json"
    extractor_hash=file_hash(Path(__file__))
    old=json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    if old and old.get("extractor_sha256")!=extractor_hash:
        p.error("Extractor changed; use a separate data root or review/remove only generated outputs")
    records=[]
    con=duckdb.connect()
    con.execute("SET threads=4")
    con.execute("SET TimeZone='UTC'")
    for src in downloads["files"]:
        if src.get("kind")!="citybikes" or src.get("error"):
            continue
        raw=root/src["path"]
        if file_hash(raw)!=src["sha256"]:
            raise ValueError(f"Raw SHA mismatch: {raw}")
        target=out/(src["month"]+".parquet")
        previous=next((r for r in old.get("parts",[]) if r["month"]==src["month"]),None)
        if previous and target.exists() and previous["source_sha256"]==src["sha256"] and file_hash(target)==previous["sha256"]:
            records.append(previous)
            continue
        con.execute("CREATE OR REPLACE TEMP TABLE normalized AS "+normalize_sql(),
            [src["month"],raw.name,src["sha256"],str(raw)])
        n,lo,hi=con.execute("SELECT count(*),min(timestamp),max(timestamp) FROM normalized").fetchall()[0]
        tmp=target.with_suffix(".parquet.tmp")
        con.execute("COPY (SELECT * FROM normalized ORDER BY station_id,timestamp) TO ? (FORMAT PARQUET,COMPRESSION ZSTD)",[str(tmp)])
        tmp.replace(target)
        record=dict(month=src["month"],path=target.relative_to(root).as_posix(),rows=n,
                    first_epoch=lo,last_epoch=hi,source_sha256=src["sha256"],sha256=file_hash(target))
        records.append(record)
        payload=dict(extractor_sha256=extractor_hash,source_manifest_sha256=file_hash(root/"download_manifest.json"),
            record_semantics="Only inventory changes; no complete polling heartbeat",
            source_license="ODbL-1.0 compilation; underlying operator terms separate",parts=records)
        manifest_path.write_text(json.dumps(payload,indent=2)+"\n")
        print(f"Normalized {src['month']}: {n:,} change events",flush=True)
    con.close()
    print(f"Normalized {sum(r['rows'] for r in records):,} rows in {len(records)} monthly parts",flush=True)


if __name__=="__main__":
    main()
