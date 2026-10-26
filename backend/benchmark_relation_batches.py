"""Compare Step batch sizes without changing production scores or learning records."""
import argparse
import base64
import json
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from app import relations
from build_relations import connect, parse_batch_scores, score_job, ScoringError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work',default='data/relations/scoring-v4-production.db')
    parser.add_argument('--gateway',default='data/relations/gateway.json')
    parser.add_argument('--job-id',type=int,default=660)
    parser.add_argument('--sizes',type=int,nargs='+',default=[32,192])
    parser.add_argument('--timeout',type=int,default=360)
    args = parser.parse_args()
    work = connect(args.work)
    job = dict(work.execute("SELECT * FROM jobs WHERE id=? AND status='done'",(args.job_id,)).fetchone())
    if job['model']!='step-5-preview':
        raise ValueError('Benchmark requires a completed Step job')
    original_pairs = json.loads(job['target_ids'])
    baseline = parse_batch_scores(job['response'],original_pairs)
    docs = {r['id']:json.loads(r['payload']) for r in work.execute('SELECT * FROM documents')}
    work.close()
    queues = []
    for source,targets in original_pairs.items():
        buckets = [deque(t for t in targets if baseline[(int(source),t)]['score']>=75),
                   deque(t for t in targets if 50<=baseline[(int(source),t)]['score']<75),
                   deque(t for t in targets if baseline[(int(source),t)]['score']<50)]
        ordered = []
        while any(buckets):
            for bucket in buckets:
                if bucket:
                    ordered.append((source,bucket.popleft()))
        queues.append(deque(ordered))
    ordered = []
    while any(queues):
        for queue in queues:
            if queue:
                ordered.append(queue.popleft())
    cfg = json.loads(Path(args.gateway).read_text())
    report = {'model':job['model'],'reference_job':job['id'],'reference_pairs':len(baseline),
              'reference_seconds':job['seconds'],'started_at':datetime.now(timezone.utc).isoformat(),'cases':[]}
    output = Path(args.work).parent/f"step-batch-benchmark-{int(time.time())}.json"
    for size in args.sizes:
        pairs = {}
        for source,target in ordered[:size]:
            pairs.setdefault(source,[]).append(target)
        ids = {int(s) for s in pairs} | {t for targets in pairs.values() for t in targets}
        figures = {}
        for qid in ids:
            path = Path(args.work).parent/'figures'/f"{qid}-{docs[qid]['fingerprint'][:12]}.png"
            if path.exists():
                figures[qid] = 'data:image/png;base64,'+base64.b64encode(path.read_bytes()).decode()
        started = time.monotonic()
        case = {'requested_pairs':sum(map(len,pairs.values())),'sources':len(pairs),
                'documents':len(ids),'images':len(figures),'pairs':pairs}
        print(relations.dumps({'starting':{k:v for k,v in case.items() if k!='pairs'}}),flush=True)
        try:
            scores,response,seconds = score_job({'model':job['model'],'target_ids':relations.dumps(pairs)},
                                                 docs,figures,cfg,args.timeout)
            case.update({'complete':True,'response':response,'seconds':seconds})
        except Exception as exc:
            scores = exc.partial if isinstance(exc,ScoringError) else {}
            case.update({'complete':False,'response':getattr(exc,'response',''),
                         'error':str(exc).replace(cfg['api_key'],'[redacted]'),
                         'seconds':round(time.monotonic()-started,2)})
        differences = [{'source':s,'target':t,'before':baseline[(s,t)]['score'],'after':v['score'],
                        'before_reason':baseline[(s,t)]['reason'],'after_reason':v['reason']}
                       for (s,t),v in scores.items()
                       if (baseline[(s,t)]['score']>=75)!=(v['score']>=75)]
        case.update({'valid_pairs':len(scores),'decision_flips':differences,
                     'mean_score_change':round(sum(abs(v['score']-baseline[key]['score']) for key,v in scores.items())/len(scores),2)
                     if scores else None})
        report['cases'].append(case)
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
        print(relations.dumps({k:v for k,v in case.items() if k not in ('pairs','response')}),flush=True)
    print(relations.dumps({'report':str(output)}),flush=True)


if __name__=='__main__':
    main()
