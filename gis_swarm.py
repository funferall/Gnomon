"""Town GIS-data swarm: find every Massachusetts town's GIS portals and sign/traffic layers, verify them, download what is public.

build     registry in data/gis/registry/ (same 350 towns as the regulations swarm) + town websites (Wikidata, regulations registry)
sweep     ArcGIS Online catalog search per town (no web-search budget): sign/traffic layers, open-data hubs, map apps
assign    queue every town for the research agents (towns without a sign layer first)
next      claim the worker's next town and print what is already known          (used by research agents)
links URL print a page's GIS-related links (portal, viewer, open data, REST, downloads)   (agent helper, no search budget)
submit    record links an agent found ("kind|url|title"), verify them (ArcGIS REST is crawled and counted) and set the status
release   hand a town back unchanged
download  save every public sign/traffic layer as GeoJSON in data/gis/downloads/<slug>/
export    data/gis/gis_inventory.csv + .json (one row per link)

Status: found = public sign layer with features; partial = GIS portal/viewer or other layers, no public sign layer;
not_found = nothing public; error.  The dashboard tab (swarm.html#gis) reads data/gis/registry/status.json,
written by `python swarm.py status --kind gis`.
"""
import argparse, csv, json, os, re, sys, time, threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse, urljoin
import requests

ROOT = Path(__file__).resolve().parent
GIS = ROOT / 'data' / 'gis'; REG = GIS / 'registry'; CAT = REG / 'catalog'; TOWNS = REG / 'towns'
UA = {'User-Agent': 'Gnomon-GIS-inventory/1.0 (municipal open-data research)'}
SIGN = re.compile(r'(?<!de)(?<!as)(?<!re)sign(?!al|ed|er|if|at|ment)|stop.?sign|r1-1|mutcd|traffic.?order', re.I)
TRAFFIC = re.compile(r'traffic|one.?way|turn.?(proh|restr)|regulat|parking|crosswalk|pavement|road.?(inv|condition|segment)|street.?(inv|light|segment)|curb|sidewalk|speed|guard.?rail|signal|hydrant', re.I)
NOISE = re.compile(r'billboard|bus.?stop|trail|historic|interpretive|campaign|yard.?sign|sign.?up|signup|design|wayfinding|gateway|kiosk|survey123_.*_form|winter.?ban|parking.?ban|pvms|message.?sign|sign.?district', re.I)
VENDORS = re.compile(r'arcgis|axisgis|mapsonline|peoplegis|mainstreetmaps|mapgeo|cai-tech|caitech|simplegis|tighebond|nearmap|gisweb|/gis|gis\.|opendata|open-data|hub\.|maps\.|mapserver|featureserver|rest/services|geoserver|qgiscloud|vgsi|patriotproperties', re.I)
KW = re.compile(r'\bgis\b|map|geographic|open ?data|parcel|shapefile|\.zip|\.kmz?|geojson|layer|sign|traffic|pavement|road|street|engineering|public works|dpw|assessor', re.I)
KINDS = ('viewer', 'opendata', 'rest', 'layer', 'download', 'document', 'other', 'portal')
if hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(encoding='utf-8', errors='replace')


def read(p):
    try: return json.loads(Path(p).read_text(encoding='utf-8'))
    except (OSError, ValueError): return None


def write(p, d):
    p = Path(p); tmp = p.with_suffix(p.suffix + f'.{os.getpid()}.tmp'); tmp.write_text(json.dumps(d, indent=1), encoding='utf-8')
    for i in range(40):   # Windows refuses the replace while a reader (the dashboard aggregator) has the file open
        try: os.replace(tmp, p); return
        except PermissionError: time.sleep(0.1 * (i + 1))
    tmp.unlink(missing_ok=True); raise PermissionError(f'could not write {p}')


def unlink(p):
    for i in range(20):
        try: Path(p).unlink(missing_ok=True); return
        except PermissionError: time.sleep(0.1 * (i + 1))


@contextmanager
def town_lock(slug):
    lk = REG / 'locks' / f'{slug}.lock'; lk.parent.mkdir(exist_ok=True)
    for _ in range(600):
        try: fd = os.open(lk, os.O_CREAT | os.O_EXCL | os.O_WRONLY); os.close(fd); break
        except FileExistsError:
            if time.time() - lk.stat().st_mtime > 120: lk.unlink(missing_ok=True)
            time.sleep(0.1)
    try: yield
    finally: lk.unlink(missing_ok=True)


def towns(): return json.loads((REG / 'towns.json').read_text(encoding='utf-8'))['towns']


def jget(url, **params):
    params.setdefault('f', 'json'); r = requests.get(url, params=params, headers=UA, timeout=60); r.raise_for_status(); d = r.json()
    if isinstance(d, dict) and d.get('error'): raise RuntimeError(str(d['error'].get('message') or d['error'])[:120])
    return d


# ---------------------------------------------------------------- build: registry + town websites
def build():
    import shutil
    REG.mkdir(parents=True, exist_ok=True); TOWNS.mkdir(exist_ok=True); CAT.mkdir(exist_ok=True); (REG / 'workers').mkdir(exist_ok=True)
    shutil.copy(ROOT / 'data/regulations/registry/towns.json', REG / 'towns.json')
    sites = {}
    q = ('SELECT ?item ?itemLabel ?site WHERE { ?item wdt:P131 ?county . ?county wdt:P131 wd:Q771 . ?item wdt:P856 ?site . '
         'SERVICE wikibase:label { bd:serviceParam wikibase:language "en". } }')
    try:
        r = requests.get('https://query.wikidata.org/sparql', params={'query': q, 'format': 'json'}, headers=UA, timeout=120); r.raise_for_status()
        for b in r.json()['results']['bindings']:
            name = re.sub(r',.*$', '', b['itemLabel']['value']).strip().lower(); sites.setdefault(name, b['site']['value'])
    except Exception as e: print('wikidata failed:', e)
    skip = re.compile(r'ecode360|generalcode|municode|amlegal|mass\.gov|google|scribd|archive\.org|issuu|dropbox')
    n = 0
    for t in towns():
        rd = read(ROOT / 'data/regulations/registry/towns' / f"{t['slug']}.json") or {}
        urls = [(rd.get('document') or {}).get('url'), (rd.get('verification') or {}).get('url')] + (rd.get('candidates') or [])
        tok = re.sub('[^a-z]', '', t['name'].lower())[:6]
        hosts = [urlparse(u).netloc.lower() for u in urls if u and not skip.search(urlparse(u).netloc.lower())]
        own = next((h for h in hosts if tok in re.sub('[^a-z]', '', h)), None)
        site = sites.get(t['name'].lower()) or (f'https://{own}/' if own else None)
        p = CAT / f"{t['slug']}.json"; c = read(p) or {'slug': t['slug']}; c['website'] = site; write(p, c); n += bool(site)
    if not (REG / 'assignments.json').exists(): write(REG / 'assignments.json', {'gis': [t['slug'] for t in towns()]})
    print(f'{len(towns())} towns; websites known for {n} (Wikidata {len(sites)} names)')


# ---------------------------------------------------------------- layer probing
def probe_layer(url, title=''):
    """One ArcGIS layer: name, geometry, feature count, stop-sign count, public?"""
    url = url.rstrip('/'); m = jget(url); name = m.get('name') or title
    out = {'url': url, 'name': name, 'geometry': (m.get('geometryType') or '').replace('esriGeometry', ''), 'type': m.get('type')}
    if m.get('type') not in ('Feature Layer', 'Table', None): return out
    try: out['features'] = jget(url + '/query', where='1=1', returnCountOnly='true').get('count')
    except Exception as e: out['error'] = str(e)[:100]; return out
    if out.get('features'):   # same-named towns exist in other states: drop layers that map elsewhere
        try:
            e = jget(url + '/query', where='1=1', returnExtentOnly='true', outSR=4326).get('extent') or {}
            cx, cy = (e['xmin'] + e['xmax']) / 2, (e['ymin'] + e['ymax']) / 2
            if not (MA_BOX[0] <= cx <= MA_BOX[2] and MA_BOX[1] <= cy <= MA_BOX[3]): out['outside_ma'] = True
        except Exception: pass
    sf = [f['name'] for f in m.get('fields') or [] if f.get('type') == 'esriFieldTypeString'][:25]
    if out.get('features') and (SIGN.search(name + ' ' + title) or any(SIGN.search(f) for f in sf)):
        w = ' OR '.join(f"UPPER({f}) LIKE '%STOP%' OR UPPER({f}) LIKE '%R1-1%'" for f in sf)
        try: out['stop_signs'] = jget(url + '/query', where=w, returnCountOnly='true').get('count') if sf else None
        except Exception:   # older services reject long or UPPER() clauses: count field by field, keep the largest
            best = None
            for f in sf:
                try: n = jget(url + '/query', where=f"{f} LIKE '%Stop%' OR {f} LIKE '%STOP%' OR {f} LIKE 'R1-1%'", returnCountOnly='true').get('count')
                except Exception: continue
                best = max(best or 0, n or 0)
            out['stop_signs'] = best
        if SIGN.search(name) and re.search(r'stop', name, re.I): out['stop_signs'] = out['features']
    return out


def probe_service(url, title='', want=lambda n: True, cap=12):
    """FeatureServer/MapServer: probe the layers whose names look relevant (all if the service itself is relevant)."""
    url = url.rstrip('/'); s = jget(url); res = []
    for lyr in (s.get('layers') or [])[:60]:
        if len(res) >= cap: break
        if want(lyr.get('name', '') + ' ' + title):
            try: res.append(probe_layer(f"{url}/{lyr['id']}", title))
            except Exception as e: res.append({'url': f"{url}/{lyr['id']}", 'name': lyr.get('name'), 'error': str(e)[:100]})
    return res


def relevant(name): return bool((SIGN.search(name) or TRAFFIC.search(name)) and not NOISE.search(name))


def probe_rest_dir(url, cap=80):
    """ArcGIS Server services directory (or folder): find services/layers named like signs or traffic and probe them."""
    url = url.split('?')[0].rstrip('/'); d = jget(url); res = []; seen = 0
    queue = [(url, d)]
    for f in (d.get('folders') or [])[:30]:
        try: queue.append((f'{url}/{f}', jget(f'{url}/{f}')))
        except Exception: pass
    base = url[:url.lower().index('/rest/services') + len('/rest/services')] if '/rest/services' in url.lower() else url
    for _, dd in queue:
        for s in dd.get('services') or []:
            if s.get('type') not in ('FeatureServer', 'MapServer') or seen >= cap: continue
            seen += 1; su = f"{base}/{s['name']}/{s['type']}"
            try:
                sv = jget(su); names = [l.get('name', '') for l in sv.get('layers') or []]
                if relevant(s['name']) or any(relevant(n) for n in names):
                    res += probe_service(su, s['name'], want=lambda n: relevant(n) or relevant(s['name']))
            except Exception: pass
    return res


def classify_url(u):
    lu = u.lower()
    if re.search(r'/(featureserver|mapserver)/\d+/?$', lu): return 'layer'
    if re.search(r'/(featureserver|mapserver)/?$', lu): return 'service'
    if '/rest/services' in lu: return 'rest'
    return None


MA_BOX = (-73.6, 41.15, -69.8, 42.95)
_portal_cache = {}


def extent_in_ma(e):
    """ArcGIS extent dict (any SR in {4326, 3857/102100}) -> True/False, None if unknown."""
    try:
        import math
        wk = (e.get('spatialReference') or {}).get('latestWkid') or (e.get('spatialReference') or {}).get('wkid')
        lon = lambda v: v / 6378137 * 180 / math.pi if wk in (102100, 3857, 102113) else v
        lat = lambda v: math.degrees(2 * math.atan(math.exp(v / 6378137)) - math.pi / 2) if wk in (102100, 3857, 102113) else v
        if wk not in (4326, None, 102100, 3857, 102113): return None
        if lon(e['xmax']) - lon(e['xmin']) > 5: return None   # the default continental / world view says nothing about where the org is
        x, y = (lon(e['xmin']) + lon(e['xmax'])) / 2, (lat(e['ymin']) + lat(e['ymax'])) / 2
        return MA_BOX[0] <= x <= MA_BOX[2] and MA_BOX[1] <= y <= MA_BOX[3]
    except Exception: return None


def portal_in_ma(key):
    """Is <key>.maps.arcgis.com an organisation whose default map is in Massachusetts? (cached; None = unknown)"""
    if key not in _portal_cache:
        try: _portal_cache[key] = extent_in_ma(jget(f'https://{key}.maps.arcgis.com/sharing/rest/portals/self').get('defaultExtent') or {})
        except Exception: _portal_cache[key] = None
    return _portal_cache[key]
ITEM_ID = re.compile(r'(?:appid|webmap|id)=([0-9a-f]{32})|/experience/([0-9a-f]{32})|/items/([0-9a-f]{32})', re.I)


def arcgis_item(u):
    """ArcGIS Online app/map/item link -> (item info, relevant layer URLs inside it). None if not an item link."""
    m = ITEM_ID.search(u)
    if not m or not re.search(r'arcgis\.com', u, re.I): return None
    iid = next(g for g in m.groups() if g); base = 'https://www.arcgis.com/sharing/rest/content/items/'
    it = jget(base + iid); urls = []
    def from_map(mid):
        try: return [l.get('url') for l in jget(base + mid + '/data').get('operationalLayers') or [] if classify_url(l.get('url') or '') and relevant((l.get('title') or '') + ' ' + it.get('title', ''))]
        except Exception: return []
    if it.get('type') == 'Web Map': urls = from_map(iid)
    else:
        try: data = jget(base + iid + '/data')
        except Exception: data = {}
        for mid in set(re.findall(r'"(?:webmap|itemId|id)"\s*:\s*"([0-9a-f]{32})"', json.dumps(data))) - {iid}:
            urls += from_map(mid)
    return it, list(dict.fromkeys(u for u in urls if u))


def verify_link(link):
    """link = {kind,url,title}: probe ArcGIS endpoints, otherwise check that the page/file answers.
    ArcGIS Online apps/maps are opened: rejected if they map somewhere outside Massachusetts, else their sign/traffic layers are probed."""
    u = link['url']; k = classify_url(u); out = dict(link)
    try:
        ai = arcgis_item(u) if not k else None
        if ai:
            it, lurls = ai; ext = it.get('extent') or []
            if len(ext) == 2 and abs(ext[1][0] - ext[0][0]) <= 5:   # wider = a default world/US box, says nothing
                (a, b), (c, d) = ext; cx, cy = (a + c) / 2, (b + d) / 2
                if not (MA_BOX[0] <= cx <= MA_BOX[2] and MA_BOX[1] <= cy <= MA_BOX[3]):
                    out.update(ok=False, error=f'maps outside Massachusetts (centre {cx:.2f},{cy:.2f}; owner {it.get("owner")})'); return out
            out['ok'] = True; out['layers'] = []
            for lu in lurls[:8]:
                try: out['layers'] += [probe_layer(lu, it.get('title', ''))] if classify_url(lu) == 'layer' else probe_service(lu, it.get('title', ''), want=relevant)
                except Exception: pass
            return out
        if k == 'layer': out['layers'] = [probe_layer(u, link.get('title', ''))]; out['ok'] = True
        elif k == 'service': out['layers'] = probe_service(u, link.get('title', ''), want=lambda n: relevant(n) or bool(SIGN.search(link.get('title', '') + ' ' + u))); out['ok'] = True
        elif k == 'rest': out['layers'] = probe_rest_dir(u); out['ok'] = True
        else:
            tries = [u, u, 'https://' + u[7:] if u.startswith('http://') else u]   # map-viewer hosts (AxisGIS) reset connections / refuse plain http
            for attempt, tu in enumerate(tries):
                try: r = requests.get(tu, headers=UA, timeout=45, stream=True, allow_redirects=True); break
                except (requests.ConnectionError, requests.Timeout):
                    if attempt == len(tries) - 1: raise
                    time.sleep(3 * (attempt + 1))
            out['ok'] = r.status_code < 400; out['http'] = r.status_code
            out['content_type'] = r.headers.get('content-type', '').split(';')[0]; out['final_url'] = r.url
            if 'html' in out['content_type']:
                m = re.search(rb'<title[^>]*>(.*?)</title>', r.raw.read(200000, decode_content=True) or b'', re.S | re.I)
                if m and not link.get('title'): out['title'] = re.sub(r'\s+', ' ', m.group(1).decode('utf-8', 'replace')).strip()[:120]
            r.close()
    except Exception as e: out['ok'] = False; out['error'] = str(e)[:140]
    return out


# ---------------------------------------------------------------- catalog sweep (ArcGIS Online)
_org_cache, _org_lock = {}, threading.Lock()
ORG_TYPES = ('type:"Feature Service" OR type:"Map Service" OR type:"Web Map" OR type:"Hub Site Application" OR type:"Site Application" OR '
             'type:"Web Mapping Application" OR type:"Dashboard" OR type:"Web Experience" OR type:"Shapefile" OR type:"File Geodatabase" OR type:"CSV" OR type:"GeoJson"')
VIEWERISH = re.compile(r'\bgis\b|viewer|open ?data|\bhub\b|mapgeo|parcel|propert|assessor|infrastructure|public works|\bdpw\b|engineering|official.{0,12}map|town map|city map|sign|traffic|street|road|pavement|sidewalk', re.I)


def org_items(owner):
    """All public mapping items of an ArcGIS Online account (cached; capped at 2,000), plus its organisation's portal if public.
    (Anonymous search results carry no organisation id, so accounts are the unit.)"""
    with _org_lock:
        if owner in _org_cache: return _org_cache[owner]
    items, start = [], 1
    while start and start <= 2000:
        try: r = jget('https://www.arcgis.com/sharing/rest/search', q=f'owner:"{owner}" AND ({ORG_TYPES})', num=100, start=start)
        except Exception: break
        items += r.get('results', []); start = r.get('nextStart', -1); start = start if start and start > 0 else None
    info = {}
    try:
        u = jget(f'https://www.arcgis.com/sharing/rest/community/users/{owner}')
        if u.get('orgId'): info = jget(f"https://www.arcgis.com/sharing/rest/portals/{u['orgId']}")
    except Exception: pass
    res = (items, {'name': info.get('name'), 'urlKey': info.get('urlKey'), 'in_ma': extent_in_ma((info.get('defaultExtent') or {}))})
    with _org_lock: _org_cache[owner] = res
    return res


def sweep_town(t, poly):
    from collections import Counter
    from shapely.geometry import box, Point
    x0, y0, x1, y1 = poly.bounds; area = (x1 - x0) * (y1 - y0); tok = re.sub('[^a-z]', '', t['name'].lower())
    def inside(it):
        ext = it.get('extent') or []
        if len(ext) != 2: return None
        (a, b), (c, d) = ext
        return box(a, b, c, d).area <= area * 4 and poly.contains(Point((a + c) / 2, (b + d) / 2))
    # 1. which ArcGIS organisations publish this town's data?
    score, seen = Counter(), {}
    for q in (f'"{t["name"]}"', f'"{t["name"]}" AND (sign OR signs OR traffic OR streets OR roads OR GIS)'):
        start = 1
        while start and start <= 200:
            try: r = jget('https://www.arcgis.com/sharing/rest/search', q=q, bbox=f'{x0},{y0},{x1},{y1}', num=100, start=start)
            except Exception: break
            for it in r.get('results', []):
                o = it.get('owner')
                if not o: continue
                if tok in re.sub('[^a-z]', '', it.get('owner', '').lower()): score[o] += 3
                if inside(it): score[o] += 1
                seen[it['id']] = it
            start = r.get('nextStart', -1); start = start if start and start > 0 else None
    links, items = [], dict(seen)
    portals = set()
    for o, sc in score.most_common(5):
        if sc < 2: break
        its, info = org_items(o)
        for it in its: items.setdefault(it['id'], it)
        if info.get('urlKey') and info['urlKey'] not in portals and info.get('in_ma') is not False and tok in re.sub('[^a-z]', '', (info.get('name') or '').lower() + info['urlKey'].lower()):
            portals.add(info['urlKey']); links.append({'kind': 'portal', 'url': f"https://{info['urlKey']}.maps.arcgis.com/home/", 'title': f"ArcGIS Online: {info.get('name')}", 'ok': True, 'source': 'arcgis_catalog'})
    # 2. keep relevant items located in the town
    for it in items.values():
        typ = it['type']; url = it.get('url'); text = it['title'] + ' ' + ' '.join(it.get('tags') or []) + ' ' + (it.get('snippet') or '')
        ins = inside(it); named = t['name'].lower() in it['title'].lower()
        base = {'title': it['title'], 'owner': it['owner'], 'item': f"https://www.arcgis.com/home/item.html?id={it['id']}", 'access': it.get('access'), 'source': 'arcgis_catalog', 'item_type': typ}
        if typ in ('Hub Site Application', 'Site Application'):
            if (named or ins) and ins is not False: links.append(verify_link({**base, 'kind': 'opendata', 'url': base['item']}) | {'url': url or base['item']})
            continue
        if typ in ('Web Mapping Application', 'Dashboard', 'Web Experience'):
            if (named or ins or ins is None and tok in re.sub('[^a-z]', '', it['owner'].lower())) and VIEWERISH.search(it['title']) and not NOISE.search(it['title']):
                v = verify_link({**base, 'kind': 'viewer', 'url': base['item']}); links.append(v | {'url': url or base['item']})
            continue
        if ins is False or (ins is None and not named) or not relevant(text): continue
        if typ in ('Feature Service', 'Map Service') and url and url.rstrip('/') not in {x['url'].rstrip('/') for x in links}: links.append(verify_link({**base, 'kind': 'layer', 'url': url}))
        elif typ == 'Web Map':
            try:
                dd = jget(f"https://www.arcgis.com/sharing/rest/content/items/{it['id']}/data")
                for l in dd.get('operationalLayers') or []:
                    lu = l.get('url') or ''
                    if classify_url(lu) and lu not in {x['url'] for x in links} and relevant((l.get('title') or '') + ' ' + it['title']):
                        links.append(verify_link({**base, 'kind': 'layer', 'url': lu, 'title': f"{it['title']} / {l.get('title')}"}))
            except Exception: pass
        elif typ in ('Shapefile', 'File Geodatabase', 'GeoJson', 'CSV'): links.append({**base, 'kind': 'download', 'url': base['item'], 'ok': True})
    return links


def sweep(threads=6, only=None):
    import geopandas as gpd
    from shapely.geometry import shape
    tw = {t['slug']: t for t in towns()}
    g = gpd.read_file('zip://' + str(ROOT / 'data/towns.zip')).to_crs(4326); g['name'] = g.NAME.str.replace(r'\s+(Town|City)$', '', regex=True)
    polys = {r['name']: r.geometry for _, r in g.iterrows()}
    todo = [t for s, t in tw.items() if (not only or s in only) and not (read(CAT / f'{s}.json') or {}).get('swept_at')]
    print(f'sweeping {len(todo)} towns', flush=True); done = [0]

    def one(t):
        try: links = sweep_town(t, polys[t['name']])
        except Exception as e: links = []; print('  ', t['slug'], 'ERR', e, flush=True)
        with town_lock(t['slug']):
            c = read(CAT / f"{t['slug']}.json") or {'slug': t['slug']}; c['links'] = links; c['swept_at'] = time.time(); write(CAT / f"{t['slug']}.json", c)
            recompute(t['slug'])
        done[0] += 1; s = summarize(links)
        if s['sign_layers'] or done[0] % 25 == 0: print(f"  [{done[0]}/{len(todo)}] {t['name']}: {s['sign_layers']} sign layers ({s['stop_signs']} stop), {len(links)} links", flush=True)
    with ThreadPoolExecutor(threads) as ex: list(ex.map(one, todo))


# ---------------------------------------------------------------- town record
def summarize(links):
    parent = {}
    for k in links:
        for l in k.get('layers') or []: parent.setdefault(l.get('url'), k.get('title') or '')
    lay = [l for l in {l.get('url') or id(l): l for k in links for l in (k.get('layers') or [])}.values() if not l.get('outside_ma')]   # one layer can be reached through several items
    # signs by the layer's own name, or a generic layer ("survey") of an item titled as a sign inventory that has stop signs in it;
    # a "Traffic Orders" map can also hold e.g. statewide address points ("Stop & Shop"), hence the size cap
    def is_sign(l):
        name = l.get('name', ''); title = parent.get(l.get('url'), '')
        if NOISE.search(name) or NOISE.search(title) or not 0 < (l.get('features') or 0) <= 200000: return False
        return bool(SIGN.search(name) or (l.get('stop_signs') and SIGN.search(title) and not TRAFFIC.search(name)))
    sign = [l for l in lay if is_sign(l)]
    return {'links': len(links), 'ok_links': sum(1 for k in links if k.get('ok')), 'layers': len(lay), 'sign_layers': len(sign),
            'sign_features': max([l.get('features') or 0 for l in sign] or [0]), 'stop_signs': max([l.get('stop_signs') or 0 for l in sign] or [0]),
            'traffic_layers': sum(1 for l in lay if (l.get('features') or 0) > 0 and l not in sign)}


OTHER_STATE = re.compile(r'[a-z](AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY)(GIS)?\.(hub|maps)\.arcgis\.com')


def recompute(slug):
    """Merge catalog + agent links into towns/<slug>.json (what the dashboard aggregator reads).
    Hub/portal addresses carry the organisation key, often ending in its state (AbingtonPA, DouglasWA): those are dropped."""
    c = read(CAT / f'{slug}.json') or {}; p = TOWNS / f'{slug}.json'; d = read(p) or {'slug': slug}
    links = [l for l in (c.get('links') or []) + (d.get('agent_links') or []) if not OTHER_STATE.search(l.get('url') or '')]; s = summarize(links)
    if d.get('status') != 'searching':   # an agent is working on it: keep showing that until it submits
        d['status'] = 'found' if s['sign_layers'] else 'partial' if s['ok_links'] else 'not_found' if d.get('agent_done') else 'queued'
    lay = sorted([(l, k) for k in links for l in (k.get('layers') or []) if (l.get('features') or 0) > 0], key=lambda x: (-(x[0].get('stop_signs') or 0), -bool(SIGN.search(x[0].get('name', ''))), -(x[0].get('features') or 0)))
    best = lay[0] if lay else None; portal = next((k for k in links if k.get('kind') in ('opendata', 'portal', 'viewer', 'rest') and k.get('ok')), None)
    if best: d['document'] = {'url': best[0]['url'], 'title': f"{best[1].get('title') or ''} / {best[0].get('name')}".strip(' /'), 'format': best[1].get('kind'), 'features': best[0].get('features'), 'stop_signs': best[0].get('stop_signs'), 'verified': True}
    elif portal: d['document'] = {'url': portal['url'], 'title': portal.get('title') or portal['url'], 'format': portal['kind'], 'verified': True}
    d['summary'] = s; d['website'] = c.get('website')
    d['links'] = [{k: v for k, v in x.items() if k in ('kind', 'url', 'title', 'ok', 'source', 'owner', 'access', 'http', 'error')} | {'layers': [{k: v for k, v in l.items() if k in ('url', 'name', 'features', 'stop_signs', 'geometry', 'error', 'outside_ma')} for l in (x.get('layers') or [])][:12]} for x in links][:40]
    d['candidates'] = [x['url'] for x in links if x.get('ok')][:5]
    d['notes'] = d.get('agent_note') or (f"Catalog: {s['sign_layers']} sign layers, {s['traffic_layers']} other layers, {s['links']} links." if c.get('swept_at') else '')
    write(p, d)


# ---------------------------------------------------------------- agent commands
AGENT_CAP = 15   # towns per research agent (keeps a small model's context short)


def next_town(worker):
    import swarm as S
    S.REG = REG; S.CLAIMS = REG / 'claims'
    if worker.startswith('gis-') and len(read(REG / f'{worker}_done.json') or []) >= AGENT_CAP:
        print(f'DONE: {worker} has finished its {AGENT_CAP} towns'); return
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf): S.next_town(worker, 'gis')
    line = buf.getvalue().strip()
    if not line.startswith('NEXT'): print(line); return
    slug = line.split()[1]; c = read(CAT / f'{slug}.json') or {}; d = read(TOWNS / f'{slug}.json') or {}
    t = {x['slug']: x for x in towns()}[slug]; s = summarize(c.get('links') or [])
    print(f"NEXT {slug} | {t['name']}, Massachusetts ({t['county']} County)")
    print(f"website: {c.get('website') or 'unknown'}")
    print(f"already found by catalog search: {s['sign_layers']} sign layers ({s['stop_signs']} stop signs), {s['traffic_layers']} other layers, {s['links']} links")
    for k in (c.get('links') or [])[:6]: print(f"  - {k.get('kind')}: {k.get('title', '')[:60]} {k['url']}")


def links_cmd(url):
    from bs4 import BeautifulSoup
    try: r = requests.get(url, headers=UA, timeout=30); r.raise_for_status()
    except Exception as e: print('FETCH FAILED:', str(e)[:160]); return
    soup = BeautifulSoup(r.text, 'html.parser'); title = (soup.title.string or '').strip() if soup.title else ''
    print(f'PAGE {r.url} | {title[:100]}')
    root = lambda u: '.'.join(urlparse(u).netloc.lower().split('.')[-2:])
    if root(r.url) != root(url):
        if VENDORS.search(r.url): print(f'NOTE: this page redirects to a map viewer: {r.url}  (submit it as a viewer)')
        elif urlparse(url).path.strip('/') == '': print(f'WARNING: {url} redirected to a different site ({urlparse(r.url).netloc}); it may not be the official town website')
    seen = set(); rows = []
    for a in soup.find_all('a', href=True):
        h = urljoin(r.url, a['href']).split('#')[0]; txt = re.sub(r'\s+', ' ', a.get_text(' ')).strip()[:70]
        if h in seen or h.startswith(('mailto:', 'tel:', 'javascript:')): continue
        if VENDORS.search(h) or KW.search(txt) or re.search(r'\.(zip|kmz|kml|geojson|shp|gdb)(\?|$)', h, re.I):
            seen.add(h); rows.append((0 if VENDORS.search(h) else 1, txt, h))
    # menus built by JavaScript: URLs (and site paths) embedded in the page source
    raw = r.text.replace('\\/', '/')
    for h in re.findall(r'https?://[^\s"\'<>\\)]+', raw) + [urljoin(r.url, x) for x in re.findall(r'["\'](/[^"\'\s<>]{1,120})["\']', raw)]:
        h = h.rstrip('.,;').split('#')[0]
        if h in seen or re.search(r'\.(js|css|png|jpe?g|gif|svg|woff2?|ico)(\?|$)|google\.|facebook|apple\.com|bing\.com', h, re.I): continue
        if VENDORS.search(h) or re.search(r'(?i)/[^/]*(gis|maps?|mapping|open-?data|sign|traffic|pavement)[^/]*/?$', h):
            seen.add(h); rows.append((0 if VENDORS.search(h) else 2, '(in page data)', h))
    for _, txt, h in sorted(rows)[:45]: print(f'  {txt or "(no text)"} -> {h}')
    if not rows: print('  (no GIS-looking links on this page)')


def submit(worker, slug, raw_links, note):
    links = []
    for raw in raw_links:
        parts = raw.split('|', 2)
        if len(parts) < 2 or not parts[1].startswith('http'): print('skipping malformed link (use kind|url|title):', raw); continue
        kind = parts[0].strip().lower(); kind = kind if kind in KINDS else 'other'
        links.append(verify_link({'kind': kind, 'url': parts[1].strip(), 'title': parts[2].strip() if len(parts) > 2 else '', 'source': worker}))
    with town_lock(slug):
        p = TOWNS / f'{slug}.json'; d = read(p) or {'slug': slug}; prev = d.pop('previous', {}) or {}
        old = [x for x in d.get('agent_links') or [] if x['url'] not in {l['url'] for l in links}]
        d.update({'agent_links': old + links, 'agent_note': note[:500], 'agent_done': True, 'worker': worker, 'status': 'queued'}); write(p, d); recompute(slug)
        d = read(p)
    done_p = REG / f'{worker}_done.json'; done = read(done_p) or []; write(done_p, sorted(set(done) | {slug}))
    unlink(REG / 'claims' / f'{slug}.claim')
    s = d['summary']; print(f"RESULT {slug}: {d['status']} | sign layers {s['sign_layers']} ({s['stop_signs']} stop signs) | working links {s['ok_links']}/{s['links']}")
    for l in links: print(f"  {'ok ' if l.get('ok') else 'BAD'} {l['kind']}: {l['url'][:110]}" + (f" ({len(l.get('layers') or [])} relevant layers)" if l.get('layers') is not None else '') + (f" [{l.get('error')}]" if l.get('error') else ''))
    export(quiet=True)


def release(worker, slug):
    import swarm as S
    S.REG = REG; S.CLAIMS = REG / 'claims'; S.release(worker, slug); recompute(slug)


# ---------------------------------------------------------------- outputs
def export(quiet=False):
    rows = []
    for t in towns():
        d = read(TOWNS / f"{t['slug']}.json") or {}
        for k in d.get('links') or []:
            lay = k.get('layers') or [None]
            for l in lay:
                rows.append({'town': t['name'], 'county': t['county'], 'status': d.get('status'), 'kind': k.get('kind'), 'title': k.get('title'), 'url': k['url'],
                             'working': k.get('ok'), 'layer_name': (l or {}).get('name'), 'layer_url': (l or {}).get('url'), 'features': (l or {}).get('features'),
                             'stop_signs': (l or {}).get('stop_signs'), 'found_by': k.get('source'), 'owner': k.get('owner'), 'website': d.get('website')})
    with open(GIS / 'gis_inventory.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ['town']); w.writeheader(); w.writerows(rows)
    write(GIS / 'gis_inventory.json', rows)
    # tracked copies in gis/ (data/ is not in git): no account names (some ArcGIS user names are email addresses)
    pub = ROOT / 'gis'; pub.mkdir(exist_ok=True)
    with open(pub / 'gis_inventory.csv', 'w', newline='', encoding='utf-8') as f:
        cols = [c for c in (list(rows[0]) if rows else ['town']) if c != 'owner']
        w = csv.DictWriter(f, fieldnames=cols, extrasaction='ignore'); w.writeheader(); w.writerows(rows)
    with open(pub / 'gis_towns.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f); w.writerow(['town', 'county', 'status', 'stop_signs', 'signs_in_largest_sign_layer', 'sign_layers', 'other_layers', 'working_links',
                                      'best_link_kind', 'best_link_title', 'best_link', 'website', 'notes'])
        for t in towns():
            d = read(TOWNS / f"{t['slug']}.json") or {}; s = d.get('summary') or {}; b = d.get('document') or {}
            w.writerow([t['name'], t['county'], d.get('status', 'queued'), s.get('stop_signs', 0), s.get('sign_features', 0), s.get('sign_layers', 0), s.get('traffic_layers', 0),
                        s.get('ok_links', 0), b.get('format', ''), b.get('title', ''), b.get('url', ''), d.get('website') or '', re.sub(r'\S+@\S+', '', d.get('notes') or '')[:300]])
    if not quiet: print(f'gis_inventory.csv: {len(rows)} rows, {len({r["town"] for r in rows})} towns')


def download(min_features=1, max_features=250000):
    out = GIS / 'downloads'; n = 0
    for t in towns():
        d = read(TOWNS / f"{t['slug']}.json") or {}
        for k in d.get('links') or []:
            for l in k.get('layers') or []:
                if not l.get('url') or not (min_features <= (l.get('features') or 0) <= max_features): continue
                if not (SIGN.search(l.get('name', '')) or l.get('stop_signs') or TRAFFIC.search(l.get('name', ''))): continue
                fn = out / t['slug'] / (re.sub(r'[^A-Za-z0-9]+', '_', l.get('name') or 'layer').strip('_')[:60] + f"_{abs(hash(l['url'])) % 10**6}.geojson")
                if fn.exists(): continue
                fn.parent.mkdir(parents=True, exist_ok=True); feats = []; off = 0
                try:
                    while True:
                        r = requests.get(l['url'] + '/query', params={'where': '1=1', 'outFields': '*', 'outSR': 4326, 'f': 'geojson', 'resultOffset': off, 'resultRecordCount': 2000}, headers=UA, timeout=120).json()
                        fs = r.get('features') or []; feats += fs; off += len(fs)
                        if not fs or not (r.get('exceededTransferLimit') or (r.get('properties') or {}).get('exceededTransferLimit')) and len(fs) < 2000: break
                    fn.write_text(json.dumps({'type': 'FeatureCollection', 'source': l['url'], 'features': feats}), encoding='utf-8'); n += 1
                    print(f"  {t['name']}: {l.get('name')} -> {len(feats)} features", flush=True)
                except Exception as e: print(f"  {t['name']}: {l.get('name')} FAILED {str(e)[:80]}", flush=True)
    print(f'downloaded {n} layers to {out}')


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__.split(chr(10))[0])
    ap.add_argument('command', choices=['build', 'sweep', 'assign', 'next', 'links', 'submit', 'release', 'download', 'export', 'recompute'])
    ap.add_argument('args', nargs='*'); ap.add_argument('--worker', default='agent'); ap.add_argument('--note', default='')
    ap.add_argument('--link', action='append', default=[], help='kind|url|title  (kind: viewer, opendata, rest, layer, download, document, other)')
    ap.add_argument('--website', help='corrected official town website (submit)')
    ap.add_argument('--only', nargs='*'); ap.add_argument('--threads', type=int, default=6); a = ap.parse_args()
    if a.command == 'build': build()
    elif a.command == 'sweep': sweep(a.threads, set(a.only) if a.only else None); export()
    elif a.command == 'assign':
        order = sorted(towns(), key=lambda t: ((read(TOWNS / f"{t['slug']}.json") or {}).get('status') == 'found', t['name']))
        write(REG / 'assignments.json', {'gis': [t['slug'] for t in order]}); print('queued', len(order))
    elif a.command == 'next': next_town(a.worker)
    elif a.command == 'links': links_cmd(a.args[0])
    elif a.command == 'submit':
        if a.website:
            with town_lock(a.args[0]):
                c = read(CAT / f'{a.args[0]}.json') or {'slug': a.args[0]}; c['website'] = a.website; write(CAT / f'{a.args[0]}.json', c)
        submit(a.worker, a.args[0], a.link, a.note)
    elif a.command == 'release': release(a.worker, a.args[0])
    elif a.command == 'download': download()
    elif a.command == 'export': export()
    elif a.command == 'recompute':
        for t in towns(): recompute(t['slug'])
        export()
