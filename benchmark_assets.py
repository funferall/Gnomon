"""Freeze stratified candidate and no-detection-view audit samples; never invent labels."""
import argparse,collections,hashlib,json,random,math
from pathlib import Path
from review_store import connect,ROOT,LABELS,now

def split(raw,provider,image):
 key=provider+':'+str(raw.get('sequence') or raw.get('collection') or image);n=int(hashlib.sha256(key.encode()).hexdigest()[:8],16)%100
 return 'development' if n<60 else 'calibration' if n<80 else 'test'

def prepare(name,target):
 c=connect()
 if c.execute('select 1 from benchmark_items where benchmark_id=?',(name,)).fetchone():raise SystemExit('Benchmark already frozen; choose another name')
 groups=collections.defaultdict(list);rng=random.Random(20261104)
 for r in c.execute('select o.*,i.raw from observations o join images i on o.provider=i.provider and o.image_id=i.id'):
  b=json.loads(r['box']);x1,y1,x2,y2=b['xyxy'];px=min(x2-x1,y2-y1);size='under16' if px<16 else '16to31' if px<32 else '32to63' if px<64 else '64plus';conf='low' if r['score']<.35 else 'medium' if r['score']<.6 else 'high';raw=json.loads(r['raw']);sp=split(raw,r['provider'],r['image_id']);key=(r['label'],size,conf,sp);groups[key].append(dict(r))
 for a in groups.values():rng.shuffle(a)
 chosen=[];budget=round(target*.85)
 while len(chosen)<budget and any(groups.values()):
  for key in sorted(groups):
   if groups[key] and len(chosen)<budget:chosen.append((key,groups[key].pop()))
 with c:
  for key,r in chosen:
   c.execute('insert into benchmark_items values(?,?,?,?,?,?,?,?,?)',(name,r['id'],'candidate',r['id'],r['provider'],r['image_id'],json.loads(r['box']).get('view_file'),key[3],json.dumps(key[:3])))
 # Audit views sampled without conditioning on detections: needed to estimate detector misses.
 candidates=list((ROOT/'data/wellesley/views').rglob('*.jpg'));rng.shuffle(candidates);audits=0
 for file in candidates:
  if audits>=target-len(chosen):break
  provider=file.parent.name;i=file.stem.rsplit('_',1)[0];r=c.execute('select raw from images where provider=? and id=?',(provider,i)).fetchone()
  if not r:continue
  sp=split(json.loads(r[0]),provider,i);item='audit:'+provider+':'+file.stem
  c.execute('insert or ignore into benchmark_items values(?,?,?,?,?,?,?,?,?)',(name,item,'frame_audit',None,provider,i,str(file.relative_to(ROOT)).replace('\\','/'),sp,'full-view visible-object audit'));audits+=1
 c.commit();counts=dict(c.execute('select kind,count(*) from benchmark_items where benchmark_id=? group by kind',(name,)));report={'name':name,'frozen_at':now(),'target_total':target,'actual':counts,'candidate_class_counts':dict(c.execute('select o.label,count(*) from benchmark_items b join observations o on b.observation_id=o.id where b.benchmark_id=? group by o.label',(name,))),'notes':['Pixel-size strata are not physical distance. Measure or independently estimate distance and record its basis.','No human labels yet: AI agreement is not accuracy.','Adjacent frames in a sequence share split. Street-level grouping and cross-provider duplicate audit still needed before final held-out evaluation.','Sparse/missing classes must be enriched deliberately; this snapshot is a seed, not a comprehensive benchmark.']}
 out=ROOT/'data/wellesley/benchmarks';out.mkdir(exist_ok=True);(out/(name+'.json')).write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2))

def wilson(success,total):
 if not total:return None
 z=1.96;p=success/total;d=1+z*z/total;h=z*((p*(1-p)/total+z*z/(4*total*total))**.5)/d;mid=(p+z*z/(2*total))/d
 return [max(0,mid-h),min(1,mid+h)]

def iou(a,b):
 x=max(0,min(a[2],b[2])-max(a[0],b[0]));y=max(0,min(a[3],b[3])-max(a[1],b[1]));inter=x*y;union=(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-inter
 return inter/union if union>0 else 0

def frame_metrics(c,name):
 rows=c.execute('select b.*,f.objects from benchmark_items b join frame_labels f on b.benchmark_id=f.benchmark_id and b.item_id=f.item_id where b.benchmark_id=? and b.kind="frame_audit"',(name,)).fetchall();summary=[]
 for threshold in [.25,.5,.75]:
  stats=collections.defaultdict(collections.Counter);used=0
  for r in rows:
   truth=json.loads(r['objects'])
   if any(t['label']=='unknown' for t in truth):continue
   used+=1;pred=[]
   for o in c.execute('select label,score,box from observations where provider=? and image_id=? order by score desc',(r['provider'],r['image_id'])):
    b=json.loads(o['box'])
    if b.get('view_file')==r['view_file']:pred.append({'label':o['label'],'box':b['xyxy']})
   matched=set()
   for p in pred:
    choices=[(iou(p['box'],t['box']),i) for i,t in enumerate(truth) if i not in matched and t['label']==p['label']];best=max(choices,default=(0,None));key=(r['split'],p['label'])
    if best[0]>=threshold:matched.add(best[1]);stats[key]['tp']+=1
    else:stats[key]['fp']+=1
   for i,t in enumerate(truth):
    if i not in matched:stats[(r['split'],t['label'])]['fn']+=1
  for (sp,label),v in sorted(stats.items()):summary.append({'iou':threshold,'split':sp,'class':label,**v,'precision':v['tp']/(v['tp']+v['fp']) if v['tp']+v['fp'] else None,'recall':v['tp']/(v['tp']+v['fn']) if v['tp']+v['fn'] else None,'audited_frames':used})
 return {'labelled_frames':len(rows),'detector_metrics':summary}

def report(name):
 c=connect();rows=c.execute('select b.split,b.stratum,o.label,r.decision,r.label truth,r.text,r.distance_m,r.visibility,r.occlusion,v.response from benchmark_items b join observations o on o.id=b.observation_id left join human_reviews r on r.observation_id=o.id left join verifications v on v.cache_key=(select cache_key from verifications where observation_id=o.id and prompt_version="routing-v2-regulatory-context-v3" order by created_at desc limit 1) where b.benchmark_id=? and b.kind="candidate"',(name,)).fetchall();stats=collections.defaultdict(lambda:collections.Counter())
 for r in rows:
  distance='unknown' if r['distance_m'] is None else '0to5m' if r['distance_m']<5 else '5to15m' if r['distance_m']<15 else '15to30m' if r['distance_m']<30 else '30mplus'
  for group in [(r['split'],r['label'],'all'),(r['split'],r['label'],distance),(r['split'],r['label'],'visibility:'+str(r['visibility'] or 'unknown'))]:
   s=stats[group];s['items']+=1
   if not r['decision'] or r['decision']=='uncertain':continue
   s['human_labelled']+=1
   if not r['response']:continue
   a=json.loads(r['response']);s['paired']+=1;positive=r['decision'] in ['accept','duplicate'];pred=a['decision']=='accept';s['human_positive']+=positive
   if a['decision']=='uncertain':s['abstained']+=1;continue
   s['tp' if pred and positive else 'fp' if pred else 'fn' if positive else 'tn']+=1
   if positive and pred and a['correct_class']==r['truth']:s['class_correct']+=1
   if positive and pred and r['text'].strip():s['ocr_pairs']+=1;s['ocr_exact']+=a.get('visible_text','').strip()==r['text'].strip()
 out=[]
 for (sp,label,group),s in sorted(stats.items()):
  x={'split':sp,'yolo_class':label,'stratum':group,**s};den=s['tp']+s['fp'];x['precision']=s['tp']/den if den else None;x['precision_95ci']=wilson(s['tp'],den);x['positive_acceptance_rate']=s['tp']/s['human_positive'] if s['human_positive'] else None;x['abstention_rate']=s['abstained']/s['paired'] if s['paired'] else None;out.append(x)
 result={'benchmark':name,'metrics':out,'full_view_audits':frame_metrics(c,name),'warning':'No human truth means no hit rate. Sequence split still requires street/cross-provider leakage audit. Model-suggested labels are never human truth. Rejection/uncertainty must not silently discard potential routing controls.'};(ROOT/'data/wellesley/benchmarks'/f'{name}-metrics.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print('Wrote metrics; human paired cases:',sum(v.get('paired',0) for v in out if v['stratum']=='all'),'full-view audits:',result['full_view_audits']['labelled_frames'])

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('command',choices=['prepare','report']);p.add_argument('--name',default='wellesley-routing-v2');p.add_argument('--target',type=int,default=4000);a=p.parse_args();prepare(a.name,a.target) if a.command=='prepare' else report(a.name)
