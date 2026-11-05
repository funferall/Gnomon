"""Follow "see Schedule X" references to the actual stop-sign list (see REGULATIONS_PLAN.md).

Many towns' rules say the stop streets are "listed in Schedule B / Schedule 11 / Schedule J". For each town whose found
document had no list: collect the schedule IDs referenced near its stop-sign rules, look for that schedule's heading
in the same document, then in every candidate document the swarm found for the town (downloaded and checked for the
right town). The schedule block, or failing that the best stop-sign section of a candidate, is written to
stop_section.txt for the parsing agents.
"""
import argparse, json, re
from pathlib import Path
import reg_multitown as M, swarm_verify as V

ROOT = Path(__file__).resolve().parent; REG = ROOT / 'data' / 'regulations' / 'registry'
REF = re.compile(r'schedule\s*(?:no\.?|number|#)?\s*([A-Z]{1,2}(?:[.\-]\d+)?|\d{1,3}[A-Z]?|[IVXL]{1,5}(?:-[A-Z])?)\b', re.I)


def schedule_block(text, sid):
    lines = text.splitlines(); head = re.compile(rf'^\s*schedule\s*(?:no\.?|number|#)?\s*{re.escape(sid)}\b', re.I)
    best = []
    for i, l in enumerate(lines):
        if head.match(l.strip()):
            block = []
            for j in range(i + 1, min(len(lines), i + 1500)):
                s = lines[j].strip()
                if re.match(r'^\s*schedule\s*(?:no\.?|number|#)?\s*\S+', s, re.I) and not head.match(s) and len(block) > 5: break
                if s: block.append((j, s))
            if sum(1 for _, s in block if V.STREET.search(s)) > sum(1 for _, s in best if V.STREET.search(s)): best = block
    return best if sum(1 for _, s in best if V.STREET.search(s)) >= 5 else []


def refs(text):
    ids = []
    for _, block in M.stop_windows(text):
        for _, l in block[:60]:
            ids += [m.group(1).upper() for m in REF.finditer(l)]
    return list(dict.fromkeys(ids))


def run(slugs):
    towns = {t['slug']: t for t in json.loads((REG / 'towns.json').read_text(encoding='utf-8'))['towns']}
    for slug in slugs:
        rd = json.loads((REG / 'towns' / f'{slug}.json').read_text(encoding='utf-8')); name = towns[slug]['name']; d = ROOT / 'data' / 'regulations' / slug
        text = M.doc_text(slug) or ''; ids = refs(text); found, where = [], None
        for sid in ids:
            found = schedule_block(text, sid)
            if found: where = f'same document, Schedule {sid}'; break
        if not found:
            urls = [u for u in [(rd.get('document') or {}).get('url')] + (rd.get('candidates') or []) if u]
            for u in dict.fromkeys(urls):
                got, err = V.fetch(u)
                if err: continue
                t, fmt = V.to_text(got[0], got[1]); s = V.score(t, name)
                if not s['mentions_town'] and name.lower() not in u.lower(): continue
                for sid in ids:
                    found = schedule_block(t, sid)
                    if found: where = f'{u} (Schedule {sid})'; break
                if not found and s['stop_rows'] >= 8:
                    wins = M.stop_windows(t); found = max((b for _, b in wins), key=len, default=[]); where = f'{u} (stop-sign section)' if found else None
                if found:
                    (d / ('schedule_source' + ('.pdf' if got[0][:5] == b'%PDF-' else '.html'))).write_bytes(got[0]); break
        if found:
            (d / 'stop_section.txt').write_text(f'--- {where} ---\n' + '\n'.join(f'{ln}\t{l}' for ln, l in found), encoding='utf-8')
            (d / 'stop_rows_ai.json').unlink(missing_ok=True)
        print(f"{slug:14} refs {ids[:6]} -> {('FOUND ' + str(len(found)) + ' lines in ' + where) if found else 'not found'}", flush=True)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__.split(chr(10))[0]); ap.add_argument('--only', nargs='*', required=True); run(ap.parse_args().only)
