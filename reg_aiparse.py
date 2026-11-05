"""Model-assisted stop-sign parsing for towns the deterministic pass could not read (see REGULATIONS_PLAN.md).

sections  write each town's stop-sign sections, with line numbers, to data/regulations/<slug>/stop_section.txt
ingest    read agent-structured rows (stop_rows_ai.json), validate every street against the town gazetteer
          (MassGIS names), merge with the deterministic rows, geocode/place, rewrite the town layer and the statewide layer
Agents only structure text; nothing reaches the map without passing the gazetteer and intersection checks.
"""
import argparse, json, re
from collections import Counter
from pathlib import Path
import reg_harness as H, reg_multitown as M

ROOT = Path(__file__).resolve().parent; REG = ROOT / 'data' / 'regulations' / 'registry'
COMP = {'N': 0, 'NE': 45, 'E': 90, 'SE': 135, 'S': 180, 'SW': 225, 'W': 270, 'NW': 315}
FROM_DIR = re.compile(r'from\s+the\s+(north|south|east|west|northeast|northwest|southeast|southwest)\b', re.I)


def write_sections(slugs):
    sizes = {}
    for slug in slugs:
        text = M.doc_text(slug)
        if not text: continue
        lines = []
        for head, block in M.stop_windows(text):
            lines.append(f'--- section starting at line {head} ---'); lines += [f'{ln}\t{l}' for ln, l in block]
        (ROOT / 'data' / 'regulations' / slug / 'stop_section.txt').write_text('\n'.join(lines), encoding='utf-8'); sizes[slug] = len(lines)
    return sizes


def ingest(slug):
    d = ROOT / 'data' / 'regulations' / slug; ai = json.loads((d / 'stop_rows_ai.json').read_text(encoding='utf-8'))
    got, err = M.parse_town(slug)
    if err: return {'town': slug, 'error': err}
    gz, recs, cand = got; seen = {(r['on_street'], tuple(r['at_streets']), tuple(r.get('directions') or [])) for r in recs}
    def canon(name):
        toks = H.norm_tokens(name or ''); c, n, how = gz.resolve(toks)
        return (c, how) if c and n >= len(toks) - 1 else (None, None)
    added = 0; reasons = Counter()
    for i, row in enumerate(ai.get('rows', [])):
        on, how = canon(row.get('on_street')); ats = [a for a in (canon(x)[0] for x in (row.get('at_streets') or [])) if a]
        if not on: reasons['on_street_not_in_gazetteer'] += 1; continue
        if not ats: reasons['at_street_not_in_gazetteer'] += 1; continue
        dirs = [COMP[x] for x in (row.get('travel_directions') or []) if x in COMP]
        if not dirs:   # "from the east" = approaching from the east = travelling west
            for m in FROM_DIR.finditer(row.get('direction_text') or row.get('raw') or ''):
                dirs.append((H.COMPASS[m.group(1).lower()] + 180) % 360)
        key = (on, tuple(ats), tuple(dirs))
        if key in seen: continue
        seen.add(key); added += 1
        recs.append({'kind': 'stop', 'on_street': on, 'at_streets': ats, 'directions': dirs, 'enacted': [], 'facing_text': row.get('direction_text') or '',
                     'flags': ['model_structured'] + ([] if how == 'exact' else ['on_street_' + str(how)]), 'id': f'{slug}:stop-ai:{row.get("line", i)}', 'town': slug,
                     'schedule': 'stop', 'source': {'url': H.town_cfg(slug).get('doc_url'), 'line': row.get('line'), 'raw': (row.get('raw') or '')[:300]}})
    # "Facing North" can mean travelling north or a sign face pointing north (traffic travelling south). Let the street
    # geometry decide per town: keep the reading whose approach legs line up better with the stated directions.
    flipped = [{**r, 'directions': [(d + 180) % 360 for d in r['directions']]} if 'model_structured' in r['flags'] else r for r in recs]
    def fit(rs):
        g, sg, un = H.geocode(slug, gz, rs); errs = [s['direction_error_deg'] for s in sg if 'model_structured' in s['flags'] and s.get('direction_error_deg') is not None]
        return (sorted(errs)[len(errs) // 2] if errs else 999), g, sg, un
    e1, g1, s1, u1 = fit(recs); e2, g2, s2, u2 = fit(flipped) if any(r['directions'] for r in recs if 'model_structured' in r['flags']) else (999, None, None, None)
    reading = 'as written' if e1 <= e2 else 'flipped (sign-face direction)'
    gz, signs, unresolved = (g1, s1, u1) if e1 <= e2 else (g2, s2, u2)
    if e1 > e2:
        for s in signs:
            if 'model_structured' in s['flags']: s['flags'] = s['flags'] + ['direction_flipped_by_geometry']
    placed = [s for s in signs if s['kind'] == 'stop']; directed = sum(1 for s in placed if s.get('method') == 'deterministic_approach_offset')
    feats = [{'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [round(s['lon'], 8), round(s['lat'], 8)]},
              'properties': {k: s.get(k) for k in ('id', 'town', 'kind', 'on_street', 'at_street', 'travel_deg', 'facing_text', 'enacted', 'method', 'uncertainty95_m', 'flags', 'source')}} for s in placed]
    (d / 'regulatory_signs.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': feats}), encoding='utf-8')
    (d / 'unresolved.json').write_text(json.dumps(unresolved, indent=1, default=str), encoding='utf-8')
    rp = REG / 'towns' / f'{slug}.json'; rd = json.loads(rp.read_text(encoding='utf-8'))
    rd['pipeline'] = f'mapped {len(placed)} stop signs ({directed} with direction; {added} rows model-structured); {len(unresolved)} rows need review'
    rp.write_text(json.dumps(rd, indent=1), encoding='utf-8')
    return {'town': slug, 'candidate_lines': cand, 'agent_rows': len(ai.get('rows', [])), 'model_rows_added': added, 'rejected': dict(reasons),
            'unresolved_rows': len(unresolved), 'stop_signs_placed': len(placed), 'with_direction': directed,
            'direction_reading': reading, 'median_leg_error_deg': {'as_written': e1, 'flipped': e2}}


def rebuild_statewide():
    state = []
    for f in sorted((ROOT / 'data' / 'regulations').glob('*/regulatory_signs.geojson')):
        for ft in json.loads(f.read_text(encoding='utf-8'))['features']:
            if ft['properties'].get('kind', 'stop') == 'stop': ft['properties'].setdefault('town', f.parent.name); state.append(ft)
    (ROOT / 'data' / 'regulations' / 'statewide_stop_signs.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': state}), encoding='utf-8')
    print(f'statewide layer: {len(state)} stop signs from {len({ft["properties"]["town"] for ft in state})} towns', flush=True)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__.split(chr(10))[0]); ap.add_argument('command', choices=['sections', 'ingest']); ap.add_argument('--only', nargs='*'); a = ap.parse_args()
    if a.command == 'sections': print(json.dumps(write_sections(a.only or []), indent=1))
    else:
        for s in a.only or [p.parent.name for p in (ROOT / 'data' / 'regulations').glob('*/stop_rows_ai.json')]:
            try: print(json.dumps(ingest(s)), flush=True)
            except Exception as e: print(s, 'ERROR', type(e).__name__, e, flush=True)
        rebuild_statewide()
