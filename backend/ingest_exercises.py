#!/usr/bin/env python
"""导入 CSGraduates 经典练习。默认预览；--apply 增量写入，绝不清空题库或练习记录。"""
import argparse
from collections import Counter, defaultdict
import hashlib
from html import unescape
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import quote, urljoin, urlparse
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup, Tag

from app.exercises import EXERCISE_BASE, SECTIONS, classify
from app.scheduler import split_tags


ROOT = Path(__file__).resolve().parent
DEFAULT_CACHE = ROOT / 'data' / 'raw_exercise'
PREVIOUS_QUESTION = re.compile(r'上一题|前一题|上题|前题|上一问')


def fetch_page(section, cache_dir, refresh=False):
    filename = section.replace('/', '-') + '.html'
    target = Path(cache_dir) / filename
    if refresh or not target.exists():
        url = EXERCISE_BASE + section + '/'
        request = Request(url, headers={'User-Agent': 'Mozilla/5.0 (408 study question importer)'})
        with urlopen(request, timeout=30) as response:
            data = response.read()
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix('.tmp')
        temporary.write_bytes(data)
        temporary.replace(target)
    return target.read_text(encoding='utf-8')


def clean_html(fragment, page_url):
    doc = BeautifulSoup(str(fragment), 'html.parser')
    for node in doc.select('script, style, link, iframe, object, embed, form, input, button, noscript'):
        node.decompose()
    for node in doc.find_all(True):
        for attr in list(node.attrs):
            if attr.lower().startswith(('on', 'data-')) or attr in ('srcdoc', 'autofocus', 'contenteditable'):
                del node.attrs[attr]
                continue
            if attr in ('href', 'src', 'xlink:href'):
                value = str(node.attrs[attr]).strip()
                if value.startswith('#'):
                    continue
                if value.startswith(('data:image/png;', 'data:image/jpeg;', 'data:image/gif;', 'data:image/webp;')):
                    if node.name in ('img', 'image'):
                        continue
                elif urlparse(urljoin(page_url, value)).scheme in ('http', 'https'):
                    node.attrs[attr] = urljoin(page_url, value)
                    continue
                del node.attrs[attr]
            elif attr == 'style' and re.search(r'url\s*\(|expression\s*\(', str(node.attrs[attr]), re.I):
                del node.attrs[attr]
        if node.name == 'a':
            node['target'] = '_blank'
            node['rel'] = 'noopener noreferrer'
    return str(doc).strip()


def plain(fragment):
    if '<' not in (fragment or ''):
        return unescape(fragment or '').strip()
    doc = BeautifulSoup(fragment or '', 'html.parser')
    return plain_document(doc)


def plain_document(doc):
    # 源站经典题使用仅 HTML 的 KaTeX；只有同时存在 MathML 时才能去掉重复的 HTML。
    for formula in doc.select('.katex'):
        if formula.select_one('math, .katex-mathml'):
            for node in formula.select('.katex-html'):
                node.decompose()
    for node in doc.select('annotation'):
        node.decompose()
    return doc.get_text(' ', strip=True)


def before_nested_box(node, box_id):
    """兼容原网页将选项 div 放进题干 p 的情况，严格截掉选项及其后的解析。"""
    doc = BeautifulSoup(str(node), 'html.parser')
    target = doc.find(id=box_id)
    if target is None:
        raise ValueError('找不到题目的选项边界')
    cursor = target
    while cursor is not doc:
        for sibling in list(cursor.next_siblings):
            sibling.extract()
        parent = cursor.parent
        if cursor is target:
            cursor.extract()
        cursor = parent
    return str(doc)


def fingerprint(stem_html, options):
    def content(fragment):
        if '<' not in (fragment or ''):
            return re.sub(r'\s+', '', unescape(fragment or '')).casefold() + '\n'
        doc = BeautifulSoup(fragment or '', 'html.parser')
        # 图形及公式结构均参与去重，不能把 x² 与 x₂、不同公式选项当成同一道题。
        figures = [str(node) for node in doc.select('svg, img, .katex, math')]
        text = re.sub(r'\s+', '', plain_document(doc)).casefold()
        return text + '\n' + '\n'.join(figures)
    body = [content(stem_html)] + [content(option['text']) for option in options]
    return hashlib.sha256(json.dumps(body, ensure_ascii=False).encode()).hexdigest()


def parse_page(html, section, vocabulary=()):
    subject, title, _fallback = SECTIONS[section]
    page_url = EXERCISE_BASE + section + '/'
    soup = BeautifulSoup(html, 'html.parser')
    content = soup.select_one('main .td-content')
    if content is None:
        raise ValueError(f'{section}: 找不到题目正文')
    records, skipped = [], []
    boxes = content.select('.choice-container, .answer-container')
    used = set()
    previous_stem, previous_number = '', None
    for box in boxes:
        marker = box.find_previous('h5')
        if marker is None or not marker.get('id') or not any(parent is content for parent in marker.parents):
            raise ValueError(f'{section}: 题目缺少稳定的来源锚点')
        anchor = marker['id']
        if anchor in used:
            raise ValueError(f'{section}: 重复的题目锚点 {anchor}')
        used.add(anchor)
        stem_nodes = []
        found_box = False
        for node in marker.next_siblings:
            if node is box:
                found_box = True
                break
            if isinstance(node, Tag) and any(child is box for child in node.descendants):
                stem_nodes.append(before_nested_box(node, box['id']))
                found_box = True
                break
            if isinstance(node, Tag) and node.name in ('h1', 'h2', 'h3', 'h4', 'h5'):
                break
            stem_nodes.append(str(node))
        if not found_box:
            raise ValueError(f'{section}#{anchor}: 找不到题干结束位置')
        stem_html = clean_html(''.join(stem_nodes), page_url)
        number = int(anchor) if anchor.isdigit() else len(records) + len(skipped) + 1
        has_shared_context = bool(PREVIOUS_QUESTION.search(plain(stem_html)))
        if has_shared_context:
            if not previous_stem:
                skipped.append({'source_url': page_url + '#' + anchor, 'reason': '引用前题但缺少前题条件'})
                continue
            # 强化抽题会打散章节；只带上前题题干，不带正确答案或解析。
            stem_html = (
                '<div class="question-context">'
                f'<p><strong>本题引用的前题条件（原专题第 {previous_number} 题）</strong></p>'
                + previous_stem + '</div>' + stem_html)
        previous_stem, previous_number = stem_html, number
        is_choice = 'choice-container' in box.get('class', [])
        options, answer = [], ''
        if is_choice:
            raw_answer = (box.get('data-answer') or '').strip()
            answer = raw_answer.strip('*_').strip().upper()
            for option in box.select('label.choice-option, label.choice-option-inline'):
                radio = option.select_one('input[value]')
                text = option.select_one('.choice-text')
                if radio is not None:
                    options.append({'key': radio['value'].upper(), 'text': clean_html(text.decode_contents(), page_url) if text else ''})
            keys = [option['key'] for option in options]
            explanation = box.select_one('.explanation')
            if answer not in keys and explanation is not None:
                # 只恢复源站明确写出的答案，不从解题过程猜选项。
                match = re.match(r'^正确答案\s*[:：]\s*[*_]*([A-Z])[*_]*(?=\s|$)', explanation.get_text(' ', strip=True))
                if match:
                    answer = match.group(1)
            if box.get('data-multiple') == 'true' or answer not in keys or not 2 <= len(keys) <= 8 or len(set(keys)) != len(keys):
                skipped.append({'source_url': page_url + '#' + anchor, 'reason': '非完整单选题或答案无效'})
                continue
        else:
            explanation = box.find_next_sibling(class_='solution-detail')
            expected = 'solution-' + (box.get('id') or '').removeprefix('quiz-')
            if explanation is not None and explanation.get('id') != expected:
                explanation = None
        answer_html = clean_html(explanation.decode_contents(), page_url) if explanation else ''
        if not plain(stem_html) or not plain(answer_html):
            skipped.append({'source_url': page_url + '#' + anchor, 'reason': '题干或解析为空'})
            continue
        tags = classify(section, plain(stem_html), [plain(o['text']) for o in options], plain(answer_html), vocabulary)
        records.append({
            'year': 0, 'subject': subject, 'number': number,
            'qtype': 'choice' if is_choice else 'subjective', 'source': 'exercise',
            'stem_html': stem_html, 'options': options, 'answer': answer,
            'answer_normalized': is_choice and answer != raw_answer,
            'has_shared_context': has_shared_context,
            'answer_html': answer_html, 'tags': ','.join(tags),
            'source_url': page_url + '#' + quote(anchor),
        })
    if len(records) + len(skipped) != len(boxes) or not boxes:
        raise ValueError(f'{section}: 题目数量校验失败')
    return records, skipped


def vocabulary_by_subject(conn):
    result = defaultdict(set)
    for row in conn.execute("SELECT subject,tags FROM questions WHERE source='exam'"):
        result[row['subject']].update(split_tags(row['tags']))
    return result


def import_records(conn, records, apply=False):
    existing_urls = {r['source_url'] for r in conn.execute("SELECT source_url FROM questions WHERE source='exercise'")}
    signatures = {}
    for row in conn.execute('SELECT id,stem_html,options_json FROM questions'):
        signatures.setdefault(fingerprint(row['stem_html'], json.loads(row['options_json'] or '[]')), row['id'])
    added, existing, duplicates = [], [], []
    for record in records:
        if record['source_url'] in existing_urls:
            existing.append(record['source_url'])
            continue
        signature = fingerprint(record['stem_html'], record['options'])
        if signature in signatures:
            duplicates.append({'source_url': record['source_url'], 'same_as': signatures[signature]})
            continue
        if apply:
            cur = conn.execute(
                'INSERT INTO questions(year,subject,number,qtype,source,stem_html,options_json,answer,answer_html,tags,source_url)'
                ' VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                (record['year'], record['subject'], record['number'], record['qtype'], 'exercise',
                 record['stem_html'], json.dumps(record['options'], ensure_ascii=False), record['answer'],
                 record['answer_html'], record['tags'], record['source_url']))
            signature_id = cur.lastrowid
        else:
            signature_id = record['source_url']
        existing_urls.add(record['source_url'])
        signatures[signature] = signature_id
        added.append(record)
    return {'added': len(added), 'choice': sum(r['qtype'] == 'choice' for r in added),
            'subjective': sum(r['qtype'] == 'subjective' for r in added),
            'normalized_answers': sum(bool(r.get('answer_normalized')) for r in added),
            'with_shared_context': sum(bool(r.get('has_shared_context')) for r in added),
            'by_subject': dict(Counter(r['subject'] for r in added)),
            'existing': len(existing), 'duplicates': duplicates}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=ROOT / 'data' / 'study.db')
    parser.add_argument('--cache-dir', type=Path, default=DEFAULT_CACHE)
    parser.add_argument('--refresh', action='store_true', help='重新下载缓存网页')
    parser.add_argument('--apply', action='store_true', help='确认解析后增量写入数据库')
    parser.add_argument('--report', type=Path, help='保存本次导入报告 JSON')
    args = parser.parse_args()
    if not args.db.is_file():
        parser.error('数据库不存在，请先初始化 408cs')
    # 先完成所有页面的下载与解析，写事务仅包含实际 INSERT。
    with sqlite3.connect(f'file:{args.db.resolve()}?mode=ro', uri=True) as conn:
        conn.row_factory = sqlite3.Row
        vocabulary = vocabulary_by_subject(conn)
    records, skipped = [], []
    for section, (subject, title, _fallback) in SECTIONS.items():
        html = fetch_page(section, args.cache_dir, args.refresh)
        parsed, invalid = parse_page(html, section, vocabulary[subject])
        records.extend(parsed)
        skipped.extend(invalid)
        print(f'{subject} · {title}: {len(parsed)} 道，跳过 {len(invalid)} 道', flush=True)
    mode = 'rw' if args.apply else 'ro'
    with sqlite3.connect(f'file:{args.db.resolve()}?mode={mode}', uri=True, timeout=30) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        if args.apply:
            conn.execute('BEGIN IMMEDIATE')
        report = import_records(conn, records, args.apply)
    report.update({'applied': args.apply, 'parsed': len(records), 'skipped': skipped})
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    summary = {key: value for key, value in report.items() if key not in ('duplicates', 'skipped')}
    summary.update({'duplicates': len(report['duplicates']), 'skipped': len(skipped)})
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
