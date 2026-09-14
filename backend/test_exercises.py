import json
import sqlite3
import unittest
from unittest.mock import patch

from app import api, schema
from app.exercises import classify, source_label
from ingest_exercises import fingerprint, import_records, parse_page, plain


def page(stem='<p>哪一个资源分配过程会导致死锁？</p>', answer='B', keys='ABCD', nested=False):
    options = ''.join(
        f'<label class="choice-option"><input value="{key}"><span class="choice-text">选项 {key}</span></label>'
        for key in keys
    )
    box = (
        f'<div class="choice-container" id="quiz-choice-sample-1" data-answer="{answer}" data-multiple="false">'
        f'<form>{options}</form><div class="explanation"><p>这段解析只应在交卷后显示。</p></div></div>'
    )
    if nested:
        stem += '<p>以下选项中（ ）' + box + '</p>'
    else:
        stem += box
    return '<main><div class="td-content"><h1>经典练习</h1><h5 id="1">1</h5>' + stem + '</div></main>'


class ExerciseParserTests(unittest.TestCase):
    def test_nested_options_do_not_leak_answers_into_stem(self):
        records, skipped = parse_page(page(nested=True), 'os/deadlock')
        self.assertEqual(skipped, [])
        question = records[0]
        self.assertIn('资源分配', question['stem_html'])
        self.assertIn('以下选项', question['stem_html'])
        self.assertNotIn('解析只应', question['stem_html'])
        self.assertNotIn('选项 B', question['stem_html'])
        self.assertNotIn('data-answer', question['stem_html'])
        self.assertIn('解析只应', question['answer_html'])
        self.assertEqual(question['answer'], 'B')

    def test_followup_question_keeps_shared_data_without_the_previous_answer(self):
        first = page(stem='<p>链路速率为 100 Mbps，帧长 1200 字节。</p>')
        second = page(stem='<p>考虑上一题的数据，窗口为 4 时的利用率是多少？</p>')
        second_body = second.split('<h5 id="1">1</h5>', 1)[1].removesuffix('</div></main>')
        second_body = second_body.replace('quiz-choice-sample-1', 'quiz-choice-sample-2')
        html = first.replace('</div></main>', '<h5 id="2">2</h5>' + second_body + '</div></main>')
        records, skipped = parse_page(html, 'network/datalink_layer')
        self.assertFalse(skipped)
        self.assertEqual(len(records), 2)
        self.assertTrue(records[1]['has_shared_context'])
        self.assertIn('100 Mbps', records[1]['stem_html'])
        self.assertIn('原专题第 1 题', records[1]['stem_html'])
        self.assertNotIn('解析只应', records[1]['stem_html'])
        self.assertNotIn('选项 B', records[1]['stem_html'])

    def test_followup_without_source_context_is_skipped(self):
        records, skipped = parse_page(page(stem='<p>考虑上一题的数据。</p>'), 'os/memory')
        self.assertFalse(records)
        self.assertEqual(skipped[0]['reason'], '引用前题但缺少前题条件')

    def test_valid_fifth_option_is_kept_and_missing_answer_is_skipped(self):
        records, skipped = parse_page(page(answer='E', keys='ABCDE'), 'data_structure/linked_list')
        self.assertEqual(records[0]['answer'], 'E')
        self.assertEqual(len(records[0]['options']), 5)
        self.assertFalse(skipped)
        records, skipped = parse_page(page(answer=''), 'data_structure/queue')
        self.assertFalse(records)
        self.assertEqual(len(skipped), 1)

    def test_only_explicit_source_answers_are_recovered(self):
        html = page(answer='').replace('这段解析只应在交卷后显示。', '正确答案： C 解析：原站明确给出答案。')
        records, skipped = parse_page(html, 'os/deadlock')
        self.assertFalse(skipped)
        self.assertEqual(records[0]['answer'], 'C')
        self.assertTrue(records[0]['answer_normalized'])
        records, skipped = parse_page(page(answer='**A**'), 'os/deadlock')
        self.assertEqual(records[0]['answer'], 'A')
        self.assertFalse(skipped)

    def test_preserves_code_math_and_diagrams_but_removes_active_content(self):
        stem = ('<p onclick="alert(1)">计算复杂度</p><pre>for i in range(n):\n    total += i</pre>'
                '<span class="katex"><math><mi>n</mi></math></span>'
                '<svg viewBox="0 0 10 10"><path d="M0 0L10 10"/></svg>'
                '<img src="/images/test.png" onerror="alert(1)">'
                '<script>alert(1)</script><a href="javascript:alert(1)">链接</a>')
        records, _ = parse_page(page(stem=stem), 'data_structure/complexity')
        html = records[0]['stem_html']
        self.assertIn('\n    total', html)
        self.assertIn('<math>', html)
        self.assertIn('<svg', html)
        self.assertIn('https://www.csgraduates.com/images/test.png', html)
        self.assertNotIn('alert(', html)
        self.assertNotIn('<script', html)

    def test_generic_stem_uses_options_and_source_subject_for_tags(self):
        tags = classify('data_structure/binary_tree', '下列说法正确的是？', ['完全二叉树的叶结点'], '', ['完全二叉树'])
        self.assertIn('完全二叉树', tags)
        self.assertNotIn('死锁概念', tags)
        tags = classify('os/deadlock', '程序先执行 P(mutex) 再执行 V(mutex)', [], '', [])
        self.assertIn('信号量', tags)
        self.assertNotIn('死锁概念', tags)
        tags = classify('data_structure/graph', '广度优先遍历这个图', [], '', [])
        self.assertIn('图的遍历', tags)
        self.assertNotIn('二叉树遍历', tags)

    def test_different_figures_are_not_deduplicated_as_the_same_question(self):
        a = '<p>图中的答案是？</p><svg><path d="M0 0L10 10"/></svg>'
        b = '<p>图中的答案是？</p><svg><path d="M0 0L20 20"/></svg>'
        self.assertNotEqual(fingerprint(a, []), fingerprint(b, []))

    def test_math_only_html_is_preserved_in_text_and_deduplication(self):
        formula = '<span class="katex"><span class="katex-html">n<sup>2</sup></span></span>'
        self.assertEqual(plain(formula), 'n 2')
        other_formula = formula.replace('<sup>2</sup>', '<sub>2</sub>')
        self.assertNotEqual(fingerprint(formula, []), fingerprint(other_formula, []))
        self.assertNotEqual(
            fingerprint('公式是？', [{'key': 'A', 'text': formula}]),
            fingerprint('公式是？', [{'key': 'A', 'text': other_formula}]),
        )
        combined = formula.replace('<span class="katex-html">', '<math><mi>n</mi><mn>2</mn></math><span class="katex-html">')
        self.assertEqual(plain(combined), 'n 2')

    def test_incidental_terms_do_not_create_unrelated_weak_points(self):
        tags = classify('os/memory', '磁盘调度策略 SSTF 和 FCFS（先来先服务）使磁头改变方向多少次？', [], '')
        self.assertIn('磁盘调度算法', tags)
        self.assertNotIn('处理机调度算法', tags)
        tags = classify('os/process', '进程以先进先出（FIFO）顺序进入临界区', [], '')
        self.assertNotIn('页面置换算法', tags)
        tags = classify('architecture/storage', '组相联高速缓存按字节寻址，地址共 32 位', [], '')
        self.assertIn('cache映射方式', tags)
        self.assertNotIn('指令寻址方式', tags)
        tags = classify('data_structure/binary_tree', '高度为 h 的二叉树最多有多少个结点？', ['2^h', '2^(h+1)-1'], '满二叉树和完全二叉树的结构可以辅助理解。')
        self.assertEqual(tags, ['树的概念'])


class ExerciseIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        schema.initialize(self.conn)

    def tearDown(self):
        self.conn.close()

    def add_question(self, source='exam', year=2010, tag='死锁概念', number=1, stem='原有题目'):
        return self.conn.execute(
            'INSERT INTO questions(source,year,number,stem_html,tags,answer,options_json) VALUES(?,?,?,?,?,?,?)',
            (source, year, number, stem, tag, 'A', json.dumps([{'key': 'A', 'text': '甲'}, {'key': 'B', 'text': '乙'}]))
        ).lastrowid

    def due_point(self, tag='死锁概念'):
        self.conn.execute("INSERT INTO point_schedule(tag,due_at) VALUES(?, '2000-01-01')", (tag,))

    def test_import_is_additive_idempotent_and_keeps_existing_history(self):
        qid = self.add_question()
        self.conn.execute("INSERT INTO sessions(id,kind,year,status) VALUES(1,'exam',2010,'graded')")
        self.conn.execute("INSERT INTO session_items(session_id,question_id,chosen,result) VALUES(1,?,'B','wrong')", (qid,))
        self.conn.execute("INSERT INTO notes(question_id,body) VALUES(?,'保留我的笔记')", (qid,))
        records, _ = parse_page(page(), 'os/deadlock')
        first = import_records(self.conn, records, apply=True)
        second = import_records(self.conn, records, apply=True)
        self.assertEqual((first['added'], second['added'], second['existing']), (1, 0, 1))
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM questions').fetchone()[0], 2)
        self.assertEqual(self.conn.execute('SELECT chosen,result FROM session_items').fetchone()[:], ('B', 'wrong'))
        self.assertEqual(self.conn.execute('SELECT body FROM notes').fetchone()[0], '保留我的笔记')
        self.assertEqual(api._exam_question_ids(self.conn, 2010), [qid])

    def test_identical_existing_exam_is_not_imported_as_a_new_exercise(self):
        records, _ = parse_page(page(), 'os/deadlock')
        record = records[0]
        self.conn.execute(
            'INSERT INTO questions(year,number,stem_html,options_json) VALUES(2024,1,?,?)',
            (record['stem_html'], json.dumps(record['options'])))
        report = import_records(self.conn, records, apply=True)
        self.assertEqual(report['added'], 0)
        self.assertEqual(len(report['duplicates']), 1)

    def test_import_does_not_replace_an_active_reinforcement_paper(self):
        qid = self.add_question()
        self.due_point()
        sid = api._open_session_id(self.conn, 'reinforce')
        self.conn.execute("UPDATE session_items SET chosen='B',fuzzy=1 WHERE session_id=?", (sid,))
        records, _ = parse_page(page(), 'os/deadlock')
        import_records(self.conn, records, apply=True)
        self.assertEqual(api._open_session_id(self.conn, 'reinforce'), sid)
        payload = api._session_payload(self.conn, api._get_session(self.conn, sid))
        self.assertEqual([q['id'] for q in payload['questions']], [qid])
        self.assertEqual(payload['items'][qid]['chosen'], 'B')
        self.assertTrue(payload['items'][qid]['fuzzy'])

    def test_same_local_number_in_different_chapters_remains_distinct(self):
        a, _ = parse_page(page(stem='<p>死锁问题</p>'), 'os/deadlock')
        b, _ = parse_page(page(stem='<p>排序问题</p>'), 'data_structure/sort')
        report = import_records(self.conn, a + b, apply=True)
        self.assertEqual(report['added'], 2)
        urls = [row[0] for row in self.conn.execute("SELECT source_url FROM questions WHERE source='exercise'")]
        self.assertEqual(len(set(urls)), 2)

    def test_new_exercises_come_before_mock_and_exam_questions(self):
        exam = self.add_question('exam')
        mock = self.add_question('simulate', year=1)
        exercise = self.add_question('exercise', year=0)
        self.due_point()
        self.assertEqual(api._reinforce_question_ids(self.conn, False), [exercise, mock, exam])

    def test_reserved_exam_is_available_only_after_the_full_paper_is_completed(self):
        self.conn.execute("INSERT INTO plan_config(id,mock_years) VALUES(1,'2024,2025,2026')")
        qid = self.add_question('exam', year=2024)
        self.due_point()
        self.assertEqual(api._reinforce_question_ids(self.conn, False), [])
        self.conn.execute("INSERT INTO sessions(kind,year,status) VALUES('exam',2024,'graded')")
        self.assertEqual(api._reinforce_question_ids(self.conn, False), [qid])

    def test_recent_questions_still_observe_the_cooldown(self):
        recent = self.add_question('exercise', year=0)
        eligible = self.add_question('simulate', year=1)
        self.conn.execute("INSERT INTO sessions(id,kind,status) VALUES(1,'reinforce','graded')")
        self.conn.execute(
            'INSERT INTO session_items(session_id,question_id,updated_at) VALUES(1,?,?)',
            (recent, '2030-01-01T00:00:00+00:00'))
        self.due_point()
        with patch('app.scheduler.hours_ago_iso', return_value='2029-12-31T12:00:00+00:00'):
            self.assertEqual(api._reinforce_question_ids(self.conn, False), [eligible])

    def test_source_and_explanation_are_returned_without_leaking_the_answer_before_grading(self):
        records, _ = parse_page(page(), 'os/deadlock')
        import_records(self.conn, records, apply=True)
        self.due_point()
        sid = api._open_session_id(self.conn, 'reinforce')
        before = api._session_payload(self.conn, api._get_session(self.conn, sid))
        question = before['questions'][0]
        item = before['items'][question['id']]
        self.assertEqual(question['source_label'], '经典练习 · 死锁')
        self.assertNotIn('answer', question)
        self.assertNotIn('reference_html', item)
        self.conn.execute('UPDATE session_items SET chosen=? WHERE session_id=?', ('B', sid))
        after = api.submit(sid, self.conn)
        self.assertIn('解析只应', after['items'][question['id']]['reference_html'])
        self.assertEqual(after['items'][question['id']]['answer'], 'B')


if __name__ == '__main__':
    unittest.main()
