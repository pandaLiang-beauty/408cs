"""Precompute DeepSeek diagram facts for Qwen without accessing relation scores."""
import argparse
import base64
import concurrent.futures
import hashlib
import json
import signal
import time
from datetime import datetime, timezone
from pathlib import Path

from app import relations
from build_relations import load_gateways, load_questions, model_response, work_lock
import relation_vision as vision


def enlarged_tiles(directory,images,hashes,browser_path):
    from playwright.sync_api import sync_playwright
    output = directory/'transcription-tiles'
    output.mkdir(exist_ok=True)
    tiles = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True,executable_path=browser_path or None,args=['--no-sandbox'])
        page = browser.new_page(device_scale_factor=2)
        for qid,url in images.items():
            manifest = output/f'{hashes[qid]}-800-2x-v1.json'
            if manifest.exists():
                paths = json.loads(manifest.read_text())
            else:
                page.set_content(f'<html><body style="margin:0"><img src="{url}"></body></html>')
                page.wait_for_function('document.images[0].complete && document.images[0].naturalWidth>0')
                width,height = page.locator('img').evaluate('(i)=>[i.naturalWidth,i.naturalHeight]')
                page.set_viewport_size({'width':width,'height':height})
                paths = []
                def positions(size):
                    return sorted(set([*range(0,max(1,size-799),650),max(0,size-800)]))
                for x in positions(width):
                    for y in positions(height):
                        name = f'{hashes[qid]}-{x}-{y}-800-2x-v1.png'
                        page.screenshot(path=str(output/name),clip={'x':x,'y':y,'width':min(800,width-x),'height':min(800,height-y)})
                        paths.append(name)
                manifest.write_text(json.dumps(paths))
            tiles[qid] = ['data:image/png;base64,'+base64.b64encode((output/p).read_bytes()).decode() for p in paths]
        browser.close()
    return tiles


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',default='data/study.db')
    parser.add_argument('--directory',default='data/relations')
    parser.add_argument('--gateway',default='data/relations/routes-v5.json')
    parser.add_argument('--workers',type=int,default=8)
    parser.add_argument('--timeout',type=int,default=180)
    parser.add_argument('--attempts',type=int,default=3)
    parser.add_argument('--question-ids',default='')
    parser.add_argument('--exclude-question-ids',default='',help='Hold diagrams requiring manual inspection')
    parser.add_argument('--browser',default='')
    args = parser.parse_args()
    if min(args.workers,args.timeout,args.attempts)<1:
        parser.error('Limits must be positive')
    directory = Path(args.directory)
    cfg = load_gateways(args.gateway)[vision.MODEL]
    docs = {d['id']:d for d in relations.prepare_documents(load_questions(args.db))}
    selected = {int(s) for s in args.question_ids.split(',') if s}
    excluded = {int(s) for s in args.exclude_question_ids.split(',') if s}
    images, hashes = {}, {}
    for qid,doc in docs.items():
        path = directory/'figures'/f"{qid}-{doc['fingerprint'][:12]}.png"
        if path.exists() and qid not in excluded and (not selected or qid in selected):
            raw = path.read_bytes()
            hashes[qid] = hashlib.sha256(raw).hexdigest()
            images[qid] = 'data:image/png;base64,'+base64.b64encode(raw).decode()
    cache_path = directory/'deepseek-transcriptions.db'
    stopping = [False]
    def stop(signum,frame):
        stopping[0] = True
    signal.signal(signal.SIGTERM,stop)
    signal.signal(signal.SIGINT,stop)
    tiles = enlarged_tiles(directory,images,hashes,args.browser)

    def transcribe(qid):
        started = time.monotonic()
        response, error = '', ''
        try:
            # No stem, solution, pair list or saved review is sent to the transcriber.
            content = [
                {'type':'text','text':json.dumps({'question_id':qid})},
                {'type':'image_url','image_url':{'url':images[qid]}}]
            for index,url in enumerate(tiles[qid]):
                content.extend([{'type':'text','text':f'Enlarged overlapping region {index+1} of the same original diagram'},
                                {'type':'image_url','image_url':{'url':url}}])
            response = model_response(cfg,vision.MODEL,content,args.timeout,system=vision.PROMPT)
            vision.parse_transcription(response)
        except Exception as exc:
            error = str(exc).replace(cfg['api_key'],'[redacted]')[:600]
        return response,error,round(time.monotonic()-started,2)

    with work_lock(cache_path),vision.open_cache(cache_path) as cache:
        for attempt in range(args.attempts):
            existing = vision.load_transcriptions(cache_path,docs,hashes,cfg['base_url'])
            todo = iter(qid for qid in images if qid not in existing)
            print(relations.dumps({'cached':len(existing),'total':len(images),'round':attempt+1}),flush=True)
            with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
                pending = {}
                def fill():
                    while len(pending)<args.workers and not stopping[0]:
                        qid = next(todo,None)
                        if qid is None:
                            break
                        pending[pool.submit(transcribe,qid)] = qid
                fill()
                while pending:
                    done,_ = concurrent.futures.wait(pending,return_when=concurrent.futures.FIRST_COMPLETED)
                    for future in done:
                        qid = pending.pop(future)
                        response,error,seconds = future.result()
                        meta = vision.provenance(docs[qid],hashes[qid],cfg['base_url'])
                        with cache:
                            cache.execute('INSERT INTO attempts(cache_key,question_id,response,error,seconds,created_at) VALUES(?,?,?,?,?,?)',
                                (vision.cache_key(meta),qid,response,error,seconds,datetime.now(timezone.utc).isoformat()))
                        if not error:
                            vision.store_transcription(cache,meta,response)
                        print(relations.dumps({'question_id':qid,'seconds':seconds,'error':error}),flush=True)
                    fill()
            if stopping[0]:
                break
        cached = vision.load_transcriptions(cache_path,docs,hashes,cfg['base_url'])
        print(relations.dumps({'cached':len(cached),'total':len(images),
                              'missing':sorted(set(images)-set(cached))}),flush=True)


if __name__=='__main__':
    main()
