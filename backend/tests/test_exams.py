"""exam_countdown counts days and drops past exams. Run from the backend folder:
    .venv/bin/python -m unittest tests.test_exams
"""

import unittest
from datetime import date

from tools import exams, registry


class ExamsTest(unittest.TestCase):
    def test_countdown(self):
        rows = exams.countdown([
            {"title": "CS paper", "date": "2026-10-20"},
            {"title": "Old", "date": "2026-10-01"},
            {"title": "Tomorrow", "date": "2026-10-12T09:00:00"},
            {"title": "Bad", "date": "soon"},
        ], today=date(2026, 10, 11))
        self.assertEqual([r[0] for r in rows], ["Tomorrow", "CS paper"])
        self.assertEqual([r[2] for r in rows], ["tomorrow", "9 days"])

    def test_is_read(self):
        self.assertEqual(registry.classify(registry.PREFIX + "exam_countdown"), "read")
