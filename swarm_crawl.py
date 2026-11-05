"""Search-free discovery for towns whose codes are hosted on ecode360 (163 Massachusetts municipalities).

The town list comes from General Code's public source library (ecode360_ma.json). For each town still unresolved:
open the code's table of contents, pick traffic-related chapters (vehicles and traffic, traffic rules, parking,
streets), fetch them, and score them for a stop-sign schedule (swarm_verify.score). Runs as six "crawler" workers
that report through the same town/heartbeat files as the research agents, so the swarm dashboard shows them live.
Polite: one request at a time per worker, with a pause between requests.
"""
import argparse, concurrent.futures as cf, html, json, re, time
from pathlib import Path
import swarm_verify as V

ROOT = Path(__file__).resolve().parent; REG = ROOT / 'data' / 'regulations' / 'registry'
TRAFFIC = re.compile(r'traffic|vehicles and traffic|motor vehicles?|parking|stop signs?|streets?\b|ways\b', re.I)
SKIP = re.compile(r'junk|sale of|for hire|taxi|storage|abandoned|subdivision|zoning|numbering|excavat|snow|sidewalk caf', re.I)


def write(slug, d): (REG / 'towns' / f'{slug}.json').write_text(json.dumps(d, indent=1), encoding='utf-8')


def toc(code):
    got, err = V.fetch(f'https://ecode360.com/{code}')
    if err: return None, err
    h = got[0].decode('utf-8', 'replace'); out = []
    for m in re.finditer(r'data-guid="(\d+)"[^>]*>(.*?)</a>', h, re.S):
        t = ' '.join(html.unescape(re.sub(r'<[^>]+>', ' ', m.group(2))).split())
        if t and re.match(r'(Chapter|Part|Article)', t) and TRAFFIC.search(t) and not SKIP.search(t): out.append((m.group(1), t))
    return out, None


PAUSE = 0.6


def crawl_town(worker, slug, name, code, prev):
    base = {**prev, 'slug': slug, 'worker': worker}
    write(slug, {**base, 'status': 'searching'}); (REG / 'workers' / f'{worker}.json').write_text(json.dumps({'current': slug}), encoding='utf-8')
    chapters, err = toc(code); time.sleep(PAUSE); best = None
    for guid, title in (chapters or [])[:6]:
        got, e = V.fetch(f'https://ecode360.com/{guid}'); time.sleep(PAUSE)
        if e: continue
        text, fmt = V.to_text(got[0], got[1]); s = V.score(text, name); s.update(url=f'https://ecode360.com/{guid}', title=title)
        if best is None or s['stop_rows'] > best['stop_rows']: best = s
    notes = [n for n in [prev.get('notes')] if n]
    cands = list(dict.fromkeys((prev.get('candidates') or []) + ([best['url']] if best else [])))[:6]
    if err: status, doc = ('error' if prev.get('status') in (None, 'error') else prev['status']), prev.get('document'); notes = [n for n in notes if 'http_429' not in n] + [f'ecode360 {code}: {err}']
    elif best and best['stop_rows'] >= 8 and best['mentions_town']:
        status = 'found'; doc = {'url': best['url'], 'title': f"{name} code: {best['title']}", 'format': 'ecode360', 'last_updated': None, 'has_stop_signs': True,
                                 'has_turn_prohibitions': best['turn_prohibitions'], 'has_one_way': best['one_way'], 'verified': True}
        notes.append(f"Crawler: {best['stop_rows']} stop-sign rows in {best['title']}.")
    elif best:
        status = 'found' if prev.get('status') == 'found' else 'partial'; doc = prev.get('document') or {'url': best['url'], 'title': f"{name} code: {best['title']}", 'format': 'ecode360',
                 'has_stop_signs': False, 'has_turn_prohibitions': best['turn_prohibitions'], 'has_one_way': best['one_way'], 'verified': True}
        notes.append(f"Crawler: town code has traffic chapters ({best['title']}) but no stop-sign schedule ({best['stop_rows']} rows); the schedule is probably in separate Select Board traffic rules.")
    else:
        status = prev.get('status') if prev.get('status') in ('partial', 'found') else 'not_found'; doc = prev.get('document')
        notes.append(f'Crawler: ecode360 code {code} has no traffic chapter.')
    out = {**base, 'status': status, 'document': doc, 'candidates': cands, 'notes': ' '.join(notes)[:600], 'crawl': {'ecode360': code, 'chapters': [t for _, t in (chapters or [])][:6], 'best_stop_rows': best['stop_rows'] if best else 0}}
    if status == 'found': out['pipeline'] = 'ready to map'
    write(slug, out); return slug, status, best['stop_rows'] if best else None


def run(workers, only_errors=False):
    towns = {x['slug']: x for x in json.loads((REG / 'towns.json').read_text(encoding='utf-8'))['towns']}
    eco = json.loads((REG / 'ecode360_ma.json').read_text(encoding='utf-8')); todo = []
    for slug, entries in eco.items():
        p = REG / 'towns' / f'{slug}.json'; prev = json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
        if prev.get('status') == 'found' or (only_errors and prev.get('status') != 'error'): continue
        todo.append((slug, towns[slug]['name'], entries[0]['code'], prev))
    names = ['crawler-retry'] if only_errors else [f'crawler-{i + 1:02d}' for i in range(workers)]; batches = {n: todo[i::len(names)] for i, n in enumerate(names)}
    assign = json.loads((REG / 'assignments.json').read_text(encoding='utf-8')); moved = {t[0] for t in todo}
    assign = {k: [s for s in v if s not in moved] for k, v in assign.items() if only_errors or not k.startswith('crawler-')}
    assign.update({n: [t[0] for t in b] for n, b in batches.items()}); (REG / 'assignments.json').write_text(json.dumps(assign, indent=1), encoding='utf-8')
    print(f'crawling {len(todo)} ecode360 towns with {workers} workers', flush=True)
    def worker(n):
        res = []
        for slug, name, code, prev in batches[n]:
            try: res.append(crawl_town(n, slug, name, code, prev))
            except Exception as e: write(slug, {**prev, 'slug': slug, 'worker': n, 'status': prev.get('status', 'error'), 'notes': f'crawler error {type(e).__name__}'}); res.append((slug, 'error', None))
            print(n, *res[-1], flush=True)
        (REG / 'workers' / f'{n}.json').write_text(json.dumps({'current': None, 'state': 'done'}), encoding='utf-8'); return res
    with cf.ThreadPoolExecutor(workers) as pool: list(pool.map(worker, names))


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__.split(chr(10))[0]); ap.add_argument('--workers', type=int, default=6); ap.add_argument('--only-errors', action='store_true'); ap.add_argument('--pause', type=float, default=0.6)
    a = ap.parse_args(); PAUSE = a.pause; run(a.workers, a.only_errors)
