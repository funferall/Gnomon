import os,json,time,requests,mercantile,mapbox_vector_tile,geopandas as gpd
from pathlib import Path
from shapely.geometry import box,LineString,MultiLineString
from pyproj import Transformer
from shapely.ops import transform
from concurrent.futures import ThreadPoolExecutor
D=Path('data');token=os.environ.get('MAPILLARY_ACCESS_TOKEN')
if not token:
 for l in Path('.env').read_text(encoding='utf-8-sig').splitlines():
  k,sep,v=l.partition('=')
  if sep and k.strip()=='MAPILLARY_ACCESS_TOKEN':token=v.strip();break
if not token:raise SystemExit('MAPILLARY_ACCESS_TOKEN missing')
state=gpd.read_file('zip://data/states.zip').query("STUSPS=='MA'").geometry.iloc[0]; tiles=[t for t in mercantile.tiles(-73.51,41.2,-69.85,42.9,9) if state.intersects(box(*mercantile.bounds(t)))];cache=D/'mapillary_tiles_z9';cache.mkdir(exist_ok=True)
def load(t):
 p=cache/f'{t.z}_{t.x}_{t.y}.pbf'
 if not p.exists():
  try:
   r=requests.get(f'https://tiles.mapillary.com/maps/vtp/mly1_public/2/{t.z}/{t.x}/{t.y}',params={'access_token':token},timeout=90);r.raise_for_status();p.write_bytes(r.content)
  except Exception as e:return t,None,type(e).__name__
 return t,p.read_bytes(),None
trans=Transformer.from_crs(3857,26986,always_xy=True);boundary=gpd.GeoSeries([state],crs=4326).to_crs(26986).iloc[0];records=[];errors=[]
with ThreadPoolExecutor(max_workers=3) as pool:
 for n,(t,content,error) in enumerate(pool.map(load,tiles),1):
  if error:errors.append({'x':t.x,'y':t.y,'error':error});print('failed',t.x,t.y,error,flush=True);continue
  seq=mapbox_vector_tile.decode(content).get('sequence',{});ex=seq.get('extent',4096);bounds=mercantile.xy_bounds(t)
  for f in seq.get('features',[]):
   geom=f.get('geometry',{});coords=geom.get('coordinates',[]);typ=geom.get('type');lines=[coords] if typ=='LineString' else coords if typ=='MultiLineString' else []
   for line in lines:
    if len(line)<2:continue
    xs=[bounds.left+x/ex*(bounds.right-bounds.left) for x,y in line];ys=[bounds.bottom+y/ex*(bounds.top-bounds.bottom) for x,y in line];x,y=trans.transform(xs,ys);g=LineString(zip(x,y))
    if g.is_empty or not g.intersects(boundary):continue
    props=f.get('properties',{});ts=props.get('captured_at');year=time.gmtime(ts/1000).tm_year if ts else None;records.append({'sequence':str(props.get('id','')),'year':year,'geometry':g})
  print(n,'/',len(tiles),'lines',len(records),flush=True)
if errors: (D/'mapillary_town_tile_errors.json').write_text(json.dumps(errors,indent=2));raise SystemExit('Tile failures; results withheld')
gdf=gpd.GeoDataFrame(records,crs=26986);gdf.to_parquet(D/'mapillary_z9_lines.parquet',index=False);print('saved',len(gdf),'lines',flush=True)
