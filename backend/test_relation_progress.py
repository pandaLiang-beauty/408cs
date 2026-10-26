import io
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone, timedelta
from pathlib import Path

from app import relations
from build_relations import WORK_SCHEMA, progress_report, status, work_lock


class ProgressTests(unittest.TestCase):
    def setUp(self):
        self.work = sqlite3.connect(':memory:')
        self.work.row_factory = sqlite3.Row
        self.addCleanup(self.work.close)
        self.work.executescript(WORK_SCHEMA)
        self.models = list(relations.MODELS)
        self.now = datetime(2026,9,29,12,tzinfo=timezone.utc)
        self.work.execute('INSERT INTO meta VALUES(?,?)',('config',json.dumps({'models':self.models})))
        self.work.execute('INSERT INTO meta VALUES(?,?)',('worker_state',json.dumps({
            'state':'running','remaining_jobs':999,'at':(self.now-timedelta(minutes=10)).isoformat()})))
        self.work.executemany('INSERT INTO candidates VALUES(1,?)',[(i,) for i in range(2,12)])
        for model,done in zip(self.models,(3,1)):
            self.work.executemany('INSERT INTO evaluations VALUES(1,?,?,80,\'skill\')',
                                  [(i,model) for i in range(2,2+done)])
            self.work.execute('INSERT INTO jobs(source_id,model,target_ids,status) VALUES(1,?,?,?)',
                              (model,json.dumps({'1':list(range(2+done,12))}),'failed' if done==3 else 'pending'))

    def test_percentage_counts_saved_pairs_not_batches_or_cached_remaining_jobs(self):
        report = progress_report(self.work,self.now)
        self.assertEqual(report['overall'],{'done':4,'total':20,'remaining':16,'percent':20.0})
        self.assertEqual(report['models'][self.models[0]]['percent'],30.0)
        self.assertEqual(report['models'][self.models[1]]['percent'],10.0)
        self.assertEqual(report['fully_scored_pairs']['percent'],10.0)
        self.assertEqual(report['accepted_pairs'],1)
        self.assertEqual(report['remaining_jobs'],2)
        self.assertEqual(report['models'][self.models[0]]['batches']['failed'],1)
        self.assertIsNone(report['eta_seconds'])

    def test_discarded_models_and_unrelated_pairs_do_not_inflate_progress(self):
        self.work.execute("INSERT INTO evaluations VALUES(1,2,'qwen3.8-flash',100,'unused')")
        self.work.execute('INSERT INTO evaluations VALUES(1,999,?,100,\'unused\')',(self.models[0],))
        self.work.execute("INSERT INTO jobs(source_id,model,target_ids) VALUES(1,'qwen3.8-flash','{}')")
        report = progress_report(self.work,self.now)
        self.assertEqual(report['overall']['done'],4)
        self.assertEqual(report['fully_scored_pairs']['done'],1)
        self.assertEqual(report['remaining_jobs'],2)

    def test_low_score_is_finished_but_not_accepted(self):
        self.work.execute('UPDATE evaluations SET score=74 WHERE model=?',(self.models[1],))
        report = progress_report(self.work,self.now)
        self.assertEqual(report['fully_scored_pairs']['done'],1)
        self.assertEqual(report['accepted_pairs'],0)

    def test_empty_database_has_no_division_by_zero_or_false_eta(self):
        self.work.execute('DELETE FROM candidates')
        report = progress_report(self.work,self.now)
        self.assertEqual(report['overall']['percent'],0.0)
        self.assertEqual(report['overall']['remaining'],0)
        self.assertIsNone(report['eta_seconds'])

    def test_all_saved_scores_show_100_percent_and_zero_eta(self):
        for model in self.models:
            self.work.executemany('INSERT OR IGNORE INTO evaluations VALUES(1,?,?,80,\'skill\')',
                                  [(i,model) for i in range(2,12)])
        report = progress_report(self.work,self.now)
        self.assertEqual(report['overall']['percent'],100.0)
        self.assertEqual(report['fully_scored_pairs']['percent'],100.0)
        self.assertEqual(report['eta_seconds'],0)

    def add_samples(self):
        for model in self.models:
            for i in range(5):
                job = self.work.execute("INSERT INTO jobs(source_id,model,target_ids,status) VALUES(1,?,?,'done')",
                    (model,json.dumps({'1':[2+i]}))).lastrowid
                self.work.execute('INSERT INTO job_attempts(job_id,response,error,seconds,created_at) VALUES(?,\'{}\',\'\',60,?)',
                    (job,(self.now-timedelta(seconds=240-30*i)).strftime('%Y-%m-%d %H:%M:%S')))

    def test_eta_uses_recent_success_throughput_and_slowest_model(self):
        self.add_samples()
        report = progress_report(self.work,self.now)
        self.assertEqual(report['models'][self.models[0]]['pairs_per_minute'],1.0)
        self.assertEqual(report['models'][self.models[0]]['eta_seconds'],7*60)
        self.assertEqual(report['models'][self.models[1]]['eta_seconds'],9*60)
        self.assertEqual(report['eta_seconds'],9*60)
        self.assertIsNone(progress_report(self.work,self.now+timedelta(minutes=10))['eta_seconds'])

    def test_eta_is_hidden_while_stopped_or_in_provider_cooldown(self):
        self.add_samples()
        self.work.execute('INSERT INTO meta VALUES(?,?)',('model_cooldowns',json.dumps({
            self.models[0]:(self.now+timedelta(hours=1)).isoformat()})))
        self.assertIsNone(progress_report(self.work,self.now)['eta_seconds'])
        self.work.execute("DELETE FROM meta WHERE key='model_cooldowns'")
        self.work.execute("UPDATE meta SET value=? WHERE key='worker_state'",(json.dumps({'state':'stopped'}),))
        self.assertIsNone(progress_report(self.work,self.now)['eta_seconds'])

    def test_human_output_and_json_output_are_both_available(self):
        with redirect_stdout(io.StringIO()) as output:
            status(self.work)
        self.assertIn('20.0%',output.getvalue())
        self.assertIn('4/20',output.getvalue())
        self.assertIn('剩余 16',output.getvalue())
        with redirect_stdout(io.StringIO()) as output:
            status(self.work,json_output=True)
        self.assertEqual(json.loads(output.getvalue())['overall']['percent'],20.0)

    def test_cli_reads_while_worker_lock_is_held_and_does_not_create_missing_database(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'work.db'
            self.work.commit()
            with sqlite3.connect(path) as target:
                self.work.backup(target)
            script = str(Path(__file__).with_name('build_relations.py'))
            with work_lock(path):
                result = subprocess.run([sys.executable,script,'status','--work',str(path),'--json'],
                                        capture_output=True,text=True,timeout=20)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(result.stdout)['overall']['percent'],20.0)
            missing = Path(directory)/'missing'/'work.db'
            result = subprocess.run([sys.executable,script,'status','--work',str(missing)],
                                    capture_output=True,text=True,timeout=20)
            self.assertNotEqual(result.returncode,0)
            self.assertFalse(missing.parent.exists())


if __name__=='__main__':
    unittest.main()
