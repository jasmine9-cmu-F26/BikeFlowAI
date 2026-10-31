"""Extract immutable Git snapshots without checking out commits. Local output only.

Each atomic part has station rows and a snapshot inventory. Completed parts are
reused only for the same HEAD and part size; an interrupted part is rebuilt.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

import pyarrow as pa
import pyarrow.parquet as pq

VERSION = 1
FIELDS = {
    "timestamp": pa.int64(), "commit_timestamp": pa.int64(),
    "source_commit": pa.string(), "status_blob": pa.string(),
    "information_blob": pa.string(), "information_timestamp": pa.int64(),
    "station_id": pa.string(), "legacy_id": pa.string(),
    "information_station_id": pa.string(), "external_id": pa.string(),
    "name": pa.string(), "region_id": pa.string(),
    "num_bikes_available": pa.int32(), "num_docks_available": pa.int32(),
    "num_bikes_disabled": pa.int32(), "num_docks_disabled": pa.int32(),
    "is_installed": pa.bool_(), "is_renting": pa.bool_(),
    "is_returning": pa.bool_(), "last_reported": pa.int64(),
    "capacity": pa.int32(), "lat": pa.float64(), "lon": pa.float64(),
    "metadata_join": pa.string(),
}
SCHEMA = pa.schema(list(FIELDS.items()))


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args])


def history(repo):
    # Raw diff blob IDs avoid launching 80,000 `git show` processes.
    raw = git(repo, "log", "HEAD", "--reverse", "--raw", "--no-abbrev",
              "--format=@%H %ct %cI").decode("utf-8")
    records, blobs = [], {}
    for line in raw.splitlines():
        if line.startswith("@"):
            commit, epoch, date = line[1:].split(" ", 2)
            records.append(dict(commit=commit, commit_timestamp=int(epoch),
                                commit_date=date, blobs=blobs.copy()))
        elif line.startswith(":"):
            details, path = line.split("\t", 1)
            new_blob = details.split()[3]
            if new_blob == "0" * 40:
                blobs.pop(path, None)
            else:
                blobs[path] = new_blob
            records[-1]["blobs"] = blobs.copy()
    return records


class BlobReader:
    def __init__(self, repo):
        self.proc = subprocess.Popen(["git", "-C", str(repo), "cat-file", "--batch"],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE)

    def read(self, oid):
        self.proc.stdin.write((oid + "\n").encode("ascii"))
        self.proc.stdin.flush()
        header = self.proc.stdout.readline().split()
        if len(header) != 3 or header[1] != b"blob":
            raise ValueError(f"Not a blob: {header!r}")
        size = int(header[2])
        data = self.proc.stdout.read(size)
        if len(data) != size or self.proc.stdout.read(1) != b"\n":
            raise ValueError("Truncated git cat-file output")
        return json.loads(data)

    def close(self):
        self.proc.stdin.close()
        self.proc.stdout.close()
        self.proc.wait()


def flag(value):
    return bool(value) if value in (0, 1, False, True) else None


def text(value):
    return None if value is None else str(value)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", type=Path, default=Path("."))
    p.add_argument("--output", type=Path, default=Path("data/generated"))
    p.add_argument("--part-size", type=int, default=500)
    p.add_argument("--limit", type=int, help="Smoke run only; audit marks incomplete")
    args = p.parse_args()
    if args.part_size < 1:
        p.error("part-size must be positive")
    if git(args.repo, "rev-parse", "--is-shallow-repository").strip() != b"false":
        p.error("Full Git history required")
    if int(git(args.repo, "rev-list", "--min-parents=2", "--count", "HEAD")):
        p.error("This extractor requires linear history; merge commits found")
    records = history(args.repo)
    identity = {
        "extractor_version": VERSION,
        "extractor_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "source_head": git(args.repo, "rev-parse", "HEAD").decode().strip(),
        "source_remote": git(args.repo, "remote", "get-url", "origin").decode().strip(),
        "commit_count": len(records), "part_size": args.part_size, "limit": args.limit,
    }
    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    meta = out / "extraction_manifest.json"
    if meta.exists() and json.loads(meta.read_text()) != identity:
        p.error("Output belongs to a different extraction; use a new --output directory")
    meta.write_text(json.dumps(identity, indent=2) + "\n")
    (out / "parts").mkdir(exist_ok=True)
    inventory_fields = ["source_commit", "commit_timestamp", "commit_date", "status_blob",
                        "information_blob", "timestamp", "information_timestamp",
                        "station_count", "error"]
    selected = records[:args.limit] if args.limit else records
    cache = {}
    reader = BlobReader(args.repo)
    start = time.monotonic()
    try:
        for offset in range(0, len(selected), args.part_size):
            stem = out / "parts" / f"part-{offset // args.part_size:05d}"
            parquet = stem.with_suffix(".parquet")
            inventory = stem.with_suffix(".csv")
            if parquet.exists() and inventory.exists():
                continue
            columns = {k: [] for k in FIELDS}
            snapshots = []
            for rec in selected[offset:offset + args.part_size]:
                sb = rec["blobs"].get("station_status.json")
                ib = rec["blobs"].get("station_information.json")
                inv = dict(source_commit=rec["commit"], commit_timestamp=rec["commit_timestamp"],
                           commit_date=rec["commit_date"], status_blob=sb, information_blob=ib,
                           timestamp=None, information_timestamp=None, station_count=0, error="")
                snapshots.append(inv)
                if not sb or not ib:
                    inv["error"] = "missing_status_or_information_file"
                    continue
                try:
                    for kind, oid in (("status", sb), ("info", ib)):
                        if cache.get(kind, (None,))[0] != oid:
                            cache[kind] = (oid, reader.read(oid))
                    status, info = cache["status"][1], cache["info"][1]
                    ts, its = int(status["last_updated"]), int(info["last_updated"])
                    inv.update(timestamp=ts, information_timestamp=its)
                    by_id = {str(s["station_id"]): s for s in info["data"]["stations"]}
                    by_external = {str(s["external_id"]): s for s in info["data"]["stations"]
                                   if s.get("external_id")}
                    seen = set()
                    for s in status["data"]["stations"]:
                        sid = str(s["station_id"])
                        if sid in seen:
                            raise ValueError(f"duplicate station_id {sid}")
                        seen.add(sid)
                    for s in status["data"]["stations"]:
                        sid = str(s["station_id"])
                        m = by_id.get(sid) or by_external.get(sid) or {}
                        row = dict(timestamp=ts, commit_timestamp=rec["commit_timestamp"],
                                   source_commit=rec["commit"], status_blob=sb, information_blob=ib,
                                   information_timestamp=its, station_id=sid,
                                   legacy_id=text(s.get("legacy_id", m.get("legacy_id"))),
                                   information_station_id=text(m.get("station_id")),
                                   external_id=text(m.get("external_id")), name=m.get("name"),
                                   region_id=text(m.get("region_id")),
                                   last_reported=s.get("last_reported"),
                                   capacity=m.get("capacity"), lat=m.get("lat"), lon=m.get("lon"),
                                   metadata_join="station_id" if sid in by_id else
                                   "external_id" if sid in by_external else "unmatched")
                        for key in ("num_bikes_available", "num_docks_available",
                                    "num_bikes_disabled", "num_docks_disabled"):
                            row[key] = s.get(key)
                        for key in ("is_installed", "is_renting", "is_returning"):
                            row[key] = flag(s.get(key))
                        for key in FIELDS:
                            columns[key].append(row[key])
                    inv["station_count"] = len(seen)
                except (KeyError, ValueError, TypeError) as exc:
                    # Invalid snapshots are recorded, never turned into zero inventories.
                    inv["error"] = f"{type(exc).__name__}: {exc}"
            pq.write_table(pa.Table.from_pydict(columns, schema=SCHEMA),
                           str(parquet) + ".tmp", compression="zstd")
            with open(str(inventory) + ".tmp", "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=inventory_fields)
                writer.writeheader()
                writer.writerows(snapshots)
            os.replace(str(parquet) + ".tmp", parquet)
            os.replace(str(inventory) + ".tmp", inventory)
            print(f"{min(offset + args.part_size, len(selected))}/{len(selected)} commits; "
                  f"{time.monotonic() - start:.1f}s", flush=True)
    finally:
        reader.close()
    print(f"Partitioned station_snapshots.parquet dataset: {out / 'parts'}", flush=True)


if __name__ == "__main__":
    main()
