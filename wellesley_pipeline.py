"""Resumable Wellesley inventory and candidate extraction. No surveyed asset coordinates inferred."""
import argparse, datetime as dt, hashlib, json, math, os, sqlite3, time
from pathlib import Path
import requests

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'data'/'wellesley'; OUT.mkdir(exist_ok=True)
from asset_taxonomy import LABELS,VERSION as TAXONOMY_VERSION
def now(): return dt.datetime.now(dt.timezone.utc).isoformat()
def token():
 v=os.getenv('MAPILLARY_ACCESS_TOKEN')
 if not v:
  for line in (ROOT/'.env').read_text(encoding='utf-8-sig').splitlines():
   k,sep,value=line.partition('=')
   if sep and k.strip()=='MAPILLARY_ACCESS_TOKEN':v=value.strip().strip('"').strip("'")
 if not v:raise RuntimeError('MAPILLARY_ACCESS_TOKEN missing')
 return v

def db():
 c=sqlite3.connect(OUT/'inventory.sqlite',timeout=30);c.execute('pragma busy_timeout=30000');c.execute('pragma journal_mode=WAL');c.execute('pragma foreign_keys=ON')
 c.executescript('''CREATE TABLE IF NOT EXISTS queries(key TEXT PRIMARY KEY,bbox TEXT,cursor TEXT,done INTEGER DEFAULT 0,error TEXT,pages INTEGER DEFAULT 0);
 CREATE TABLE IF NOT EXISTS images(provider TEXT,id TEXT,lon REAL,lat REAL,captured TEXT,raw TEXT,rights TEXT,status TEXT DEFAULT 'pending',sha256 TEXT,error TEXT,PRIMARY KEY(provider,id));
 CREATE TABLE IF NOT EXISTS observations(id TEXT PRIMARY KEY,provider TEXT,image_id TEXT,label TEXT,score REAL,box TEXT,crop TEXT,model TEXT,review TEXT DEFAULT 'unreviewed',FOREIGN KEY(provider,image_id) REFERENCES images(provider,id));
 CREATE TABLE IF NOT EXISTS assets(id TEXT PRIMARY KEY,class TEXT,lon REAL,lat REAL,uncertainty_m REAL,method TEXT,review TEXT,valid_from TEXT,valid_to TEXT);
 CREATE TABLE IF NOT EXISTS evidence(asset_id TEXT,observation_id TEXT,PRIMARY KEY(asset_id,observation_id),FOREIGN KEY(asset_id) REFERENCES assets(id),FOREIGN KEY(observation_id) REFERENCES observations(id));''');return c

def boundary():
 import geopandas as gpd
 return gpd.read_file('zip://'+str(ROOT/'data/towns.zip')).query("NAME=='Wellesley'").to_crs(4326).geometry.iloc[0]

def graph(path,params):
 for attempt in range(5):
  try:
   r=requests.get('https://graph.mapillary.com/'+path,params=params,headers={'Authorization':'OAuth '+token()},timeout=60)
   if r.status_code==429 or r.status_code>=500:
    time.sleep(min(30,2**attempt));continue
   if not r.ok:raise RuntimeError('Graph HTTP '+str(r.status_code))
   return r.json()
  except requests.RequestException:
   if attempt==4:raise RuntimeError('Graph transport failed') from None
   time.sleep(2**attempt)
 raise RuntimeError('Graph retry budget exhausted')

def inventory(c,max_pages):
 from shapely.geometry import box,Point
 import pandas as pd
 town=boundary();town_json={'type':'FeatureCollection','features':[{'type':'Feature','properties':{'name':'Wellesley'},'geometry':__import__('shapely').geometry.mapping(town)}]};(OUT/'boundary.geojson').write_text(json.dumps(town_json),encoding='utf-8')
 x0,y0,x1,y1=town.bounds
 for ix in range(math.ceil((x1-x0)/.01)):
  for iy in range(math.ceil((y1-y0)/.01)):
   b=[x0+ix*.01,y0+iy*.01,min(x1,x0+(ix+1)*.01),min(y1,y0+(iy+1)*.01)]
   if town.intersects(box(*b)):c.execute('insert or ignore into queries(key,bbox) values(?,?)',(f'{ix}:{iy}',','.join(map(str,b))))
 c.commit()
 pan=ROOT/'data/panoramax_massachusetts_images.csv'
 if pan.exists():
  for _,r in pd.read_csv(pan).iterrows():
   if not town.covers(Point(r.lon,r.lat)):continue
   raw={k:(None if pd.isna(v) else v) for k,v in r.to_dict().items()};rights={'license':r.license,'basis':'federated catalog record','source_url':str(r.instance_url)+'/api/pictures/'+str(r.id),'retrieved_at':now(),'creator':r.producer}
   c.execute('insert or ignore into images(provider,id,lon,lat,captured,raw,rights) values(?,?,?,?,?,?,?)',('panoramax',str(r.id),r.lon,r.lat,r.captured_at,json.dumps(raw),json.dumps(rights)))
 c.commit();pages=0
 for key,bbox,cursor in c.execute('select key,bbox,cursor from queries where done=0 order by key').fetchall():
  while True:
   if max_pages and pages>=max_pages:return
   params={'bbox':bbox,'fields':'id,geometry,captured_at,compass_angle,is_pano,sequence','limit':2000}
   if cursor:params['after']=cursor
   try:j=graph('images',params)
   except RuntimeError as e:
    b=list(map(float,bbox.split(',')))
    if (b[2]-b[0])>.0026 and ('retry' in str(e) or 'transport' in str(e) or 'HTTP 500' in str(e)):
     mx=(b[0]+b[2])/2;my=(b[1]+b[3])/2
     for n,child in enumerate([[b[0],b[1],mx,my],[mx,b[1],b[2],my],[b[0],my,mx,b[3]],[mx,my,b[2],b[3]]]):
      c.execute('insert or ignore into queries(key,bbox) values(?,?)',(key+'/'+str(n),','.join(map(str,child))))
     c.execute('update queries set done=1,error=? where key=?',('subdivided after API failure',key))
    else:c.execute('update queries set error=? where key=?',(str(e),key))
    c.commit();print(key,str(e),flush=True);break
   for r in j.get('data',[]):
    lon,lat=r['geometry']['coordinates'][:2]
    if not town.covers(Point(lon,lat)):continue
    captured=dt.datetime.fromtimestamp(r['captured_at']/1000,dt.timezone.utc).isoformat() if r.get('captured_at') else None
    rights={'license':'provider terms apply; individual notice not retrieved yet','terms_url':'https://www.mapillary.com/terms','source_url':'https://www.mapillary.com/app/?pKey='+r['id'],'retrieved_at':now()}
    c.execute('insert or ignore into images(provider,id,lon,lat,captured,raw,rights) values(?,?,?,?,?,?,?)',('mapillary',r['id'],lon,lat,captured,json.dumps(r),json.dumps(rights)))
   paging=j.get('paging',{});nxt=paging.get('cursors',{}).get('after') if paging.get('next') else None
   if nxt and nxt==cursor:raise RuntimeError('Pagination cursor repeated; inventory not complete')
   c.execute('update queries set cursor=?,done=?,pages=pages+1,error=NULL where key=?',(nxt,int(not nxt),key));c.commit();cursor=nxt;pages+=1
   print('inventory page',pages,'cell',key,'images',c.execute('select count(*) from images').fetchone()[0],flush=True)
   if not cursor:break
   time.sleep(.15)

def views(im, pano):
 if not pano:
  yield 'flat',im
  return
 import cv2,numpy as np
 from PIL import Image
 size=768;v=(np.arange(size,dtype=np.float32)+.5)/size*2-1;x,y=np.meshgrid(v,-v)
 for name,yaw,pitch in [('front',0,0),('right',90,0),('back',180,0),('left',270,0),('up',0,90),('down',0,-90)]:
  z=np.ones_like(x);a=np.deg2rad(pitch);rx=x;ry=y*np.cos(a)+z*np.sin(a);rz=-y*np.sin(a)+z*np.cos(a);a=np.deg2rad(yaw);xx=rx*np.cos(a)+rz*np.sin(a);zz=-rx*np.sin(a)+rz*np.cos(a)
  lon=np.arctan2(xx,zz);lat=np.arctan2(ry,np.sqrt(xx**2+zz**2));mx=((lon/(2*np.pi)+.5)*im.width).astype(np.float32);my=np.clip((.5-lat/np.pi)*im.height,0,im.height-1).astype(np.float32)
  yield name,Image.fromarray(cv2.remap(np.array(im),mx,my,cv2.INTER_LINEAR,borderMode=cv2.BORDER_WRAP))

_MODEL=None

def fetch_image(row):
 provider,i,raw,rights=row;r=json.loads(raw);rights=json.loads(rights);start=time.perf_counter();base=OUT/'images'/provider;file=base/(i+'.jpg');side=base/(i+'.rights.json')
 try:
  cached=json.loads(side.read_text(encoding='utf-8')) if side.exists() else {}
  if file.exists() and cached.get('source_bytes_saved'):
   data=file.read_bytes();rights=cached
  else:
   if provider=='mapillary':
    meta=graph(i,{'fields':'id,thumb_2048_url,creator'});url=meta['thumb_2048_url'];rights.update(creator=meta.get('creator'),metadata_checked_at=now())
   else:url=r['image_url']
   response=requests.get(url,timeout=60)
   if not response.ok:raise RuntimeError('Image HTTP '+str(response.status_code))
   data=response.content
  return row,r,rights,data,start,time.perf_counter()-start,None
 except Exception as e:return row,r,rights,None,start,time.perf_counter()-start,type(e).__name__

def scan(c,limit):
 from PIL import Image
 from io import BytesIO
 from ultralytics import YOLOWorld
 global _MODEL
 if _MODEL is None:
  _MODEL=YOLOWorld(str(ROOT/'yolov8s-worldv2.pt'));_MODEL.set_classes(LABELS)
 model=_MODEL
 rows=c.execute("select provider,id,raw,rights from images where status='pending' order by captured desc limit ?",(limit if limit else -1,)).fetchall()
 from concurrent.futures import ThreadPoolExecutor
 from collections import deque
 pool=ThreadPoolExecutor(max_workers=2);source=iter(rows);pending=deque()
 for _ in range(2):
  row=next(source,None)
  if row:pending.append(pool.submit(fetch_image,row))
 batch_start=time.perf_counter();index=0
 while pending:
  result=pending.popleft().result();row,r,rights,data,started,fetch_seconds,error=result;provider,i,raw,_=row
  nxt=next(source,None)
  if nxt:pending.append(pool.submit(fetch_image,nxt))
  index+=1;post_start=time.perf_counter();inference_ms=0;view_count=0
  try:
   if error:raise RuntimeError(error)
   digest=hashlib.sha256(data).hexdigest();im=Image.open(BytesIO(data)).convert('RGB');base=OUT/'images'/provider;base.mkdir(parents=True,exist_ok=True);(base/(i+'.jpg')).write_bytes(data)
   rights.update(source_image_sha256=digest,source_bytes_saved=True);(base/(i+'.rights.json')).write_text(json.dumps(rights,indent=2),encoding='utf-8')
   candidate_count=0
   projected=list(views(im,r.get('is_pano',False)))
   # Microbatch three views at once; fp32 and detector thresholds stay unchanged.
   predicted=[]
   for k in range(0,len(projected),3):predicted.extend(model.predict([v for name,v in projected[k:k+3]],conf=.2,imgsz=1280,device=0,verbose=False))
   for (view_name,view),result in zip(projected,predicted):
    view_count+=1;inference_ms+=result.speed.get('inference',0)
    viewdir=OUT/'views'/provider;viewdir.mkdir(parents=True,exist_ok=True);viewfile=viewdir/f'{i}_{view_name}.jpg';view.save(viewfile)
    for n,b in enumerate(result.boxes):
     coords=[round(float(v),2) for v in b.xyxy[0]];obs=f'{provider}:{i}:{TAXONOMY_VERSION}:{view_name}:{n}';crop=OUT/'crops'/provider;crop.mkdir(parents=True,exist_ok=True);file=crop/f'{i}_{view_name}_{n}.jpg';view.crop(tuple(coords)).save(file)
     c.execute('insert or replace into observations(id,provider,image_id,label,score,box,crop,model) values(?,?,?,?,?,?,?,?)',(obs,provider,i,LABELS[int(b.cls.item())],float(b.conf.item()),json.dumps({'xyxy':coords,'width':view.width,'height':view.height,'view':view_name,'projection':{'fov_deg':90 if r.get('is_pano') else None,'relative_yaw_deg':{'front':0,'right':90,'back':180,'left':270,'up':0,'down':0}.get(view_name),'relative_pitch_deg':{'up':90,'down':-90}.get(view_name,0)},'view_file':str(viewfile.relative_to(ROOT)).replace('\\','/')}),str(file.relative_to(ROOT)).replace('\\','/'),'yolov8s-worldv2; imgsz1280; conf0.2; vocabulary routing-v2; CUDA; fp32; microbatch3; polefix'))
     candidate_count+=1
   c.execute('update images set status=?,sha256=?,rights=?,error=NULL where provider=? and id=?',('scanned',digest,json.dumps(rights),provider,i));c.commit();print('scan',index,'/',len(rows),provider,i,candidate_count,'candidates',flush=True)
  except Exception as e:
   # Never serialize request exceptions: their URLs can include credentials.
   c.rollback();c.execute('update images set status=?,error=? where provider=? and id=?',('failed',type(e).__name__,provider,i));c.commit();print('scan failed',provider,i,type(e).__name__,flush=True)
  with (OUT/'timings.jsonl').open('a',encoding='utf-8') as log:log.write(json.dumps({'image_id':i,'provider':provider,'completed_at':now(),'fetch_seconds':fetch_seconds,'post_fetch_seconds':time.perf_counter()-post_start,'image_latency_seconds':time.perf_counter()-started,'detector_inference_ms':inference_ms,'views':view_count})+'\n')
  if index%25==0:export(c)
 pool.shutdown(wait=True)
 export(c)
 with (OUT/'batch_timings.jsonl').open('a',encoding='utf-8') as log:log.write(json.dumps({'completed_at':now(),'images':len(rows),'seconds':time.perf_counter()-batch_start})+'\n')

def export(c):
 features=[]
 for provider,i,lon,lat,captured,raw,rights,status in c.execute("select provider,id,lon,lat,captured,raw,rights,status from images where status!='pending'"):
  r=json.loads(raw);rights=json.loads(rights);detections=[]
  for label,score,b,crop in c.execute('select label,score,box,crop from observations where provider=? and image_id=?',(provider,i)):
   b=json.loads(b);detections.append({'label':label,'confidence':round(score,3),'bbox_xyxy':b['xyxy'],'image_width':b['width'],'image_height':b['height'],'crop':crop,'view_file':b.get('view_file')})
  groups={}
  for d in detections:groups.setdefault(d.pop('view_file',None),[]).append(d)
  for viewfile,items in (groups.items() if groups else [(None,[])]):
   features.append({'type':'Feature','geometry':{'type':'Point','coordinates':[lon,lat]},'properties':{'image_id':i,'captured_at':captured,'producer':str(rights.get('creator','unknown')),'source_url':rights.get('source_url'),'license':rights.get('terms_url',rights.get('source_url')),'image_url':viewfile or f'data/wellesley/images/{provider}/{i}.jpg','detections':items,'scan_status':status,'location_type':'camera position; asset coordinates unverified'}})

 (OUT/'observations.geojson').write_text(json.dumps({'type':'FeatureCollection','features':features}),encoding='utf-8')
 summary={'updated_at':now(),'images_by_provider':dict(c.execute('select provider,count(*) from images group by provider')),'images_by_status':dict(c.execute('select status,count(*) from images group by status')),'queries':dict(c.execute('select case when done=1 then "completed" else "pending" end,count(*) from queries group by done')),'observations':c.execute('select count(*) from observations').fetchone()[0],'verified_assets':c.execute("select count(*) from assets where review='verified'").fetchone()[0]};(OUT/'status.json').write_text(json.dumps(summary,indent=2),encoding='utf-8');return summary

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('command',choices=['inventory','scan','status','retry']);p.add_argument('--limit',type=int,default=25,help='scan image or inventory page limit; 0 means all');a=p.parse_args();c=db()
 if a.command=='inventory':inventory(c,a.limit)
 if a.command=='scan':scan(c,a.limit)
 if a.command=='retry':c.execute("update images set status='pending' where status='failed'");c.commit()
 print(json.dumps(export(c),indent=2))
