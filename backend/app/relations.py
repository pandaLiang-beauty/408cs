"""Offline question matching and lookup of published, independently scored relations."""
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone, timedelta

from bs4 import BeautifulSoup

from .exercises import ALIASES
from .scheduler import split_tags
from . import scheduler

VERSION = 'relations-v6-step-deepseek'
PAPER_LIMIT = 50
SUBJECTIVE_PAPER_LIMIT = 20
MIN_SCORE = 75
MODELS = ('step-5-preview', 'deepseek-v4-flash')
MIN_VOTES = len(MODELS)
REINFORCEMENT_TYPES = {'reinforce': 'choice', 'reinforce_subjective': 'subjective'}

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS relation_build (
  id INTEGER PRIMARY KEY CHECK(id=1), version TEXT NOT NULL,
  fingerprint TEXT NOT NULL, models_json TEXT NOT NULL, published_at TEXT NOT NULL,
  source_count INTEGER NOT NULL, pair_count INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS relation_sources (
  question_id INTEGER PRIMARY KEY REFERENCES questions(id) ON DELETE CASCADE,
  fingerprint TEXT NOT NULL, tags_json TEXT NOT NULL,
  candidate_count INTEGER NOT NULL, accepted_count INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS question_relations (
  source_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
  target_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
  target_fingerprint TEXT NOT NULL, score REAL NOT NULL,
  votes INTEGER NOT NULL, evaluations_json TEXT NOT NULL,
  PRIMARY KEY(source_id,target_id), CHECK(source_id<>target_id)
);
CREATE INDEX IF NOT EXISTS idx_relations_rank ON question_relations(source_id,score DESC);
CREATE TABLE IF NOT EXISTS relation_reviews (
  session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  source_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
  result TEXT NOT NULL, PRIMARY KEY(session_id,source_id)
);
"""

# Deliberately broad first-stage families. The models judge the actual task afterwards.
FAMILIES = {
 'stack_queue': '栈|队列|缓冲区|中缀|后缀|后序表达式|卡特兰',
 'list_array': '链表|线性表|顺序表|数组|矩阵|三元组',
 'binary_tree': '二叉树遍历|完全二叉树|满二叉树|二叉树存储|二叉树构建|线索二叉树|树的概念',
 'forest': '森林|树和二叉树的转换|图表示树',
 'search_tree': '二叉排序树|平衡二叉树|平均查找长度',
 'btree': r'B\+?树|B-树',
 'huffman': '哈夫曼|赫夫曼|前缀编码|带权路径长度',
 'graph': '图的|邻接|最短路径|最小生成树|拓扑|关键路径',
 'search': '数组查找|折半查找|分块查找|平均查找长度|散列表|哈希|KMP',
 'sort': '排序算法|快速排序|希尔排序|基数排序|归并排序|插入排序|外部排序|堆|败者树',
 'complexity': '复杂度分析',
 'integer': '补码|原码|反码|数制|移位|类型转换|无符号|运算电路|溢出|定点|标志寄存器',
 'float': '浮点|类型转换',
 'cache': 'cache|缓存',
 'ram': '主存容量|存储器概念|存储器地址|数据对齐|大小端',
 'paging': '地址翻译|TLB|页表|虚拟页式|缺页|访存|驻留集|页框',
 'page_replacement': '页面置换|LRU|clock|Belady|抖动|页框',
 'allocation': '内存管理方式|段式|动态分区|程序的装入|程序的链接',
 'instruction': '指令寻址|指令格式|操作码|指令体系|指令种类|复杂和精简',
 'cpu_datapath': '控制器|寄存器|微程序|数据通路|单周期处理器|指令执行',
 'pipeline': '流水线|计算机性能指标|指令执行指标',
 'architecture': '计算机体系结构|多处理机|编译过程',
 'interrupt': '异常|中断|陷阱',
 'io': 'IO|I/O|DMA|设备|SPOOLing',
 'bus': '总线',
 'disk': '磁盘|CHS|RAID|外存空间|位图法',
 'process': '进程概念|进程和线程|进程状态|进程间通信|用户级和内核级',
 'scheduling': '处理机调度|时间片|调度指标',
 'synchronization': '信号量|互斥|临界|管程|同步|条件变量',
 'deadlock': '死锁|银行家',
 'os_basics': '操作系统概念|系统调用|用户态|内核态|系统引导',
 'file': '文件|inode|目录|链接|FCB',
 'physical': '调制|编码方法|物理层|奈奎斯特|香农|传输介质|通信指标|CDMA',
 'reliability': 'ARQ|窗口大小限制|信道利用率|HDLC',
 'ethernet': 'CSMA|以太网|交换机|VLAN|MAC|介质访问',
 'error_code': '差错|循环冗余|海明',
 'ip': 'IP数据报|子网|网络号|CIDR|NAT|IPv6|ARP|ICMP',
 'routing': '路由|距离向量|最长前缀|软件定义网络',
 'tcp_window': 'TCP滑动窗口|TCP拥塞控制|TCP首部',
 'tcp_connection': 'TCP三次握手|TCP四次挥手|TCP首部|UDP',
 'application': '应用层|FTP|DNS|HTTP|邮件|网络应用|DHCP|P2P',
 'net_architecture': 'OSI|TCP/IP模型|网络体系|协议数据单元|网络协议|网络设备|交换方式|数据报和虚电路',
}


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def fingerprint(row):
    return hashlib.sha256(dumps({k: row[k] for k in
        ('source', 'year', 'number', 'qtype', 'subject', 'tags', 'stem_html',
         'options_json', 'answer', 'answer_html')}).encode()).hexdigest()


def plain_html(html):
    if '<' not in (html or ''):
        return html or ''
    soup = BeautifulSoup(html or '', 'html.parser')
    for el in soup.select('script,style'):
        el.decompose()
    for formula in soup.select('.katex'):
        annotation = formula.find('annotation')
        if annotation:
            formula.replace_with(' ' + annotation.get_text() + ' ')
        else:
            math = formula.find('math')
            if math:
                formula.replace_with(' ' + math.get_text(' ', strip=True) + ' ')
    for svg in soup.find_all('svg'):
        svg.replace_with('[diagram: ' + svg.get_text(' ', strip=True) + ']')
    for img in soup.find_all('img'):
        img.replace_with('[image: ' + img.get('alt', '') + ']')
    return re.sub(r'[ \t]+', ' ', soup.get_text(' ', strip=True)).strip()


def content_fingerprint(row,stem,options):
    media = []
    fragments = [row['stem_html']] + [o['text'] for o in json.loads(row['options_json'] or '[]')]
    for html in fragments:
        if '<' not in (html or ''):
            media.append([])
            continue
        soup = BeautifulSoup(html or '', 'html.parser')
        media.append([str(node) for node in soup.select('svg,img,math,.katex,sup,sub')])
    # Identical wording does not make different diagrams or formulas duplicates.
    return hashlib.sha256(dumps([stem,options,media]).encode()).hexdigest()


def prepare_documents(rows):
    vocabulary = {}
    for row in rows:
        if row['subject']:
            for tag in split_tags(row['tags']):
                vocabulary.setdefault(tag, Counter())[row['subject']] += 1
    result = []
    for row in rows:
        original_tags = set(split_tags(row['tags']))
        tags = set(original_tags)
        subject = row['subject']
        if not subject:
            votes = Counter()
            for tag in tags:
                votes.update(vocabulary.get(tag, {}))
            if votes:
                subject = votes.most_common(1)[0][0]
            else:
                n = row['number']
                subject = ('数据结构' if n <= 10 or n in (41,42) else
                           '组成原理' if n <= 22 or n in (43,44) else
                           '操作系统' if n <= 32 or n in (45,46) else '计算机网络')
        stem = plain_html(row['stem_html'])
        options = [{'key': o['key'], 'text': plain_html(o['text'])}
                   for o in json.loads(row['options_json'] or '[]')]
        content = re.sub(r'\s+', '', stem + dumps(options)).lower()
        for tag, pattern in ALIASES.get(subject, {}).items():
            if re.search(pattern, content, re.I):
                tags.add(tag)
        for tag, subjects in vocabulary.items():
            if subject in subjects and re.sub(r'\s+', '', tag).lower() in content:
                tags.add(tag)
        families = {key for key, pattern in FAMILIES.items()
                    if re.search(pattern, '|'.join(tags), re.I)}
        if not families:
            families = {key for key, pattern in FAMILIES.items() if re.search(pattern, content, re.I)}
        retrieval_tags = original_tags or tags
        retrieval_families = {key for key,pattern in FAMILIES.items()
                              if re.search(pattern,'|'.join(retrieval_tags),re.I)}
        if not retrieval_families and not original_tags:
            retrieval_families = families
        result.append({
            'id': row['id'], 'source': row['source'], 'year': row['year'], 'number': row['number'],
            'type': row['qtype'], 'subject': subject, 'tags': sorted(tags), 'families': sorted(families),
            'retrieval_tags':sorted(retrieval_tags),'retrieval_families':sorted(retrieval_families),
            'stem': stem, 'options': options, 'answer': row['answer'],
            'reference': plain_html(row['answer_html']), 'fingerprint': fingerprint(row),
            'content_hash': content_fingerprint(row,stem,options),
        })
    return result


def candidates_for(source, documents):
    candidates, neighbours = [], []
    for target in documents:
        if target['id'] == source['id'] or target['content_hash'] == source['content_hash']:
            continue
        same_tags = set(source['retrieval_tags']) & set(target['tags'])
        same_family = set(source['retrieval_families']) & set(target['families'])
        same_subject = target['subject'] == source['subject']
        if same_tags:
            candidates.append(target)
        elif same_subject and (same_family or not source['retrieval_tags']):
            neighbours.append(target)
    if len(candidates)<8:
        candidates.extend(neighbours)
    return sorted(candidates, key=lambda d: d['id'])


def consensus(evaluations):
    if set(evaluations) != set(MODELS):
        raise ValueError('All configured independent model scores are required')
    scores = [evaluations[m]['score'] for m in MODELS]
    if any(isinstance(s, bool) or not isinstance(s, (int, float)) or not 0 <= s <= 100 for s in scores):
        raise ValueError('Invalid relation score')
    votes = sum(s >= MIN_SCORE for s in scores)
    score = round(sum(scores) / len(scores), 2)
    return {'score': score, 'votes': votes,
            'accepted': votes >= MIN_VOTES and score >= MIN_SCORE and min(scores) >= 40}


def update_source_schedule(conn,source_id,result):
    if not conn.execute('SELECT 1 FROM review_schedule WHERE question_id=?',(source_id,)).fetchone():
        previous = conn.execute(
            "SELECT result FROM session_items WHERE question_id=? AND result IN ('wrong','fuzzy') "
            'ORDER BY datetime(updated_at) DESC,id DESC LIMIT 1',(source_id,)).fetchone()
        if previous:
            scheduler.update(conn,source_id,previous['result'])
    scheduler.update(conn,source_id,result)


def settle_source_review(conn,session_id,source_id):
    results = [r['result'] for r in conn.execute(
        'SELECT result FROM session_items WHERE session_id=? AND relation_source_id=?',
        (session_id,source_id))]
    if not results or any(result not in ('correct','fuzzy','wrong') for result in results):
        return
    # A source is reviewed once per paper, after all its variants have been graded.
    result = max(results,key={'correct':0,'fuzzy':1,'wrong':2}.get)
    created = conn.execute('INSERT OR IGNORE INTO relation_reviews VALUES(?,?,?)',
                           (session_id,source_id,result)).rowcount
    if created:
        update_source_schedule(conn,source_id,result)


def utc_time(value):
    parsed = datetime.fromisoformat(value)
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def weak_sources(conn, all_pool=False, *, qtype=None):
    if not conn.execute('SELECT 1 FROM relation_build WHERE id=1').fetchone():
        return []
    now = datetime.now(timezone.utc)
    point_due = {r['tag']: r['due_at'] for r in conn.execute('SELECT tag,due_at FROM point_schedule')}
    schedules = {r['question_id']: r['due_at'] for r in conn.execute('SELECT question_id,due_at FROM review_schedule')}
    anchors = conn.execute(
        "SELECT q.*,rs.tags_json,rs.fingerprint stored_fingerprint,MIN(datetime(si.updated_at)) missed_at "
        "FROM questions q JOIN session_items si ON si.question_id=q.id "
        "JOIN relation_sources rs ON rs.question_id=q.id "
        "WHERE q.source='exam' AND si.result IN ('wrong','fuzzy') "
        "AND EXISTS(SELECT 1 FROM question_relations r JOIN questions target ON target.id=r.target_id "
        "WHERE r.source_id=q.id AND (? IS NULL OR target.qtype=?)) GROUP BY q.id",
        (qtype,qtype)).fetchall()
    selected = []
    for anchor in anchors:
        if fingerprint(anchor) != anchor['stored_fingerprint']:
            continue
        if anchor['id'] in schedules:
            dates = [schedules[anchor['id']]]
        else:
            dates = [point_due[t] for t in json.loads(anchor['tags_json']) if t in point_due]
            if not dates:
                dates = [anchor['missed_at']]
        due = min(utc_time(value) for value in dates)
        if all_pool or due <= now:
            selected.append((due.isoformat(),anchor))
    return selected


def select_questions(conn, all_pool=False, *, with_sources=False, qtype='choice'):
    """Read published relations only; no candidate search or AI during paper creation."""
    if qtype not in REINFORCEMENT_TYPES.values():
        raise ValueError('Unknown reinforcement question type')
    cutoff = datetime.now(timezone.utc) - timedelta(hours=12)
    anchors = weak_sources(conn,all_pool,qtype=qtype)
    queues = []
    cfg = conn.execute('SELECT mock_years FROM plan_config WHERE id=1').fetchone()
    reserved = {int(y.strip()) for y in (cfg['mock_years'] if cfg else '2024,2025,2026').split(',') if y.strip().isdigit()}
    reserved -= {r['year'] for r in conn.execute("SELECT year FROM sessions WHERE kind='exam' AND status='graded'")}
    history = {r['question_id']: dict(r) for r in conn.execute(
        "SELECT question_id,COUNT(*) attempts,MAX(datetime(updated_at)) last_at,"
        "MAX(result IN ('wrong','fuzzy')) missed FROM session_items GROUP BY question_id")}
    fingerprints = {}
    for due,anchor in anchors:
        ranked = []
        for row in conn.execute(
            'SELECT q.*,r.score,r.target_fingerprint FROM question_relations r '
            'JOIN questions q ON q.id=r.target_id WHERE r.source_id=? AND q.qtype=? '
            'ORDER BY r.score DESC,r.target_id',
            (anchor['id'],qtype)):
            if row['source'] == 'exam' and row['year'] in reserved:
                continue
            if row['id'] not in fingerprints:
                fingerprints[row['id']] = fingerprint(row)
            if fingerprints[row['id']] != row['target_fingerprint']:
                continue
            past = history.get(row['id'])
            if past and utc_time(past['last_at']) > cutoff:
                continue
            # Relevance dominates. Within a five-point band favour fresh practice.
            tier = 0 if not past else 1 if past['missed'] else 2
            ranked.append((-(int(row['score']) // 5), tier, -row['score'],
                           {'exercise':0,'simulate':1,'exam':2}.get(row['source'],3), row['id']))
        if ranked:
            queues.append((due, anchor['id'], [r[-1] for r in sorted(ranked)]))
    queues.sort()
    paper_limit = SUBJECTIVE_PAPER_LIMIT if qtype == 'subjective' else PAPER_LIMIT
    picked, seen = [], set()
    while len(picked) < paper_limit and any(q[2] for q in queues):
        for _, source_id, queue in queues:
            while queue and queue[0] in seen:
                queue.pop(0)
            if queue:
                qid = queue.pop(0)
                picked.append({'question_id':qid,'source_id':source_id})
                seen.add(qid)
                if len(picked) == paper_limit:
                    break
    return picked if with_sources else [item['question_id'] for item in picked]
