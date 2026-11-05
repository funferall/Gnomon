"""Experiment: AI placement of regulation signs on aerial imagery with gpt-6-luna (see REGULATIONS_PLAN.md, stage 5).
Not used for the published layers: the self-calibrated rule placed signs more accurately (4.4 m vs 5.3 m median).

For each expected stop sign that imagery also triangulated, every model gets one annotated MassGIS 2025 aerial crop
(north up, ~0.11 m/px): both centerlines, the stopping traffic's direction, the deterministic first guess and pixel
gridlines. It returns a pixel; code converts it to coordinates and applies gates (within 35 m of the intersection,
right-hand side of the approach). The triangulated position is the reference and is never shown to the model.
Reference caveat: imagery-derived positions carry ~2 m absolute georegistration error, so errors under ~2 m are noise.
"""
import argparse, io, json, math, statistics, concurrent.futures as cf
from pathlib import Path
import numpy as np, requests
from PIL import Image, ImageDraw, ImageFont
from pyproj import Transformer
import llm_providers as llm, reg_harness as H

ROOT = Path(__file__).resolve().parent
PROMPT_VERSION = 'aerial-place-v2'  # v2: arrow follows the approach leg
TILE = 'https://tiles.arcgis.com/tiles/hGdibHYSPO59RG1h/arcgis/rest/services/Massachusetts_Aerial_Imagery_2025/MapServer/tile/{z}/{y}/{x}'
Z, SIZE = 20, 640
TO, BACK = Transformer.from_crs(4326, 26986, always_xy=True), Transformer.from_crs(26986, 4326, always_xy=True)
SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['x', 'y', 'confidence', 'stop_line_visible', 'evidence'],
          'properties': {'x': {'type': 'number'}, 'y': {'type': 'number'}, 'confidence': {'type': 'number'}, 'stop_line_visible': {'type': 'boolean'}, 'evidence': {'type': 'string'}}}
SYSTEM = 'You locate traffic-sign posts on north-up aerial photographs for a municipal GIS team. Answer with pixel coordinates read from the gridlines.'
_tiles = {}


def gpx(lon, lat):  # global Web Mercator pixel at zoom Z
    n = 256 * 2 ** Z; s = math.sin(math.radians(lat))
    return (lon + 180) / 360 * n, (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * n


def lonlat(px, py):
    n = 256 * 2 ** Z; lon = px / n * 360 - 180; lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * py / n)))); return lon, lat


def tile(x, y):
    if (x, y) not in _tiles:
        r = requests.get(TILE.format(z=Z, x=x, y=y), timeout=60, headers={'User-Agent': 'Gnomon-regulations/0.1'}); r.raise_for_status()
        _tiles[(x, y)] = Image.open(io.BytesIO(r.content)).convert('RGB')
    return _tiles[(x, y)]


def aerial(center_lon, center_lat):
    cx, cy = gpx(center_lon, center_lat); x0, y0 = int(cx - SIZE / 2), int(cy - SIZE / 2); im = Image.new('RGB', (SIZE, SIZE))
    for tx in range(x0 // 256, (x0 + SIZE) // 256 + 1):
        for ty in range(y0 // 256, (y0 + SIZE) // 256 + 1): im.paste(tile(tx, ty), (tx * 256 - x0, ty * 256 - y0))
    to_px = lambda x, y: (lambda g: (g[0] - x0, g[1] - y0))(gpx(*BACK.transform(x, y)))
    from_px = lambda u, v: TO.transform(*lonlat(u + x0, v + y0))
    m_per_px = 156543.03392 * math.cos(math.radians(center_lat)) / 2 ** Z
    return im, to_px, from_px, m_per_px


def annotate(im, to_px, gz, s, P):
    d = ImageDraw.Draw(im, 'RGBA'); font = ImageFont.load_default()
    for street, col in ((s['on_street'], (40, 140, 255, 200)), (s['at_street'], (255, 150, 30, 200))):
        g = gz.geom[street]
        for line in getattr(g, 'geoms', [g]): d.line([to_px(x, y) for x, y in line.coords], fill=col, width=3)
    # arrow along the actual approach leg (not the compass word), ending 6 m before the intersection
    leg = math.radians(s.get('approach_leg_bearing', (s['travel_deg'] + 180) % 360)); lx, ly = math.sin(leg), math.cos(leg)
    a = to_px(P.x + lx * 34, P.y + ly * 34); b = to_px(P.x + lx * 6, P.y + ly * 6)
    d.line([a, b], fill=(255, 235, 0, 255), width=5); ang = math.atan2(b[1] - a[1], b[0] - a[0])
    d.polygon([b, (b[0] - 14 * math.cos(ang - .45), b[1] - 14 * math.sin(ang - .45)), (b[0] - 14 * math.cos(ang + .45), b[1] - 14 * math.sin(ang + .45))], fill=(255, 235, 0, 255))
    gx, gy = to_px(s['x'], s['y']); d.ellipse([gx - 9, gy - 9, gx + 9, gy + 9], outline=(255, 255, 255, 255), width=3); d.text((gx + 11, gy - 6), 'G', fill=(255, 255, 255, 255), font=font)
    for k in range(0, SIZE + 1, 64):   # gridlines with labels for reading coordinates
        d.line([(k, 0), (k, SIZE)], fill=(255, 255, 255, 60), width=1); d.line([(0, k), (SIZE, k)], fill=(255, 255, 255, 60), width=1)
        d.text((k + 2, 2), str(k), fill=(255, 255, 255, 230), font=font); d.text((2, k + 2), str(k), fill=(255, 255, 255, 230), font=font)
    return im


def prompt(s, gz, m_per_px):
    on, at = gz.display.get(s['on_street'], s['on_street']), gz.display.get(s['at_street'], s['at_street'])
    dirs = {0: 'north', 45: 'northeast', 90: 'east', 135: 'southeast', 180: 'south', 225: 'southwest', 270: 'west', 315: 'northwest'}
    return (f'North-up aerial photo, {SIZE}x{SIZE} px, about {m_per_px:.2f} m per pixel; faint gridlines every 64 px are labelled along the top and left edges.\n'
            f'Blue line: centerline of {on}. Orange line: centerline of {at}. Yellow arrow: {dirs.get(int(s["travel_deg"]), "the")}bound traffic on {on} approaching {at}.\n'
            f'The town traffic regulations require a STOP sign on {on} at {at} facing that traffic ("{s["source"]["raw"]}").\n'
            'Stop signs normally stand on the right-hand side of the approaching traffic, at the curb or sidewalk edge, near the painted stop line or a few metres before the intersection.\n'
            'The white ring marked G is an automatic first guess from the centerlines; it may be off.\n'
            'Using the curb lines, sidewalks, driveways, any painted stop line, and any visible post or its shadow, return the pixel (x, y) where the sign post most likely stands, '
            'a confidence from 0 to 1, whether a stop line is visible, and one sentence on the evidence you used.')


def gates(s, P, X, Y):
    if math.hypot(X - P.x, Y - P.y) > 35: return 'more_than_35m_from_intersection'
    leg = math.radians(s.get('approach_leg_bearing', (s['travel_deg'] + 180) % 360)); tx, ty = -math.sin(leg), -math.cos(leg)   # travel = toward P
    if (X - P.x) * ty - (Y - P.y) * tx < -2: return 'left_of_approaching_traffic'
    return None


def run(town, providers, limit):
    gz, recs = H.parse(town); gz, signs, _ = H.geocode(town, gz, recs); signs, _ = H.match(town, signs)
    test = [s for s in signs if s.get('evidence') == 'imagery_triangulated'][:limit or None]
    out = ROOT / 'data' / 'regulations' / town / 'ai' / 'place'; out.mkdir(parents=True, exist_ok=True); rows = []
    from shapely.geometry import Point
    jobs = []
    for s in test:
        P = Point(*TO.transform(*s['intersection'])); im, to_px, from_px, mpp = aerial(*s['intersection']); im = annotate(im, to_px, gz, s, P)
        buf = io.BytesIO(); im.save(buf, 'PNG'); png = buf.getvalue(); (out / (s['id'].replace(':', '_') + f"_{int(s['travel_deg'])}.png")).write_bytes(png)
        ref = s['evidence_xy']; base_err = math.hypot(s['x'] - ref[0], s['y'] - ref[1])
        for p in providers: jobs.append((s, P, from_px, mpp, png, ref, base_err, p))
    def work(j):
        s, P, from_px, mpp, png, ref, base_err, p = j
        r = llm.call(p, SYSTEM, prompt(s, gz, mpp), SCHEMA, images=[(png, 'image/png')], max_tokens=32000, schema_name='sign_position')
        row = {'sign': s['id'], 'travel_deg': s['travel_deg'], 'provider': p, 'model': r['model'], 'baseline_error_m': round(base_err, 2), 'cost_usd': r.get('cost_usd'), 'latency_s': r['latency_s'], 'error': r.get('error')}
        if 'data' in r:
            X, Y = from_px(r['data']['x'], r['data']['y']); g = gates(s, P, X, Y)
            row.update(ai_error_m=round(math.hypot(X - ref[0], Y - ref[1]), 2), gate=g, confidence=r['data']['confidence'], stop_line_visible=r['data']['stop_line_visible'], evidence=r['data']['evidence'])
            row['final_error_m'] = row['baseline_error_m'] if g else row['ai_error_m']
        return row
    with cf.ThreadPoolExecutor(6) as pool: rows = list(pool.map(work, jobs))
    (out / 'results.json').write_text(json.dumps({'prompt_version': PROMPT_VERSION, 'rows': rows}, indent=1), encoding='utf-8')
    base = [r['baseline_error_m'] for r in rows if r['provider'] == providers[0]]
    print(f"\n{len(test)} stop signs with a triangulated imagery reference. Deterministic baseline: median {statistics.median(base):.1f} m, mean {statistics.mean(base):.1f} m")
    print(f"{'provider':10} {'model':18} {'ok':>4} {'AI median':>9} {'AI mean':>8} {'after gates':>11} {'better than base':>16} {'gated':>6} {'$ total':>8} {'sec/call':>8}")
    for p in providers:
        rs = [r for r in rows if r['provider'] == p]; ok = [r for r in rs if 'ai_error_m' in r]
        if not ok: print(p, 'FAILED', rs[0].get('error')); continue
        print(f"{p:10} {ok[0]['model']:18} {len(ok):>4} {statistics.median(r['ai_error_m'] for r in ok):9.1f} {statistics.mean(r['ai_error_m'] for r in ok):8.1f} "
              f"{statistics.median(r['final_error_m'] for r in ok):11.1f} {sum(r['ai_error_m'] < r['baseline_error_m'] for r in ok):>9}/{len(ok):<6} {sum(1 for r in ok if r['gate']):>6} "
              f"{sum(r['cost_usd'] or 0 for r in rs):8.4f} {statistics.mean(r['latency_s'] for r in rs):8.1f}")
    return rows


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0]); ap.add_argument('--town', default='wellesley'); ap.add_argument('--providers', default='openai'); ap.add_argument('--limit', type=int, default=0)
    a = ap.parse_args(); run(a.town, a.providers.split(','), a.limit)
