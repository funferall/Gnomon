import os, winreg, requests, mercantile, mapbox_vector_tile, geopandas as gpd, math, json, collections, datetime, time
from shapely.geometry import box, Point
from shapely.prepared import prep
from pathlib import Path
token=os.environ.get('MAPILLARY_ACCESS_TOKEN')
if not token and Path('.env').exists():
 for line in Path('.env').read_text(encoding='utf-8-sig').splitlines():
  key, sep, value = line.partition('=')
  if sep and key.strip() == 'MAPILLARY_ACCESS_TOKEN':
   token = value.strip().strip('\"').strip("'")
   break
if not token:
 with winreg.OpenKey(winreg.HKEY_CURRENT_USER,'Environment') as key: token=winreg.QueryValueEx(key,'MAPILLARY_ACCESS_TOKEN')[0]
state=gpd.read_file('zip://data/states.zip').query("STUSPS=='MA'").geometry.iloc[0];fast=prep(state)
tiles=[t for t in mercantile.tiles(-73.51,41.2,-69.85,42.9,9) if state.intersects(box(*mercantile.bounds(t)))];cells={};seqs=set();year_seqs=collections.defaultdict(set);errors=[];started=time.time();seen=0
for n,t in enumerate(tiles,1):
 try:
  r=requests.get(f'https://tiles.mapillary.com/maps/vtp/mly1_public/2/{t.z}/{t.x}/{t.y}',params={'access_token':token},timeout=75);r.raise_for_status();d=mapbox_vector_tile.decode(r.content); seq=d.get('sequence',{});extent=seq.get('extent',4096);b=mercantile.xy_bounds(t)
  for f in seq.get('features',[]):
   props=f.get('properties',{});sid=str(props.get('id',''));ts=props.get('captured_at');year=datetime.datetime.fromtimestamp(ts/1000,datetime.timezone.utc).year if ts else None;geom=f.get('geometry',{});coords=geom.get('coordinates',[])
   if geom.get('type')=='LineString': lines=[coords]
   elif geom.get('type')=='MultiLineString': lines=coords
   elif geom.get('type')=='Point': lines=[[coords]]
   else: continue
   touched=set()
   for line in lines:
    for point in line:
     mx=b.left+(point[0]/extent)*(b.right-b.left);my=b.bottom+(point[1]/extent)*(b.top-b.bottom);lng,lat=mercantile.lnglat(mx,my)
     if not fast.contains(Point(lng,lat)):continue
     key=(math.floor(lng/.02),math.floor(lat/.02))
     if key in touched:continue
     touched.add(key);cell=cells.setdefault(key,{'sequences':set(),'years':collections.defaultdict(set),'latest':0,'id':None,'lon':lng,'lat':lat})
     cell['sequences'].add(sid)
     if year:cell['years'][year].add(sid)
     if ts and ts>cell['latest']:cell.update(latest=ts,id=str(props.get('image_id','')),lon=lng,lat=lat)
   if touched:
    seqs.add(sid)
    if year:year_seqs[year].add(sid)
    seen+=1
  print(f'{n}/{len(tiles)} tile features {len(seq.get("features",[]))}, occupied cells {len(cells)}',flush=True)
 except Exception as e:
  errors.append({'z':t.z,'x':t.x,'y':t.y,'error_type':type(e).__name__});print(f'{n}/{len(tiles)} failed {type(e).__name__}',flush=True)
 time.sleep(.15)
features=[]
for cell in cells.values():
 date=datetime.datetime.fromtimestamp(cell['latest']/1000,datetime.timezone.utc).isoformat().replace('+00:00','Z') if cell['latest'] else None
 features.append({'type':'Feature','geometry':{'type':'Point','coordinates':[cell['lon'],cell['lat']]},'properties':{'count':len(cell['sequences']),'years':{str(k):len(v) for k,v in sorted(cell['years'].items())},'latest':date,'id':cell['id']}})
Path('data/mapillary_coverage_grid.geojson').write_text(json.dumps({'type':'FeatureCollection','features':features}),encoding='utf-8')
summary={'retrieved_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'zoom':9,'tiles_requested':len(tiles),'tiles_failed':errors,'grid_cells':len(cells),'unique_sequence_ids':len(seqs),'sequence_fragments':seen,'sequences_by_year':{str(k):len(v) for k,v in sorted(year_seqs.items())},'seconds':round(time.time()-started)};Path('data/mapillary_coverage_summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8');print(json.dumps(summary,indent=2),flush=True)
