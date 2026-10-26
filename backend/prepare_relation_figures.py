"""Render original figures for vision reviewers and the Qwen transcription bridge."""
import argparse
import json
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from app import relations
from build_relations import load_questions


def figure_html(row):
    sections = [('stem',row['stem_html'])]
    sections += [(o['key'],o['text']) for o in json.loads(row['options_json'] or '[]')]
    fragments = []
    for label, html in sections:
        if '<' not in html:
            continue
        soup = BeautifulSoup(html,'html.parser')
        for node in soup.select('script,style'):
            node.decompose()
        for node in soup.find_all(['svg','img']):
            if node.find_parent(['svg','foreignobject']):
                continue
            fragments.append(f'<p>{label}</p><div class="figure">{node}</div>')
    return ''.join(fragments)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db',default='data/study.db')
    p.add_argument('--work',default='data/relations/scoring-v6-production.db')
    p.add_argument('--limit',type=int,default=0)
    p.add_argument('--browser',default='')
    args = p.parse_args()
    directory = Path(args.work).parent/'figures'
    directory.mkdir(parents=True,exist_ok=True)
    jobs = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True,executable_path=args.browser or None,args=['--no-sandbox'])
        page = browser.new_page(viewport={'width':1400,'height':1000},device_scale_factor=1)
        for row in load_questions(args.db):
            html = figure_html(row)
            if not html:
                continue
            path = directory/f"{row['id']}-{relations.fingerprint(row)[:12]}.png"
            if not path.exists():
                page.set_content('<html><head><style>body{margin:0;background:white;color:black;}'
                    '#figures{padding:16px;width:1320px;}svg{max-width:1280px;height:auto;}'
                    'img{max-width:1280px;height:auto}.figure{padding:10px;border-bottom:1px solid #ddd}</style></head>'
                    '<body><div id="figures">'+html+'</div></body></html>',wait_until='networkidle',timeout=60000)
                page.wait_for_function('Array.from(document.images).every(i=>i.complete && i.naturalWidth>0)',timeout=60000)
                page.locator('#figures').screenshot(path=str(path))
            jobs.append((row,path))
            if args.limit and len(jobs)>=args.limit:
                break
        browser.close()
    print(relations.dumps({'original_figures_rendered':len(jobs)}),flush=True)


if __name__=='__main__':
    main()
