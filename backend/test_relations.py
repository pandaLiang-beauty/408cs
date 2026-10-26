import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime,timezone,timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from app import api, grading, plan, relations, schema
from build_relations import (parse_scores, parse_batch_scores, ScoringError, publish, score_job,
                             model_response, work_lock, split_pending_jobs, available_models,
                             pause_model, watch, load_gateways, route_metadata, reuse_scores,
                             transport_metadata, configure_transport, RequestPacer,
                             WORK_SCHEMA, SYSTEM, REQUEST_OPTIONS, MODEL_CONCURRENCY)


class RelationTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        schema.initialize(self.conn)

    def tearDown(self):
        self.conn.close()

    def question(self,source='exam',year=2010,qtype='choice',tags='cache映射方式',stem='计算地址字段',subject='组成原理'):
        qid = self.conn.execute('INSERT INTO questions(source,year,number,qtype,tags,stem_html,subject) VALUES(?,?,1,?,?,?,?)',
                                (source,year,qtype,tags,stem,subject)).lastrowid
        return qid

    def row(self,qid):
        return self.conn.execute('SELECT * FROM questions WHERE id=?',(qid,)).fetchone()

    def anchor(self,qtype='choice',tags='cache映射方式'):
        qid = self.question(qtype=qtype,tags=tags)
        sid = self.conn.execute("INSERT INTO sessions(kind,status) VALUES('exam','graded')").lastrowid
        self.conn.execute("INSERT INTO session_items(session_id,question_id,result) VALUES(?,?,'wrong')",(sid,qid))
        self.conn.execute('INSERT INTO relation_sources VALUES(?,?,?,?,?)',
                          (qid,relations.fingerprint(self.row(qid)),json.dumps(tags.split(',')),0,0))
        self.conn.execute("INSERT OR IGNORE INTO relation_build VALUES(1,'test','test','[]','2026-01-01',1,0)")
        self.conn.execute("INSERT OR IGNORE INTO point_schedule(tag,due_at) VALUES(?,'2000-01-01')",(tags,))
        return qid

    def edge(self,anchor,target,score=90):
        self.conn.execute('INSERT INTO question_relations VALUES(?,?,?,?,?,?)',
                          (anchor,target,relations.fingerprint(self.row(target)),score,relations.MIN_VOTES,'{}'))

    def test_same_tag_without_approved_relation_is_not_recommended(self):
        anchor = self.anchor()
        good = self.question('exercise')
        self.question('exercise',stem='仅考Cache写策略定义')
        self.edge(anchor,good)
        self.assertEqual(api._reinforce_question_ids(self.conn,False),[good])

    def test_both_active_reviewers_must_agree_and_missing_model_cannot_pass(self):
        self.assertEqual(relations.MODELS,('step-5-preview','deepseek-v4-flash'))
        self.assertEqual(relations.MIN_VOTES,2)
        scores = {m:{'score':90,'reason':'同一具体考点'} for m in relations.MODELS}
        self.assertTrue(relations.consensus(scores)['accepted'])
        scores[relations.MODELS[0]]['score'] = 74
        self.assertFalse(relations.consensus(scores)['accepted'])
        del scores[relations.MODELS[0]]
        with self.assertRaises(ValueError):
            relations.consensus(scores)

    def test_invalid_or_incomplete_model_output_is_not_saved_as_success(self):
        for items in [[{'id':1,'score':80,'reason':'x'}],
                      [{'id':1,'score':80,'reason':'x'},{'id':1,'score':80,'reason':'x'}],
                      [{'id':1,'score':True,'reason':'x'},{'id':2,'score':80,'reason':'x'}]]:
            with self.assertRaises(ValueError):
                parse_scores(json.dumps({'scores':items}),[1,2])

    def test_partial_batch_keeps_valid_pairs_but_requires_missing_and_duplicate_repairs(self):
        response = json.dumps({'scores':{'1':[[2,80],[3,20],[3,25],[999,90]]},'reasons':{'1:2':'地址字段划分'}})
        with self.assertRaises(ScoringError) as caught:
            parse_batch_scores(response,{'1':[2,3,4]})
        self.assertEqual(caught.exception.partial,{(1,2):{'score':80,'reason':'地址字段划分'}})
        self.assertEqual(caught.exception.response,response)

    def test_changed_question_invalidates_precomputed_match(self):
        anchor = self.anchor()
        target = self.question('exercise')
        self.edge(anchor,target)
        self.conn.execute("UPDATE questions SET stem_html='题目已更换' WHERE id=?",(target,))
        self.assertEqual(api._reinforce_question_ids(self.conn,False),[])

    def test_changed_anchor_invalidates_its_whole_match_list(self):
        anchor = self.anchor()
        target = self.question('exercise')
        self.edge(anchor,target)
        self.conn.execute("UPDATE questions SET tags='cache写策略' WHERE id=?",(anchor,))
        self.assertEqual(api._reinforce_question_ids(self.conn,False),[])

    def test_choice_only_fifty_limit_and_dedup(self):
        a, b = self.anchor(), self.anchor()
        targets = [self.question('exercise',qtype='subjective' if i==0 else 'choice',stem=f'变式{i}') for i in range(65)]
        for target in targets:
            self.edge(a,target)
            self.edge(b,target)
        selected = api._reinforce_question_ids(self.conn,False)
        self.assertEqual(len(selected),50)
        self.assertEqual(len(set(selected)),50)
        self.assertNotIn(targets[0],selected)

    def test_subjective_only_twenty_limit_and_dedup(self):
        a, b = self.anchor(), self.anchor(qtype='subjective')
        targets = [self.question('exercise',qtype='choice' if i==0 else 'subjective',stem=f'大题{i}') for i in range(65)]
        for target in targets:
            self.edge(a,target)
            self.edge(b,target)
        selected = relations.select_questions(self.conn,qtype='subjective')
        self.assertEqual(len(selected),20)
        self.assertEqual(len(set(selected)),20)
        self.assertNotIn(targets[0],selected)

    def test_subjective_anchor_without_original_tags_uses_its_review_schedule(self):
        anchor = self.anchor(qtype='subjective',tags='')
        target = self.question('exercise',qtype='subjective')
        self.edge(anchor,target)
        self.conn.execute('DELETE FROM point_schedule')
        self.conn.execute("INSERT INTO review_schedule(question_id,due_at) VALUES(?,'2000-01-01')",(anchor,))
        self.assertEqual(relations.select_questions(self.conn,qtype='subjective'),[target])

    def test_high_relevance_precedes_lower_relevance_new_question(self):
        anchor = self.anchor()
        high, low = self.question('exam'),self.question('exercise')
        self.edge(anchor,high,96)
        self.edge(anchor,low,76)
        sid = self.conn.execute("INSERT INTO sessions(kind,status) VALUES('reinforce','graded')").lastrowid
        self.conn.execute("INSERT INTO session_items(session_id,question_id,result,updated_at) VALUES(?,?,'wrong','2000-01-01')",(sid,high))
        self.assertEqual(api._reinforce_question_ids(self.conn,False),[high,low])

    def test_cooldown_handles_both_sqlite_and_iso_timestamps(self):
        anchor = self.anchor()
        targets = [self.question('exercise',stem=f'v{i}') for i in range(3)]
        sid = self.conn.execute("INSERT INTO sessions(kind,status) VALUES('reinforce','graded')").lastrowid
        now = datetime.now(timezone.utc)
        for target,stamp in zip(targets,[now.isoformat(),now.strftime('%Y-%m-%d %H:%M:%S'),(now-timedelta(hours=13)).isoformat()]):
            self.edge(anchor,target)
            self.conn.execute('INSERT INTO session_items(session_id,question_id,updated_at) VALUES(?,?,?)',(sid,target,stamp))
        self.assertEqual(api._reinforce_question_ids(self.conn,False),[targets[2]])

    def test_all_pool_does_not_change_existing_paper_or_call_ai(self):
        anchor = self.anchor()
        target = self.question('exercise')
        self.edge(anchor,target)
        sid = api._open_session_id(self.conn,'reinforce')
        self.conn.execute("UPDATE session_items SET chosen='C' WHERE session_id=?",(sid,))
        self.conn.execute('DELETE FROM question_relations')
        self.assertEqual(api._open_session_id(self.conn,'reinforce',all_pool=True),sid)
        self.assertEqual(self.conn.execute('SELECT chosen FROM session_items WHERE session_id=?',(sid,)).fetchone()[0],'C')

    def test_matching_result_updates_original_weak_question_and_waits_until_due(self):
        anchor = self.anchor()
        target = self.question('exercise')
        self.conn.execute("UPDATE questions SET answer='A' WHERE id=?",(target,))
        self.edge(anchor,target)
        sid = api._open_session_id(self.conn,'reinforce')
        item = self.conn.execute('SELECT * FROM session_items WHERE session_id=?',(sid,)).fetchone()
        self.assertEqual(item['relation_source_id'],anchor)
        self.conn.execute("UPDATE session_items SET chosen='A' WHERE session_id=?",(sid,))
        api.submit(sid,self.conn)
        schedule = self.conn.execute('SELECT * FROM review_schedule WHERE question_id=?',(anchor,)).fetchone()
        self.assertEqual(schedule['last_result'],'correct')
        self.assertGreater(datetime.fromisoformat(schedule['due_at']),datetime.now(timezone.utc))
        other = self.question('exercise',stem='另一个准确变式')
        self.edge(anchor,other)
        self.assertEqual(api._reinforce_question_ids(self.conn,False),[])
        self.assertEqual(api._reinforce_question_ids(self.conn,True),[other])

    def test_source_review_waits_for_all_variants_and_advances_only_once(self):
        anchor = self.anchor()
        targets = [self.question('exercise',stem=f'variant {i}') for i in range(3)]
        for target in targets:
            self.edge(anchor,target)
        sid = api._open_session_id(self.conn,'reinforce')
        self.conn.execute("UPDATE session_items SET result='correct' WHERE session_id=? AND question_id<>?",(sid,targets[-1]))
        relations.settle_source_review(self.conn,sid,anchor)
        self.assertIsNone(self.conn.execute('SELECT * FROM review_schedule WHERE question_id=?',(anchor,)).fetchone())
        self.conn.execute("UPDATE session_items SET result='correct' WHERE session_id=?",(sid,))
        relations.settle_source_review(self.conn,sid,anchor)
        relations.settle_source_review(self.conn,sid,anchor)
        schedule = self.conn.execute('SELECT * FROM review_schedule WHERE question_id=?',(anchor,)).fetchone()
        self.assertEqual((schedule['level'],schedule['reps']),(1,2))

    def test_source_review_uses_worst_result_regardless_of_item_order(self):
        anchor = self.anchor()
        for i in range(3):
            target = self.question('exercise',stem=f'variant {i}')
            self.conn.execute("UPDATE questions SET answer='A' WHERE id=?",(target,))
            self.edge(anchor,target)
        sid = api._open_session_id(self.conn,'reinforce')
        self.conn.execute("UPDATE session_items SET chosen='A' WHERE session_id=?",(sid,))
        self.conn.execute("UPDATE session_items SET chosen='B' WHERE session_id=? AND position=0",(sid,))
        api.submit(sid,self.conn)
        schedule = self.conn.execute('SELECT * FROM review_schedule WHERE question_id=?',(anchor,)).fetchone()
        self.assertEqual((schedule['level'],schedule['last_result']),(0,'wrong'))

    def test_mixed_paper_settles_source_after_subjective_grading(self):
        anchor = self.anchor()
        choice = self.question('exercise')
        subjective = self.question('exercise',qtype='subjective')
        for target in (choice,subjective):
            self.edge(anchor,target)
        sid = api._open_session_id(self.conn,'reinforce')
        # Recreate a legacy mixed paper without changing new-paper selection policy.
        self.conn.execute('INSERT INTO session_items(session_id,question_id,position,relation_source_id) VALUES(?,?,1,?)',
                          (sid,subjective,anchor))
        api.submit(sid,self.conn)
        self.assertIsNone(self.conn.execute('SELECT * FROM relation_reviews').fetchone())
        cfg = {'base_url':'https://example.invalid','api_key':'test','model':'test'}
        with patch.object(api.llmconfig,'active_config',return_value=cfg), patch.object(grading,'grade',return_value={
            'verdict':'对','score_ratio':1,'comment':'correct'}):
            api.grade_subjective(sid,api.GradeIn(question_id=subjective,answer_text='my answer'),self.conn)
        self.assertEqual(self.conn.execute('SELECT result FROM relation_reviews').fetchone()[0],'wrong')

    def test_stats_count_weak_source_questions_not_tags(self):
        a, b = self.anchor(),self.anchor(qtype='subjective',tags='')
        target = self.question('exercise')
        self.edge(a,target)
        self.edge(b,target)
        self.conn.execute("INSERT INTO review_schedule(question_id,due_at) VALUES(?,'2999-01-01')",(b,))
        self.assertEqual(api.reinforce_stats(self.conn),{'due':1,'pool':2})
        self.assertEqual(plan._due_points(self.conn),1)

    def test_stats_and_plan_counts_are_separated_by_target_type(self):
        anchor = self.anchor()
        target = self.question('exercise',qtype='subjective')
        self.edge(anchor,target)
        self.assertEqual(api.reinforce_stats(self.conn),{'due':0,'pool':0})
        self.assertEqual(plan._due_points(self.conn),0)
        self.assertEqual(plan._due_points(self.conn,'subjective'),1)

    def test_paper_types_resume_separately_and_keep_answers(self):
        anchor = self.anchor()
        choice = self.question('exercise')
        subjective = self.question('exercise',qtype='subjective')
        for target in (choice,subjective):
            self.edge(anchor,target)
        choice_sid = api._open_session_id(self.conn,'reinforce')
        subjective_sid = api._open_session_id(self.conn,'reinforce_subjective')
        self.assertNotEqual(choice_sid,subjective_sid)
        self.conn.execute("UPDATE session_items SET answer_text='saved answer' WHERE session_id=?",(subjective_sid,))
        for kind,sid,qid in [('reinforce',choice_sid,choice),('reinforce_subjective',subjective_sid,subjective)]:
            self.assertEqual(api._open_session_id(self.conn,kind,all_pool=True),sid)
            payload = api.get_session(sid,self.conn)
            self.assertEqual(payload['kind'],kind)
            self.assertEqual([q['id'] for q in payload['questions']],[qid])
        self.assertEqual(api.get_session(subjective_sid,self.conn)['items'][subjective]['answer_text'],'saved answer')

    def test_legacy_mixed_paper_is_preserved_but_not_resumed_as_choice_only(self):
        anchor = self.anchor()
        old_choice, new_choice = self.question('exercise'), self.question('exercise',stem='new')
        subjective = self.question('exercise',qtype='subjective')
        self.edge(anchor,new_choice)
        old_sid = self.conn.execute("INSERT INTO sessions(kind) VALUES('reinforce')").lastrowid
        for qid in (old_choice,subjective):
            self.conn.execute("INSERT INTO session_items(session_id,question_id,chosen) VALUES(?,?,'C')",(old_sid,qid))
        sid = api._open_session_id(self.conn,'reinforce')
        self.assertNotEqual(sid,old_sid)
        self.assertEqual([q['id'] for q in api.get_session(sid,self.conn)['questions']],[new_choice])
        self.assertEqual([r[0] for r in self.conn.execute('SELECT chosen FROM session_items WHERE session_id=?',(old_sid,))],['C','C'])

    def test_missing_requested_type_does_not_fall_back_to_other_type(self):
        anchor = self.anchor()
        target = self.question('exercise',qtype='subjective')
        self.edge(anchor,target)
        with self.assertRaises(api.HTTPException) as caught:
            api._open_session_id(self.conn,'reinforce',all_pool=True)
        self.assertEqual(caught.exception.status_code,409)
        self.conn.execute('DELETE FROM question_relations')
        self.edge(anchor,self.question('exercise'))
        with self.assertRaises(api.HTTPException) as caught:
            api._open_session_id(self.conn,'reinforce_subjective',all_pool=True)
        self.assertEqual(caught.exception.status_code,409)

    def test_subjective_paper_can_submit_before_grading_and_finish_later(self):
        anchor = self.anchor()
        target = self.question('exercise',qtype='subjective')
        self.edge(anchor,target)
        sid = api._open_session_id(self.conn,'reinforce_subjective')
        submitted = api.submit(sid,self.conn)
        self.assertEqual(submitted['status'],'graded')
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM relation_reviews WHERE session_id=?',(sid,)).fetchone()[0],0)
        cfg = {'base_url':'https://example.invalid','api_key':'test','model':'test'}
        with patch.object(api.llmconfig,'active_config',return_value=cfg), patch.object(grading,'grade',return_value={
            'verdict':'对','score_ratio':1,'comment':'correct'}):
            result = api.grade_subjective(sid,api.GradeIn(question_id=target,answer_text='my answer'),self.conn)
            self.assertEqual(result['result'],'correct')
            self.assertEqual(api.grade_subjective(sid,api.GradeIn(question_id=target,answer_text='retry'),self.conn)['result'],'correct')
        self.assertEqual(api.submit(sid,self.conn)['status'],'graded')
        self.assertEqual(self.conn.execute('SELECT result FROM relation_reviews WHERE session_id=?',(sid,)).fetchone()[0],'correct')

    @patch('app.plan.today_str',return_value='2026-10-12')
    def test_overdue_sunday_task_still_opens_subjective_paper_on_monday(self,_today):
        anchor = self.anchor()
        target = self.question('exercise',qtype='subjective')
        self.edge(anchor,target)
        tid = self.conn.execute("INSERT INTO daily_tasks(plan_date,kind) VALUES('2026-10-11','reinforce_subjective')").lastrowid
        result = api.start_task(tid,self.conn)
        self.assertEqual(result['mode'],'reinforce_subjective')
        self.assertEqual([q['id'] for q in api.get_session(result['session_id'],self.conn)['questions']],[target])
        self.assertEqual(api.start_task(tid,self.conn),result)

    def test_no_index_does_not_create_empty_reinforcement_session(self):
        with self.assertRaises(api.HTTPException) as caught:
            api._open_session_id(self.conn,'reinforce')
        self.assertEqual(caught.exception.status_code,409)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM sessions').fetchone()[0],0)

    def test_all_models_receive_original_images_not_shared_descriptions(self):
        source = self.question()
        target = self.question('exercise',stem='相同方法的另一道题')
        docs = {d['id']:d for d in relations.prepare_documents([dict(self.row(i)) for i in (source,target)])}
        images = {source:'data:image/png;base64,original-source',target:'data:image/png;base64,original-target'}
        response = json.dumps({'scores':{str(source):[[target,85]]},'reasons':{f'{source}:{target}':'同一地址分解方法'}})
        for model in relations.MODELS:
            with patch('build_relations.model_response',return_value=response) as call:
                scores,_,_ = score_job({'source_id':source,'target_ids':json.dumps({str(source):[target]}),'model':model},
                    docs,images,{'base_url':'https://example.invalid/v1','api_key':'test'},10)
                content = call.call_args.args[2]
                self.assertEqual([b['image_url']['url'] for b in content if b['type']=='image_url'],list(images.values()))
                self.assertEqual(scores[(source,target)]['score'],85)

    def test_untagged_subjective_questions_receive_broad_candidates(self):
        source = self.question(qtype='subjective',tags='',stem='设计链表算法查找倒数第k个结点',subject='数据结构')
        target = self.question('exercise',tags='链表',stem='快慢指针寻找链表中点',subject='数据结构')
        unrelated = self.question('exercise',tags='死锁概念',stem='计算死锁资源数',subject='操作系统')
        docs = relations.prepare_documents([dict(self.row(i)) for i in (source,target,unrelated)])
        self.assertEqual([d['id'] for d in relations.candidates_for(docs[0],docs)],[target])

    def test_exact_duplicate_and_self_are_not_reinforcement_variants(self):
        source = self.question()
        duplicate = self.question('exercise')
        docs = relations.prepare_documents([dict(self.row(i)) for i in (source,duplicate)])
        self.assertEqual(relations.candidates_for(docs[0],docs),[])

    def test_same_words_with_different_diagrams_are_still_candidates(self):
        source = self.question(stem='<p>计算图中的字段</p><svg><path d="M0 0L10 10"/></svg>')
        target = self.question('exercise',stem='<p>计算图中的字段</p><svg><path d="M0 0L20 20"/></svg>')
        docs = relations.prepare_documents([dict(self.row(i)) for i in (source,target)])
        self.assertEqual([d['id'] for d in relations.candidates_for(docs[0],docs)],[target])

    def test_publication_refuses_partial_model_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            work = sqlite3.connect(Path(directory)/'work.db')
            work.row_factory = sqlite3.Row
            work.executescript(WORK_SCHEMA)
            work.execute("INSERT INTO jobs(source_id,model,target_ids,status) VALUES(1,'qwen3.8-flash','[2]','failed')")
            with self.assertRaisesRegex(ValueError,'every job'):
                publish(SimpleNamespace(db='does-not-exist',apply=True),work)
            work.close()

    @contextmanager
    def publication_fixture(self):
        source = self.question()
        target = self.question('exercise',qtype='subjective',stem='具体变式')
        self.conn.execute("INSERT INTO sessions(id,kind,status) VALUES(1,'exam','doing')")
        self.conn.execute("INSERT INTO session_items(session_id,question_id,chosen) VALUES(1,?,'B')",(source,))
        self.conn.execute("INSERT INTO notes(question_id,body) VALUES(?,'keep this note')",(source,))
        self.conn.commit()
        docs = relations.prepare_documents([dict(r) for r in self.conn.execute('SELECT * FROM questions')])
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory)/'study.db'
            gateway = Path(directory)/'gateway.json'
            gateway.write_text(json.dumps({'base_url':'https://example.invalid/v1','api_key':'test'}))
            target_db = sqlite3.connect(db)
            self.conn.backup(target_db)
            target_db.close()
            work = sqlite3.connect(':memory:')
            work.row_factory = sqlite3.Row
            work.executescript(WORK_SCHEMA)
            config = {'version':relations.VERSION,'prompt_hash':hashlib.sha256(SYSTEM.encode()).hexdigest(),
                      'models':list(relations.MODELS),'request_options':REQUEST_OPTIONS,'source_hash':'test-snapshot',
                      'routes':route_metadata(load_gateways(gateway)),
                      'transports':transport_metadata(load_gateways(gateway))}
            work.execute('INSERT INTO meta VALUES(?,?)',('config',relations.dumps(config)))
            work.execute('INSERT INTO meta VALUES(?,?)',('figure_hash','test-figures'))
            work.executemany('INSERT INTO documents VALUES(?,?)',[(d['id'],relations.dumps(d)) for d in docs])
            work.execute('INSERT INTO candidates VALUES(?,?)',(source,target))
            for model in relations.MODELS:
                work.execute('INSERT INTO evaluations VALUES(?,?,?,?,?)',(source,target,model,85,'same concrete skill'))
            try:
                yield work,SimpleNamespace(db=str(db),gateway=str(gateway),apply=True),source,target
            finally:
                work.close()

    def test_publication_preserves_learning_records_and_is_idempotent(self):
        with self.publication_fixture() as (work,args,source,target):
            with patch('builtins.print'):
                publish(args,work)
                publish(args,work)
            with sqlite3.connect(args.db) as db:
                self.assertEqual(db.execute('SELECT source_id,target_id,votes FROM question_relations').fetchone(),(source,target,2))
                self.assertEqual(db.execute('SELECT chosen,result FROM session_items').fetchone(),('B',''))
                self.assertEqual(db.execute('SELECT status FROM sessions').fetchone(),('doing',))
                self.assertEqual(db.execute('SELECT body FROM notes').fetchone(),('keep this note',))

    def test_publication_refuses_stale_snapshot(self):
        with self.publication_fixture() as (work,args,source,target):
            with sqlite3.connect(args.db) as db:
                db.execute("UPDATE questions SET stem_html='changed' WHERE id=?",(target,))
            with self.assertRaisesRegex(ValueError,'snapshot changed'):
                publish(args,work)

    def test_publication_refuses_missing_vote_even_with_no_pending_jobs(self):
        with self.publication_fixture() as (work,args,source,target):
            work.execute('DELETE FROM evaluations WHERE model=?',(relations.MODELS[0],))
            with self.assertRaisesRegex(ValueError,'All configured'):
                publish(args,work)

    def test_publication_requires_exact_candidate_set_not_just_same_count(self):
        with self.publication_fixture() as (work,args,source,target):
            work.execute('UPDATE evaluations SET source_id=?,target_id=?',(target,source))
            with self.assertRaisesRegex(ValueError,'coverage is incomplete'):
                publish(args,work)

    def test_work_lock_rejects_duplicate_runner_and_releases_after_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'work.db'
            with work_lock(path):
                with self.assertRaisesRegex(ValueError,'already updating'):
                    with work_lock(path):
                        self.fail('duplicate lock acquired')
            with work_lock(path):
                pass

    def test_streaming_collects_content_and_ignores_reasoning(self):
        events = [{'choices':[{'delta':{'reasoning_content':'do not save as scores'}}]},
                  {'choices':[{'delta':{'content':'{"scores":'}}]},
                  {'choices':[{'delta':{'content':'{}}'}}]}]
        data = ''.join('data: '+json.dumps(event)+'\n\n' for event in events)+'data: [DONE]\n\n'
        requests = []
        def handler(request):
            requests.append(json.loads(request.content))
            return httpx.Response(200,headers={'content-type':'text/event-stream'},text=data)
        client = httpx.Client(transport=httpx.MockTransport(handler))
        with patch('build_relations.httpx.Client',return_value=client):
            response = model_response({'base_url':'https://example.invalid','api_key':'test'},relations.MODELS[0],[],10)
        self.assertEqual(response,'{"scores":{}}')
        self.assertTrue(requests[0]['stream'])

    def test_hard_quota_is_not_retried(self):
        source = self.question()
        target = self.question('exercise',stem='variant')
        docs = {d['id']:d for d in relations.prepare_documents([dict(self.row(i)) for i in (source,target)])}
        with patch('build_relations.model_response',side_effect=grading.GatewayError('Individual quota reached')) as call:
            with self.assertRaises(grading.GatewayError):
                score_job({'model':relations.MODELS[0],'target_ids':json.dumps({str(source):[target]})},docs,{}, {},10)
        self.assertEqual(call.call_count,1)

    def test_responses_sends_images_and_client_headers_and_keeps_only_final_text(self):
        events = [{'type':'response.reasoning_text.delta','delta':'not a score'},
                  {'type':'response.output_text.delta','delta':'{"scores":{}}'},
                  {'type':'response.output_text.done','text':'{"scores":{}}'},
                  {'type':'response.completed','response':{'status':'completed','output':[
                      {'type':'reasoning','summary':[]},
                      {'type':'message','content':[{'type':'output_text','text':'{"scores":{}}'}]}]}}]
        stream = ''.join('data: '+json.dumps(event)+'\n\n' for event in events)
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(200,headers={'content-type':'text/event-stream'},text=stream)
        cfg = {'base_url':'https://example.invalid/v1','api_key':'test','api_format':'responses',
               'headers':{'User-Agent':'codex_cli_rs/test','Originator':'codex_cli_rs','OpenAI-Beta':'responses=experimental'}}
        content = [{'type':'text','text':'question 1'},
                   {'type':'image_url','image_url':{'url':'data:image/png;base64,original'}}]
        client = httpx.Client(transport=httpx.MockTransport(handler))
        with patch('build_relations.httpx.Client',return_value=client):
            result = model_response(cfg,'qwen3.8-flash',content,10)
        self.assertEqual(result,'{"scores":{}}')
        request = requests[0]
        self.assertEqual(request.url.path,'/v1/responses')
        self.assertEqual(request.headers['originator'],'codex_cli_rs')
        self.assertEqual(request.headers['authorization'],'Bearer test')
        body = json.loads(request.content)
        self.assertEqual(body['instructions'],SYSTEM)
        self.assertEqual(body['input'][0]['content'],[
            {'type':'input_text','text':'question 1'},
            {'type':'input_image','image_url':'data:image/png;base64,original'}])
        self.assertFalse(body['store'])

    def test_responses_requires_successful_terminal_event(self):
        endings = [None,{'type':'response.incomplete','response':{'incomplete_details':{'reason':'max_output_tokens'}}},
                   {'type':'response.failed','response':{'error':{'message':'upstream failed'}}}]
        for ending in endings:
            events = [{'type':'response.output_text.delta','delta':'{"scores":{}}'}]
            if ending:
                events.append(ending)
            stream = ''.join('data: '+json.dumps(event)+'\n\n' for event in events)
            client = httpx.Client(transport=httpx.MockTransport(
                lambda request:httpx.Response(200,headers={'content-type':'text/event-stream'},text=stream)))
            with patch('build_relations.httpx.Client',return_value=client):
                with self.assertRaises(ScoringError):
                    model_response({'base_url':'https://example.invalid','api_key':'test','api_format':'responses'},
                                   'qwen3.8-flash',[],10)

    def test_transport_upgrade_preserves_other_models_and_rejects_scored_model_changes(self):
        with self.publication_fixture() as (work,args,source,target):
            work.execute("DELETE FROM evaluations WHERE model='deepseek-v4-flash'")
            path = Path(args.gateway)
            cfg = json.loads(path.read_text())
            (path.parent/'qwen.json').write_text(json.dumps({**cfg,'api_format':'responses'}))
            manifest = path.parent/'routes.json'
            manifest.write_text(json.dumps({'default':path.name,'models':{'deepseek-v4-flash':'qwen.json'}}))
            args.gateway = str(manifest)
            before = [tuple(r) for r in work.execute('SELECT * FROM evaluations')]
            with patch('builtins.print'):
                configure_transport(args,work)
            self.assertEqual([tuple(r) for r in work.execute('SELECT * FROM evaluations')],before)
            config = json.loads(work.execute("SELECT value FROM meta WHERE key='config'").fetchone()[0])
            self.assertEqual(config['transports']['deepseek-v4-flash']['api_format'],'responses')
            cfg['api_format'] = 'responses'
            path.write_text(json.dumps(cfg))
            with self.assertRaisesRegex(ValueError,'saved scores'):
                configure_transport(args,work)

    def test_request_pacer_spaces_requests_instead_of_bursting_to_rpm_limit(self):
        pacer = RequestPacer(50)
        with patch('build_relations.time.monotonic',return_value=100),patch('build_relations.time.sleep') as sleep:
            pacer.wait()
            pacer.wait()
            pacer.wait()
        self.assertAlmostEqual(sleep.call_args_list[0].args[0],1.2)
        self.assertAlmostEqual(sleep.call_args_list[1].args[0],2.4)

    def test_step_uses_five_slots_and_other_models_keep_their_own_limits(self):
        self.assertEqual(MODEL_CONCURRENCY,{'step-5-preview':5,'qwen3.8-flash':40,'deepseek-v4-flash':8})

    def test_model_can_be_enabled_without_restarting_other_queues(self):
        work = sqlite3.connect(':memory:')
        work.executescript(WORK_SCHEMA)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'gateway.json').write_text(json.dumps({'base_url':'https://example.invalid','api_key':'test'}))
            config = {'default':'gateway.json','transports':{'deepseek-v4-flash':{'enabled':False}}}
            path = root/'routes.json'
            path.write_text(json.dumps(config))
            args = SimpleNamespace(gateway=str(path),models=None)
            self.assertNotIn('deepseek-v4-flash',available_models(work,args))
            config['transports']['deepseek-v4-flash']['enabled'] = True
            path.write_text(json.dumps(config))
            self.assertEqual(available_models(work,args),list(relations.MODELS))
        work.close()

    def test_smaller_batches_preserve_all_remaining_pairs_without_repeating_finished_jobs(self):
        work = sqlite3.connect(':memory:')
        work.row_factory = sqlite3.Row
        work.executescript(WORK_SCHEMA)
        group = {'1':list(range(10,20)),'2':list(range(10,20))}
        work.execute('INSERT INTO jobs(source_id,model,target_ids) VALUES(?,?,?)',(1,relations.MODELS[1],relations.dumps(group)))
        work.execute("INSERT INTO jobs(source_id,model,target_ids,status) VALUES(?,?,?,'done')",(1,relations.MODELS[0],relations.dumps(group)))
        split_pending_jobs(work,6)
        pairs = []
        for job in work.execute("SELECT * FROM jobs WHERE status<>'done'"):
            batch = json.loads(job['target_ids'])
            self.assertLessEqual(sum(map(len,batch.values())),6)
            pairs.extend((s,t) for s,targets in batch.items() for t in targets)
        self.assertEqual(len(pairs),20)
        self.assertEqual(set(pairs),{(s,t) for s,targets in group.items() for t in targets})
        self.assertEqual(work.execute("SELECT COUNT(*) FROM jobs WHERE status='done'").fetchone()[0],1)
        work.close()

    def test_model_specific_batch_limits(self):
        work = sqlite3.connect(':memory:')
        work.row_factory = sqlite3.Row
        work.executescript(WORK_SCHEMA)
        for model in relations.MODELS:
            work.execute('INSERT INTO jobs(source_id,model,target_ids) VALUES(?,?,?)',
                         (1,model,relations.dumps({'1':list(range(10,250))})))
        limits = {'step-5-preview':192,'qwen3.8-flash':96,'deepseek-v4-flash':192}
        split_pending_jobs(work,limits)
        for model in relations.MODELS:
            sizes = [sum(map(len,json.loads(r[0]).values())) for r in work.execute('SELECT target_ids FROM jobs WHERE model=?',(model,))]
            self.assertEqual(sum(sizes),240)
            self.assertEqual(max(sizes),limits[model])
        work.close()

    def test_routes_keep_each_providers_key_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'default.json').write_text(json.dumps({'base_url':'https://first.invalid/v1','api_key':'first-key'}))
            (root/'qwen.json').write_text(json.dumps({'base_url':'https://second.invalid/v1','api_key':'second-key'}))
            (root/'routes.json').write_text(json.dumps({'default':'default.json','models':{'deepseek-v4-flash':'qwen.json'}}))
            gateways = load_gateways(root/'routes.json')
            self.assertEqual(gateways['deepseek-v4-flash']['api_key'],'second-key')
            self.assertEqual(gateways['step-5-preview']['api_key'],'first-key')
            self.assertNotIn('qwen3.8-flash',gateways)
            self.assertNotIn('key',json.dumps(route_metadata(gateways)))

    def test_reuse_keeps_only_explicitly_selected_unchanged_reviewers(self):
        with self.publication_fixture() as (work,args,source,target):
            path = Path(args.db).parent/'origin.db'
            work.commit()
            origin = sqlite3.connect(path)
            work.backup(origin)
            origin.close()
            work.execute('DELETE FROM evaluations')
            for model in relations.MODELS:
                work.execute('INSERT INTO jobs(source_id,model,target_ids) VALUES(?,?,?)',
                             (source,model,relations.dumps({str(source):[target]})))
            with patch('builtins.print'):
                reuse_scores(work,path,['step-5-preview'])
            self.assertEqual([r[0] for r in work.execute('SELECT model FROM evaluations')],['step-5-preview'])
            self.assertEqual(work.execute("SELECT COUNT(*) FROM jobs WHERE status='done'").fetchone()[0],1)
            config = json.loads(work.execute("SELECT value FROM meta WHERE key='config'").fetchone()[0])
            config['routes']['deepseek-v4-flash'] = 'https://changed-provider.invalid/v1'
            work.execute("UPDATE meta SET value=? WHERE key='config'",(relations.dumps(config),))
            with self.assertRaisesRegex(ValueError,'gateway route'):
                reuse_scores(work,path,['deepseek-v4-flash'])

    def test_dual_model_migration_does_not_import_discarded_qwen_scores(self):
        with self.publication_fixture() as (work,args,source,target):
            path = Path(args.db).parent/'three-model-origin.db'
            work.commit()
            origin = sqlite3.connect(path)
            work.backup(origin)
            config = json.loads(origin.execute("SELECT value FROM meta WHERE key='config'").fetchone()[0])
            config['version'] = 'relations-v5-routed-vision'
            config['models'].append('qwen3.8-flash')
            config['routes']['qwen3.8-flash'] = 'https://discarded.invalid/v1'
            origin.execute("UPDATE meta SET value=? WHERE key='config'",(relations.dumps(config),))
            origin.execute('INSERT INTO evaluations VALUES(?,?,?,?,?)',(source,target,'qwen3.8-flash',5,'discarded'))
            origin.commit()
            origin.close()
            work.execute('DELETE FROM evaluations')
            with patch('builtins.print'):
                reuse_scores(work,path)
            scores = {r['model']:{'score':r['score'],'reason':r['reason']} for r in work.execute('SELECT * FROM evaluations')}
            self.assertEqual(set(scores),set(relations.MODELS))
            self.assertTrue(relations.consensus(scores)['accepted'])
            scores['qwen3.8-flash'] = {'score':100,'reason':'must not affect consensus'}
            with self.assertRaises(ValueError):
                relations.consensus(scores)

    def test_current_routes_never_load_the_discarded_qwen_credential(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'default.json').write_text(json.dumps({'base_url':'https://example.invalid/v1','api_key':'test'}))
            (root/'routes.json').write_text(json.dumps({'default':'default.json',
                'models':{'qwen3.8-flash':'missing-qwen-credential.json'}}))
            self.assertEqual(set(load_gateways(root/'routes.json')),set(relations.MODELS))

    def test_quota_cooldown_survives_a_new_run_and_does_not_pause_other_models(self):
        work = sqlite3.connect(':memory:')
        work.executescript(WORK_SCHEMA)
        args = SimpleNamespace(models=None)
        pause_model(work,relations.MODELS[0],'Individual quota reached. Resets in 4h2m40s.')
        self.assertEqual(available_models(work,args),list(relations.MODELS[1:]))
        work.close()

    def test_watch_completion_validates_but_does_not_publish(self):
        work = sqlite3.connect(':memory:')
        work.executescript(WORK_SCHEMA)
        args = SimpleNamespace(max_hours=1,limit_jobs=0,max_pairs=96,apply=True)
        with patch('build_relations.publish') as publication, patch('build_relations.signal.signal'), patch('builtins.print'):
            watch(args,work)
        publication.assert_called_once_with(args,work)
        self.assertFalse(args.apply)
        self.assertEqual(args.limit_jobs,0)
        state = json.loads(work.execute("SELECT value FROM meta WHERE key='worker_state'").fetchone()[0])
        self.assertEqual(state['state'],'ready_to_publish')
        work.close()


if __name__=='__main__':
    unittest.main()
