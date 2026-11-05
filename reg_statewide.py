"""Statewide layers for the regulations map: town outlines with search/mapping status, and the stop-sign points.

Writes data/regulations/statewide_towns.geojson (simplified outlines, lon/lat) with each town's registry status, document,
and mapped sign counts. The sign layer itself (statewide_stop_signs.geojson) is rebuilt by reg_aiparse/reg_multitown.
"""
import json
from collections import Counter
from pathlib import Path
import geopandas as gpd

ROOT = Path(__file__).resolve().parent; REG = ROOT / 'data' / 'regulations' / 'registry'


def run():
    reg = {t['slug']: t for t in json.loads((REG / 'towns.json').read_text(encoding='utf-8'))['towns']}
    signs = json.loads((ROOT / 'data' / 'regulations' / 'statewide_stop_signs.geojson').read_text(encoding='utf-8'))['features']
    n = Counter(f['properties']['town'] for f in signs); nd = Counter(f['properties']['town'] for f in signs if f['properties'].get('method') == 'deterministic_approach_offset')
    t = gpd.read_file('zip://' + str(ROOT / 'data/towns.zip')).to_crs(26986)
    t = t[~t.NAME.str.contains('not defined') & (t.NAME != 'Boston')].copy()
    t['name'] = t.NAME.str.replace(r'\s+(Town|City)$', '', regex=True)
    t['geometry'] = t.geometry.simplify(60); t = t.to_crs(4326)
    feats = []
    for _, r in t.iterrows():
        slug = next((s for s, x in reg.items() if x['name'] == r['name']), None)
        d = json.loads((REG / 'towns' / f'{slug}.json').read_text(encoding='utf-8')) if slug and (REG / 'towns' / f'{slug}.json').exists() else {}
        status = 'mapped' if n.get(slug) else d.get('status', 'queued')
        feats.append({'type': 'Feature', 'geometry': r.geometry.__geo_interface__, 'properties': {
            'slug': slug, 'name': r['name'], 'county': reg.get(slug, {}).get('county'), 'status': status, 'search_status': d.get('status'),
            'signs': n.get(slug, 0), 'with_direction': nd.get(slug, 0), 'document': (d.get('document') or {}).get('url'),
            'document_title': (d.get('document') or {}).get('title'), 'notes': (d.get('notes') or '')[:300]}})
    out = ROOT / 'data' / 'regulations' / 'statewide_towns.geojson'; out.write_text(json.dumps({'type': 'FeatureCollection', 'features': feats}), encoding='utf-8')
    c = Counter(f['properties']['status'] for f in feats)
    (ROOT / 'data' / 'regulations' / 'statewide_summary.json').write_text(json.dumps({
        'municipalities': len(feats), 'towns_mapped': sum(1 for f in feats if f['properties']['signs']), 'stop_signs': len(signs),
        'with_direction_pct': round(100 * sum(nd.values()) / max(1, len(signs))), 'searched': sum(1 for f in feats if f['properties']['search_status'])}), encoding='utf-8')
    print(f'statewide_towns.geojson: {len(feats)} towns {dict(c)}; {len(signs)} signs', flush=True)


if __name__ == '__main__': run()
