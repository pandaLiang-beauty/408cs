import base64
from collections import deque
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import relation_vision as vision
from build_relations import (score_job, transport_settings, pin_transcriptions,
                             take_ready_job, concurrency_limits, WORK_SCHEMA, SYSTEM)


class VisionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'cache.db'
        self.cache = vision.open_cache(self.path)
        self.addCleanup(self.cache.close)
        self.docs = {i:{'id':i,'fingerprint':f'question-{i}','type':'choice','subject':'data',
                       'tags':[],'stem':'stem','options':[],'reference':''} for i in (1,2)}
        self.image_hashes = {1:hashlib.sha256(b'original-png').hexdigest()}
        self.images = {1:'data:image/png;base64,'+base64.b64encode(b'original-png').decode()}
        self.route = 'https://deepseek.invalid/v1'
        self.meta = vision.provenance(self.docs[1],self.image_hashes[1],self.route)
        self.response = json.dumps({'readable':True,'description':'A has 3 nodes. B has 5 nodes.','uncertainties':[]})
        self.cfg = {'base_url':'https://qwen.invalid/v1','api_key':'test','api_format':'responses',
                    'vision_input':vision.MODE,'transcription_route':self.route}
        self.job = {'model':'qwen3.8-flash','target_ids':'{"1":[2]}'}

    def load(self):
        return vision.load_transcriptions(self.path,self.docs,self.image_hashes,self.route)

    def test_cache_is_reusable_immutable_and_bound_to_image_question_and_route(self):
        vision.store_transcription(self.cache,self.meta,self.response)
        first = self.load()
        vision.store_transcription(self.cache,self.meta,self.response.replace('3 nodes','4 nodes'))
        self.assertEqual(self.load(),first)
        self.assertEqual(vision.load_transcriptions(self.path,self.docs,{1:'new-image'},self.route),{})
        self.assertEqual(vision.load_transcriptions(self.path,self.docs,self.image_hashes,'https://other.invalid'),{})
        self.docs[1]['fingerprint'] = 'changed-question'
        self.assertEqual(self.load(),{})

    def test_uncertain_empty_or_score_bearing_output_is_not_cached(self):
        data = json.loads(self.response)
        for change in ({'readable':False},{'description':''},{'uncertainties':['edge unclear']},
                       {'scores':{'1':[[2,90]]}},{'readable':1}):
            with self.assertRaises(ValueError):
                vision.store_transcription(self.cache,self.meta,json.dumps({**data,**change}))
        self.assertEqual(self.load(),{})

    def test_corrupted_cached_description_is_rejected(self):
        vision.store_transcription(self.cache,self.meta,self.response)
        with self.cache:
            self.cache.execute("UPDATE transcriptions SET description='different'")
        with self.assertRaisesRegex(ValueError,'Corrupt'):
            self.load()

    def test_qwen_gets_only_transcription_and_still_produces_its_own_score(self):
        vision.store_transcription(self.cache,self.meta,self.response)
        with patch('build_relations.model_response',return_value='{"scores":{"1":[[2,10]]}}') as call:
            scores,_,_ = score_job(self.job,self.docs,self.images,self.cfg,10,self.load())
        self.assertEqual(scores[(1,2)]['score'],10)
        content = call.call_args.args[2]
        self.assertTrue(all(item['type']=='text' for item in content))
        self.assertIn('figure_transcription',json.dumps(content))
        self.assertNotIn('cache_key',json.dumps(content))
        self.assertEqual(call.call_args.kwargs['system'],SYSTEM+'\n'+vision.QWEN_NOTE)

    def test_missing_or_stale_transcription_never_calls_qwen(self):
        vision.store_transcription(self.cache,self.meta,self.response)
        stale = self.load()
        stale[1]['metadata']['fingerprint'] = 'changed'
        for records in ({},stale):
            with patch('build_relations.model_response') as call,self.assertRaisesRegex(ValueError,'Missing or stale'):
                score_job(self.job,self.docs,self.images,self.cfg,10,records)
            call.assert_not_called()

    def test_step_and_deepseek_keep_original_images_and_original_prompt(self):
        for model in ('step-5-preview','deepseek-v4-flash'):
            with patch('build_relations.model_response',return_value='{"scores":{"1":[[2,10]]}}') as call:
                score_job({**self.job,'model':model},self.docs,self.images,{},10)
            self.assertEqual([b for b in call.call_args.args[2] if b['type']=='image_url'],
                             [{'type':'image_url','image_url':{'url':self.images[1]}}])
            self.assertEqual(call.call_args.kwargs,{})
            with self.assertRaisesRegex(ValueError,'Only Qwen'):
                score_job({**self.job,'model':model},self.docs,self.images,self.cfg,10)

    def test_unready_figure_does_not_block_text_jobs_or_consume_attempts(self):
        text_job = {'target_ids':'{"2":[3]}'}
        queue = deque([self.job,text_job])
        self.assertEqual(take_ready_job(queue,self.images,{}),text_job)
        self.assertIsNone(take_ready_job(queue,self.images,{}))
        self.assertEqual(list(queue),[self.job])
        self.assertEqual(take_ready_job(queue,self.images,{1:{}}),self.job)

    def test_pinned_inputs_cannot_change_after_scoring(self):
        vision.store_transcription(self.cache,self.meta,self.response)
        work = sqlite3.connect(':memory:')
        self.addCleanup(work.close)
        work.executescript(WORK_SCHEMA)
        entries = self.load()
        pin_transcriptions(work,entries)
        pin_transcriptions(work,entries)
        entries[1]['description'] = 'different'
        with self.assertRaisesRegex(ValueError,'changed after use'):
            pin_transcriptions(work,entries)

    def test_bridge_policy_is_versioned_without_changing_original_transport(self):
        self.assertEqual(transport_settings({}),{'api_format':'chat_completions','headers':{}})
        cfg = transport_settings(self.cfg)
        self.assertEqual(cfg['vision_input'],vision.policy(self.route))
        self.assertEqual(transport_settings({**self.cfg,'enabled':False,'requests_per_minute':40}),cfg)

    def test_operational_concurrency_can_follow_provider_limit_without_rescoring(self):
        gateways = {'step-5-preview':{},'deepseek-v4-flash':{},'qwen3.8-flash':{**self.cfg,'concurrency':4}}
        self.assertEqual(concurrency_limits(gateways),{'step-5-preview':5,'deepseek-v4-flash':8,'qwen3.8-flash':4})
        self.assertEqual(transport_settings(gateways['qwen3.8-flash']),transport_settings(self.cfg))
        gateways['qwen3.8-flash']['concurrency'] = 40
        self.assertEqual(concurrency_limits(gateways)['qwen3.8-flash'],40)
        for invalid in (0,41,True,'4'):
            gateways['qwen3.8-flash']['concurrency'] = invalid
            with self.assertRaises(ValueError):
                concurrency_limits(gateways)


if __name__=='__main__':
    unittest.main()
