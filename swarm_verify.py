"""Search-free verification of swarm leads: download each candidate document and check it really holds a stop-sign schedule.

For every town file with a document URL or candidate URLs: fetch directly (no web search), extract text
(pdftotext -raw for PDFs, tag-stripped HTML for code hosts such as ecode360), confirm the town is named, and count
rows that look like stop-sign entries (two street-type words) under a stop-sign heading. A town becomes `found`
(verified by harness) at >= 8 such rows. Municode is behind a Cloudflare CAPTCHA and is left for a human; we do not
attempt to get around it. Documents are cached under data/regulations/<slug>/ for the mapping pipeline.
"""
import argparse, concurrent.futures as cf, hashlib, html, json, re, subprocess
from pathlib import Path
import requests
import reg_harness as H

ROOT = Path(__file__).resolve().parent; REG = ROOT / 'data' / 'regulations' / 'registry'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36 Gnomon-regulations/0.1'
STREET = re.compile(r'\b(?:road|rd|street|st|avenue|ave|av|lane|ln|drive|dr|way|place|pl|terrace|ter|circle|cir|court|ct|parkway|pkwy|highway|hwy|square|sq|boulevard|blvd|path|row|hill|extension|ext)\b\.?', re.I)
STOP_HEAD = re.compile(r'stop\s+signs?|stop\s+streets?|stop\s+intersections?|through\s+ways?|schedule\s+of\s+stop', re.I)


def fetch(url):
    if 'municode.com' in url: return None, 'municode_captcha_needs_human'
    try:
        r = requests.get(url, headers={'User-Agent': UA}, timeout=45, allow_redirects=True, stream=True)
        if r.status_code != 200: return None, f'http_{r.status_code}'
        data = r.raw.read(40 * 1024 * 1024, decode_content=True)
        return (data, r.headers.get('content-type', ''), r.url), None
    except Exception as e: return None, type(e).__name__   # any network/protocol failure is a per-URL miss, not a crash


def to_text(data, ctype):
    if data[:5] == b'%PDF-':
        import os, tempfile   # this pdftotext cannot read a PDF from stdin: go through a temp file
        fd, tmp = tempfile.mkstemp(suffix='.pdf'); os.write(fd, data); os.close(fd)
        try: txt = subprocess.run([H.pdftotext(), '-raw', '-enc', 'UTF-8', tmp, '-'], capture_output=True, timeout=180).stdout.decode('utf-8', 'replace')
        finally: os.unlink(tmp)
        pages = max(1, txt.count('\f'))
        return txt, 'pdf_scanned' if len(txt.strip()) < 200 * pages * 0.2 else 'pdf_text'
    if 'html' in ctype or data[:200].lstrip().lower().startswith((b'<!doctype', b'<html')):
        t = re.sub(r'(?is)<(script|style).*?</\1>', ' ', data.decode('utf-8', 'replace'))
        t = re.sub(r'(?i)<br\s*/?>|</(p|div|tr|li|h\d)>', '\n', t); t = html.unescape(re.sub(r'<[^>]+>', ' ', t))
        return t, 'html'
    return '', 'other'


def score(text, town):
    lines = [l.strip() for l in text.splitlines() if l.strip()]; stop_rows, best, i = 0, 0, 0
    heads = [k for k, l in enumerate(lines) if STOP_HEAD.search(l) and len(l) < 120]
    for k in heads:   # rows that name two streets in the 400 lines after a stop-sign heading
        n = sum(1 for l in lines[k + 1:k + 400] if len(STREET.findall(l)) >= 2 and len(l) < 200)
        best = max(best, n)
    low = text.lower()
    return {'stop_rows': best, 'stop_headings': len(heads), 'mentions_town': town.lower() in low,
            'turn_prohibitions': bool(re.search(r'(no\s+(left|right)\s+turn|turns?\s+prohibited|prohibited\s+turns?)', low)),
            'one_way': bool(re.search(r'one[\s-]way\s+(streets?|traffic)', low)), 'chars': len(text)}


def verify_town(path, towns):
    d = json.loads(path.read_text(encoding='utf-8')); slug = d.get('slug') or path.stem; name = towns.get(slug, {}).get('name', slug)
    if d.get('verification', {}).get('by') == 'harness' and d['status'] == 'found' and d['verification'].get('stop_rows', 0) >= 8: return slug, d['status'], 'already verified'
    urls = [u for u in [(d.get('document') or {}).get('url')] + (d.get('candidates') or []) if u and u.startswith('http')]
    best, notes = None, []
    for u in dict.fromkeys(urls):
        got, err = fetch(u)
        if err: notes.append(f'{err}: {u}'); continue
        data, ctype, final = got; text, fmt = to_text(data, ctype); s = score(text, name); s.update(url=final, format=fmt, bytes=len(data))
        if best is None or (s['stop_rows'], s['mentions_town']) > (best['stop_rows'], best['mentions_town']): best = s; best_data = data
    if not best: d['verification'] = {'by': 'harness', 'result': 'could_not_download', 'notes': notes[:5]}
    else:
        d['verification'] = {'by': 'harness', **{k: best[k] for k in ('url', 'format', 'bytes', 'stop_rows', 'stop_headings', 'mentions_town', 'turn_prohibitions', 'one_way')}, 'notes': notes[:5]}
        if best['stop_rows'] >= 8 and best['mentions_town'] and best['format'] != 'pdf_scanned':
            doc = d.get('document') or {}
            doc.update(url=best['url'], format='ecode360' if 'ecode360' in best['url'] else best['format'], has_stop_signs=True,
                       has_turn_prohibitions=doc.get('has_turn_prohibitions') or best['turn_prohibitions'], has_one_way=doc.get('has_one_way') or best['one_way'], verified=True)
            doc.setdefault('title', f'{name} traffic regulations'); d['document'] = doc; d['status'] = 'found'; d['pipeline'] = 'ready to map'
            out = ROOT / 'data' / 'regulations' / slug; out.mkdir(parents=True, exist_ok=True)
            ext = '.pdf' if best_data[:5] == b'%PDF-' else '.html'; (out / ('source' + ext)).write_bytes(best_data)
            (out / 'source.json').write_text(json.dumps({'town': slug, 'url': best['url'], 'sha256': hashlib.sha256(best_data).hexdigest(), 'bytes': len(best_data)}, indent=1), encoding='utf-8')
        elif best['format'] == 'pdf_scanned' and d['status'] == 'not_found': d['status'] = 'partial'
    path.write_text(json.dumps(d, indent=1), encoding='utf-8')
    v = d['verification']; return slug, d['status'], f"{v.get('result') or str(v.get('stop_rows')) + ' stop rows'} {v.get('format', '')}"


def run(workers):
    towns = {x['slug']: x for x in json.loads((REG / 'towns.json').read_text(encoding='utf-8'))['towns']}
    files = [p for p in (REG / 'towns').glob('*.json') if p.stem != 'wellesley']
    with cf.ThreadPoolExecutor(workers) as pool:
        for slug, st, info in pool.map(lambda p: verify_town(p, towns), files): print(f'{slug:24} {st:10} {info}', flush=True)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0]); ap.add_argument('--workers', type=int, default=6); run(ap.parse_args().workers)
