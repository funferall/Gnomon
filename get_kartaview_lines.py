import geopandas as gpd,requests,mercantile
from shapely.geometry import box,LineString
from shapely.ops import transform
from pyproj import Transformer
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
s=gpd.read_file('zip://data/states.zip').query("STUSPS=='MA'").geometry.iloc[0];tiles=[t for t in mercantile.tiles(-73.51,41.2,-69.85,42.9,9) if s.intersects(box(*mercantile.bounds(t)))];conv=Transformer.from_crs(4326,26986,always_xy=True);rows=[];errors=[]
def fetch(t):
 try:
  r=requests.get(f'https://api.kartaview.org/2.0/sequence/tiles/{t.x}/{t.y}/{t.z}.json',timeout=70);r.raise_for_status();return t,r.json()['lines'],None
 except Exception as e:return t,[],type(e).__name__
with ThreadPoolExecutor(max_workers=3) as pool:
 for n,(t,lines,err) in enumerate(pool.map(fetch,tiles),1):
  if err:errors.append((t.x,t.y,err));continue
  for line in lines:
   try:
    track=line.get('track',[]);xs=[float(p['lng']) for p in track];ys=[float(p['lat']) for p in track]
    if len(xs)<2:continue
    x,y=conv.transform(xs,ys);g=LineString(zip(x,y));rows.append(g)
   except (ValueError,KeyError,TypeError):continue
  print(n,'/',len(tiles),'lines',len(rows),flush=True)
if errors: print('ERRORS',errors,flush=True);raise SystemExit('Tile failures; no coverage output')
gpd.GeoDataFrame({'geometry':rows},crs=26986).to_parquet(Path('data/kartaview_z9_lines.parquet'),index=False);print('Done',len(rows),flush=True)
