import requests,mercantile,mapbox_vector_tile,geopandas as gpd,math,json,time,collections
from shapely.geometry import box,Point
from shapely.prepared import prep
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
state=prep(gpd.read_file('zip://data/states.zip').query("STUSPS=='MA'").geometry.iloc[0]);state_geom=gpd.read_file('zip://data/states.zip').query("STUSPS=='MA'").geometry.iloc[0]
D=Path('data'); bbox=(-73.51,41.20,-69.85,42.90)
def tile_set(z):return [t for t in mercantile.tiles(*bbox,z) if state_geom.intersects(box(*mercantile.bounds(t)))]
def karta(t):
 try:
  r=requests.get(f'https://api.kartaview.org/2.0/sequence/tiles/{t.x}/{t.y}/{t.z}.json',timeout=50);r.raise_for_status();j=r.json();return t,j.get('lines',[]),None
 except Exception as e:return t,[],type(e).__name__
def mapilio(t):
 try:
  r=requests.get('https://geo.mapilio.com/geoserver/gwc/service/wmts',params={'REQUEST':'GetTile','SERVICE':'WMTS','VERSION':'1.0.0','LAYER':'mapilio:map_roads_line','STYLE':'','TILEMATRIX':f'EPSG:900913:{t.z}','TILEMATRIXSET':'EPSG:900913','FORMAT':'application/vnd.mapbox-vector-tile','TILECOL':t.x,'TILEROW':t.y},timeout=45);r.raise_for_status();return t,(mapbox_vector_tile.decode(r.content).get('map_roads_line',{}) if r.content else {}),None
 except Exception as e:return t,{},type(e).__name__
def feature(cells):
 return {'type':'FeatureCollection','features':[{'type':'Feature','geometry':{'type':'Point','coordinates':[c['lon'],c['lat']]},'properties':{k:v for k,v in c.items() if k not in ('lat','lon','ids')}} for c in cells.values()]}
for kind,z,fn in [('kartaview',9,karta),('mapilio',10,mapilio)]:
 tiles=tile_set(z);cells={};errors=[];found=0;ids=set();t0=time.time();print(kind,'tiles',len(tiles),flush=True)
 with ThreadPoolExecutor(max_workers=3) as pool:
  for n,(tile,data,err) in enumerate(pool.map(fn,tiles),1):
   if err:errors.append({'x':tile.x,'y':tile.y,'error':err});continue
   if kind=='kartaview':
    for line in data:
     for pt in line.get('track',[]):
      try:lon,lat=float(pt['lng']),float(pt['lat'])
      except (KeyError,ValueError,TypeError):continue
      if not state.contains(Point(lon,lat)):continue
      key=(math.floor(lon/.02),math.floor(lat/.02));cells.setdefault(key,{'lon':lon,'lat':lat,'count':1,'latest':None,'years':{},'id':None});found+=1
   else:
    extent=data.get('extent',4096);b=mercantile.xy_bounds(tile)
    for f in data.get('features',[]):
     p=f['properties'];sid=p.get('sequence_uuid');date=p.get('capture_time');geometry=f.get('geometry',{});coords=geometry.get('coordinates',[]);lines=[coords] if geometry.get('type')=='LineString' else coords if geometry.get('type')=='MultiLineString' else []
     for line in lines:
      for x,y in line:
       lon,lat=mercantile.lnglat(b.left+x/extent*(b.right-b.left),b.bottom+y/extent*(b.top-b.bottom))
       if not state.contains(Point(lon,lat)):continue
       key=(math.floor(lon/.02),math.floor(lat/.02));cell=cells.setdefault(key,{'lon':lon,'lat':lat,'count':0,'latest':None,'years':{},'id':None,'ids':set()});
       if sid and sid not in cell['ids']:
        cell['ids'].add(sid);cell['count']+=1
        if date:year=str(date)[:4];cell['years'][year]=cell['years'].get(year,0)+1
       if date and (not cell['latest'] or date>cell['latest']):cell.update(latest=date,id=sid,lon=lon,lat=lat)
       if sid:ids.add(sid)
       found+=1
   print(kind,n,'/',len(tiles),'cells',len(cells),flush=True)
 (D/f'{kind}_coverage_grid.geojson').write_text(json.dumps(feature(cells)),encoding='utf-8');summary={'zoom':z,'tiles':len(tiles),'errors':errors,'cells':len(cells),'matched_vertices':found,'unique_sequences':len(ids) if kind=='mapilio' else None,'elapsed_seconds':round(time.time()-t0)};(D/f'{kind}_coverage_summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8');print(kind,summary,flush=True)
