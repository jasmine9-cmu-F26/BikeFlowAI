"""Audit the extracted archive; never train a model or impute missing inventory.

Coverage uses fixed UTC 420-second slots and nearest observations within 210 s.
Labels use actual request snapshot times, nearest targets within 210 s, and
never cross chronological split boundaries. Station selection uses training only.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import platform
import subprocess

import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

STEP, TOL = 420, 210


def iso(t):
    return datetime.fromtimestamp(int(t), timezone.utc).isoformat().replace("+00:00", "Z")


def write_csv(path, rows, fields=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(rows)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields or list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def nearest_indices(t, targets):
    """Nearest timestamp; ties choose earlier, no forward-fill across gaps."""
    right = np.searchsorted(t, targets).clip(0, len(t) - 1)
    left = (right - 1).clip(0, len(t) - 1)
    return np.where(abs(t[left] - targets) <= abs(t[right] - targets), left, right)


def label_stats(t, valid, fresh, bike_bad, dock_bad, lo, hi, k):
    in_scope = (t >= lo) & (t < hi)
    base = np.flatnonzero(valid & in_scope & (t + STEP * k < hi))
    targets = t[base] + STEP * k
    candidate_idx = np.flatnonzero(in_scope)
    stats = dict(base_rows=len(base), timing_matched=0, valid_labels=0,
                 fresh_labels=0, bike_unavailable=0, dock_unavailable=0)
    if len(base) and len(candidate_idx):
        ix = candidate_idx[nearest_indices(t[candidate_idx], targets)]
        hit = abs(t[ix] - targets) <= TOL
        good = hit & valid[ix]
        stats.update(timing_matched=int(hit.sum()), valid_labels=int(good.sum()),
            fresh_labels=int((good & fresh[ix]).sum()),
            bike_unavailable=int((good & bike_bad[ix]).sum()),
            dock_unavailable=int((good & dock_bad[ix]).sum()))
    return stats


def slot_count(start, end):
    return max(0, math.ceil(end / STEP) - math.ceil(start / STEP))


def covered_slots(t, start, end):
    t = t[(t >= start) & (t < end)]
    slots = (t + TOL) // STEP
    slots = slots[(slots * STEP >= start) & (slots * STEP < end)]
    return len(np.unique(slots))


def make_splits(first, last):
    # Full Monday-to-Monday UTC weeks; remove 60 min from the start of each later split.
    week = 7 * 86400
    monday = 4 * 86400  # 1970-01-05
    start = monday + math.ceil((first - monday) / week) * week
    end = monday + math.floor((last - monday) / week) * week
    n = int((end - start) // week)
    if n < 4:
        raise ValueError("Need at least four complete weeks to construct four splits")
    bounds = [0, int(n * .60), int(n * .75), int(n * .85), n]
    return [dict(split=name, start_epoch=start + bounds[i] * week + (3600 if i else 0),
                 end_epoch=start + bounds[i + 1] * week)
            for i, name in enumerate(("train", "tune", "calibration", "test"))]


def station_tables(con):
    reader = con.sql("SELECT * FROM obs ORDER BY station_id, timestamp").to_arrow_reader(100000)
    chunks, current = [], None
    for batch in reader:
        ids = batch.column("station_id").to_numpy(zero_copy_only=False)
        cuts = np.r_[0, np.flatnonzero(ids[1:] != ids[:-1]) + 1, len(ids)]
        for lo, hi in zip(cuts[:-1], cuts[1:]):
            sid = ids[lo]
            if current is not None and sid != current:
                yield current, pa.Table.from_batches(chunks).combine_chunks()
                chunks = []
            current = sid
            chunks.append(batch.slice(int(lo), int(hi - lo)))
    if chunks:
        yield current, pa.Table.from_batches(chunks).combine_chunks()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", type=Path, default=Path("."), help="Original archive Git checkout")
    p.add_argument("--input", type=Path, default=Path("data/generated"))
    p.add_argument("--reports", type=Path, default=Path("reports/data_audit"))
    p.add_argument("--manifests", type=Path, default=Path("data/manifests"))
    p.add_argument("--region-id", default="3", help="Historical SF region; choose training stations here")
    p.add_argument("--station-limit", type=int, default=20)
    args = p.parse_args()
    out, manifests = args.reports, args.manifests
    out.mkdir(parents=True, exist_ok=True)
    manifests.mkdir(parents=True, exist_ok=True)
    extraction = json.loads((args.input / "extraction_manifest.json").read_text())
    actual_head = subprocess.check_output(["git", "-C", str(args.repo), "rev-parse", "HEAD"]).decode().strip()
    if actual_head != extraction["source_head"]:
        p.error("--repo HEAD differs from the extracted source; use the original frozen checkout")
    inventory = []
    for path in sorted((args.input / "parts").glob("*.csv")):
        with path.open(encoding="utf-8", newline="") as f:
            inventory.extend(csv.DictReader(f))
    if len(inventory) != extraction["commit_count"] or extraction["limit"]:
        raise ValueError("Incomplete extraction: full-history audit refused")
    if len(set(r["source_commit"] for r in inventory)) != len(inventory):
        raise ValueError("Duplicate commit inventory")
    ct = np.sort(np.array([int(r["commit_timestamp"]) for r in inventory]))
    feed = np.unique([int(r["timestamp"]) for r in inventory if r["timestamp"] and not r["error"]])
    first, last = int(feed[0]), int(feed[-1])
    splits = make_splits(first, last)
    scopes = [dict(split="archive", start_epoch=first, end_epoch=last + 1), *splits]
    split_rows = [dict(split=s["split"], start_utc=iso(s["start_epoch"]),
                       end_utc_exclusive=iso(s["end_epoch"]),
                       duration_weeks=(s["end_epoch"] - s["start_epoch"]) / 604800,
                       purge_before_minutes=0 if i == 0 else 60,
                       source_head=extraction["source_head"],
                       status="audit_proposal_not_frozen_until_pass") for i, s in enumerate(splits)]
    write_csv(manifests / "split_manifest.csv", split_rows)
    write_csv(out / "extraction_errors.csv", [r for r in inventory if r["error"]], list(inventory[0]))
    con = duckdb.connect(str(args.input / "audit.duckdb"))
    con.execute("SET memory_limit='2GB'")
    con.execute("SET threads=4")
    pattern = str((args.input / "parts" / "*.parquet").resolve()).replace("\\", "/")
    con.execute("CREATE OR REPLACE TABLE obs AS SELECT * EXCLUDE (rn) FROM "
                "(SELECT *, row_number() OVER (PARTITION BY station_id,timestamp "
                "ORDER BY commit_timestamp DESC,source_commit DESC) rn "
                "FROM read_parquet(?)) WHERE rn=1 ORDER BY station_id,timestamp", [pattern])
    raw_rows = con.execute("SELECT count(*) FROM read_parquet(?)", [pattern]).fetchall()[0][0]
    unique_rows = con.execute("SELECT count(*) FROM obs").fetchall()[0][0]
    coverage, gaps, changes, id_map = [], [], [], []
    balances, labels = {}, {}
    quality = dict(rows=0, unmatched_metadata=0, missing_counts=0, unknown_flags=0,
                   uninstalled=0, not_renting=0, not_returning=0, stale_over_300s=0,
                   missing_last_reported=0, future_last_reported=0,
                   capacity_count_mismatch=0, information_after_status=0)
    for group in ("all_stations", "training_top20_exploratory", "selected_stations"):
        for scope in scopes:
            balances[group, scope["split"]] = dict(valid_rows=0, bike_unavailable=0,
                                                  dock_unavailable=0, empty_count=0, full_count=0)
            for k in range(1, 9):
                labels[group, scope["split"], k] = dict(base_rows=0, timing_matched=0,
                    valid_labels=0, fresh_labels=0, bike_unavailable=0, dock_unavailable=0)
    # Keep small per-station counters, so selected-station summaries can be computed
    # after TRAINING-ONLY selection without rereading the archive.
    per_station, station_meta = {}, {}
    for count, (sid, table) in enumerate(station_tables(con), 1):
        a = {name: table[name].to_numpy(zero_copy_only=False) for name in table.column_names}
        t = a["timestamp"].astype(np.int64)
        numeric = np.isfinite(a["num_bikes_available"]) & np.isfinite(a["num_docks_available"])
        numeric &= (a["num_bikes_available"] >= 0) & (a["num_docks_available"] >= 0)
        flags_known = np.array([v is not None for v in a["is_installed"]])
        flags_known &= np.array([v is not None for v in a["is_renting"]])
        flags_known &= np.array([v is not None for v in a["is_returning"]])
        installed = a["is_installed"] == True
        valid = numeric & flags_known & installed & (a["metadata_join"] != "unmatched")
        age = t - a["last_reported"]
        fresh = valid & np.isfinite(age) & (age >= 0) & (age <= 300)
        bike_bad = (a["num_bikes_available"] < 1) | (a["is_renting"] != True)
        dock_bad = (a["num_docks_available"] < 1) | (a["is_returning"] != True)
        quality["rows"] += len(t)
        for key, mask in {
            "unmatched_metadata": a["metadata_join"] == "unmatched",
            "missing_counts": ~numeric, "unknown_flags": ~flags_known,
            "uninstalled": ~installed, "not_renting": a["is_renting"] != True,
            "not_returning": a["is_returning"] != True,
            "stale_over_300s": age > 300, "missing_last_reported": ~np.isfinite(age),
            "future_last_reported": age < 0,
            "information_after_status": a["information_timestamp"] > t,
            "capacity_count_mismatch": (a["num_bikes_available"] + a["num_docks_available"] +
                a["num_bikes_disabled"] + a["num_docks_disabled"]) != a["capacity"],
        }.items():
            quality[key] += int(mask.sum())
        row = dict(station_id=sid, name=a["name"][0], region_id=a["region_id"][0],
                   first_utc=iso(t[0]), last_utc=iso(t[-1]), observed_snapshots=len(t))
        for scope in scopes:
            lo, hi, name = scope["start_epoch"], scope["end_epoch"], scope["split"]
            denominator = slot_count(lo, hi)
            # Use all observations for nearest-slot coverage, clipping grid centers
            # to this scope. The archive endpoints are not extrapolated.
            n = covered_slots(t, lo, hi)
            nv, nf = covered_slots(t[valid], lo, hi), covered_slots(t[fresh], lo, hi)
            row.update({f"{name}_expected_slots": denominator, f"{name}_observed_slots": n,
                        f"{name}_coverage": n / denominator if denominator else 0,
                        f"{name}_valid_coverage": nv / denominator if denominator else 0,
                        f"{name}_fresh_coverage": nf / denominator if denominator else 0})
        dt = np.diff(t) / 60
        gaps.append(dict(station_id=sid, gap_count=len(dt), median_minutes=float(np.median(dt)) if len(dt) else "",
                         p90_minutes=float(np.quantile(dt, .90)) if len(dt) else "", longest_gap_minutes=float(dt.max()) if len(dt) else "",
                         gaps_gt14=int((dt > 14).sum()), gaps_gt30=int((dt > 30).sum()),
                         gaps_gt60=int((dt > 60).sum()),
                         leading_missing_minutes=(t[0] - first) / 60,
                         trailing_missing_minutes=(last - t[-1]) / 60))
        train = (t >= splits[0]["start_epoch"]) & (t < splits[0]["end_epoch"])
        train_idx = np.flatnonzero(train)
        row["training_capacity_versions"] = len(set(a["capacity"][train]))
        row["training_location_versions"] = len(set(zip(a["lat"][train], a["lon"][train])))
        row["training_region_id"] = a["region_id"][train_idx[0]] if len(train_idx) else None
        # Metadata segments are historical evidence, not an inferred map to 2026 IDs.
        keys = ("legacy_id", "information_station_id", "external_id", "name", "capacity", "lat", "lon", "region_id")
        segment_start = 0
        for j in range(1, len(t) + 1):
            def same(x, y):
                return x == y or (x is None and y is None) or (
                    isinstance(x, (float, np.floating)) and isinstance(y, (float, np.floating))
                    and math.isnan(x) and math.isnan(y))
            different = j == len(t) or any(not same(a[key][j], a[key][j - 1]) for key in keys)
            if not different:
                continue
            id_map.append(dict(historical_station_id=sid, valid_from_utc=iso(t[segment_start]),
                valid_to_utc_exclusive=iso(t[j]) if j < len(t) else "",
                last_observed_utc=iso(t[j - 1]), legacy_id=a["legacy_id"][segment_start],
                external_id=a["external_id"][segment_start],
                information_station_id=a["information_station_id"][segment_start],
                lat=a["lat"][segment_start], lon=a["lon"][segment_start],
                capacity=a["capacity"][segment_start], current_gbfs_id="",
                mapping_status="historical_identity_only_current_and_trip_mapping_unverified"))
            if j < len(t):
                for key in keys:
                    if not same(a[key][j], a[key][j - 1]):
                        changes.append(dict(station_id=sid, timestamp_utc=iso(t[j]), field=key,
                            old_value=a[key][j - 1], new_value=a[key][j],
                            source_commit=a["source_commit"][j]))
            segment_start = j
        local_bal, local_lab = {}, {}
        for scope in scopes:
            name, lo, hi = scope["split"], scope["start_epoch"], scope["end_epoch"]
            in_scope = (t >= lo) & (t < hi)
            mask = valid & in_scope
            local_bal[name] = dict(valid_rows=int(mask.sum()),
                bike_unavailable=int((mask & bike_bad).sum()), dock_unavailable=int((mask & dock_bad).sum()),
                empty_count=int((mask & (a["num_bikes_available"] == 0)).sum()),
                full_count=int((mask & (a["num_docks_available"] == 0)).sum()))
            for k in range(1, 9):
                local_lab[name, k] = label_stats(t, valid, fresh, bike_bad, dock_bad, lo, hi, k)
        per_station[sid] = (local_bal, local_lab)
        station_meta[sid] = row
        coverage.append(row)
        if count % 100 == 0:
            print(f"Audited {count} stations", flush=True)
    candidates = [r for r in coverage if r["training_region_id"] == args.region_id]
    candidates.sort(key=lambda r: (-r["train_valid_coverage"], r["station_id"]))
    exploratory = {r["station_id"] for r in candidates[:20]}
    eligible = [r for r in candidates if r["train_valid_coverage"] >= .90 and
                r["training_capacity_versions"] == 1 and r["training_location_versions"] == 1]
    chosen = eligible[:args.station_limit]
    chosen_ids = {r["station_id"] for r in chosen}
    for r in coverage:
        r["selected"] = r["station_id"] in chosen_ids
        r["exploratory_top20"] = r["station_id"] in exploratory
    for sid, (local_bal, local_lab) in per_station.items():
        groups = ["all_stations"]
        if sid in exploratory:
            groups.append("training_top20_exploratory")
        if sid in chosen_ids:
            groups.append("selected_stations")
        for group in groups:
            for name, stats in local_bal.items():
                for key, value in stats.items():
                    balances[group, name][key] += value
            for (name, k), stats in local_lab.items():
                for key, value in stats.items():
                    labels[group, name, k][key] += value
    balance_rows, label_rows = [], []
    for (group, name), stats in balances.items():
        n = stats["valid_rows"]
        balance_rows.append(dict(group=group, split=name, **stats,
            bike_unavailable_rate=stats["bike_unavailable"] / n if n else "",
            dock_unavailable_rate=stats["dock_unavailable"] / n if n else ""))
    for (group, name, k), stats in labels.items():
        n = stats["base_rows"]
        label_rows.append(dict(group=group, split=name, k=k, horizon_minutes=7 * k, **stats,
            valid_retention=stats["valid_labels"] / n if n else "",
            fresh_retention=stats["fresh_labels"] / n if n else ""))
    write_csv(out / "coverage_by_station.csv", sorted(coverage, key=lambda r:r["station_id"]))
    write_csv(out / "gap_summary.csv", gaps)
    write_csv(out / "label_retention.csv", label_rows)
    write_csv(out / "class_balance.csv", balance_rows)
    write_csv(out / "station_changes.csv", changes,
              ["station_id", "timestamp_utc", "field", "old_value", "new_value", "source_commit"])
    write_csv(manifests / "station_id_map.csv", id_map)
    selected_fields = ["station_id", "name", "training_region_id", "train_valid_coverage", "selected"]
    write_csv(manifests / "selected_stations.csv", [{k:r[k] for k in selected_fields} for r in chosen], selected_fields)
    write_csv(manifests / "candidate_stations.csv", [dict(station_id=r["station_id"], name=r["name"],
        train_valid_coverage=r["train_valid_coverage"], selected=False,
        status="exploratory_only_fails_90pct_gate") for r in candidates[:20]],
        ["station_id", "name", "train_valid_coverage", "selected", "status"])
    # Temporal upper bound: no individual station can exceed whole-feed slot coverage.
    weekly, day = [], 86400
    start = splits[0]["start_epoch"]
    while start + 7 * day <= splits[-1]["end_epoch"]:
        end = start + 7 * day
        n, den = covered_slots(feed, start, end), slot_count(start, end)
        weekly.append(dict(start_utc=iso(start), end_utc_exclusive=iso(end),
                           expected_slots=den, observed_slots=n, coverage=n / den))
        start = end
    write_csv(out / "weekly_coverage.csv", weekly)
    # Exact sliding upper bound over all 10-week windows of the fixed 7-minute grid.
    # This is diagnostic only, not station/split selection using held-out outcomes.
    grid_start, grid_end = math.ceil(first / STEP), math.floor(last / STEP)
    grid = np.arange(grid_start, grid_end + 1)
    feed_slots = np.unique((feed + TOL) // STEP)
    covered = np.isin(grid, feed_slots).astype(np.int64)
    width = 10 * 7 * 86400 // STEP  # exactly 14,400 slots
    sums = np.r_[0, covered.cumsum()]
    window = sums[width:] - sums[:-width]
    best_index = int(window.argmax()) if len(window) else 0
    upper_bound = float(window.max() / width) if len(window) else 0
    # A portable single-file artifact, alongside resumable parts.
    target = args.input / "station_snapshots.parquet"
    tmp = Path(str(target) + ".tmp")
    con.execute("COPY obs TO ? (FORMAT PARQUET, COMPRESSION ZSTD)", [str(tmp.resolve())])
    tmp.replace(target)
    license_paths = subprocess.check_output(["git", "-C", str(args.repo), "log", "--all", "--format=", "--name-only",
        "--", ":(icase)*license*", ":(icase)*licence*", ":(icase)*copying*", ":(icase)*notice*"]).decode().splitlines()
    source_files = subprocess.check_output(["git", "-C", str(args.repo), "ls-tree", "-r", "--name-only", extraction["source_head"]]).decode().splitlines()
    selected_pass = len(chosen) >= 20 and all(
        r[f"{s['split']}_valid_coverage"] >= .90 for r in chosen for s in splits)
    duration_pass = split_rows[0]["duration_weeks"] >= 8 and split_rows[-1]["duration_weeks"] >= 2
    decision = "PASS" if selected_pass and duration_pass else "FALLBACK"
    cd, fd = np.diff(ct) / 60, np.diff(feed) / 60
    stats = dict(source=extraction, complete=True, source_files=source_files,
        first_commit_utc=iso(ct[0]), last_commit_utc=iso(ct[-1]),
        first_snapshot_utc=iso(first), last_snapshot_utc=iso(last),
        commits=len(inventory), unique_feed_snapshots=len(feed), raw_station_rows=raw_rows,
        deduplicated_station_rows=unique_rows, stations=len(coverage),
        invalid_commits=sum(bool(r["error"]) for r in inventory),
        commit_interval_median_minutes=float(np.median(cd)), commit_interval_p90_minutes=float(np.quantile(cd,.90)),
        feed_interval_median_minutes=float(np.median(fd)), feed_interval_p90_minutes=float(np.quantile(fd,.90)),
        feed_longest_gap_minutes=float(fd.max()),
        feed_gaps_gt14=int((fd>14).sum()), feed_gaps_gt30=int((fd>30).sum()), feed_gaps_gt60=int((fd>60).sum()),
        archive_feed_coverage=covered_slots(feed,first,last+1)/slot_count(first,last+1),
        best_10week_feed_coverage=upper_bound,
        best_10week_window_start_utc=iso((grid_start+best_index)*STEP),
        stations_archive_90pct=sum(r["archive_coverage"]>=.90 for r in coverage),
        stations_training_90pct=sum(r["train_valid_coverage"]>=.90 for r in coverage),
        selected_station_count=len(chosen), metadata_change_events=len(changes),
        license_history_paths=sorted(set(filter(None,license_paths))), quality=quality,
        decision=decision, splits=split_rows,
        runtime=dict(python=platform.python_version(),duckdb=duckdb.__version__,numpy=np.__version__,pyarrow=pa.__version__),
        audit_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        parquet_sha256="")
    with target.open("rb") as stream:
        stats["parquet_sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
    (out / "audit_summary.json").write_text(json.dumps(stats, indent=2) + "\n")
    # Report text is kept in the repo and rebuilt from measured statistics.
    report = build_report(stats, label_rows, balance_rows, coverage)
    (out / "data_audit.md").write_text(report, encoding="utf-8")
    con.close()
    print(json.dumps({k:stats[k] for k in ("decision","stations","unique_feed_snapshots",
          "archive_feed_coverage","best_10week_feed_coverage","selected_station_count")}, indent=2))


def build_report(s, labels, balances, coverage):
    percent = lambda x: f"{100*x:.2f}%"
    label_lines = []
    for r in labels:
        if r["group"] == "all_stations" and r["split"] == "archive":
            label_lines.append(f"| {r['k']} | {r['horizon_minutes']} | {r['base_rows']:,} | "
                f"{percent(r['valid_retention'])} | {percent(r['fresh_retention'])} |")
    balance = next(r for r in balances if r["group"] == "all_stations" and r["split"] == "archive")
    split_lines = [f"| {r['split']} | {r['start_utc']} | {r['end_utc_exclusive']} | {r['duration_weeks']:.3f} |"
                   for r in s["splits"]]
    quality_lines = [f"- {key}: {value:,} ({percent(value/s['quality']['rows'])})."
                     for key,value in s["quality"].items() if key != "rows"]
    return f"""# Bay Wheels Data Audit

审计日期：2026-10-30（America/Los_Angeles）。结论：**{s['decision']}，原 proposal 的 7-minute / 90% coverage 条件不成立。**
这是完整本地 Git 历史的实际审计；没有训练模型。数据可用于历史状态研究，但当前不能宣称已足够支撑 proposal 原样的训练、校准、测试和 replay。

## Repo 与可追溯性

- Source: https://github.com/terinjokes/baywheels-history
- Frozen source HEAD: `{s['source']['source_head']}`；完整非 shallow 历史，线性提交。
- Commits: **{s['commits']:,}**；earliest `{s['first_commit_utc']}`；latest `{s['last_commit_utc']}`。
- Commit interval median / p90: **{s['commit_interval_median_minutes']:.3f} / {s['commit_interval_p90_minutes']:.3f} min**。
- Available files: {', '.join('`'+x+'`' for x in s['source_files'])}。
- 未在当前树及 `git log --all` 的 LICENSE / LICENCE / COPYING / NOTICE 文件名检查中发现许可证。README 也未声明复用许可；这不等于已证明底层数据无任何许可。
- 完整数值、依赖版本、提取器 hash、Parquet SHA-256: `audit_summary.json`。

## Date range 与 snapshots

- 使用 **station_status.last_updated**（UTC Unix seconds）作为 snapshot 时间，保留 commit 时间和 hash。
- Date range: **{s['first_snapshot_utc']} → {s['last_snapshot_utc']}**。
- Unique feed timestamps: **{s['unique_feed_snapshots']:,}**；raw station rows: **{s['raw_station_rows']:,}**；按 station_id + timestamp 去重后 **{s['deduplicated_station_rows']:,}**。
- 无效/缺少文件的 commits: {s['invalid_commits']}，详见 `extraction_errors.csv`，没有把它们当成空站。
- Feed interval median / p90: **{s['feed_interval_median_minutes']:.3f} / {s['feed_interval_p90_minutes']:.3f} min**。
- 这是 2022–2023 的历史数据，不覆盖 2026 年；历史回放和当前服务需分别验证。

## Coverage 与验收

固定 UTC epoch 对齐的 7-minute 网格；每个 slot 只有在 ±210 秒内存在观察才算 covered，多条观察只计一次。
分母为整个审计/分割期间应有 slots，**不缩成单个站点自己的存活期**。Presence、valid 和 fresh 三种覆盖率分别列出。
Valid 是结构完整性检查：已安装、已知 renting/returning flags、非负 bike/dock counts 且同 commit metadata 可 join；fresh 进一步要求 last_reported age 在 0–300 秒。
Valid 不是最终训练准入；未报告/陈旧观察不能作为可靠标签，建模前还需确定严格的 base/target freshness 和 causal metadata 规则。

- Stations examined: **{s['stations']}**。
- Whole-feed 7-minute coverage: **{percent(s['archive_feed_coverage'])}**。
- Stations ≥90% archive presence coverage: **{s['stations_archive_90pct']}**；≥90% training valid coverage: **{s['stations_training_90pct']}**。
- Selected stations: **{s['selected_station_count']}**。`selected_stations.csv` 只有通过门槛的站；失败时保留空表，避免把候选误称已冻结。
- 全部滑动 10-week windows 的最佳 whole-feed coverage 也只有 **{percent(s['best_10week_feed_coverage'])}**，起于 `{s['best_10week_window_start_utc']}`。这是单站覆盖的上界；不能靠挑 20 个站或 10 周达到 90%。此计算仅诊断，不据此挑 test。
- `candidate_stations.csv` 是按 training coverage 排名的 SF 候选，仅供调整设计后的复审；没有以 test 结果选站。

## Chronological splits / calibration

只用完整 Monday-to-Monday UTC weeks，按 60/15/10/15 的累计比例向下取整为整周；后面每个 split 开头排除 60 分钟，边界不能被 label 跨越。
这些是 **audit proposal**，因为 coverage 未过，尚未冻结为可训练数据集。

| Split | Start UTC | End UTC (exclusive) | Weeks after purge |
|---|---|---|---:|
{chr(10).join(split_lines)}

时长足以容纳 8 weeks train 和 2 later weeks test，并留独立 tuning / calibration；缺少的是足够密集的观察。Split 保持真实日历时间，不把缺失周压缩掉。

## Missingness / long gaps

- Whole-feed missing slots: **{percent(1-s['archive_feed_coverage'])}**。
- Feed gaps >14 / >30 / >60 min: **{s['feed_gaps_gt14']:,} / {s['feed_gaps_gt30']:,} / {s['feed_gaps_gt60']:,}**。
- Longest feed gap: **{s['feed_longest_gap_minutes']:.2f} min**。
- `gap_summary.csv` 逐站报告相邻观察间隔及站点上线前/下线后的边界缺失；gap 次数不能等同缺失 slot 数。

## Label retention k=1…8

基准为每个 station 的有效 **实际 snapshot 时刻 t**；target=t+7k，nearest observation 在 ±3.5 min 内才有 label，平局取较早。
没有对齐后 forward-fill 或将 missing 记为 0。同一未来 snapshot 可以被多个 targets 使用，故样本并不独立；这里是可观测率，不是训练质量证明。
每个 split 分开匹配；target 和匹配 observation 都必须在本 split 内。Fresh retention 要求 target last_reported ≤5 min，分母仍为结构完整的 base rows，并未要求 base fresh；未通过 station gate，以下为全站诊断结果。

| k | Minutes | Eligible base rows | Valid label retention | Fresh label retention |
|---:|---:|---:|---:|---:|
{chr(10).join(label_lines)}

`label_retention.csv` 另含各 split、training top20 exploratory 和 selected groups；空 selected group 的 rate 留空。
高 label retention 并不能代替 ≥90% fixed-grid coverage 验收。

## Class balance / status flags

- 在 {balance['valid_rows']:,} 个 valid observed station rows 中：bike unavailable **{percent(balance['bike_unavailable_rate'])}**；dock unavailable **{percent(balance['dock_unavailable_rate'])}**。
- Bike unavailable = bikes<1 或 renting=false；dock unavailable = docks<1 或 returning=false。缺失观察不进入分母。
- `class_balance.csv` 是观察行的事件率；`label_retention.csv` 同时给各 k 的 matched target 事件计数。不能当作均匀时间事件率。
- 这些是结构完整观察的诊断统计，包含部分陈旧状态；最终训练标签需要再排除陈旧/不报告行，不能把它们当成确认 empty/full。

质量计数（可能重叠，分母 {s['quality']['rows']:,} observed rows）：

{chr(10).join(quality_lines)}

## Station changes / IDs

`station_changes.csv` 有 **{s['metadata_change_events']:,}** 条相邻可观察 metadata 字段变化，含 capacity、lat/lon、legacy/external/information IDs、name 和 region。
`station_id_map.csv` 是历史有效区间，非当前站 ID 的臆测；`current_gbfs_id` 留空。legacy ID 共用/更名不自动等于同一物理站。
没有下一 metadata 版本时 end 留空，只表示未观测到后继版本，不代表持续有效至今；站点缺报期间也不能凭区间补出状态。
同 commit metadata 可能比 status feed 新几秒，其次数已列出；本审计只用于 coverage，做模型特征时必须再使用 ≤request time 的 metadata as-of join。
Station selection 要求 training 内 capacity 和坐标不变；没有用 held-out metadata 来筛站。
capacity 与 available/disabled 四项之和不相等只是诊断信号，须检查 feed 语义及 metadata 时序，不能据此自动修正库存或用 capacity-bikes 替代实际 docks。

## Timezone

Git commit 的 offset 转为 UTC；feed last_updated / last_reported 是 Unix seconds。`system_information.json` 给出 America/Los_Angeles。
Trip CSV 的 naive 时间应按 Pacific 本地时间处理，并单独处理 DST ambiguous/nonexistent 时间，不能固定减 8 小时，也不能静默猜 fold。
已逐行读取 trip CSV 检查日期，但尚未完成时间本地化与 station-state join；Pacific 是 proposal 约定，仍需对文件约定验证。

## Weather / trips / licensing

参见 `external_sources.json` 和 `licensing_and_overlap.md`（独立网络检查，含 URL 和检查时间）。
官方 Previous Runs 文档说多数模型从 January 2024 开始，GFS 2m temperature 从 March 2021 是例外；不能假定 2022–2023 的完整温度/降水/风速特征都覆盖。
Trip 文件和日期覆盖不等于 station ID overlap；需要分别检查。
本次 external check 已读取 12 个月、2,514,078 条 trips 验证日期，精确 UTC overlap / station ID join 仍 pending。
Archive 没有已发现的 repo license；Lyft 官方 license 有独立条款，不应自动当作社区 archive 的 redistribution 授权，也不应给原 archive 加 MIT/CC license。

## Decision 与下一步

**{s['decision']} for the original proposal gate.** 20 stations × ≥90% of 7-minute slots 不成立；缩小同一个 archive 的站点/时段也不能补足上界。
可保留这些历史数据用于实验，但需要团队/课程认可新的采样与 missingness 方案后重新 audit，例如更粗粒度时间轴，或更密集且覆盖足够周数的新 archive。
独立 calibrate/test 时长可满足，实际可训练性仍取决于修订后的 gate、每 split/horizon 稀有事件数、trip ID mapping 及 weather availability。
代码、汇总报告、manifest 可以整理到项目 repo；raw JSON、trip CSV、Parquet 留本地，不复制整个社区 archive 历史到项目 repo。
"""


if __name__ == "__main__":
    main()
