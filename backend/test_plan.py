import sqlite3
import unittest
from unittest.mock import patch

from app import plan


class PlanProgressionTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript("""
            CREATE TABLE plan_config (
                id INTEGER PRIMARY KEY,
                exam_date TEXT NOT NULL,
                start_date TEXT NOT NULL,
                mock_years TEXT NOT NULL,
                mock_days INTEGER NOT NULL
            );
            CREATE TABLE daily_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plan_date TEXT NOT NULL,
                kind TEXT NOT NULL,
                ref_year INTEGER,
                session_id INTEGER,
                status TEXT NOT NULL DEFAULT 'todo'
            );
            CREATE TABLE sessions (id INTEGER PRIMARY KEY, status TEXT NOT NULL);
            CREATE TABLE questions (year INTEGER, source TEXT, qtype TEXT, tags TEXT);
            CREATE TABLE point_schedule (tag TEXT, due_at TEXT);
            CREATE TABLE session_items (question_id INTEGER, session_id INTEGER);
        """)
        self.conn.execute(
            "INSERT INTO plan_config VALUES (1, '2026-12-19', '2026-09-01', '2024,2025,2026', 21)"
        )
        self.conn.execute("INSERT INTO questions VALUES (2009, 'exam', 'choice', '栈')")

    def tearDown(self):
        self.conn.close()

    @patch('app.plan.today_str', return_value='2026-09-02')
    def test_unfinished_exam_blocks_reinforcement_and_future_preview(self, _today):
        self.conn.execute(
            "INSERT INTO daily_tasks(plan_date, kind, ref_year) VALUES ('2026-09-01', 'exam', 2009)"
        )

        plan.ensure_through_today(self.conn)

        today = self.conn.execute("SELECT * FROM daily_tasks WHERE plan_date='2026-09-02'").fetchone()
        self.assertIsNone(today)
        self.assertEqual(plan.upcoming(self.conn, plan.ensure_config(self.conn)), [])

    @patch('app.plan.today_str', return_value='2026-09-02')
    def test_completed_exam_unlocks_the_following_reinforcement(self, _today):
        self.conn.execute(
            "INSERT INTO daily_tasks(plan_date, kind, ref_year, status) "
            "VALUES ('2026-09-01', 'exam', 2009, 'done')"
        )

        plan.ensure_through_today(self.conn)

        today = self.conn.execute("SELECT kind FROM daily_tasks WHERE plan_date='2026-09-02'").fetchone()
        self.assertEqual(today['kind'], 'reinforce')

    @patch('app.plan.today_str', return_value='2026-09-02')
    def test_legacy_duplicate_and_premature_reinforcement_are_repaired(self, _today):
        self.conn.execute(
            "INSERT INTO daily_tasks(plan_date, kind, ref_year) VALUES ('2026-09-01', 'exam', 2009)"
        )
        self.conn.execute(
            "INSERT INTO daily_tasks(plan_date, kind, ref_year) VALUES ('2026-09-01', 'exam', 2009)"
        )
        self.conn.execute("INSERT INTO daily_tasks(plan_date, kind) VALUES ('2026-09-02', 'reinforce')")

        plan.ensure_through_today(self.conn)

        rows = self.conn.execute('SELECT plan_date, kind FROM daily_tasks ORDER BY plan_date').fetchall()
        self.assertEqual([(row['plan_date'], row['kind']) for row in rows], [('2026-09-01', 'exam')])


if __name__ == '__main__':
    unittest.main()
