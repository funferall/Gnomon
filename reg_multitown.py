"""Map stop signs for every town whose regulations the swarm found (deterministic pass; see REGULATIONS_PLAN.md).

For each town with a saved, verified document: extract text, cut out the stop-sign sections (lines after a
stop-sign heading, until the next schedule/section heading), parse each line with the town's street gazetteer
(MassGIS names + TIGER geometry, reg_harness), geocode and place. Lines that do not parse are kept for a later
model pass. Writes per-town layers, a statewide layer, and a yield table; updates the swarm registry's pipeline field.
"""
import argparse, json, re, traceback
from collections import Counter
from pathlib import Path
import reg_harness as H, swarm_verify as V

ROOT = Path(__file__).resolve().parent; REG = ROOT / 'data' / 'regulations' / 'registry'
NEXT_HEAD = re.compile(r'^\s*(schedule|article|section|chapter|part|appendix|§)\s*[\dIVXL]', re.I)


def doc_text(slug):
    d = ROOT / 'data' / 'regulations' / slug
    for f in (d / 'source.pdf', d / 'source.html'):
        if f.exists(): return V.to_text(f.read_bytes(), 'application/pdf' if f.suffix == '.pdf' else 'text/html')[0]
    return None


def stop_windows(text):
    lines = [l.strip() for l in text.splitlines()]; out, i = [], 0
    while i < len(lines):
        if V.STOP_HEAD.search(lines[i]) and len(lines[i]) < 140:
            j = i + 1; block = []
            while j < len(lines) and j < i + 600:
                if NEXT_HEAD.match(lines[j]) and len(block) > 5 and not V.STOP_HEAD.search(lines[j]): break
                if lines[j]: block.append((j, lines[j]))
                j += 1
            out.append((i, block)); i = j
        else: i += 1
    return out


def parse_town(slug):
    text = doc_text(slug)
    if not text: return None, 'no saved document'
    gz = H.Gazetteer(slug); recs, seen, cand_lines = [], set(), 0
    for head, block in stop_windows(text):
        k = 0
        while k < len(block):
            ln, line = block[k]
            if len(V.STREET.findall(line)) == 0: k += 1; continue
            cand_lines += 1; r = H.parse_table_row(gz, 'stop', line)
            if ('on_street' not in r or not r.get('at_streets')) and k + 1 < len(block):   # wrapped row: try joining the next line
                r2 = H.parse_table_row(gz, 'stop', line + ' ' + block[k + 1][1])
                if 'on_street' in r2 and r2.get('at_streets'): r = r2; line = line + ' ' + block[k + 1][1]; k += 1
            if 'on_street' in r and r.get('at_streets'):
                key = (r['on_street'], tuple(r['at_streets']), tuple(r.get('directions') or []))
                if key not in seen:
                    seen.add(key); r.update(id=f'{slug}:stop:{ln}', town=slug, schedule='stop', source={'url': H.town_cfg(slug).get('doc_url'), 'line': ln, 'raw': line[:300]})
                    recs.append(r)
            k += 1
    return (gz, recs, cand_lines), None


def run(only):
    reg_towns = {p.stem: json.loads(p.read_text(encoding='utf-8')) for p in (REG / 'towns').glob('*.json')}
    found = [s for s, d in reg_towns.items() if d.get('status') == 'found' and s != 'wellesley' and (not only or s in only)]
    table, state = [], []
    for slug in sorted(found):
        try:
            got, err = parse_town(slug)
            if err: table.append({'town': slug, 'error': err}); continue
            gz, recs, cand = got
            gz, signs, unresolved = H.geocode(slug, gz, recs)
            placed = [s for s in signs if s['kind'] == 'stop']; directed = sum(1 for s in placed if s.get('method') == 'deterministic_approach_offset')
            d = ROOT / 'data' / 'regulations' / slug; d.mkdir(parents=True, exist_ok=True)
            feats = [{'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [round(s['lon'], 8), round(s['lat'], 8)]},
                      'properties': {k: s.get(k) for k in ('id', 'town', 'kind', 'on_street', 'at_street', 'travel_deg', 'facing_text', 'enacted', 'method', 'uncertainty95_m', 'flags', 'source')}} for s in placed]
            (d / 'regulatory_signs.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': feats}), encoding='utf-8')
            (d / 'unresolved.json').write_text(json.dumps(unresolved, indent=1, default=str), encoding='utf-8')
            state += feats
            row = {'town': slug, 'candidate_lines': cand, 'parsed_rows': len(recs), 'unresolved_rows': len(unresolved), 'stop_signs_placed': len(placed),
                   'with_direction': directed, 'parse_rate': round(len(recs) / max(1, cand), 2), 'roads': gz.source[:60]}
            table.append(row); print(json.dumps(row), flush=True)
            rp = REG / 'towns' / f'{slug}.json'; rd = json.loads(rp.read_text(encoding='utf-8'))
            rd['pipeline'] = f"mapped {len(placed)} stop signs ({directed} with direction); {len(unresolved)} rows need review" if placed else 'parsed 0 rows: needs model extraction'
            rp.write_text(json.dumps(rd, indent=1), encoding='utf-8')
        except Exception as e:
            table.append({'town': slug, 'error': f'{type(e).__name__}: {e}'[:200]}); print(slug, 'ERROR', type(e).__name__, e, flush=True)
    # Statewide outputs are rebuilt from every town's saved layer, so a partial (--only) run never drops other towns.
    ypath = ROOT / 'data' / 'regulations' / 'multitown_yield.json'
    old = {r['town']: r for r in json.loads(ypath.read_text(encoding='utf-8'))} if ypath.exists() else {}
    old.update({r['town']: r for r in table}); ypath.write_text(json.dumps(list(old.values()), indent=1), encoding='utf-8')
    state = []
    for f in sorted((ROOT / 'data' / 'regulations').glob('*/regulatory_signs.geojson')):
        for ft in json.loads(f.read_text(encoding='utf-8'))['features']:
            if ft['properties'].get('kind', 'stop') == 'stop': ft['properties'].setdefault('town', f.parent.name); state.append(ft)
    (ROOT / 'data' / 'regulations' / 'statewide_stop_signs.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': state}), encoding='utf-8')
    print(f'statewide layer: {len(state)} stop signs from {len({ft["properties"]["town"] for ft in state})} towns', flush=True)
    ok = [t for t in table if 'stop_signs_placed' in t]
    print(f"\n{len(ok)} towns processed, {sum(t['stop_signs_placed'] for t in ok)} stop signs placed; "
          f"{sum(1 for t in ok if t['stop_signs_placed'] >= 10)} towns with >= 10 signs; {len(table) - len(ok)} errors", flush=True)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__.split(chr(10))[0]); ap.add_argument('--only', nargs='*'); a = ap.parse_args(); run(set(a.only or []))
