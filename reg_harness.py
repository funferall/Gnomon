"""Traffic Rules and Orders -> GIS: deterministic harness (see REGULATIONS_PLAN.md).

acquire  download the town's regulations document, hash it
parse    pdftotext -raw -> schedules -> rows; table schedules (stop, yield, turn on red) are split into
         on / at / direction by matching the town street gazetteer (TIGER centerlines), not by column position
geocode  street-pair intersection from centerlines; legs; sign placed on the approach leg for the stated
         travel direction, set back from the intersection and offset to the right of travel
match    compare expected signs to imagery-derived estimates and human-placed assets
export   GeoJSON layers + unresolved rows with reasons

Free-form schedules (turn prohibitions, one-way, U-turn) are handled by reg_ai.py, which reuses the validators
and geometry here. Nothing here calls a model.
"""
import argparse, datetime as dt, hashlib, json, math, os, re, shutil, subprocess, sqlite3
from collections import defaultdict
from pathlib import Path
import numpy as np, requests

ROOT = Path(__file__).resolve().parent
COUNTY_FIPS = {'Barnstable': '25001', 'Berkshire': '25003', 'Bristol': '25005', 'Dukes': '25007', 'Essex': '25009', 'Franklin': '25011', 'Hampden': '25013', 'Hampshire': '25015', 'Middlesex': '25017', 'Nantucket': '25019', 'Norfolk': '25021', 'Plymouth': '25023', 'Suffolk': '25025', 'Worcester': '25027'}
TOWNS = {'wellesley': {'name': 'Wellesley', 'county_fips': '25021', 'doc_url': 'https://www.wellesleyma.gov/2000/Traffic-Regulations',
                       'aliases': {'route 9': 'worcester street', 'rte 9': 'worcester street', 'babson rec drive': 'babson recreation center driveway'}}}
VERSION = 'reg-harness-v1'
SCHEDULES = [  # (regex on header line, schedule id, kind)
    (r'SCHEDULE\s+III\s*\(\s*SUB-?SECTION\s*A\s*\)', 'III-A', 'no_turn'),
    (r'SCHEDULE\s+III\b(?!\s*\()', 'III', 'no_u_turn'),
    (r'SCHEDULE\s+II\b', 'II', 'one_way'),
    (r'SCHEDULE\s+IV\b', 'IV', 'stop'),
    (r'SCHEDULE\s+VIII\b', 'VIII', 'yield'),
    (r'SCHEDULE\s+VI\b', 'VI', 'turn_lane'),
    (r'SCHEDULE\s+IX\b', 'IX', 'rtor_permitted'),
    (r'SCHEDULE\s+X\b(?!I)', 'X', 'rtor_prohibited'),
    (r'SCHEDULE\s+(?:I-A|I-B|I|V|VII|XI)\b', None, None),  # parking, heavy vehicles, service zones: out of scope
]
TABLE_KINDS = {'stop', 'yield', 'rtor_permitted', 'rtor_prohibited'}
ABBR = {'st': 'street', 'rd': 'road', 'ave': 'avenue', 'av': 'avenue', 'dr': 'drive', 'ln': 'lane', 'pl': 'place', 'ter': 'terrace',
        'terr': 'terrace', 'cir': 'circle', 'ct': 'court', 'pkwy': 'parkway', 'hwy': 'highway', 'sq': 'square', 'blvd': 'boulevard',
        'rte': 'route', 'rec': 'recreation', 'ext': 'extension', 'pk': 'park', 'hts': 'heights', 'rdg': 'ridge', 'trl': 'trail', 'xing': 'crossing'}
PLACE_TYPES = {'square', 'island', 'circle_place'}
STREET_TYPES = {'street', 'road', 'avenue', 'drive', 'lane', 'place', 'terrace', 'circle', 'court', 'parkway', 'highway', 'square',
                'boulevard', 'way', 'path', 'row', 'park', 'heights', 'extension', 'driveway'} - {'square'}
COMPASS = {'north': 0, 'northeast': 45, 'east': 90, 'southeast': 135, 'south': 180, 'southwest': 225, 'west': 270, 'northwest': 315}
FILLER = {'at', 'intersection', 'with', 'of', 'the', 'n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw', '(', ')'}
DATE = re.compile(r'\(\s*(\d{1,2}/\d{2,4}|n/a)\s*\)', re.I)
SETBACK_M, OFFSET_M = 8.0, 5.5          # along the approach from the intersection centre; right of travel
UNC95 = {'stop': 9.0, 'yield': 9.0, 'rtor_prohibited': 15.0, 'rtor_permitted': 15.0, 'no_turn': 12.0}


def now(): return dt.datetime.now(dt.timezone.utc).isoformat()


def town_cfg(town):
    """Town settings: Wellesley's hand-tuned entry, otherwise built from the swarm registry (name, county, document)."""
    if town in TOWNS: return TOWNS[town]
    reg = ROOT / 'data' / 'regulations' / 'registry'
    t = next(x for x in json.loads((reg / 'towns.json').read_text(encoding='utf-8'))['towns'] if x['slug'] == town)
    d = json.loads((reg / 'towns' / f'{town}.json').read_text(encoding='utf-8')) if (reg / 'towns' / f'{town}.json').exists() else {}
    TOWNS[town] = {'name': t['name'], 'county': t['county'], 'county_fips': COUNTY_FIPS.get(t['county']),
                   'doc_url': (d.get('document') or {}).get('url'), 'aliases': {}}
    return TOWNS[town]
def town_dir(town): d = ROOT / 'data' / 'regulations' / town; d.mkdir(parents=True, exist_ok=True); return d


# ---------------------------------------------------------------- acquire + extract
def acquire(town, refresh=False):
    d = town_dir(town); pdf = d / 'source.pdf'
    if refresh or not pdf.exists():
        r = requests.get(TOWNS[town]['doc_url'], headers={'User-Agent': 'Gnomon-regulations/0.1'}, timeout=120); r.raise_for_status()
        if not r.content.startswith(b'%PDF'): raise ValueError('Expected a PDF from ' + TOWNS[town]['doc_url'])
        pdf.write_bytes(r.content)
    meta = {'town': town, 'url': TOWNS[town]['doc_url'], 'sha256': hashlib.sha256(pdf.read_bytes()).hexdigest(), 'bytes': pdf.stat().st_size, 'checked_at': now()}
    (d / 'source.json').write_text(json.dumps(meta, indent=1), encoding='utf-8'); return pdf, meta


def pdftotext():
    p = shutil.which('pdftotext') or r'C:\Program Files\Git\mingw64\bin\pdftotext.exe'
    if not Path(p).exists() and not shutil.which(p): raise RuntimeError('pdftotext not found (install poppler or Git for Windows)')
    return p


def pages(pdf):
    out = subprocess.run([pdftotext(), '-raw', '-enc', 'UTF-8', str(pdf), '-'], capture_output=True, check=True).stdout.decode('utf-8', 'replace')
    return out.split('\f')


def schedule_blocks(page_texts):
    """Yield (schedule_id, kind, page_no, [lines]) for schedule tables; table-of-contents lines are skipped."""
    blocks = []; cur = None
    for pno, text in enumerate(page_texts, 1):
        for line in text.splitlines():
            s = line.strip()
            if not s or re.fullmatch(r'-\s*\d+\s*-', s): continue
            if '....' in s: continue  # table of contents
            hit = next(((sid, kind) for rx, sid, kind in SCHEDULES if re.search(rx, s, re.I)), None)
            if hit and re.match(r'SCHEDULE', s, re.I):
                if cur is None or cur[0] != hit[0]: cur = [hit[0], hit[1], pno, []]; blocks.append(cur)
                continue
            if cur is not None: cur[3].append((pno, s))
    return [b for b in blocks if b[0]]


# ---------------------------------------------------------------- gazetteer
def norm_tokens(s):
    toks = re.findall(r"[a-z0-9']+|/", s.lower().replace('.', ' '))
    return [ABBR.get(t, t) for t in toks]


class Gazetteer:
    def __init__(self, town):
        import geopandas as gpd
        cfg = town_cfg(town)
        towns = gpd.read_file('zip://' + str(ROOT / 'data/towns.zip')).to_crs(26986)
        self.boundary = towns[towns.NAME.str.replace(r'\s+(Town|City)$', '', regex=True) == cfg['name']].geometry.iloc[0]   # Census: 'Amherst Town'
        mg = ROOT / 'data' / 'massgis_roads.parquet'
        if mg.exists() and os.environ.get('GNOMON_ROADS') != 'tiger':   # MassGIS Roads (statewide, full street names, municipality on each side): preferred
            roads = gpd.read_parquet(mg); town = cfg['name'].upper()
            near = roads.sindex.query(self.boundary.buffer(300), predicate='intersects')
            roads = roads.iloc[near]; roads = roads[roads.ST_NAME_ST.notna()].rename(columns={'ST_NAME_ST': 'FULLNAME'})
            self.source = 'MassGIS Roads ' + str(roads.DATE_UPD.max())[:10]
        else:
            roads = gpd.read_file('zip://' + str(ROOT / f"data/tiger_roads/tl_2024_{cfg['county_fips']}_roads.zip")).to_crs(26986)
            roads = roads[roads.FULLNAME.notna() & roads.intersects(self.boundary.buffer(300))]; self.source = 'Census TIGER 2024'
        self.display_case = True
        from shapely.ops import linemerge, unary_union
        groups = defaultdict(list)
        for name, geom in zip(roads.FULLNAME, roads.geometry): groups[' '.join(norm_tokens(name))].append(geom)
        def merge(v):
            u = unary_union(v); return linemerge(u) if u.geom_type == 'MultiLineString' else u
        self.geom = {k: merge(v) for k, v in groups.items()}
        if 'MassGIS' in self.source and os.environ.get('GNOMON_ROADS') != 'massgis':
            # Hybrid: MassGIS supplies the names; TIGER supplies geometry where the same street exists there.
            # On Wellesley, TIGER intersections sat closer to real signs (MassDOT survey: 4.8 vs 6.5 m median).
            fips = cfg.get('county_fips') or COUNTY_FIPS.get(cfg.get('county', ''))
            zp = ROOT / f'data/tiger_roads/tl_2024_{fips}_roads.zip'
            if fips and zp.exists():
                tg = gpd.read_file('zip://' + str(zp)).to_crs(26986); tg = tg[tg.FULLNAME.notna() & tg.intersects(self.boundary.buffer(300))]
                tgroups = defaultdict(list)
                for name, geom in zip(tg.FULLNAME, tg.geometry): tgroups[' '.join(norm_tokens(name))].append(geom)
                swapped = 0; self.alt = dict(self.geom)   # keep MassGIS geometry for pairs TIGER cannot resolve
                for k in self.geom:
                    if k in tgroups: self.geom[k] = merge(tgroups[k]); swapped += 1
                self.source += f' names + TIGER 2024 geometry for {swapped}/{len(self.geom)} streets'
        self.display = {' '.join(norm_tokens(n)): n.title() for n in roads.FULLNAME}
        self.aliases = {' '.join(norm_tokens(k)): v for k, v in cfg.get('aliases', {}).items()}
        base = defaultdict(set)
        for k in self.geom:
            t = k.split()
            if len(t) > 1 and t[-1] in STREET_TYPES: base[' '.join(t[:-1])].add(k)
        self.base = {b: next(iter(v)) for b, v in base.items() if len(v) == 1}   # unique base names only
        self.max_len = max(len(k.split()) for k in self.geom)

    def resolve(self, tokens):
        """Longest gazetteer street at the start of tokens -> (canonical, n_tokens, how)."""
        for n in range(min(len(tokens), self.max_len + 1), 0, -1):
            k = ' '.join(tokens[:n])
            if k in self.aliases and self.aliases[k] in self.geom: return self.aliases[k], n, 'alias'
            if k in self.geom: return k, n, 'exact'
        for n in range(min(len(tokens), self.max_len), 0, -1):
            k = ' '.join(tokens[:n]); nxt = tokens[n] if n < len(tokens) else None
            if nxt in PLACE_TYPES: return None, 0, 'place_name_needs_alias'      # e.g. Wellesley Sq.: a place, not a street
            if k in self.base:
                if nxt in STREET_TYPES: return self.base[k], n + 1, 'street_type_mismatch'
                return self.base[k], n, 'base_name'
        return None, 0, None


# ---------------------------------------------------------------- table schedule parsing
HEADER = re.compile(r'LOCAT(ED|IONS?)\s+ON|SO AS TO FACE|DIRECTION OF TRAVEL', re.I)


def logical_rows(lines):
    rows, buf, start, seen_header = [], [], None, False
    for pno, s in lines:
        if HEADER.search(s) and not DATE.search(s): seen_header = True; continue
        if not seen_header or re.search(r'AT THE FOLLOWING', s, re.I): continue
        if re.fullmatch(r'(YIELD SIGNS|STOP SIGNS|A RIGHT TURN ON RED|RIGHT TURN ON RED.*)', s, re.I): continue
        if not buf: start = pno
        buf.append(s)
        if DATE.search(s) and re.search(r'\)\s*$', s): rows.append((start, ' '.join(buf))); buf = []
    if buf: rows.append((start, ' '.join(buf) + '  [no date: row may be incomplete]'))
    return rows


def parse_directions(text):
    """'North and southbound drivers on X' -> [0, 180]; only words before drivers/traffic/on/approaching."""
    words = re.findall(r'[a-z]+', text.lower()); dirs = []
    for w in words:
        if w in ('drivers', 'traffic', 'on', 'approaching', 'towards', 'toward', 'exiting', 'from'): break
        w = {'n': 'north', 's': 'south', 'e': 'east', 'w': 'west', 'ne': 'northeast', 'nw': 'northwest', 'se': 'southeast', 'sw': 'southwest'}.get(w, w)
        m = re.fullmatch(r'(north|south)?(east|west)?(bound|erly|ly)?', w)
        if m and (m.group(1) or m.group(2)): dirs.append(COMPASS[(m.group(1) or '') + (m.group(2) or '')])
    return dirs


def parse_table_row(gz, kind, text):
    enacted = DATE.findall(text); body = DATE.sub(' ', text).replace('[no date: row may be incomplete]', ' ')
    toks = norm_tokens(body); rec = {'kind': kind, 'enacted': enacted, 'flags': []}
    on, n, how = gz.resolve(toks)
    if not on: rec['flags'].append('on_street_not_in_gazetteer'); rec['facing_text'] = body.strip(); return rec
    rec['on_street'] = on; rest = toks[n:]
    if how != 'exact': rec['flags'].append('on_street_' + how)
    at = []
    # Layout "street | direction | cross street" (e.g. Concord): consume direction words before the cross street.
    lead_dirs = []
    while rest and (re.fullmatch(r'(north|south)?(east|west)?(bound|erly)', rest[0]) and re.match(r'(north|south|east|west)', rest[0]) or rest[0] in ('and', 'bound') and lead_dirs):
        if gz.resolve(rest)[2] == 'exact': break        # "Westerly Street" is a street, not a direction
        lead_dirs.append(rest[0]); rest = rest[1:]
    while rest and rest[0] in FILLER: rest = rest[1:]
    while rest:
        a, m, how = gz.resolve(rest)
        if not a: break
        at.append(a); rest = rest[m:]
        if how != 'exact': rec['flags'].append('at_street_' + how)
        if rest and rest[0] == '/': rest = rest[1:]; continue
        break
    if not at: rec['flags'].append('at_street_not_in_gazetteer')
    rec['at_streets'] = at; rec['facing_text'] = ' '.join(lead_dirs + rest)
    rec['directions'] = parse_directions(' '.join(lead_dirs)) if lead_dirs else parse_directions(' '.join(rest))
    if not rec['directions']: rec['flags'].append('no_direction_parsed')
    return rec


def parse(town):
    pdf, meta = acquire(town); gz = Gazetteer(town); recs, skipped = [], []
    for sid, kind, pno, lines in schedule_blocks(pages(pdf)):
        if kind not in TABLE_KINDS: skipped.append({'schedule': sid, 'kind': kind, 'lines': len(lines), 'reason': 'free-form schedule: handled by reg_ai.py'}); continue
        prev = None
        for i, (page, raw) in enumerate(logical_rows(lines)):
            r = parse_table_row(gz, kind, raw)
            body = DATE.sub(' ', raw).strip()
            if prev and 'on_street' not in r and parse_directions(body) and re.match(r'(?i)(north|south|east|west|[ns][ew]?)', body):
                r = {**r, 'on_street': prev['on_street'], 'at_streets': prev.get('at_streets', []), 'directions': parse_directions(body),
                     'facing_text': body, 'flags': ['inherited_street_pair_from_previous_row']}
            if 'on_street' in r: prev = r
            r.update(id=f'{town}:{sid}:{page}:{i}', town=town, schedule=sid, source={'url': meta['url'], 'sha256': meta['sha256'], 'page': page, 'raw': raw})
            recs.append(r)
    (town_dir(town) / 'records.json').write_text(json.dumps({'parsed_at': now(), 'version': VERSION, 'records': recs, 'deferred_schedules': skipped}, indent=1), encoding='utf-8')
    by = defaultdict(lambda: [0, 0])
    for r in recs: by[r['kind']][0] += 1; by[r['kind']][1] += bool(r['flags'])
    print('parsed', {k: f'{n} rows, {f} flagged' for k, (n, f) in by.items()}, '| deferred:', [s['schedule'] for s in skipped], flush=True)
    return gz, recs


# ---------------------------------------------------------------- geometry
def bearing(dx, dy): return math.degrees(math.atan2(dx, dy)) % 360
def angdiff(a, b): return abs((a - b + 180) % 360 - 180)


def intersections(gz, a, b):
    from shapely.ops import nearest_points
    ga, gb = gz.geom.get(a), gz.geom.get(b)
    if ga is None or gb is None: return [], 'street_missing'
    x = ga.intersection(gb); pts = []
    for g in getattr(x, 'geoms', [x]):
        if g.is_empty: continue
        pts.append(g.centroid if g.geom_type != 'Point' else g)
    if pts:  # merge points closer than 15 m (dual carriageways, digitising noise)
        merged = []
        for p in pts:
            if not any(p.distance(q) < 15 for q in merged): merged.append(p)
        return merged, None
    d = ga.distance(gb)
    if d < 25:
        from shapely.geometry import Point
        p, q = nearest_points(ga, gb); return [Point((p.x + q.x) / 2, (p.y + q.y) / 2)], f'near_miss_{d:.0f}m'
    return [], f'streets_do_not_meet_{d:.0f}m'


def legs(gz, street, P, L=15.0):
    """Directions leaving intersection P along a street: [(bearing, line, s_at_P, sign)]."""
    out = []; g = gz.geom[street]
    for line in getattr(g, 'geoms', [g]):
        if line.distance(P) > 2: continue
        s = line.project(P)
        for sign in (-1, 1):
            t = s + sign * min(L, (s if sign < 0 else line.length - s))
            if abs(t - s) < 3: continue
            q = line.interpolate(t); out.append((bearing(q.x - P.x, q.y - P.y), line, s, sign))
    return out


def place_on_approach(gz, street, P, travel_deg, setback=SETBACK_M, offset=OFFSET_M):
    """Sign for traffic heading `travel_deg` toward P along `street`: approach leg points the opposite way."""
    want = (travel_deg + 180) % 360; cands = legs(gz, street, P)
    if not cands: return None
    b, line, s, sign = min(cands, key=lambda c: angdiff(c[0], want)); err = angdiff(b, want)
    t = s + sign * min(setback, (s if sign < 0 else line.length - s)); q = line.interpolate(t)
    q2 = line.interpolate(max(0, min(line.length, t - sign * 1.0)))     # 1 m closer to P: direction of travel
    tx, ty = q2.x - q.x, q2.y - q.y; n = math.hypot(tx, ty) or 1; tx, ty = tx / n, ty / n
    x, y = q.x + ty * offset, q.y - tx * offset                            # right of travel
    return {'x': x, 'y': y, 'leg_bearing': b, 'direction_error_deg': err, 'approach_point': [q.x, q.y], 'travel_unit': [tx, ty]}


QUAL = re.compile(r'(north|south|east|west|northeast|northwest|southeast|southwest|n|s|e|w|ne|nw|se|sw)(?:erly|ern)?\s+intersection(?=\W)', re.I)
QUAL = re.compile(r'(?<![A-Za-z])' + QUAL.pattern.lstrip('\x08'), re.I)   # word-start guard; strips a stray backspace if present
QUAL_DIR = {'n': 'north', 's': 'south', 'e': 'east', 'w': 'west', 'ne': 'northeast', 'nw': 'northwest', 'se': 'southeast', 'sw': 'southwest'}


def pick_by_qualifier(cand, raw):
    """'SE intersection with Abbott Rd.' -> the candidate intersection farthest toward the south-east."""
    m = QUAL.search(raw or '')
    if not m or len(cand) < 2: return cand, None
    d = math.radians(COMPASS[QUAL_DIR.get(m.group(1).lower(), m.group(1).lower())]); ux, uy = math.sin(d), math.cos(d)
    cx = sum(p.x for p, _ in cand) / len(cand); cy = sum(p.y for p, _ in cand) / len(cand)
    best = max(cand, key=lambda c: (c[0].x - cx) * ux + (c[0].y - cy) * uy); return [best], m.group(0)


class AltGeometry:
    """View of a gazetteer that uses its MassGIS geometry (hybrid fallback)."""
    def __init__(self, gz): self.geom, self.display = gz.alt, gz.display


def geocode(town, gz=None, recs=None, setback=SETBACK_M, offset=OFFSET_M):
    from pyproj import Transformer
    BACK = Transformer.from_crs(26986, 4326, always_xy=True)
    if gz is None: gz, recs = parse(town)
    signs, unresolved = [], []
    for r in recs:
        if 'on_street' not in r or not r.get('at_streets'): unresolved.append({**r, 'reason': r['flags'][0] if r['flags'] else 'unparsed'}); continue
        cand, why, G = [], None, gz
        for at in r['at_streets']:
            pts, why = intersections(gz, r['on_street'], at)
            cand += [(p, at) for p in pts]
        if not cand and getattr(gz, 'alt', None):   # hybrid fallback: MassGIS geometry for this pair
            G = AltGeometry(gz)
            for at in r['at_streets']:
                pts, why = intersections(G, r['on_street'], at); cand += [(p, at) for p in pts]
            if cand: r = {**r, 'flags': r['flags'] + ['massgis_geometry_fallback']}
        if not cand: unresolved.append({**r, 'reason': why or 'no_intersection'}); continue
        cand, qual = pick_by_qualifier(cand, r['source']['raw'])
        spread = max((a[0].distance(b[0]) for a in cand for b in cand), default=0)
        for travel in (r.get('directions') or [None]):
            best = None
            for P, at in cand:
                if travel is None: continue
                pl = place_on_approach(G, r['on_street'], P, travel, setback, offset)
                if pl and (best is None or pl['direction_error_deg'] < best[0]['direction_error_deg']): best = (pl, P, at)
            if best is None:
                P, at = cand[0]; lon, lat = BACK.transform(P.x, P.y)
                signs.append({**r, 'at_street': at, 'travel_deg': travel, 'lon': lon, 'lat': lat, 'x': P.x, 'y': P.y, 'method': 'intersection_centre_only',
                              'uncertainty95_m': 25.0, 'flags': r['flags'] + ['no_direction_used'], 'n_candidate_intersections': len(cand)}); continue
            pl, P, at = best; lon, lat = BACK.transform(pl['x'], pl['y']); ilon, ilat = BACK.transform(P.x, P.y)
            flags = list(r['flags'])
            if pl['direction_error_deg'] > 60: flags.append(f"direction_mismatch_{pl['direction_error_deg']:.0f}deg")
            if qual: flags.append('intersection_chosen_by_qualifier:' + qual.lower())
            elif spread > 30: flags.append(f'ambiguous_{len(cand)}_intersections_{spread:.0f}m_apart')
            if why and why.startswith('near_miss'): flags.append(why)
            signs.append({**r, 'at_street': at, 'travel_deg': travel, 'facing_deg': (travel + 180) % 360, 'lon': lon, 'lat': lat, 'x': pl['x'], 'y': pl['y'],
                          'intersection': [ilon, ilat], 'approach_leg_bearing': pl['leg_bearing'], 'direction_error_deg': round(pl['direction_error_deg'], 1),
                          'method': 'deterministic_approach_offset', 'uncertainty95_m': UNC95.get(r['kind'], 12.0) if not (spread > 30 and not qual) else max(UNC95.get(r['kind'], 12.0), spread), 'flags': flags})
    return gz, signs, unresolved


# ---------------------------------------------------------------- match against imagery-derived and human evidence
def match(town, signs):
    db = ROOT / 'data' / 'wellesley' / 'inventory.sqlite'
    if not db.exists(): return signs, []
    from pyproj import Transformer
    TO = Transformer.from_crs(4326, 26986, always_xy=True); c = sqlite3.connect(db)
    est = []
    try:
        for aid, cls, state, x, y, u, n in c.execute("select id,class,state,x,y,uncertainty95_m,n_observations from asset_estimates where class in ('stop sign','traffic sign')"):
            est.append(('estimate', aid, cls, state, x, y, n))
    except sqlite3.OperationalError: pass
    for aid, cls, lon, lat in c.execute("select id,class,lon,lat from assets where review='human_placed'"):
        x, y = TO.transform(lon, lat); est.append(('human', aid, cls, 'human_placed', x, y, 1))
    if not est: return signs, []
    E = np.array([[e[4], e[5]] for e in est]); from scipy.spatial import cKDTree; tree = cKDTree(E); used = set()
    for s in signs:
        if s['kind'] != 'stop' or s.get('method') != 'deterministic_approach_offset': continue
        idx = [i for i in tree.query_ball_point([s['x'], s['y']], 25) if est[i][2] == 'stop sign']
        if not idx: s['evidence'] = 'not_detected_in_imagery'; continue
        i = min(idx, key=lambda i: (est[i][0] != 'human', math.hypot(E[i][0] - s['x'], E[i][1] - s['y'])))
        e = est[i]; d = math.hypot(E[i][0] - s['x'], E[i][1] - s['y']); used.add(i)
        s['evidence'] = 'human_placed' if e[0] == 'human' else ('imagery_triangulated' if e[3] == 'multi_view_estimate' else 'imagery_single_view')
        s['evidence_id'] = e[1]; s['evidence_distance_m'] = round(d, 1); s['evidence_xy'] = [float(E[i][0]), float(E[i][1])]
    extra = [{'source': e[0], 'id': e[1], 'state': e[3], 'x': e[4], 'y': e[5], 'n_observations': e[6]} for i, e in enumerate(est)
             if e[2] == 'stop sign' and i not in used and e[3] in ('multi_view_estimate', 'human_placed')]
    return signs, extra


def calibrate_offsets(signs):
    """Residuals of expected vs triangulated/human-placed stop signs in the approach-leg frame (along travel, right of travel)."""
    along, right = [], []
    for s in signs:
        if s.get('evidence') not in ('imagery_triangulated', 'human_placed'): continue
        ax, ay = s['evidence_xy'][0] - s['x'], s['evidence_xy'][1] - s['y']
        leg = math.radians(s['approach_leg_bearing']); tx, ty = -math.sin(leg), -math.cos(leg)   # travel = toward the intersection
        along.append(ax * tx + ay * ty); right.append(ax * ty - ay * tx)
    if len(along) < 10: return None
    return {'n': len(along), 'along_travel_median_m': float(np.median(along)), 'right_of_travel_median_m': float(np.median(right)),
            'radial_median_m': float(np.median(np.hypot(along, right))), 'radial_p90_m': float(np.percentile(np.hypot(along, right), 90))}


# ---------------------------------------------------------------- export
def export(town, signs, unresolved, extra):
    from pyproj import Transformer
    BACK = Transformer.from_crs(26986, 4326, always_xy=True); d = town_dir(town); feats = []
    keep = ['id', 'town', 'schedule', 'kind', 'on_street', 'at_street', 'travel_deg', 'facing_deg', 'facing_text', 'enacted', 'method',
            'uncertainty95_m', 'direction_error_deg', 'flags', 'evidence', 'evidence_id', 'evidence_distance_m', 'calibration', 'source']
    for s in signs:
        p = {k: s.get(k) for k in keep}; p['status'] = 'machine_expected_unreviewed'
        feats.append({'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [round(s['lon'], 8), round(s['lat'], 8)]}, 'properties': p})
    (d / 'regulatory_signs.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': feats}), encoding='utf-8')
    (d / 'unresolved.json').write_text(json.dumps(unresolved, indent=1, default=str), encoding='utf-8')
    ex = [{'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': list(BACK.transform(e['x'], e['y']))}, 'properties': {k: v for k, v in e.items() if k not in ('x', 'y')}} for e in extra]
    (d / 'detected_not_in_regulations.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': ex}), encoding='utf-8')
    stops = [s for s in signs if s['kind'] == 'stop']; ev = defaultdict(int)
    for s in stops: ev[s.get('evidence', 'n/a')] += 1
    summary = {'town': town, 'version': VERSION, 'built_at': now(), 'roads': getattr(export, '_roads', None), 'signs_by_kind': dict(defaultdict(int, {k: sum(1 for s in signs if s['kind'] == k) for k in {s['kind'] for s in signs}})),
               'unresolved_rows': len(unresolved), 'unresolved_reasons': dict(defaultdict(int, {r['reason']: sum(1 for u in unresolved if u['reason'] == r['reason']) for r in unresolved})),
               'stop_sign_evidence': dict(ev), 'triangulated_stop_signs_not_in_regulations': len(extra), 'placement_residuals_vs_imagery': calibrate_offsets(signs)}
    (d / 'summary.json').write_text(json.dumps(summary, indent=1), encoding='utf-8'); print(json.dumps(summary, indent=1), flush=True); return summary


def run(town):
    """Place, measure the placement bias against triangulated/human evidence, and re-place once with corrected offsets.
    Leave-one-out on Wellesley (17 signs): 5.4 m -> 4.4 m median, better on 13/17."""
    gz, recs = parse(town); export._roads = gz.source; gz, signs, unresolved = geocode(town, gz, recs); signs, extra = match(town, signs)
    cal = calibrate_offsets(signs)
    if cal and cal['n'] >= 10:
        setback = max(2.0, SETBACK_M - cal['along_travel_median_m']); offset = max(1.0, OFFSET_M + cal['right_of_travel_median_m'])
        gz, signs, unresolved = geocode(town, gz, recs, setback, offset); signs, extra = match(town, signs)
        print(f'self-calibrated placement from {cal["n"]} signs: setback {SETBACK_M:.1f} -> {setback:.1f} m, offset {OFFSET_M:.1f} -> {offset:.1f} m', flush=True)
        for s in signs: s['calibration'] = {'setback_m': round(setback, 1), 'offset_m': round(offset, 1), 'from_n_signs': cal['n']}
    return export(town, signs, unresolved, extra)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0]); p.add_argument('command', choices=['acquire', 'parse', 'run']); p.add_argument('--town', default='wellesley'); a = p.parse_args()
    {'acquire': lambda: print(json.dumps(acquire(a.town)[1], indent=1)), 'parse': lambda: parse(a.town), 'run': lambda: run(a.town)}[a.command]()
