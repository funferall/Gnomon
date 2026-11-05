"""Regulation-document swarm: registry, assignments and the live status aggregator behind swarm.html.

build   350 Massachusetts municipalities (all except Boston) -> registry with simplified SVG outlines; deal towns to N agents
status  loop: merge per-town and per-agent JSON files (written by research agents) into status.json every 2 s
claim   give every unresolved town (queued, not found, error; then partial) to one worker, e.g. "codex"
next    mark the worker's next town as searching and print it   (used by an external agent such as Codex)
submit  record the URLs an agent found for a town; download + verify them (swarm_verify) and set the final status
        (timestamps come from file modification times, so agents never need to report a clock)

Files (data/regulations/registry/): towns.json, assignments.json, towns/<slug>.json, workers/<agent>.json, status.json
"""
import argparse, json, os, re, time, datetime as dt
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REG = ROOT / 'data' / 'regulations' / 'registry'
COUNTIES = {'001': 'Barnstable', '003': 'Berkshire', '005': 'Bristol', '007': 'Dukes', '009': 'Essex', '011': 'Franklin', '013': 'Hampden',
            '015': 'Hampshire', '017': 'Middlesex', '019': 'Nantucket', '021': 'Norfolk', '023': 'Plymouth', '025': 'Suffolk', '027': 'Worcester'}
VIEW_W = 1000


def slug(name): return re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')


def build(agents):
    import geopandas as gpd
    t = gpd.read_file('zip://' + str(ROOT / 'data/towns.zip')).to_crs(26986)
    t = t[~t.NAME.str.contains('not defined') & (t.NAME != 'Boston')].copy()
    t['clean'] = t.NAME.str.replace(r'\s+(Town|City)$', '', regex=True)
    t['geometry'] = t.geometry.simplify(120)
    x0, y0, x1, y1 = t.total_bounds; s = VIEW_W / (x1 - x0); H = (y1 - y0) * s
    def path(g):
        polys = getattr(g, 'geoms', [g]); out = []
        for p in polys:
            for ring in [p.exterior]:
                pts = [(round((x - x0) * s, 1), round((y1 - y) * s, 1)) for x, y in ring.coords]
                out.append('M' + 'L'.join(f'{a},{b}' for a, b in pts) + 'Z')
        return ''.join(out)
    towns = []
    for _, r in t.sort_values('clean').iterrows():
        c = r.geometry.representative_point()
        towns.append({'slug': slug(r.clean), 'name': r.clean, 'county': COUNTIES.get(r.COUNTYFP, r.COUNTYFP), 'kind': r.NAMELSAD.split()[-1],
                      'path': path(r.geometry), 'cx': round((c.x - x0) * s, 1), 'cy': round((y1 - c.y) * s, 1)})
    REG.mkdir(parents=True, exist_ok=True); (REG / 'towns').mkdir(exist_ok=True); (REG / 'workers').mkdir(exist_ok=True)
    (REG / 'towns.json').write_text(json.dumps({'viewbox': [0, 0, VIEW_W, round(H, 1)], 'towns': towns}), encoding='utf-8')
    todo = [x for x in towns if x['slug'] != 'wellesley']
    assign = {f'agent-{i + 1:02d}': [x['slug'] for x in todo[i::agents]] for i in range(agents)}   # dealt round-robin: the swarm lights up statewide
    (REG / 'assignments.json').write_text(json.dumps(assign, indent=1), encoding='utf-8')
    pilot = REG / 'towns' / 'wellesley.json'
    if not pilot.exists():
        pilot.write_text(json.dumps({'town': 'Wellesley', 'slug': 'wellesley', 'worker': 'pilot', 'status': 'found', 'document': {
            'url': 'https://www.wellesleyma.gov/2000/Traffic-Regulations', 'title': 'Traffic Regulations (Updated January 2026)', 'format': 'pdf_text',
            'last_updated': 'January 2026', 'has_stop_signs': True, 'has_turn_prohibitions': True, 'has_one_way': True, 'verified': True},
            'pipeline': 'mapped', 'notes': 'Pilot town: 212 stop signs, 7 turns, 6 one-way streets mapped.'}, indent=1), encoding='utf-8')
    print(f'{len(towns)} municipalities, {len(todo)} to research, {agents} agents x ~{len(todo) // agents}', flush=True)


def _todo():
    towns = json.loads((REG / 'towns.json').read_text(encoding='utf-8'))['towns']
    st = {p.stem: (read(p) or {}).get('status') for p in (REG / 'towns').glob('*.json')}
    first = [t for t in towns if st.get(t['slug']) in (None, 'queued', 'not_found', 'error', 'searching')]
    return first + [t for t in towns if st.get(t['slug']) == 'partial'], st


def claim(worker):
    todo, st = _todo(); slugs = [t['slug'] for t in todo]
    assign = read(REG / 'assignments.json') or {}; assign = {k: [s for s in v if s not in set(slugs)] for k, v in assign.items() if k != worker}
    assign[worker] = slugs; (REG / 'assignments.json').write_text(json.dumps(assign, indent=1), encoding='utf-8')
    (REG / 'workers' / f'{worker}.json').write_text(json.dumps({'current': None, 'state': 'working'}), encoding='utf-8')
    print(f'{worker} now owns {len(slugs)} towns ({sum(1 for t in todo if st.get(t["slug"]) != "partial")} unresolved first, then {sum(1 for t in todo if st.get(t["slug"]) == "partial")} partial)')


CLAIMS = REG / 'claims'


def _claim(slug, worker):
    """Atomic claim: exclusive-create a file per town, so concurrent workers (Codex, Haiku agents) never share a town."""
    CLAIMS.mkdir(exist_ok=True)
    try:
        fd = os.open(CLAIMS / f'{slug}.claim', os.O_CREAT | os.O_EXCL | os.O_WRONLY); os.write(fd, worker.encode()); os.close(fd); return True
    except FileExistsError: return False


def _all_done():
    done = set()
    for f in REG.glob('*_done.json'):
        try: done |= set(json.loads(f.read_text(encoding='utf-8')))
        except ValueError: pass
    return done


def next_town(worker, queue=None, from_end=False):
    assign = read(REG / 'assignments.json') or {}; mine = list(assign.get(queue or worker, []))
    if from_end: mine.reverse()
    towns = {t['slug']: t for t in json.loads((REG / 'towns.json').read_text(encoding='utf-8'))['towns']}; done = _all_done()
    for s in mine:
        if s in done: continue
        p = REG / 'towns' / f'{s}.json'; d = read(p) or {}
        if d.get('status') == 'searching' and d.get('worker') not in (None, worker): continue
        if not _claim(s, worker):
            owner = (CLAIMS / f'{s}.claim').read_text(encoding='utf-8')
            if owner != worker: continue
        prev = d.get('previous') or {k: d.get(k) for k in ('status', 'document') if d.get(k)}
        p.write_text(json.dumps({**d, 'slug': s, 'worker': worker, 'status': 'searching', 'previous': prev}, indent=1), encoding='utf-8')
        (REG / 'workers' / f'{worker}.json').write_text(json.dumps({'current': s}), encoding='utf-8')
        t = towns[s]; had = (prev.get('document') or {}).get('url')
        print(f"NEXT {s} | {t['name']}, Massachusetts ({t['county']} County) | previously: {prev.get('status', 'never searched')}" + (f' | already known (lacks the stop-sign list): {had}' if had else ''))
        return
    (REG / 'workers' / f'{worker}.json').write_text(json.dumps({'current': None, 'state': 'done'}), encoding='utf-8'); print('DONE: no towns left for', worker)


def release(worker, slug):
    """Hand a town back unchanged (e.g. the agent ran out of web searches)."""
    p = REG / 'towns' / f'{slug}.json'; d = read(p) or {}; prev = d.pop('previous', {}) or {}
    if prev.get('status'): d.update(prev)
    else: p.unlink(missing_ok=True); d = None
    if d is not None: d['status'] = prev.get('status', 'queued'); p.write_text(json.dumps(d, indent=1), encoding='utf-8')
    (CLAIMS / f'{slug}.claim').unlink(missing_ok=True); (REG / 'workers' / f'{worker}.json').write_text(json.dumps({'current': None}), encoding='utf-8')
    print(f'RELEASED {slug}')


def submit(worker, slug, urls, note):
    import swarm_verify as V
    p = REG / 'towns' / f'{slug}.json'; d = read(p) or {'slug': slug}; prev = d.pop('previous', {}) or {}
    d['candidates'] = list(dict.fromkeys(urls + (d.get('candidates') or [])))[:8]; d['worker'] = worker; d['notes'] = note[:500]
    if prev.get('status') == 'found': d['status'] = 'found'
    p.write_text(json.dumps(d, indent=1), encoding='utf-8')
    towns = {t['slug']: t for t in json.loads((REG / 'towns.json').read_text(encoding='utf-8'))['towns']}
    V.verify_town(p, towns); d = read(p); v = d.get('verification', {})
    if d['status'] == 'searching':
        if v.get('stop_rows', 0) > 0 or v.get('format') == 'pdf_scanned' or prev.get('status') == 'partial': d['status'] = 'partial'; d['document'] = d.get('document') or prev.get('document') or ({'url': v['url'], 'title': 'candidate', 'format': v.get('format'), 'verified': True} if v.get('url') else None)
        else: d['status'] = 'not_found'
    p.write_text(json.dumps(d, indent=1), encoding='utf-8')
    done_p = REG / f'{worker}_done.json'; done = json.loads(done_p.read_text(encoding='utf-8')) if done_p.exists() else []
    done_p.write_text(json.dumps(sorted(set(done) | {slug})), encoding='utf-8')
    print(f"RESULT {slug}: {d['status']} | stop-sign rows {v.get('stop_rows', 0)} | {v.get('url') or v.get('result', '')}")


def iso(ts): return dt.datetime.fromtimestamp(ts, dt.timezone.utc).isoformat(timespec='seconds')


def read(p):
    try: return json.loads(p.read_text(encoding='utf-8'))
    except (OSError, ValueError): return None   # mid-write or malformed: pick it up next tick


def status_once(started):
    towns = {x['slug']: x for x in json.loads((REG / 'towns.json').read_text(encoding='utf-8'))['towns']}
    assign = read(REG / 'assignments.json') or {}; owner = {s: a for a, ss in assign.items() for s in ss}
    out_t, events = {}, []
    for p in (REG / 'towns').glob('*.json'):
        d = read(p)
        if not d: continue
        s = d.get('slug') or p.stem; m = p.stat().st_mtime
        out_t[s] = {'status': d.get('status', 'searching'), 'worker': d.get('worker') or owner.get(s), 'updated_at': iso(m), 'document': d.get('document'),
                    'candidates': d.get('candidates', [])[:5], 'notes': (d.get('notes') or '')[:400], 'pipeline': d.get('pipeline')}
        events.append((m, s, out_t[s]['status'], out_t[s]['worker']))
    workers = {}
    for wf in (REG / 'workers').glob('*.json'):
        if wf.stem not in assign: assign[wf.stem] = [s for s, t in out_t.items() if t.get('worker') == wf.stem]
    for a, ss in assign.items():
        d = read(REG / 'workers' / f'{a}.json') or {}; p = REG / 'workers' / f'{a}.json'
        done = sum(1 for s in ss if out_t.get(s, {}).get('status') in ('found', 'partial', 'not_found', 'error'))
        cur = next((s for s in ss if out_t.get(s, {}).get('status') == 'searching'), None)
        workers[a] = {'assigned': len(ss), 'done': done, 'current': d.get('current') or cur, 'state': d.get('state') or ('done' if done == len(ss) else 'working' if cur or done else 'queued'),
                      'heartbeat': iso(p.stat().st_mtime) if p.exists() else None, 'towns': ss}
    counts = {k: 0 for k in ('found', 'partial', 'not_found', 'error', 'searching', 'queued')}
    for s in towns: counts[out_t.get(s, {}).get('status', 'queued')] = counts.get(out_t.get(s, {}).get('status', 'queued'), 0) + 1
    events.sort(reverse=True)
    st = {'generated_at': iso(time.time()), 'started_at': iso(started), 'total': len(towns), 'counts': counts, 'towns': out_t, 'workers': workers,
          'events': [{'at': iso(m), 'slug': s, 'name': towns.get(s, {}).get('name', s), 'status': stt, 'worker': w} for m, s, stt, w in events[:60]]}
    tmp = REG / 'status.json.tmp'; tmp.write_text(json.dumps(st), encoding='utf-8'); os.replace(tmp, REG / 'status.json')
    return st


def status_loop(interval):
    started = (REG / 'assignments.json').stat().st_mtime
    while True:
        try: status_once(started)
        except Exception as e: print('aggregator', type(e).__name__, e, flush=True)
        time.sleep(interval)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__.split(chr(10))[0]); ap.add_argument('command', choices=['build', 'status', 'once', 'claim', 'next', 'submit', 'release'])
    ap.add_argument('args', nargs='*'); ap.add_argument('--worker', default='codex'); ap.add_argument('--note', default=''); ap.add_argument('--queue'); ap.add_argument('--from-end', action='store_true')
    ap.add_argument('--agents', type=int, default=30); ap.add_argument('--interval', type=float, default=2.0); a = ap.parse_args()
    if a.command == 'claim': claim(a.worker)
    elif a.command == 'next': next_town(a.worker, a.queue, a.from_end)
    elif a.command == 'release': release(a.worker, a.args[0])
    elif a.command == 'submit': submit(a.worker, a.args[0], [u for u in a.args[1:] if u.startswith('http')], a.note)
    elif a.command == 'build': build(a.agents)
    elif a.command == 'once': s = status_once(time.time()); print(json.dumps(s['counts']))
    else: status_loop(a.interval)
