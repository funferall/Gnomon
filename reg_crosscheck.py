"""Cross-check Wellesley's regulation stop signs against what the street imagery found, and build a review queue.

Run after `asset_localization.py run` and `reg_harness.py run --town wellesley` (which links each expected stop sign to the
nearest imagery-derived stop-sign estimate within 25 m). A regulation sign that was not seen only counts as a miss where the
imagery near it has actually been scanned, so misses are split by scan coverage.

Categories (each expected stop sign / each detected one):
  confirmed            triangulated from several views (or placed by a reviewer) near the expected spot
  single_view          seen in one view only: probably right, needs a look
  missed_scanned       not detected although most imagery nearby is scanned  -> review: sign gone? hidden? detector miss?
  partly_scanned       not detected yet, but most imagery nearby is still pending
  not_scanned_yet      no scanned imagery within reach yet                    -> wait for the scan
  detected_not_listed  a multi-view stop sign with no regulation entry nearby -> review: private way, school, missing from the rules?

Writes data/regulations/wellesley/stop_crosscheck.geojson, stop_review_queue.csv, stop_crosscheck_summary.json.
"""
import csv, json, sqlite3
from collections import Counter
from pathlib import Path
import numpy as np
from pyproj import Transformer
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parent; D = ROOT / 'data' / 'regulations' / 'wellesley'; DB = ROOT / 'data' / 'wellesley' / 'inventory.sqlite'
REACH_M = 35            # a scanned image this close to an expected sign could have seen it
MIN_IMAGES = 3          # ...and at least this many of them
TO = Transformer.from_crs(4326, 26986, always_xy=True)
SV = 'https://www.google.com/maps/@?api=1&map_action=pano&viewpoint={lat:.6f},{lon:.6f}'
WB = 'http://localhost:8001/#obs={}'


def run():
    regs = [f for f in json.loads((D / 'regulatory_signs.geojson').read_text(encoding='utf-8'))['features'] if f['properties']['kind'] == 'stop']
    c = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    img = c.execute("select lon,lat,status from images where lon is not null").fetchall()
    scanned = np.array([TO.transform(lo, la) for lo, la, s in img if s == 'scanned']); pending = np.array([TO.transform(lo, la) for lo, la, s in img if s == 'pending'])
    ts, tp = cKDTree(scanned), cKDTree(pending) if len(pending) else None
    first_obs = dict(c.execute("select asset_estimate_id, min(observation_id) from asset_estimate_evidence group by 1").fetchall())
    feats, rows = [], []
    for f in regs:
        p = f['properties']; lon, lat = f['geometry']['coordinates']; x, y = TO.transform(lon, lat)
        ns = len(ts.query_ball_point([x, y], REACH_M)); npn = len(tp.query_ball_point([x, y], REACH_M)) if tp else 0
        ev = p.get('evidence')
        if p.get('method') != 'deterministic_approach_offset': cat = 'no_direction'                 # placed at the intersection only: not checked
        elif ev in ('imagery_triangulated', 'human_placed'): cat = 'confirmed'
        elif ev == 'imagery_single_view': cat = 'single_view'
        elif ns >= MIN_IMAGES and ns >= npn: cat = 'missed_scanned'    # most nearby imagery has been looked at
        elif ns: cat = 'partly_scanned'                               # the unscanned images may be the ones facing it
        else: cat = 'not_scanned_yet'
        q = {'category': cat, 'source': 'regulation', 'id': p['id'], 'on_street': p['on_street'], 'at_street': p['at_street'], 'facing': p.get('facing_text'),
             'distance_m': p.get('evidence_distance_m'), 'scanned_images_nearby': ns, 'pending_images_nearby': npn,
             'street_view': SV.format(lat=lat, lon=lon), 'workbench': WB.format(first_obs[p['evidence_id']]) if p.get('evidence_id') in first_obs else ''}
        feats.append({'type': 'Feature', 'geometry': f['geometry'], 'properties': q}); rows.append(q)
    for f in json.loads((D / 'detected_not_in_regulations.geojson').read_text(encoding='utf-8'))['features']:
        p = f['properties']; lon, lat = f['geometry']['coordinates']
        q = {'category': 'detected_not_listed', 'source': p.get('source'), 'id': p.get('id'), 'on_street': '', 'at_street': '', 'facing': '', 'distance_m': None,
             'scanned_images_nearby': p.get('n_observations'), 'pending_images_nearby': None, 'street_view': SV.format(lat=lat, lon=lon),
             'workbench': WB.format(first_obs[p['id']]) if p.get('id') in first_obs else ''}
        feats.append({'type': 'Feature', 'geometry': f['geometry'], 'properties': q}); rows.append(q)
    (D / 'stop_crosscheck.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': feats}), encoding='utf-8')
    order = {'missed_scanned': 0, 'detected_not_listed': 1, 'single_view': 2}
    queue = sorted([r for r in rows if r['category'] in order], key=lambda r: (order[r['category']], r['on_street'], r['at_street']))
    with open(D / 'stop_review_queue.csv', 'w', newline='', encoding='utf-8') as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(queue)
    n = Counter(r['category'] for r in rows); checked = n['confirmed'] + n['single_view'] + n['missed_scanned']
    s = {'expected_stop_signs': len(regs), 'categories': dict(n), 'checkable_now': checked,
         'confirmed_rate_where_scanned': round((n['confirmed'] + n['single_view']) / checked, 3) if checked else None,
         'review_queue': len(queue), 'images_scanned': len(scanned), 'images_pending': len(pending), 'reach_m': REACH_M, 'min_images': MIN_IMAGES}
    (D / 'stop_crosscheck_summary.json').write_text(json.dumps(s, indent=1), encoding='utf-8'); print(json.dumps(s, indent=1))


if __name__ == '__main__': run()
