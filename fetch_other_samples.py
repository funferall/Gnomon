import requests,json,datetime
from pathlib import Path
D=Path('data');(D/'licenses').mkdir(exist_ok=True);(D/'samples').mkdir(exist_ok=True)
sites={'kartaview_terms':'https://kartaview.org/terms','mapilio_license':'https://www.mapilio.com/licenses','mapilio_terms':'https://mapilio.com/terms'}
for key,url in sites.items():
 r=requests.get(url,timeout=35);r.raise_for_status();(D/'licenses'/f'{key}.html').write_text(r.text,encoding='utf-8');print(key,'saved',len(r.content))
k=requests.get('https://api.kartaview.org/2.0/photo/',params={'sequenceId':'3960841','page':1,'itemsPerPage':150},timeout=30).json()['result']['data']
m=requests.get('https://end.mapilio.com/api/sequence-detail',params={'sequence_uuid':'6d18a501-e66a-4636-a4fd-a4e5b6d21e07'},timeout=30).json()['data']
retrieved=datetime.datetime.now(datetime.timezone.utc).isoformat();out=[]
for x in k:
 out.append({'provider':'KartaView','id':str(x['id']),'sequence':str(x['sequenceId']),'sequence_index':x.get('sequenceIndex'),'captured_at':x.get('shotDate'),'latitude':x.get('lat'),'longitude':x.get('lng'),'creator':x.get('user'),'creator_id':'62089','image_url':x.get('imageProcUrl'),'source_url':f"https://kartaview.org/details/{x['sequenceId']}/{x.get('sequenceIndex',0)}",'license':'CC BY-SA 4.0','license_basis':'provider terms; not an image-specific license field','license_url':'https://creativecommons.org/licenses/by-sa/4.0/','terms_url':sites['kartaview_terms'],'terms_snapshot':'licenses/kartaview_terms_extracted.txt','terms_snapshot_note':'Search-index excerpt only; provider HTML response is a JavaScript shell.','retrieved_at':retrieved})
for x in m:
 url=f"https://cdn.mapilio.com/im/{x['uploaded_hash']}/{x['filename']}/1080"
 out.append({'provider':'Mapilio','id':str(x['id']),'sequence':'6d18a501-e66a-4636-a4fd-a4e5b6d21e07','captured_at':x.get('capture_time'),'latitude':None,'longitude':None,'creator_id':x.get('created_by_id'),'creator':'eclipse','image_url':url,'source_url':'https://end.mapilio.com/api/sequence-detail?sequence_uuid=6d18a501-e66a-4636-a4fd-a4e5b6d21e07','license':'CC BY-SA (version unspecified in provider policy)','license_basis':'provider public imagery policy; not an image-specific license field','license_url':'https://www.mapilio.com/licenses','terms_url':sites['mapilio_terms'],'terms_snapshot':'licenses/mapilio_terms.html','license_snapshot':'licenses/mapilio_license.html','retrieved_at':retrieved})
(D/'other_image_manifest.json').write_text(json.dumps(out,indent=2,ensure_ascii=False),encoding='utf-8');print('manifest',len(k),'Karta',len(m),'Mapilio')
for provider in ['KartaView','Mapilio']:
 item=next(x for x in out if x['provider']==provider);r=requests.get(item['image_url'],timeout=40);print(provider,'image status',r.status_code,'bytes',len(r.content),'content type',r.headers.get('Content-Type'))
 if r.ok and r.headers.get('Content-Type','').startswith('image/'):
  file=D/'samples'/f"{provider.lower()}_{item['id']}.jpg";file.write_bytes(r.content);item['local_file']=str(file)
(D/'other_image_manifest.json').write_text(json.dumps(out,indent=2,ensure_ascii=False),encoding='utf-8')
