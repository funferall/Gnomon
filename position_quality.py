"""Position QA and reversible sequence translation proposals; source coordinates remain immutable."""
import argparse,concurrent.futures,json,math,sqlite3,datetime as dt
from pathlib import Path
from collections import defaultdict
import numpy as np
import geopandas as gpd
from shapely.geometry import Point,box
from shapely.ops import nearest_points,unary_union
from pyproj import Transformer
from wellesley_pipeline import ROOT,OUT,graph,now
TO=Transformer.from_crs(4326,26986,always_xy=True);BACK=Transformer.from_crs(26986,4326,always_xy=True)
def setup(c):
 c.executescript('''CREATE TABLE IF NOT EXISTS image_pose_metadata(provider TEXT,image_id TEXT,payload TEXT,checked_at TEXT,PRIMARY KEY(provider,image_id));
 CREATE TABLE IF NOT EXISTS position_qa(provider TEXT,image_id TEXT,sequence TEXT,nearest_road TEXT,road_distance_m REAL,flags TEXT,PRIMARY KEY(provider,image_id));
 CREATE TABLE IF NOT EXISTS sequence_alignments(sequence TEXT PRIMARY KEY,dx_m REAL,dy_m REAL,target_road TEXT,statistics TEXT,status TEXT,reviewer TEXT,note TEXT,updated_at TEXT);
 CREATE TABLE IF NOT EXISTS alignment_events(id INTEGER PRIMARY KEY AUTOINCREMENT,sequence TEXT,before_json TEXT,after_json TEXT,created_at TEXT);''');c.commit()
def roads():
 r=gpd.read_file('zip://'+str(ROOT/'data/tiger_roads/tl_2024_25021_roads.zip')).to_crs(26986);return r[r.MTFCC.isin(['S1100','S1200','S1400','S1630'])].reset_index(drop=True)
def enrich(c,sequence):
 rows=[]
 for i,raw in c.execute("select id,raw from images where provider='mapillary'"):
  if json.loads(raw).get('sequence')==sequence:rows.append(i)
 def fetch(i):
  cached=cached_ids.get(i)
  if cached:return i,cached
  try:return i,graph(i,{'fields':'id,geometry,computed_geometry,compass_angle,computed_compass_angle,sequence'})
  except Exception as e:return i,{'error':type(e).__name__}
 cached_ids={i:json.loads(raw) for i,raw in c.execute("select image_id,payload from image_pose_metadata where provider='mapillary'")}
 with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(fetch,rows))
 with c:
  c.executemany('insert or replace into image_pose_metadata values(?,?,?,?)',[('mapillary',i,json.dumps(p),now()) for i,p in results if 'error' not in p])
 print('Enriched',len(rows),'sequence image records',flush=True)
def qa(c):
 r=roads();tree=__import__('shapely').STRtree(r.geometry.array);rows=c.execute('select provider,id,lon,lat,raw from images').fetchall();xy=np.array([TO.transform(x,y) for provider,i,x,y,raw in rows]);pts=__import__('shapely').points(xy);pairs,dist=tree.query_nearest(pts,all_matches=False,return_distance=True);data=[];groups=defaultdict(list)
 for k,row in enumerate(rows):
  raw=json.loads(row[4]);seq=raw.get('sequence') or raw.get('collection')
  if row[0]=='mapillary' and seq:groups[seq].append((raw.get('captured_at',0),k))
 travel={}
 for seq,values in groups.items():
  values.sort()
  for n,(_,idx) in enumerate(values):
   left=values[max(0,n-1)][1];right=values[min(len(values)-1,n+1)][1];v=xy[right]-xy[left]
   if np.linalg.norm(v)>3:travel[idx]=v/np.linalg.norm(v)
 for point_index,road_index,d in zip(pairs[0],pairs[1],dist):
  provider,i,x,y,raw=rows[point_index];raw=json.loads(raw);seq=raw.get('sequence') or raw.get('collection');flags=[]
  if d>30:flags.append('over_30m_from_mapped_road')
  if d>100:flags.append('over_100m_from_mapped_road')
  road=r.geometry.iloc[road_index]
  if point_index in travel:
   at=road.project(Point(*xy[point_index]));a=road.interpolate(max(0,at-5));b=road.interpolate(min(road.length,at+5));v=np.array([b.x-a.x,b.y-a.y]);length=np.linalg.norm(v)
   if length>0:
    angle=float(np.degrees(np.arccos(np.clip(abs(np.dot(travel[point_index],v/length)),0,1))))
    if angle>45:flags.append('track_direction_disagrees_with_nearest_road')
  data.append((provider,i,seq,str(r.iloc[road_index].FULLNAME or 'unnamed'),float(d),json.dumps(flags)))
 c.executemany('insert or replace into position_qa values(?,?,?,?,?,?)',data);c.commit();print('QA images',len(data),'flagged_any_rule',sum(json.loads(x[-1])!=[] for x in data),flush=True)
def propose(c,sequence,target):
 rows=[]
 for provider,i,x,y,captured,raw in c.execute('select provider,id,lon,lat,captured,raw from images'):
  if (json.loads(raw).get('sequence') or json.loads(raw).get('collection'))==sequence:rows.append((provider,i,x,y,captured))
 if len(rows)<3:raise ValueError('At least three inventoried images are required.')
 rows.sort(key=lambda r:r[4] or '');xy=np.array([TO.transform(r[2],r[3]) for r in rows]);ref=roads();ref=ref[(ref.FULLNAME==target)&(ref.distance(Point(*xy.mean(axis=0)))<1500)]
 if ref.empty:raise ValueError('Target street not found near the sequence.')
 line=unary_union(ref.geometry);delta=np.array([[q.x-p[0],q.y-p[1]] for p in xy for q in [nearest_points(Point(*p),line)[1]]]);shift=np.median(delta,axis=0);before=[Point(*p).distance(line) for p in xy];after=[Point(*(p+shift)).distance(line) for p in xy]
 if np.linalg.norm(shift)>200:raise ValueError('Offset too large for this translation proposal.')
 lengths=np.linalg.norm(np.diff(xy,axis=0),axis=1);stats={'images':len(rows),'road_reference':'Census TIGER 2024 S1100/S1200/S1400/S1630; not surveyed ground truth','before_median_m':float(np.median(before)),'before_p90_m':float(np.percentile(before,90)),'after_median_m':float(np.median(after)),'after_p90_m':float(np.percentile(after,90)),'translation_magnitude_m':float(np.linalg.norm(shift)),'capture_start':rows[0][4],'capture_end':rows[-1][4],'warning':'Proposed translation fitted to a named road, NOT verified position accuracy. Along-road error is unobservable from a straight parallel road; validate visual tie points and lane offset before approval.'}
 old=c.execute('select * from sequence_alignments where sequence=?',(sequence,)).fetchone()
 if old and old[5]=='approved':raise ValueError('Existing approved alignment must be reverted before proposing another.')
 c.execute('insert or replace into sequence_alignments values(?,?,?,?,?,?,?,?,?)',(sequence,float(shift[0]),float(shift[1]),target,json.dumps(stats),'proposed','', 'User reported offset; matching street visible in source context; review required.',now()));c.commit();print(json.dumps(stats,indent=2))
def export(c):
 align={r[0]:{'dx_m':r[1],'dy_m':r[2],'target_road':r[3],'statistics':json.loads(r[4]),'status':r[5],'reviewer':r[6],'note':r[7]} for r in c.execute('select * from sequence_alignments')};metadata={r[0]+':'+r[1]:json.loads(r[2]) for r in c.execute('select provider,image_id,payload from image_pose_metadata')};flags={r[0]+':'+r[1]:{'nearest_road':r[2],'road_distance_m':r[3],'flags':json.loads(r[4])} for r in c.execute('select provider,image_id,nearest_road,road_distance_m,flags from position_qa')};items={};geo=[]
 for provider,i,lon,lat,captured,raw in c.execute('select provider,id,lon,lat,captured,raw from images'):
  raw=json.loads(raw);seq=raw.get('sequence') or raw.get('collection');a=align.get(seq);key=provider+':'+i;f=flags.get(key,{});meta=metadata.get(key,{});item={'original':[lon,lat],'sequence':seq,**f}
  if meta.get('computed_geometry'):item['computed']=meta['computed_geometry']['coordinates']
  if a:
   start=a['statistics'].get('capture_start');end=a['statistics'].get('capture_end')
   try:inside=bool(captured and start and end and dt.datetime.fromisoformat(start)<=dt.datetime.fromisoformat(captured)<=dt.datetime.fromisoformat(end))
   except ValueError:inside=False
   if not inside:
    item['flags']=item.get('flags',[])+['outside_proposal_capture_interval'];a=None
  if a:
   x,y=TO.transform(lon,lat);item['proposal']=list(BACK.transform(x+a['dx_m'],y+a['dy_m']));item['alignment']=a;geo.append({'type':'Feature','geometry':{'type':'LineString','coordinates':[[lon,lat],item['proposal']]},'properties':{'provider':provider,'image_id':i,'sequence':seq,'status':a['status']}})
  # Keep the browser file small: include suspect, aligned or enriched images.
  if a or meta or item.get('flags'):items[key]=item
 (OUT/'position-quality.json').write_text(json.dumps({'updated_at':now(),'images':items,'alignments':align},ensure_ascii=False),encoding='utf-8');(OUT/'position-shifts.geojson').write_text(json.dumps({'type':'FeatureCollection','features':geo}),encoding='utf-8');print('Browser position records',len(items),flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('command',choices=['qa','enrich','propose','export']);p.add_argument('--sequence');p.add_argument('--road');a=p.parse_args();c=sqlite3.connect(OUT/'inventory.sqlite',timeout=30);setup(c)
 if a.command=='qa':qa(c)
 if a.command=='enrich':enrich(c,a.sequence)
 if a.command=='propose':propose(c,a.sequence,a.road)
 export(c)
