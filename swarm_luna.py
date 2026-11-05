"""Search with gpt-6-luna (OpenAI web search), verify deterministically. Feeds the swarm dashboard as luna-NN workers.

Luna only proposes candidate URLs (strict JSON schema, at most --max-searches web searches per town). Every candidate is
downloaded and scored by swarm_verify (stop-sign rows under a stop-sign heading, town named, not a scanned image).
HTML pages are followed one level to linked traffic-rules documents. A hallucinated URL therefore cannot become "found".
Cost per call is logged to registry/luna_costs.jsonl (tokens at $0.10/$0.50 per 1M, web search at $10 per 1,000 calls;
developers.openai.com/api/docs/pricing, checked 2026-11-05).
"""
import argparse, concurrent.futures as cf, datetime as dt, json, re, threading, time
from pathlib import Path
from urllib.parse import urljoin
import openai
import swarm_verify as V

ROOT = Path(__file__).resolve().parent; REG = ROOT / 'data' / 'regulations' / 'registry'
MODEL, PIN, POUT, PER_SEARCH = 'gpt-6-luna', 0.10, 0.50, 0.01
SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['candidates', 'notes'], 'properties': {
    'candidates': {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False, 'required': ['url', 'title', 'why'],
                                              'properties': {'url': {'type': 'string'}, 'title': {'type': 'string'}, 'why': {'type': 'string'}}}},
    'notes': {'type': 'string'}}}
LINK = re.compile(r'href="([^"]+)"[^>]*>([^<]{0,160})<', re.I)
DOCWORD = re.compile(r'traffic|rules|regulation|order|stop|bylaw|by-law|ordinance', re.I)
lock = threading.Lock(); client = openai.OpenAI(max_retries=3, timeout=240)


def write(slug, d): (REG / 'towns' / f'{slug}.json').write_text(json.dumps(d, indent=1), encoding='utf-8')


def ask(name, county, prev, max_searches):
    hint = ''
    if prev.get('status') == 'partial':
        hint = (f" Earlier research found only this, which does not contain the stop-sign list: {((prev.get('document') or {}).get('url') or '')}."
                ' Look for the separate Select Board / Board of Selectmen / Traffic Commission rules or their schedules.')
    q = (f'Find the official document of {name}, Massachusetts ({county} County) that lists STOP SIGN locations by street and cross street. '
         "It is often titled 'Traffic Rules and Orders', 'Traffic Regulations' or 'Traffic and Parking Regulations', adopted by the Select Board, "
         'Board of Selectmen, City Council or a traffic commission, sometimes as a schedule or appendix.' + hint +
         ' Return up to 4 direct URLs (PDF preferred) from the municipality\'s official website or its official code host. '
         'Only return URLs you actually saw in search results; never construct URLs. Ignore other states.')
    t0 = time.perf_counter()
    r = client.responses.create(model=MODEL, tools=[{'type': 'web_search'}], max_tool_calls=max_searches, input=q,
                                text={'format': {'type': 'json_schema', 'name': 'candidates', 'schema': SCHEMA, 'strict': True}})
    searches = sum(1 for o in r.output if o.type == 'web_search_call')
    cost = r.usage.input_tokens * PIN / 1e6 + r.usage.output_tokens * POUT / 1e6 + searches * PER_SEARCH
    return json.loads(r.output_text), {'input_tokens': r.usage.input_tokens, 'output_tokens': r.usage.output_tokens, 'searches': searches,
                                       'cost_usd': round(cost, 5), 'seconds': round(time.perf_counter() - t0, 1)}


def check(url, name, depth=0):
    """Download and score; follow an HTML page's document links one level."""
    got, err = V.fetch(url)
    if err: return None
    data, ctype, final = got; text, fmt = V.to_text(data, ctype); s = {**V.score(text, name), 'url': final, 'format': fmt, 'data': data}
    if fmt == 'html' and s['stop_rows'] < 8 and depth == 0 and 'ecode360' not in final:
        links = []
        for href, label in LINK.findall(data.decode('utf-8', 'replace')):
            u = urljoin(final, href)
            if (u.lower().endswith('.pdf') or 'DocumentCenter/View' in u or 'showpublisheddocument' in u) and (DOCWORD.search(label) or DOCWORD.search(u)): links.append(u)
        for u in list(dict.fromkeys(links))[:4]:
            c = check(u, name, 1)
            if c and c['stop_rows'] > s['stop_rows']: s = c
    return s


def do_town(worker, slug, town, max_searches):
    p = REG / 'towns' / f'{slug}.json'; prev = json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
    write(slug, {**prev, 'slug': slug, 'worker': worker, 'status': 'searching'}); (REG / 'workers' / f'{worker}.json').write_text(json.dumps({'current': slug}), encoding='utf-8')
    try: res, usage = ask(town['name'], town['county'], prev, max_searches)
    except Exception as e:
        write(slug, {**prev, 'slug': slug, 'worker': worker, 'status': prev.get('status') or 'error', 'notes': f'luna error {type(e).__name__}'}); return slug, 'error', None
    with lock, open(REG / 'luna_costs.jsonl', 'a', encoding='utf-8') as f: f.write(json.dumps({'slug': slug, 'at': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'), **usage}) + '\n')
    best = None
    for c in res['candidates'][:4]:
        s = check(c['url'], town['name'])
        if s and (best is None or (s['stop_rows'], s['mentions_town']) > (best['stop_rows'], best['mentions_town'])): best = {**s, 'title': c['title']}
    cands = list(dict.fromkeys([c['url'] for c in res['candidates']] + (prev.get('candidates') or [])))[:6]
    out = {**prev, 'slug': slug, 'worker': worker, 'candidates': cands, 'luna': {**usage, 'notes': res['notes'][:300]}}
    if best and best['stop_rows'] >= 8 and best['mentions_town'] and best['format'] != 'pdf_scanned':
        out.update(status='found', pipeline='ready to map', document={'url': best['url'], 'title': best['title'], 'format': best['format'], 'last_updated': None, 'has_stop_signs': True,
                   'has_turn_prohibitions': best['turn_prohibitions'], 'has_one_way': best['one_way'], 'verified': True},
                   notes=f"Luna search + harness check: {best['stop_rows']} stop-sign rows.")
        d = ROOT / 'data' / 'regulations' / slug; d.mkdir(parents=True, exist_ok=True)
        (d / ('source.pdf' if best['data'][:5] == b'%PDF-' else 'source.html')).write_bytes(best['data'])
    elif best:
        why = 'scanned image PDF (needs OCR)' if best['format'] == 'pdf_scanned' else f"{best['stop_rows']} stop-sign rows, below the 8-row threshold"
        if prev.get('status') != 'found':
            out.update(status='partial', document={'url': best['url'], 'title': best['title'], 'format': best['format'], 'has_stop_signs': best['stop_rows'] > 0,
                       'has_turn_prohibitions': best['turn_prohibitions'], 'has_one_way': best['one_way'], 'verified': True}, notes=f'Luna found a document, but: {why}.')
    else:
        if prev.get('status') not in ('found', 'partial'): out.update(status='not_found', document=None, notes='Luna search: no candidate could be downloaded and verified.')
    write(slug, out); return slug, out['status'], (best or {}).get('stop_rows')


def run(workers, limit, max_searches, include_partial):
    towns = {x['slug']: x for x in json.loads((REG / 'towns.json').read_text(encoding='utf-8'))['towns']}
    status = {p.stem: json.loads(p.read_text(encoding='utf-8')).get('status') for p in (REG / 'towns').glob('*.json')}
    todo = [s for s in towns if s not in status or status[s] in ('error', 'not_found')]
    if include_partial: todo += [s for s in towns if status.get(s) == 'partial']
    todo = todo[:limit] if limit else todo
    names = [f'luna-{i + 1:02d}' for i in range(workers)]; batches = {n: todo[i::workers] for i, n in enumerate(names)}
    assign = json.loads((REG / 'assignments.json').read_text(encoding='utf-8')); moved = set(todo)
    assign = {k: [s for s in v if s not in moved] for k, v in assign.items() if not k.startswith('luna-')}; assign.update(batches)
    (REG / 'assignments.json').write_text(json.dumps(assign, indent=1), encoding='utf-8')
    print(f'Luna search: {len(todo)} towns, {workers} workers, <= {max_searches} searches each', flush=True)
    def work(n):
        for s in batches[n]: print(n, *do_town(n, s, towns[s], max_searches), flush=True)
        (REG / 'workers' / f'{n}.json').write_text(json.dumps({'current': None, 'state': 'done'}), encoding='utf-8')
    with cf.ThreadPoolExecutor(workers) as pool: list(pool.map(work, names))
    costs = [json.loads(l) for l in open(REG / 'luna_costs.jsonl', encoding='utf-8')] if (REG / 'luna_costs.jsonl').exists() else []
    print(f"ledger: {len(costs)} town searches, ${sum(c['cost_usd'] for c in costs):.2f} total, ${sum(c['cost_usd'] for c in costs) / max(1, len(costs)):.3f}/town, "
          f"{sum(c['searches'] for c in costs) / max(1, len(costs)):.1f} searches/town", flush=True)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__.split(chr(10))[0]); ap.add_argument('--workers', type=int, default=5); ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--max-searches', type=int, default=4); ap.add_argument('--include-partial', action='store_true'); a = ap.parse_args()
    run(a.workers, a.limit, a.max_searches, a.include_partial)
