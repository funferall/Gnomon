"""Search inside every town ArcGIS Online organisation the swarm found (<key>.maps.arcgis.com) for sign / traffic layers,
and drop portal links to same-named organisations in other states.

Anonymous catalog search cannot filter by organisation, but each portal's `portals/self` reveals its id, so `orgid:<id>`
search lists the organisation's public items. Where the organisation is, is decided by its items' extents (portal default
extents are usually the continental-US view). Hits are verified like any other link and added to the town's catalog links.
Run it after the sweep and the agents (it is the finishing pass).
"""
import re, glob, os
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import gis_swarm as G

Q = '(sign OR signs OR signage OR "stop signs" OR "sign inventory" OR "traffic orders" OR traffic OR regulatory) AND (type:"Feature Service" OR type:"Map Service" OR type:"Web Map")'
PORTAL = re.compile(r'https?://([a-z0-9-]+)\.maps\.arcgis\.com', re.I)


def portals():
    keys = {}
    for p in glob.glob(str(G.TOWNS / '*.json')):
        d = G.read(p) or {}; slug = os.path.basename(p)[:-5]
        for l in d.get('links') or []:
            m = PORTAL.search(l.get('url') or '')
            if m: keys.setdefault(m.group(1).lower(), set()).add(slug)
    return keys


def search(q, cap):
    items, start = [], 1
    while start and start <= cap:
        try: r = G.jget('https://www.arcgis.com/sharing/rest/search', q=q, num=100, start=start)
        except Exception: break
        items += r.get('results', []); start = r.get('nextStart', -1); start = start if start and start > 0 else None
    return items


def where(items):
    """Majority vote of item extents: True = Massachusetts, False = elsewhere, None = can't tell."""
    v = Counter()
    for it in items:
        ext = it.get('extent') or []
        if len(ext) != 2: continue
        (a, b), (c, d) = ext
        if c - a > 5: continue
        cx, cy = (a + c) / 2, (b + d) / 2; v[G.MA_BOX[0] <= cx <= G.MA_BOX[2] and G.MA_BOX[1] <= cy <= G.MA_BOX[3]] += 1
    if not v: return None
    return v[True] >= v[False]


def org(key, slugs):
    try: oid = G.jget(f'https://{key}.maps.arcgis.com/sharing/rest/portals/self').get('id')
    except Exception as e: return key, slugs, None, [], 'portal unreadable'
    if not oid: return key, slugs, None, [], 'no org id'
    in_ma = where(search(f'orgid:{oid}', 200))   # where its items are beats the default map (consultants set it to any project)
    if in_ma is None: in_ma = G.portal_in_ma(key)
    if in_ma is False: return key, slugs, False, [], 'outside MA'
    links = []
    for it in search(f'orgid:{oid} AND {Q}', 500):
        if not G.relevant(it['title'] + ' ' + ' '.join(it.get('tags') or [])): continue
        base = {'title': it['title'], 'owner': it['owner'], 'item': f"https://www.arcgis.com/home/item.html?id={it['id']}", 'access': it.get('access'), 'source': 'org_search', 'item_type': it['type']}
        if it['type'] in ('Feature Service', 'Map Service') and it.get('url'): v = G.verify_link({**base, 'kind': 'layer', 'url': it['url']})
        else: v = G.verify_link({**base, 'kind': 'layer', 'url': base['item']}) | {'url': base['item']}
        if 'outside Massachusetts' not in (v.get('error') or ''): links.append(v)
    return key, slugs, in_ma, links, f'{len(links)} relevant'


def run():
    keys = portals(); print(f'{len(keys)} organisation portals in town links', flush=True); dropped = []
    with ThreadPoolExecutor(6) as ex:
        for key, slugs, in_ma, links, msg in ex.map(lambda kv: org(*kv), keys.items()):
            for slug in slugs:
                with G.town_lock(slug):
                    c = G.read(G.CAT / f'{slug}.json') or {'slug': slug}; d = G.read(G.TOWNS / f'{slug}.json') or {'slug': slug}
                    if in_ma is False:   # a same-named organisation elsewhere: remove every link into it
                        bad = lambda l: (PORTAL.search(l.get('url') or '') or [None, None])[1] and PORTAL.search(l['url']).group(1).lower() == key
                        c['links'] = [l for l in c.get('links') or [] if not bad(l)]; d['agent_links'] = [l for l in d.get('agent_links') or [] if not bad(l)]
                        G.write(G.TOWNS / f'{slug}.json', d); dropped.append(f'{key}->{slug}')
                    else:
                        have = {l['url'] for l in c.get('links') or []}
                        c['links'] = (c.get('links') or []) + [l for l in links if l['url'] not in have]
                    G.write(G.CAT / f'{slug}.json', c); G.recompute(slug)
                if in_ma is not False and links:
                    s = (G.read(G.TOWNS / f'{slug}.json') or {}).get('summary', {})
                    print(f'  {key:26} -> {slug:18} {msg:12} sign layers {s.get("sign_layers")} ({s.get("stop_signs")} stop)', flush=True)
    print(f'dropped {len(dropped)} out-of-state portal links: {", ".join(dropped)}')
    G.export()


if __name__ == '__main__': run()
