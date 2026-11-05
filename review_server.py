"""Loopback-only persistent human review application. Run: python review_server.py"""
import argparse,json,secrets,sqlite3,uuid,math,mimetypes
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse,parse_qs,unquote
from review_store import connect,observation,ROOT,OUT,LABELS,now
TO_LONLAT=None
def lonlat(x,y):
 global TO_LONLAT
 if TO_LONLAT is None:
  from pyproj import Transformer;TO_LONLAT=Transformer.from_crs(26986,4326,always_xy=True)
 return TO_LONLAT.transform(x,y)
def table_exists(c,name):return bool(c.execute("select 1 from sqlite_master where type='table' and name=?",(name,)).fetchone())
def view_detections(c,provider,image_id,view_file):
 out=[]
 for r in c.execute('select o.id,o.label,o.score,o.box,h.decision,h.label human_label from observations o left join human_reviews h on h.observation_id=o.id where o.provider=? and o.image_id=?',(provider,image_id)):
  b=json.loads(r['box'])
  if b.get('view_file')==view_file:out.append({'id':r['id'],'label':r['label'],'score':r['score'],'box':b,'decision':r['decision'],'human_label':r['human_label']})
 return out
def workbench_context(c,x):
 # Machine geometry and estimate for one observation: provisional, never a reviewed position.
 x['geometry']=None;x['estimate']=None
 if table_exists(c,'observation_geometry'):
  g=c.execute('select state,azimuth_deg,elevation_deg,range_m,range_sigma_log,camera_x,camera_y,x,y,cues,flags from observation_geometry where observation_id=?',(x['id'],)).fetchone()
  if g:
   g=dict(g);g['cues']=json.loads(g['cues']);g['flags']=json.loads(g['flags']);g['camera']=list(lonlat(g.pop('camera_x'),g.pop('camera_y')));px,py=g.pop('x'),g.pop('y');g['position']=list(lonlat(px,py)) if px is not None else None;x['geometry']=g
 if table_exists(c,'asset_estimates'):
  e=c.execute('select a.id,a.class,a.state,a.lon,a.lat,a.uncertainty95_m,a.ellipse,a.n_observations,a.n_sequences,a.max_ray_angle_deg from asset_estimate_evidence v join asset_estimates a on a.id=v.asset_estimate_id where v.observation_id=?',(x['id'],)).fetchone()
  if e:
   e=dict(e);e['ellipse']=json.loads(e['ellipse']);rays=[]
   if table_exists(c,'observation_geometry'):
    for r in c.execute('select g.camera_x,g.camera_y from asset_estimate_evidence v join observation_geometry g on g.observation_id=v.observation_id where v.asset_estimate_id=?',(e['id'],)):rays.append(list(lonlat(r[0],r[1])))
   e['cameras']=rays;x['estimate']=e
 x['siblings']=view_detections(c,x['provider'],x['image_id'],x['box'].get('view_file'))
 x.pop('raw',None);return x
TOKEN=secrets.token_urlsafe(32)
def setup():
 c=connect();__import__('position_quality').setup(c);c.execute('create table if not exists frame_labels(benchmark_id TEXT,item_id TEXT,objects TEXT,reviewer TEXT,updated_at TEXT,PRIMARY KEY(benchmark_id,item_id))');c.commit();c.close()
def sync(c,oid,previous,current):
 if previous and previous.get('asset_id'):
  c.execute('delete from evidence where observation_id=?',(oid,));a=previous['asset_id'];remaining=c.execute('select count(*) from evidence where asset_id=?',(a,)).fetchone()[0]
  if not remaining:c.execute("update assets set review='withdrawn' where id=?",(a,))
 if current and current['decision'] in ['accept','duplicate'] and current.get('asset_id'):
  a=current['asset_id']
  if current['decision']=='accept':c.execute('insert into assets(id,class,lon,lat,uncertainty_m,method,review) values(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET class=excluded.class,lon=excluded.lon,lat=excluded.lat,uncertainty_m=excluded.uncertainty_m,method=excluded.method,review=excluded.review',(a,current['label'],current['lon'],current['lat'],current['uncertainty_m'],'manual_map','human_placed'))
  else:c.execute("update assets set review='human_placed' where id=? and review='withdrawn'",(a,))
  c.execute('insert or ignore into evidence values(?,?)',(a,oid))

def save(c,p):
 oid=p.get('id');o=observation(c,oid)
 if not o:raise ValueError('Observation not found')
 previous=o['human'];rev=previous['revision'] if previous else 0
 if p.get('revision')!=rev:raise FileExistsError('This item changed. Reload before saving.')
 decision=p.get('decision');label=p.get('label');reviewer=str(p.get('reviewer','')).strip()
 if decision not in ['accept','reject','uncertain','duplicate'] or label not in LABELS+['unknown'] or not reviewer:raise ValueError('Choose a decision, class and reviewer name.')
 def number(name,minv,maxv):
  v=p.get(name)
  if v is None or v=='':return None
  if isinstance(v,bool):raise ValueError('Invalid '+name)
  v=float(v)
  if not math.isfinite(v) or not minv<=v<=maxv:raise ValueError('Invalid '+name)
  return v
 lon=number('lon',-180,180);lat=number('lat',-90,90);unc=number('uncertainty_m',.1,10000);distance=number('distance_m',0,10000)
 if (lon is None)!=(lat is None):raise ValueError('Place both latitude and longitude.')
 if lon is not None and not(-71.36<=lon<=-71.20 and 42.24<=lat<=42.36):raise ValueError('Place the asset within or near Wellesley.')
 if lon is not None and unc is None:raise ValueError('Enter the placement uncertainty in meters.')
 if distance is not None and not str(p.get('distance_basis','')).strip():raise ValueError('Record how distance was measured or estimated.')
 aid=None
 role=str(p.get('routing_role','unknown'))
 if role not in ['turn_restriction','access_restriction','speed_limit','one_way','intersection_control','street_name','infrastructure','none','unknown']:raise ValueError('Invalid routing role')
 if decision in ['accept','duplicate'] and role in ['unknown','none']:raise ValueError('Choose the routing role or explicit infrastructure exception before accepting.')
 if decision in ['accept','duplicate'] and label=='unknown':raise ValueError('Choose an in-scope class before accepting or linking an asset.')
 if decision=='accept' and lon is not None:aid=(previous or {}).get('asset_id') if (previous or {}).get('decision')=='accept' else None;aid=aid or 'asset-'+uuid.uuid4().hex[:16]
 if decision=='duplicate':
  aid=str(p.get('asset_id','')).strip()
  if not c.execute("select 1 from assets where id=? and review='human_placed'",(aid,)).fetchone():raise ValueError('Choose an existing placed asset for the duplicate.')
 current={'observation_id':oid,'decision':decision,'label':label,'text':str(p.get('text',''))[:2000],'lon':lon,'lat':lat,'uncertainty_m':unc,'distance_m':distance,'distance_basis':str(p.get('distance_basis',''))[:500],'routing_role':role,'visibility':str(p.get('visibility','unknown'))[:50],'occlusion':str(p.get('occlusion','unknown'))[:50],'notes':str(p.get('notes',''))[:4000],'reviewer':reviewer[:100],'asset_id':aid,'revision':rev+1,'updated_at':now()}
 with c:
  # Serialize revision checks with other review writers.
  existing=c.execute('select revision from human_reviews where observation_id=?',(oid,)).fetchone()
  if (existing[0] if existing else 0)!=rev:raise FileExistsError('Concurrent change. Reload.')
  columns=list(current);c.execute('insert or replace into human_reviews('+','.join(columns)+') values('+','.join('?' for _ in columns)+')',list(current.values()));sync(c,oid,previous,current);c.execute('insert into review_events(observation_id,before_json,after_json,created_at) values(?,?,?,?)',(oid,json.dumps(previous),json.dumps(current),now()))
 return current

class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def respond(self,value,code=200):
  data=json.dumps(value,ensure_ascii=False).encode();self.send_response(code);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
 def do_GET(self):
  try:self.get()
  except (ValueError,KeyError) as e:self.respond({'error':str(e)},400)
  except Exception:self.respond({'error':'Request failed; refresh and retry.'},500)
 def get(self):
  u=urlparse(self.path);q={k:v[0] for k,v in parse_qs(u.query).items()};path=unquote(u.path);c=connect()
  try:
   if path=='/api/session':return self.respond({'token':TOKEN,'labels':LABELS,'benchmarks':[dict(r) for r in c.execute('select benchmark_id,count(*) items from benchmark_items group by benchmark_id')]})
   if path=='/api/stats':return self.respond({'images':dict(c.execute('select status,count(*) from images group by status')),'observations':c.execute('select count(*) from observations').fetchone()[0],'reviews':dict(c.execute('select decision,count(*) from human_reviews group by decision')),'placed_assets':c.execute("select count(*) from assets where review='human_placed'").fetchone()[0],'ai':c.execute('select count(*) from verifications').fetchone()[0]})
   if path=='/api/observation':
    r=observation(c,q.get('id'));return self.respond(workbench_context(c,r) if r else {'error':'Not found'},200 if r else 404)
   if path=='/api/cameras':
    rows=c.execute('select i.provider,i.id,i.lon,i.lat,count(o.id),count(h.observation_id) from images i join observations o on o.provider=i.provider and o.image_id=i.id left join human_reviews h on h.observation_id=o.id group by i.provider,i.id').fetchall()
    return self.respond({'fields':['provider','image_id','lon','lat','detections','reviewed'],'cameras':[list(r) for r in rows]})
   if path=='/api/estimates':
    if not table_exists(c,'asset_estimates'):return self.respond({'fields':[],'estimates':[]})
    rows=c.execute('select a.id,a.class,a.state,a.lon,a.lat,a.uncertainty95_m,a.n_observations,(select min(observation_id) from asset_estimate_evidence v where v.asset_estimate_id=a.id) from asset_estimates a').fetchall()
    return self.respond({'fields':['id','class','state','lon','lat','uncertainty95_m','n_observations','observation_id'],'estimates':[list(r) for r in rows]})
   if path=='/api/queue':
    where=[];args=[];joins=''
    if q.get('benchmark'):joins=' join benchmark_items b on b.observation_id=o.id and b.kind="candidate" ';where.append('b.benchmark_id=?');args.append(q['benchmark'])
    if q.get('label'):where.append('o.label=?');args.append(q['label'])
    if q.get('status','unreviewed')=='unreviewed':where.append('h.observation_id is null')
    elif q.get('status')=='reviewed':where.append('h.observation_id is not null')
    if q.get('search'):where.append('(o.id like ? or h.text like ?)');args.extend(['%'+q['search']+'%']*2)
    sort={'low':'o.score asc','high':'o.score desc','new':'i.captured desc','old':'i.captured asc'}.get(q.get('sort'),'o.id');clause=' where '+' and '.join(where) if where else ''
    base=' from observations o join images i on o.provider=i.provider and o.image_id=i.id left join human_reviews h on h.observation_id=o.id '+joins+clause
    total=c.execute('select count(*)'+base,args).fetchone()[0];limit=min(100,max(1,int(q.get('limit',60))));offset=max(0,int(q.get('offset',0)));rows=c.execute('select o.id,o.label,o.score,o.crop,i.captured,h.decision'+base+' order by '+sort+' limit ? offset ?',args+[limit,offset]).fetchall();return self.respond({'total':total,'items':[dict(r) for r in rows]})
   if path=='/api/image-neighbor':
    current=c.execute('select * from images where provider=? and id=?',(q.get('provider'),q.get('image_id'))).fetchone()
    if not current:raise ValueError('Current image not found')
    direction=int(q.get('direction',1));direction=1 if direction>0 else -1 if direction<0 else 0;candidate=current if direction==0 else None;fallback=False
    raw=json.loads(current['raw']);sequence=raw.get('sequence') or raw.get('collection')
    compare='>' if direction>=0 else '<';order='asc' if direction>=0 else 'desc';where=' where status="scanned" and (coalesce(captured,""),provider,id) '+compare+' (?,?,?)';args=[current['captured'] or '',current['provider'],current['id']]
    if candidate is None and q.get('order','sequence')=='sequence' and sequence:
     candidate=c.execute('select * from images'+where+' and provider=? and coalesce(json_extract(raw,"$.sequence"),json_extract(raw,"$.collection"))=? order by coalesce(captured,"") '+order+',provider '+order+',id '+order+' limit 1',args+[current['provider'],sequence]).fetchone()
    if candidate is None and direction:
     candidate=c.execute('select * from images'+where+' order by coalesce(captured,"") '+order+',provider '+order+',id '+order+' limit 1',args).fetchone();fallback=q.get('order','sequence')=='sequence'
    if not candidate:return self.respond({'end':True})
    candidate=dict(candidate);base=ROOT/'data/wellesley/views'/candidate['provider'];views=sorted(base.glob(candidate['id']+'_*.jpg'));names={v.stem.rsplit('_',1)[-1]:str(v.relative_to(ROOT)).replace('\\','/') for v in views};preferred=q.get('view','front');preferred=preferred if preferred in names else 'flat' if 'flat' in names else 'front' if 'front' in names else next(iter(names),'')
    viewfile=names.get(preferred,f"data/wellesley/images/{candidate['provider']}/{candidate['id']}.jpg");observations=view_detections(c,candidate['provider'],candidate['id'],viewfile)
    return self.respond({'image':{'provider':candidate['provider'],'image_id':candidate['id'],'captured':candidate['captured'],'camera_lon':candidate['lon'],'camera_lat':candidate['lat'],'rights':json.loads(candidate['rights'])},'view_file':viewfile,'view_name':preferred,'views':list(names),'observations':observations,'sequence_fallback':fallback})
   if path=='/api/assets':
    features=[]
    for a in c.execute("select * from assets where review='human_placed'"):
     a=dict(a);rights=[json.loads(r[0]) for r in c.execute('select i.rights from evidence e join observations o on e.observation_id=o.id join images i on i.id=o.image_id and i.provider=o.provider where e.asset_id=?',(a['id'],))];features.append({'type':'Feature','geometry':{'type':'Point','coordinates':[a.pop('lon'),a.pop('lat')]},'properties':{**a,'rights':rights}})
    return self.respond({'type':'FeatureCollection','features':features})
   if path=='/api/audits':
    base=' from benchmark_items b join images i on b.provider=i.provider and b.image_id=i.id left join frame_labels f on b.benchmark_id=f.benchmark_id and b.item_id=f.item_id where b.benchmark_id=? and b.kind="frame_audit"';args=[q.get('benchmark')]
    if q.get('status','unreviewed')=='unreviewed':base+=' and f.item_id is null'
    elif q.get('status')=='reviewed':base+=' and f.item_id is not null'
    total=c.execute('select count(*)'+base,args).fetchone()[0];rows=c.execute('select b.*,f.objects,i.lon camera_lon,i.lat camera_lat'+base+' order by b.item_id limit 60 offset ?',args+[max(0,int(q.get('offset',0)))]).fetchall();return self.respond({'total':total,'items':[dict(r) for r in rows]})
   if path=='/api/benchmark':
    r=ROOT/'data/wellesley/benchmarks'/(q.get('name','wellesley-seed-v1')+'.json')
    if r.parent.resolve()!=(ROOT/'data/wellesley/benchmarks').resolve():raise ValueError('Invalid name')
    return self.respond(json.loads(r.read_text()) if r.exists() else {})
   if path.startswith('/api/'):return self.respond({'error':'Not found'},404)
  finally:c.close()
  rel='workbench.html' if path=='/' else path.lstrip('/');file=(ROOT/rel).resolve()
  DATA_FILES={'data/wellesley/position-quality.json','data/wellesley/asset-estimates.geojson','data/wellesley/asset-estimates-summary.json','data/wellesley/ground_truth/wellesley_hydrants.geojson'}
  allowed=rel in ['workbench.html','static/workbench.css','static/workbench.js','static/vision-ocr.js','review.html','static/review.css','static/review.js','static/map-layers.js','static/camera-positions.js','assets.html','static/assets.css','static/asset-estimates.js','static/nav.js'] or rel in DATA_FILES or (rel.startswith('data/wellesley/') and file.suffix.lower() in ['.jpg','.png','.webp'] and any('/'+k+'/' in '/'+rel for k in ['crops','views','images']))
  if not file.is_relative_to(ROOT) or not allowed or (rel.startswith('data/') and rel not in DATA_FILES and not any(file.is_relative_to(ROOT/'data/wellesley'/k) for k in ['crops','views','images'])) or not file.is_file():return self.respond({'error':'Not found'},404)
  data=file.read_bytes();self.send_response(200);self.send_header('Content-Type',mimetypes.guess_type(str(file))[0] or 'application/octet-stream');self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-cache' if file.suffix in ['.html','.js','.css','.json'] else 'max-age=86400');self.end_headers();self.wfile.write(data)
 def do_POST(self):
  origin=self.headers.get('Origin');port=self.server.server_port
  if self.headers.get('X-Review-Token')!=TOKEN or (origin and origin not in [f'http://localhost:{port}',f'http://127.0.0.1:{port}']):return self.respond({'error':'Reload the local app session.'},403)
  try:
   n=int(self.headers.get('Content-Length','0'))
   if n<1 or n>500000:raise ValueError('Invalid payload size')
   p=json.loads(self.rfile.read(n));path=urlparse(self.path).path;c=connect();c.execute('begin immediate')
   try:
    if path=='/api/review':return self.respond(save(c,p))
    if path=='/api/undo':
     oid=p['id'];row=c.execute('select * from review_events where observation_id=? order by id desc limit 1',(oid,)).fetchone();current=c.execute('select * from human_reviews where observation_id=?',(oid,)).fetchone()
     if not row or not current:raise ValueError('Nothing to undo')
     if p.get('revision')!=current['revision']:raise FileExistsError('Item changed. Reload.')
     before=json.loads(row['before_json']);previous=dict(current)
     if before:
      before.update(revision=previous['revision']+1,updated_at=now());keys=list(before);c.execute('insert or replace into human_reviews('+','.join(keys)+') values('+','.join('?' for _ in keys)+')',list(before.values()))
     else:c.execute('delete from human_reviews where observation_id=?',(oid,))
     sync(c,oid,previous,before);c.execute('insert into review_events(observation_id,before_json,after_json,created_at) values(?,?,?,?)',(oid,json.dumps(previous),json.dumps(before),now()));c.commit();return self.respond({'restored':before})
    if path=='/api/alignment-review':
     sequence=str(p.get('sequence',''));status=p.get('status');reviewer=str(p.get('reviewer','')).strip();note=str(p.get('note','')).strip()
     if status not in ['approved','proposed'] or not reviewer or len(note)<10:raise ValueError('Enter reviewer initials and a note describing the visual tie-point checks (at least 10 characters).')
     row=c.execute('select * from sequence_alignments where sequence=?',(sequence,)).fetchone()
     if not row:raise ValueError('Alignment proposal not found')
     before=dict(row);c.execute('update sequence_alignments set status=?,reviewer=?,note=?,updated_at=? where sequence=?',(status,reviewer[:100],note[:2000],now(),sequence));after=dict(c.execute('select * from sequence_alignments where sequence=?',(sequence,)).fetchone());c.execute('insert into alignment_events(sequence,before_json,after_json,created_at) values(?,?,?,?)',(sequence,json.dumps(before),json.dumps(after),now()));c.commit();__import__('position_quality').export(c);return self.respond({'status':status})
    if path=='/api/frame-label':
     benchmark=p['benchmark'];item=p['item'];objects=p['objects']
     if not c.execute('select 1 from benchmark_items where benchmark_id=? and item_id=? and kind="frame_audit"',(benchmark,item)).fetchone():raise ValueError('Frame not found')
     if not isinstance(objects,list) or len(objects)>500:raise ValueError('Invalid objects')
     for obj in objects:
      if obj.get('label') not in LABELS+['unknown'] or len(obj.get('box',[]))!=4 or not all(isinstance(v,(int,float)) and math.isfinite(v) and v>=0 for v in obj['box']):raise ValueError('Invalid object box')
     reviewer=str(p.get('reviewer','')).strip()
     if not reviewer:raise ValueError('Reviewer required')
     c.execute('insert or replace into frame_labels values(?,?,?,?,?)',(benchmark,item,json.dumps(objects),reviewer[:100],now()));c.commit();return self.respond({'saved':len(objects)})
    self.respond({'error':'Unknown action'},404)
   finally:c.close()
  except FileExistsError as e:self.respond({'error':str(e)},409)
  except (ValueError,KeyError,TypeError) as e:self.respond({'error':str(e)},400)
  except Exception:self.respond({'error':'Save failed; your form is retained. Retry.'},500)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8001);a=p.parse_args();setup();print(f'Gnomon workbench: http://localhost:{a.port}  (benchmark labeling: /review.html)',flush=True);ThreadingHTTPServer(('127.0.0.1',a.port),Handler).serve_forever()
