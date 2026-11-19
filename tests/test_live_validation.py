"""Chicago time handling in the 2026 live validation."""
from datetime import datetime, timezone
import sys
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PROJECT), str(PROJECT / 'scripts/model')]
from validate_live_2026 import dst_ambiguous  # noqa: E402


def epoch(text):
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp()


class DstTests(unittest.TestCase):
    def test_both_copies_of_the_repeated_fall_back_hour_are_flagged(self):
        # 2026-11-01: 01:00-02:00 Chicago happens at CDT (06:xx UTC) and again at CST (07:xx UTC).
        self.assertTrue(dst_ambiguous(epoch('2026-11-01T06:15:00')))
        self.assertTrue(dst_ambiguous(epoch('2026-11-01T07:45:00')))
        self.assertFalse(dst_ambiguous(epoch('2026-11-01T05:45:00')))  # 00:45 CDT
        self.assertFalse(dst_ambiguous(epoch('2026-11-01T08:00:00')))  # 02:00 CST

    def test_ordinary_and_summer_times_are_unique(self):
        self.assertFalse(dst_ambiguous(epoch('2026-11-02T14:00:00')))
        self.assertFalse(dst_ambiguous(epoch('2021-07-20T13:06:00')))


if __name__ == '__main__':
    unittest.main()
