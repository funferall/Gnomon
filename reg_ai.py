"""Model-assisted stages of the regulations harness (see REGULATIONS_PLAN.md).

extract   free-form schedules (one-way, U-turn, turn prohibitions, turn lanes) -> JSON records, per provider, N runs
score     compare each provider's records with the hand-checked gold set; accuracy, consistency, cost, latency
geometry  turn restrictions and one-way segments from records that >= 2 of 3 gpt-6-luna runs agree on (no gold needed to scale)

Models only read text here; every street name is validated against the gazetteer and every geometry is built
by deterministic code in reg_harness.py.
"""
import argparse, json, math, re, statistics
from collections import Counter, defaultdict
from pathlib import Path
import llm_providers as llm
import reg_harness as H

ROOT = Path(__file__).resolve().parent
PROMPT_VERSION = 'freeform-extract-v1'
FREEFORM = {'II', 'III', 'III-A', 'VI'}
NULLSTR = {'anyOf': [{'type': 'string'}, {'type': 'null'}]}
SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['records'], 'properties': {'records': {'type': 'array', 'items': {
    'type': 'object', 'additionalProperties': False,
    'required': ['schedule', 'kind', 'on_street', 'at_street', 'from_street', 'to_street', 'travel_direction', 'maneuver', 'onto_street', 'time_conditions', 'enacted', 'source_text'],
    'properties': {
        'schedule': {'type': 'string', 'enum': ['II', 'III', 'III-A', 'VI']},
        'kind': {'type': 'string', 'enum': ['one_way', 'no_u_turn', 'no_turn', 'turn_lane']},
        'on_street': NULLSTR, 'at_street': NULLSTR, 'from_street': NULLSTR, 'to_street': NULLSTR,
        # anyOf(enum, null): accepted by both OpenAI strict schemas and Anthropic structured outputs
        'travel_direction': {'anyOf': [{'type': 'string', 'enum': ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW', 'both']}, {'type': 'null'}]},
        'maneuver': {'anyOf': [{'type': 'string', 'enum': ['left', 'right', 'through', 'u_turn', 'lane_must_turn_left', 'lane_must_turn_right']}, {'type': 'null'}]},
        'onto_street': NULLSTR, 'time_conditions': NULLSTR, 'enacted': NULLSTR, 'source_text': {'type': 'string'}}}}}}
SYSTEM = """You convert schedules from a Massachusetts town's Traffic Rules and Orders into structured records.
The text was extracted from a PDF table; a single table row is often wrapped over several lines, and a column can wrap independently.
Rules:
- One record per regulation row. If a row covers two directions with two dates, emit two records.
- schedule: II = one-way streets, III = U-turns prohibited, III-A = turns prohibited, VI = mandatory turn lanes.
- on_street: the street the regulated traffic is travelling on (for one-way and U-turn rows: the LOCATION street). null if the row only names a driveway or lot.
- at_street: the cross street where the turn is regulated ("X at Y" -> on X, at Y). null if none.
- from_street / to_street: the limits of a one-way or U-turn stretch, as printed (keep descriptive limits such as "A point 200 feet south of Spring Street").
- travel_direction: compass direction the regulated traffic travels (Northerly/Northbound/North -> N, Easterly -> E, etc.); "both" for both directions; null if not stated.
- maneuver (turn rows): left, right, through ("continuation of travel"), u_turn; for turn lanes lane_must_turn_left/right. null for one-way rows.
- onto_street: street the prohibited turn would enter, if printed or clearly implied by "X at Y ... Right turn" (then onto_street = Y).
- time_conditions: days/hours text if the rule applies only at certain times, else null.
- enacted: the date in parentheses such as "3/79", exactly as printed; null if none or "n/a".
- source_text: the original row text, joined into one line.
Copy street names as printed. Do not invent anything that is not in the text."""


def freeform_text(town):
    pdf, meta = H.acquire(town); blocks = H.schedule_blocks(H.pages(pdf)); parts = []
    for sid, kind, pno, lines in blocks:
        if sid in FREEFORM: parts.append(f'=== SCHEDULE {sid} ({kind}) ===\n' + '\n'.join(s for _, s in lines))
    return '\n\n'.join(parts), meta


def extract(town, providers, runs):
    text, meta = freeform_text(town); out = ROOT / 'data' / 'regulations' / town / 'ai'; out.mkdir(parents=True, exist_ok=True)
    results = {}
    for p in providers:
        results[p] = []
        for i in range(runs):
            r = llm.call(p, SYSTEM, 'Schedules:\n\n' + text, SCHEMA, schema_name='regulation_records'); r['run'] = i; r['prompt_version'] = PROMPT_VERSION
            results[p].append(r); print(p, 'run', i, 'records', len((r.get('data') or {}).get('records', [])), r.get('usage'), f"${r.get('cost_usd', 0):.5f}", f"{r['latency_s']}s", r.get('error', ''), flush=True)
    (out / 'extract.json').write_text(json.dumps({'document_sha256': meta['sha256'], 'prompt_version': PROMPT_VERSION, 'results': results}, indent=1), encoding='utf-8')
    return results


# ---------------------------------------------------------------- scoring
def street_key(gz, s):
    if s is None: return None
    toks = [t for t in H.norm_tokens(s) if t not in ('the',)]
    if not toks: return None
    c, n, how = gz.resolve(toks)
    if c and n == len(toks): return c
    return ' '.join(toks)


def same_street(gz, a, b):
    ka, kb = street_key(gz, a), street_key(gz, b)
    if ka is None or kb is None: return ka == kb
    if ka == kb: return True
    A, B = set(ka.split()), set(kb.split())
    return len(A & B) / max(1, len(A | B)) >= 0.6          # descriptive limits ("a point 181 feet ...")


def norm_date(d): return None if d in (None, '', 'n/a') else '/'.join(str(int(x)) for x in re.findall(r'\d+', d)) or None
FIELDS = ['on_street', 'at_street', 'from_street', 'to_street', 'travel_direction', 'maneuver', 'onto_street', 'has_time_condition', 'enacted']


def field_ok(gz, f, g, p):
    if f.endswith('street'): return same_street(gz, g.get(f), p.get(f))
    if f == 'has_time_condition': return bool(g['has_time_condition']) == bool(p.get('time_conditions'))
    if f == 'enacted': return norm_date(g.get('enacted')) == norm_date(p.get('enacted'))
    return (g.get(f) or None) == (p.get(f) or None)


def score_run(gz, gold, pred):
    pred = [p for p in pred if p.get('schedule') in {g['schedule'] for g in gold}]; used, per_field, exact, matched = set(), Counter(), 0, 0
    for g in gold:
        best = max(((sum(field_ok(gz, f, g, p) for f in FIELDS), j) for j, p in enumerate(pred) if j not in used and p.get('schedule') == g['schedule']), default=None)
        if not best or best[0] < 5: continue   # not recognisably the same row
        used.add(best[1]); matched += 1; p = pred[best[1]]
        for f in FIELDS: per_field[f] += field_ok(gz, f, g, p)
        exact += all(field_ok(gz, f, g, p) for f in FIELDS)
    n = len(gold)
    return {'gold': n, 'matched': matched, 'recall': matched / n, 'precision': matched / max(1, len(pred)), 'exact_records': exact,
            'field_accuracy': sum(per_field.values()) / (n * len(FIELDS)), 'per_field': {f: per_field[f] / n for f in FIELDS}}


def score(town):
    gz = H.Gazetteer(town); gold = json.loads((ROOT / 'regulations' / 'gold' / f'{town}_freeform.json').read_text(encoding='utf-8'))['records']
    ext = json.loads((ROOT / 'data' / 'regulations' / town / 'ai' / 'extract.json').read_text(encoding='utf-8'))['results']; report = {}
    for p, runs in ext.items():
        ok = [r for r in runs if 'data' in r]; scores = [score_run(gz, gold, r['data']['records']) for r in ok]
        if not scores: report[p] = {'model': runs[0]['model'], 'errors': [r.get('error') for r in runs]}; continue
        report[p] = {'model': runs[0]['model'], 'runs': len(runs), 'failed_runs': len(runs) - len(ok),
                     'field_accuracy_mean': statistics.mean(s['field_accuracy'] for s in scores), 'field_accuracy_min': min(s['field_accuracy'] for s in scores),
                     'exact_records_mean': statistics.mean(s['exact_records'] for s in scores), 'recall_mean': statistics.mean(s['recall'] for s in scores),
                     'precision_mean': statistics.mean(s['precision'] for s in scores), 'per_field_mean': {f: statistics.mean(s['per_field'][f] for s in scores) for f in FIELDS},
                     'cost_usd_per_run': statistics.mean(r['cost_usd'] for r in ok), 'latency_s_mean': statistics.mean(r['latency_s'] for r in ok),
                     'tokens_mean': {k: statistics.mean(r['usage'][k] for r in ok) for k in ('input', 'output')}}
    (ROOT / 'data' / 'regulations' / town / 'ai' / 'extract_scores.json').write_text(json.dumps(report, indent=1), encoding='utf-8')
    print(f"{'provider':10} {'model':18} {'field acc':>9} {'min':>6} {'exact/21':>8} {'recall':>7} {'prec':>6} {'$/run':>9} {'sec':>6}")
    for p, r in report.items():
        if 'field_accuracy_mean' not in r: print(p, 'FAILED', r['errors']); continue
        print(f"{p:10} {r['model']:18} {r['field_accuracy_mean']:9.3f} {r['field_accuracy_min']:6.3f} {r['exact_records_mean']:8.1f} {r['recall_mean']:7.2f} {r['precision_mean']:6.2f} {r['cost_usd_per_run']:9.5f} {r['latency_s_mean']:6.1f}")
    return report


# ---------------------------------------------------------------- consensus + geometry
def record_key(gz, r):
    return (r['schedule'], street_key(gz, r.get('on_street')), street_key(gz, r.get('at_street') or r.get('from_street')), r.get('travel_direction'), r.get('maneuver'))


def consensus(town, min_runs=2):
    """Self-consistency: keep a record only if >= min_runs independent runs extracted it identically (after normalisation)."""
    gz = H.Gazetteer(town); ext = json.loads((ROOT / 'data' / 'regulations' / town / 'ai' / 'extract.json').read_text(encoding='utf-8'))['results']
    votes = defaultdict(lambda: {'runs': set(), 'records': []})
    for p, runs in ext.items():
        for r in runs:
            if 'data' not in r: continue
            for rec in r['data']['records']:
                k = record_key(gz, rec); votes[k]['runs'].add(f"{r['model']}#{r['run']}"); votes[k]['records'].append(rec)
    agreed = [{**v['records'][0], 'agreeing_providers': sorted(v['runs'])} for v in votes.values() if len(v['runs']) >= min_runs]
    disputed = [{**v['records'][0], 'agreeing_providers': sorted(v['runs'])} for v in votes.values() if len(v['runs']) < min_runs]
    return gz, agreed, disputed


DIR = {'N': 0, 'NE': 45, 'E': 90, 'SE': 135, 'S': 180, 'SW': 225, 'W': 270, 'NW': 315}


def geometry(town):
    from pyproj import Transformer
    BACK = Transformer.from_crs(26986, 4326, always_xy=True); ll = lambda x, y: [round(v, 8) for v in BACK.transform(x, y)]
    gz, agreed, disputed = consensus(town); turns, ways, unresolved = [], [], []
    def resolve(name):
        if not name: return None
        toks = H.norm_tokens(name); c, n, how = gz.resolve(toks); return c if c and n >= len(toks) - 1 else None
    for r in agreed:
        prov = {'schedule': r['schedule'], 'source_text': r['source_text'], 'enacted': r['enacted'], 'time_conditions': r['time_conditions'], 'agreeing_providers': r['agreeing_providers'], 'status': 'machine_extracted_unreviewed'}
        if r['kind'] == 'no_turn':
            on, at, onto = resolve(r['on_street']), resolve(r['at_street']), resolve(r['onto_street'] or r['at_street'])
            if not (on and at and r['travel_direction'] in DIR): unresolved.append({**r, 'reason': 'turn location needs a human (lot, landmark or unknown street)'}); continue
            pts, why = H.intersections(gz, on, at)
            if not pts: unresolved.append({**r, 'reason': why}); continue
            P = pts[0]; travel = DIR[r['travel_direction']]; app = H.place_on_approach(gz, on, P, travel, setback=20, offset=0)
            if r['maneuver'] == 'through': want = travel; out_street = on
            else: want = (travel + (-90 if r['maneuver'] == 'left' else 90)) % 360; out_street = onto or at
            dep = [l for l in H.legs(gz, out_street, P, L=20)]
            if not app or not dep: unresolved.append({**r, 'reason': 'no legs at intersection'}); continue
            b, line, s, sign = min(dep, key=lambda c: H.angdiff(c[0], want)); q = line.interpolate(s + sign * min(20, s if sign < 0 else line.length - s))
            restriction = {'left': 'no_left_turn', 'right': 'no_right_turn', 'through': 'no_straight_on', 'u_turn': 'no_u_turn'}.get(r['maneuver'], 'no_turn')
            sign_pt = H.place_on_approach(gz, on, P, travel)
            turns.append({'type': 'Feature', 'geometry': {'type': 'LineString', 'coordinates': [ll(*app['approach_point']), ll(P.x, P.y), ll(q.x, q.y)]},
                          'properties': {**prov, 'restriction': restriction, 'from_street': gz.display.get(on, on), 'via': f'{gz.display.get(on, on)} & {gz.display.get(at, at)}',
                                         'to_street': gz.display.get(out_street, out_street), 'travel_deg': travel, 'departure_angle_error_deg': round(H.angdiff(b, want), 1),
                                         'sign_estimate': ll(sign_pt['x'], sign_pt['y']) if sign_pt else None,
                                         'flags': (['departure_leg_does_not_match_maneuver'] if H.angdiff(b, want) > 60 else []) + (['approach_leg_does_not_match_direction'] if app['direction_error_deg'] > 60 else [])}})
        elif r['kind'] == 'one_way':
            on, a, b2 = resolve(r['on_street']), resolve(r['from_street']), resolve(r['to_street'])
            if not (on and a and b2): unresolved.append({**r, 'reason': 'one-way limit is descriptive or a private way; needs a human'}); continue
            pa, wa = H.intersections(gz, on, a); pb, wb = H.intersections(gz, on, b2)
            if not pa or not pb: unresolved.append({**r, 'reason': wa or wb}); continue
            line = min(getattr(gz.geom[on], 'geoms', [gz.geom[on]]), key=lambda l: l.distance(pa[0]) + l.distance(pb[0]))
            from shapely.ops import substring
            sa, sb = line.project(pa[0]), line.project(pb[0]); seg = substring(line, min(sa, sb), max(sa, sb)); coords = list(seg.coords)
            if sa > sb: coords = coords[::-1]
            bear = H.bearing(coords[-1][0] - coords[0][0], coords[-1][1] - coords[0][1]); err = H.angdiff(bear, DIR.get(r['travel_direction'], bear))
            ways.append({'type': 'Feature', 'geometry': {'type': 'LineString', 'coordinates': [ll(x, y) for x, y in coords]},
                         'properties': {**prov, 'street': gz.display.get(on, on), 'from': r['from_street'], 'to': r['to_street'], 'oneway': 'yes', 'direction_check_error_deg': round(err, 1),
                                        'flags': ['stated_direction_disagrees_with_from_to'] if err > 60 else []}})
        else: unresolved.append({**r, 'reason': f"{r['kind']}: geometry not built yet"})
    d = ROOT / 'data' / 'regulations' / town
    (d / 'turn_restrictions.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': turns}), encoding='utf-8')
    (d / 'one_way.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': ways}), encoding='utf-8')
    (d / 'freeform_unresolved.json').write_text(json.dumps({'unresolved': unresolved, 'disputed_between_models': disputed}, indent=1), encoding='utf-8')
    print(f'consensus records {len(agreed)} (disputed {len(disputed)}) -> turn restrictions {len(turns)}, one-way segments {len(ways)}, unresolved {len(unresolved)}', flush=True)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0]); ap.add_argument('command', choices=['extract', 'score', 'geometry', 'all'])
    ap.add_argument('--town', default='wellesley'); ap.add_argument('--providers', default='openai'); ap.add_argument('--runs', type=int, default=3); a = ap.parse_args()
    if a.command in ('extract', 'all'): extract(a.town, a.providers.split(','), a.runs)
    if a.command in ('score', 'all'): score(a.town)
    if a.command in ('geometry', 'all'): geometry(a.town)
