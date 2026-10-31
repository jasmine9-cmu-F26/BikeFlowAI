"""Small synthetic correctness checks for temporal matching and Git extraction."""
import csv
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "legacy/baywheels/scripts/data"))
from audit_baywheels_data import nearest_indices, covered_slots, make_splits, label_stats, TOL


class TemporalTests(unittest.TestCase):
    def test_ties_boundary_and_missing_target(self):
        t = np.array([0, 420, 1800])
        target = np.array([210, 630, 631, 1380])
        idx = nearest_indices(t, target)
        self.assertEqual(idx.tolist(), [0, 1, 1, 2])
        self.assertEqual((abs(t[idx]-target) <= TOL).tolist(), [True, True, False, False])

    def test_slot_dedup_and_training_boundary(self):
        # Two samples in one slot count once; an observation from the next
        # partition must not inflate the training coverage.
        self.assertEqual(covered_slots(np.array([400, 420, 430]), 0, 840), 1)
        self.assertEqual(covered_slots(np.array([630]), 0, 630), 0)

    def test_splits_have_separate_calibration_and_purge(self):
        splits = make_splits(1659910172, 1689793616)
        self.assertEqual([s["split"] for s in splits], ["train", "tune", "calibration", "test"])
        for before, after in zip(splits, splits[1:]):
            self.assertEqual(after["start_epoch"]-before["end_epoch"], 3600)
        self.assertGreaterEqual((splits[0]["end_epoch"]-splits[0]["start_epoch"])/604800,8)
        self.assertGreaterEqual((splits[-1]["end_epoch"]-splits[-1]["start_epoch"])/604800,2)

    def test_label_matching_cannot_use_next_partition(self):
        t = np.array([0, 620, 1000])
        valid = np.ones(3, dtype=bool)
        fresh = np.array([True, False, True])
        events = np.array([False, True, False])
        one = label_stats(t, valid, fresh, events, events, 0, 900, 1)
        self.assertEqual(one["base_rows"],1)
        self.assertEqual(one["valid_labels"],1)
        self.assertEqual(one["bike_unavailable"],1)
        self.assertEqual(one["fresh_labels"],0)
        two = label_stats(t, valid, fresh, events, events, 0, 900, 2)
        # 1000 would be within tolerance of target 840, but is outside this split.
        self.assertEqual(two["base_rows"],1)
        self.assertEqual(two["timing_matched"],0)


class ExtractorTests(unittest.TestCase):
    def test_real_git_snapshot_join_duplicate_feed_and_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "source"
            repo.mkdir()
            def git(*args):
                return subprocess.check_output(["git", "-C", str(repo), *args], stderr=subprocess.STDOUT)
            git("init", "-q")
            git("config", "user.name", "Synthetic Fixture")
            git("config", "user.email", "fixture@example.invalid")
            git("remote", "add", "origin", "https://example.invalid/synthetic")
            (repo / "README").write_text("Synthetic test only")
            git("add", ".")
            git("commit", "-qm", "initial no feed")
            status = json.loads((ROOT / "tests/fixtures/station_status_sample.json").read_text())
            info = dict(last_updated=status["last_updated"], data=dict(stations=[
                dict(station_id="synthetic-A", external_id="synthetic-A", name="Synthetic A",
                     capacity=10, lat=37.0, lon=-122.0, region_id="3"),
                dict(station_id="synthetic-B", external_id="synthetic-B", name="Synthetic B",
                     capacity=10, lat=37.1, lon=-122.1, region_id="3")]))
            (repo / "station_status.json").write_text(json.dumps(status))
            (repo / "station_information.json").write_text(json.dumps(info))
            git("add", ".")
            git("commit", "-qm", "first feed")
            info["data"]["stations"][0]["capacity"] = 12
            (repo / "station_information.json").write_text(json.dumps(info))
            git("commit", "-qam", "metadata only, repeated status timestamp")
            output = Path(tmp) / "generated"
            command = [sys.executable, str(ROOT / "legacy/baywheels/scripts/data/extract_baywheels_history.py"),
                       "--repo", str(repo), "--output", str(output), "--part-size", "2"]
            subprocess.run(command, check=True, capture_output=True)
            rows = [r for path in (output/"parts").glob("*.parquet") for r in pq.read_table(path).to_pylist()]
            self.assertEqual(len(rows),4)
            self.assertEqual({r["timestamp"] for r in rows}, {1672531200})
            self.assertEqual(sorted(r["capacity"] for r in rows if r["station_id"]=="synthetic-A"),[10,12])
            self.assertEqual({r["metadata_join"] for r in rows},{"station_id"})
            inventory = []
            for path in (output/"parts").glob("*.csv"):
                with path.open(encoding="utf-8", newline="") as stream:
                    inventory.extend(csv.DictReader(stream))
            self.assertEqual(sum(bool(r["error"]) for r in inventory),1)
            parts = list((output/"parts").glob("*.parquet"))
            mtimes = [p.stat().st_mtime_ns for p in parts]
            subprocess.run(command, check=True, capture_output=True)
            self.assertEqual([p.stat().st_mtime_ns for p in parts],mtimes)
            # Add a later period to exercise the complete audit command as well.
            status["last_updated"] += 90 * 86400
            for station in status["data"]["stations"]:
                station["last_reported"] = status["last_updated"] - 10
            info["last_updated"] = status["last_updated"]
            (repo / "station_status.json").write_text(json.dumps(status))
            (repo / "station_information.json").write_text(json.dumps(info))
            git("commit", "-qam", "later synthetic feed")
            later = Path(tmp) / "later"
            second_command = [sys.executable, str(ROOT / "legacy/baywheels/scripts/data/extract_baywheels_history.py"),
                       "--repo", str(repo), "--output", str(later), "--part-size", "2"]
            subprocess.run(second_command, check=True, capture_output=True)
            reports = Path(tmp)/"reports"
            subprocess.run([sys.executable,str(ROOT/"legacy/baywheels/scripts/data/audit_baywheels_data.py"),
                "--repo",str(repo),"--input",str(later),"--reports",str(reports),
                "--manifests",str(Path(tmp)/"manifests")],check=True,capture_output=True)
            audit = json.loads((reports/"audit_summary.json").read_text())
            self.assertEqual(audit["decision"],"FALLBACK")
            self.assertEqual(audit["raw_station_rows"],6)
            self.assertEqual(audit["deduplicated_station_rows"],4)
            self.assertEqual(audit["selected_station_count"],0)


if __name__ == "__main__":
    unittest.main()
