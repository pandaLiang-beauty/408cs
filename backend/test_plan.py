import sqlite3
import unittest
from datetime import datetime, timezone
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
        due = patch('app.plan._due_points',return_value=0)
        due.start()
        self.addCleanup(due.stop)

    def tearDown(self):
        self.conn.close()

    def test_study_day_changes_at_beijing_eight(self):
        before_boundary = datetime(2026, 9, 1, 23, 59, tzinfo=timezone.utc)  # 北京时间 9 月 2 日 07:59
        at_boundary = datetime(2026, 9, 2, 0, 0, tzinfo=timezone.utc)        # 北京时间 9 月 2 日 08:00

        self.assertEqual(plan.today_str(before_boundary), '2026-09-01')
        self.assertEqual(plan.today_str(at_boundary), '2026-09-02')
        self.assertEqual(plan.task_deadline_at('2026-09-01'), '2026-09-02T00:00:00+00:00')
        self.assertEqual(plan.next_study_boundary_at(before_boundary), '2026-09-02T00:00:00+00:00')
        self.assertEqual(plan.next_study_boundary_at(at_boundary), '2026-09-03T00:00:00+00:00')

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

    @patch('app.plan.today_str', return_value='2026-10-11')
    def test_sunday_creates_only_one_subjective_task_even_with_backlog(self, _today):
        self.conn.execute("INSERT INTO daily_tasks(plan_date,kind,ref_year) VALUES('2026-10-10','exam',2009)")
        plan.ensure_through_today(self.conn)
        plan.ensure_through_today(self.conn)
        rows = self.conn.execute('SELECT plan_date,kind,status FROM daily_tasks ORDER BY plan_date').fetchall()
        self.assertEqual([tuple(r) for r in rows],[('2026-10-10','exam','todo'),('2026-10-11','reinforce_subjective','todo')])

    @patch('app.plan.today_str', return_value='2026-10-11')
    def test_sunday_replaces_unopened_exam_and_releases_year(self, _today):
        tid = self.conn.execute("INSERT INTO daily_tasks(plan_date,kind,ref_year) VALUES('2026-10-11','exam',2009)").lastrowid
        plan.ensure_through_today(self.conn)
        row = self.conn.execute('SELECT * FROM daily_tasks WHERE id=?',(tid,)).fetchone()
        self.assertEqual((row['kind'],row['ref_year']),('reinforce_subjective',None))
        self.assertNotIn(2009,plan._used_years(self.conn))

    @patch('app.plan.today_str', return_value='2026-10-11')
    def test_sunday_keeps_already_open_paper(self, _today):
        self.conn.execute("INSERT INTO sessions VALUES(1,'doing')")
        self.conn.execute("INSERT INTO daily_tasks(plan_date,kind,ref_year,session_id) VALUES('2026-10-11','exam',2009,1)")
        plan.ensure_through_today(self.conn)
        row = self.conn.execute('SELECT kind,ref_year,session_id FROM daily_tasks').fetchone()
        self.assertEqual(tuple(row),('exam',2009,1))

    @patch('app.plan.today_str', return_value='2026-10-12')
    def test_sunday_does_not_consume_weekday_alternation(self, _today):
        self.conn.execute("INSERT INTO daily_tasks(plan_date,kind,ref_year,status) VALUES('2026-10-10','exam',2009,'done')")
        self.conn.execute("INSERT INTO daily_tasks(plan_date,kind,status) VALUES('2026-10-11','reinforce_subjective','done')")
        plan.ensure_through_today(self.conn)
        row = self.conn.execute("SELECT kind FROM daily_tasks WHERE plan_date='2026-10-12'").fetchone()
        self.assertEqual(row['kind'],'reinforce')

    @patch('app.plan.today_str', return_value='2026-10-12')
    def test_unfinished_sunday_is_kept_as_overdue(self, _today):
        self.conn.execute("INSERT INTO daily_tasks(plan_date,kind) VALUES('2026-10-11','reinforce_subjective')")
        plan.ensure_through_today(self.conn)
        self.assertIsNone(self.conn.execute("SELECT 1 FROM daily_tasks WHERE plan_date='2026-10-12'").fetchone())
        self.assertEqual(plan._overdue_rows(self.conn,'2026-10-12')[0]['kind'],'reinforce_subjective')

    @patch('app.plan.today_str', return_value='2026-10-10')
    def test_sunday_preview_matches_actual_task_despite_backlog(self, _today):
        self.conn.execute("INSERT INTO daily_tasks(plan_date,kind,ref_year) VALUES('2026-10-10','exam',2009)")
        preview = plan.upcoming(self.conn,plan.ensure_config(self.conn))
        self.assertEqual(len(preview),1)
        self.assertEqual((preview[0]['date'],preview[0]['kind']),('2026-10-11','reinforce_subjective'))
        with patch('app.plan.today_str',return_value='2026-10-11'):
            plan.ensure_through_today(self.conn)
        row = self.conn.execute("SELECT * FROM daily_tasks WHERE plan_date='2026-10-11'").fetchone()
        self.assertEqual(plan.task_public(self.conn,row)['title'],preview[0]['title'])

    def test_sunday_obeys_beijing_eight_boundary(self):
        cfg = plan.ensure_config(self.conn)
        for now,kind in [(datetime(2026,10,10,23,59,tzinfo=timezone.utc),'exam'),
                         (datetime(2026,10,11,0,0,tzinfo=timezone.utc),'reinforce_subjective'),
                         (datetime(2026,10,11,23,59,tzinfo=timezone.utc),'reinforce_subjective'),
                         (datetime(2026,10,12,0,0,tzinfo=timezone.utc),'exam')]:
            self.assertEqual(plan._decide(self.conn,cfg,plan.today_str(now),'',0,set())[0],kind)


if __name__ == '__main__':
    unittest.main()
