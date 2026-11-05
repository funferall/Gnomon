"""Check that each "found" document really belongs to its town (see REGULATIONS_PLAN.md).

Two independent signals:
  title   ecode360-style page titles name the municipality ("... - Town of West Springfield, MA")
  streets street names in the document's stop-sign sections, voted against every municipality in MassGIS Roads
A document fails if its title names another place, or if another municipality wins the street vote clearly. Failed towns
are demoted to `partial` (layer removed, reason recorded), and a Massachusetts document is offered to the town it
belongs to as a lead. Motivation: the Haiku parsing pass exposed Harwich, Westfield, Blackstone, Essex and Peabody
documents that were really West Springfield, Westfield NY, Cumberland RI, Beverly and Middleton.
"""
import argparse, json, re
from collections import Counter
from pathlib import Path
import pandas as pd
import reg_harness as H, reg_multitown as M

ROOT = Path(__file__).resolve().parent; REG = ROOT / 'data' / 'regulations' / 'registry'
NAME = re.compile(r"\b([A-Z][A-Za-z'\.]+(?:\s+[A-Z][A-Za-z'\.]+){0,3})\s+(Street|St\.?|Road|Rd\.?|Avenue|Ave\.?|Lane|Ln\.?|Drive|Dr\.?|Way|Place|Pl\.?|Terrace|Circle|Court|Ct\.?|Parkway|Highway|Boulevard|Path|Row)\b")
TITLE = re.compile(r'<title>[^<]*?(?:Town|City|Village|Borough|Township|Inhabitants of the Town) of ([^,<]+),\s*([A-Z]{2})', re.I)


def street_index():
    roads = pd.read_parquet(ROOT / 'data' / 'massgis_roads.parquet', columns=['ST_NAME_ST', 'MUNI_L', 'MUNI_R'])
    roads['k'] = roads.ST_NAME_ST.fillna('').map(lambda n: ' '.join(H.norm_tokens(n)))
    idx = {}
    for k, l, r in zip(roads.k, roads.MUNI_L, roads.MUNI_R):
        if k: idx.setdefault(k, set()).update(m for m in (l, r) if isinstance(m, str))
    return idx


def check(slug, name, idx):
    d = ROOT / 'data' / 'regulations' / slug; out = {'town': slug}
    html = (d / 'source.html').read_text(encoding='utf-8', errors='replace') if (d / 'source.html').exists() else ''
    m = TITLE.search(html)
    if m: out['title_place'] = f'{m.group(1).strip()}, {m.group(2).upper()}'
    text = M.doc_text(slug) or ''
    lines = [l for _, block in M.stop_windows(text) for _, l in block] or text.splitlines()
    names = [' '.join(H.norm_tokens(a + ' ' + b)) for l in lines for a, b in NAME.findall(l)]
    votes = Counter()
    for k in names:
        for muni in idx.get(k, ()): votes[muni] += 1
    me = name.upper(); top = votes.most_common(1)[0] if votes else (None, 0)
    out.update(street_names=len(names), claimed_votes=votes.get(me, 0), top_town=top[0], top_votes=top[1])
    wrong_title = 'title_place' in out and (out['title_place'].split(',')[0].strip().lower() != name.lower() or not out['title_place'].endswith('MA'))
    wrong_streets = len(names) >= 15 and top[0] != me and votes.get(me, 0) < 0.6 * top[1]
    out['ok'] = not (wrong_title or wrong_streets)
    out['reason'] = None if out['ok'] else (f"document title names {out['title_place']}" if wrong_title else f"street names match {top[0].title()} ({top[1]}) far better than {name} ({votes.get(me, 0)})")
    return out


def run(apply):
    towns = {t['slug']: t for t in json.loads((REG / 'towns.json').read_text(encoding='utf-8'))['towns']}
    idx = street_index(); results = []
    for p in sorted((REG / 'towns').glob('*.json')):
        rd = json.loads(p.read_text(encoding='utf-8'))
        if rd.get('status') != 'found' or p.stem == 'wellesley': continue
        r = check(p.stem, towns[p.stem]['name'], idx); results.append(r)
        print(('OK   ' if r['ok'] else 'WRONG'), f"{p.stem:20}", r.get('title_place', '(no title)'), f"| streets {r['street_names']} claimed {r['claimed_votes']} top {r['top_town']} {r['top_votes']}", '|', r['reason'] or '', flush=True)
        if apply and not r['ok']:
            doc = rd.get('document') or {}
            rd.update(status='partial', pipeline=None, notes=f"Document rejected by identity check: {r['reason']}. " + (rd.get('notes') or ''))
            rd['wrong_document'] = doc; rd['document'] = None; p.write_text(json.dumps(rd, indent=1), encoding='utf-8')
            for f in ('regulatory_signs.geojson',): (ROOT / 'data' / 'regulations' / p.stem / f).unlink(missing_ok=True)
            owner = (r.get('title_place') or '').split(',')[0].strip() if r.get('title_place', '').endswith('MA') else (r['top_town'] or '').title()
            os_ = next((s for s, t in towns.items() if t['name'].lower() == owner.lower()), None)
            if os_ and doc.get('url'):
                op = REG / 'towns' / f'{os_}.json'; od = json.loads(op.read_text(encoding='utf-8')) if op.exists() else {'slug': os_, 'status': 'not_found'}
                od['candidates'] = list(dict.fromkeys([doc['url']] + (od.get('candidates') or [])))[:8]
                od['notes'] = (od.get('notes') or '') + f' Lead from identity check: a document filed under {towns[p.stem]["name"]} is really this town\'s.'
                op.write_text(json.dumps(od, indent=1), encoding='utf-8'); print(f'      -> lead passed to {owner}', flush=True)
    (ROOT / 'data' / 'regulations' / 'identity_check.json').write_text(json.dumps(results, indent=1), encoding='utf-8')
    print(f"{sum(not r['ok'] for r in results)} of {len(results)} found documents fail the identity check", flush=True)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__.split(chr(10))[0]); ap.add_argument('--apply', action='store_true'); run(ap.parse_args().apply)
