import json,sqlite3,tempfile,threading,unittest
from pathlib import Path
import requests
import wellesley_pipeline,review_store,review_server,position_quality

class ReviewWorkflow(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.tmp=tempfile.TemporaryDirectory();cls.folder=Path(cls.tmp.name);wellesley_pipeline.OUT=cls.folder;review_store.OUT=cls.folder;position_quality.OUT=cls.folder
  c=wellesley_pipeline.db();c.execute('insert into images(provider,id,lon,lat,raw,rights) values(?,?,?,?,?,?)',('test','image',-71.29,42.30,'{}',json.dumps({'source_url':'https://example.org/source','license':'test-only'})))
  for oid in ['test:one','test:two']:
   c.execute('insert into observations(id,provider,image_id,label,score,box,crop,model) values(?,?,?,?,?,?,?,?)',(oid,'test','image','fire hydrant',.5,json.dumps({'xyxy':[1,1,10,10],'width':20,'height':20,'view_file':'none.jpg'}),'none.jpg','test'))
  c.commit();c.close();review_server.setup();cls.server=review_server.ThreadingHTTPServer(('127.0.0.1',0),review_server.Handler);threading.Thread(target=cls.server.serve_forever,daemon=True).start();cls.url='http://127.0.0.1:'+str(cls.server.server_port);cls.token=requests.get(cls.url+'/api/session').json()['token']
 @classmethod
 def tearDownClass(cls):cls.server.shutdown();cls.server.server_close();cls.tmp.cleanup()
 def post(self,path,p):return requests.post(self.url+path,json=p,headers={'X-Review-Token':self.token,'Origin':self.url})
 def test_persistent_review_conflict_duplicate_undo_and_rights(self):
  p={'id':'test:one','revision':0,'decision':'accept','label':'fire hydrant','routing_role':'infrastructure','reviewer':'tester','lon':-71.29,'lat':42.30,'uncertainty_m':3,'text':'TEST'}
  r=self.post('/api/review',p);self.assertEqual(r.status_code,200,r.text);first=r.json();self.assertTrue(first['asset_id']);self.assertEqual(self.post('/api/review',p).status_code,409)
  geo=requests.get(self.url+'/api/assets').json();self.assertEqual(len(geo['features']),1);self.assertEqual(geo['features'][0]['properties']['rights'][0]['license'],'test-only')
  second=self.post('/api/review',{'id':'test:two','revision':0,'decision':'duplicate','label':'fire hydrant','routing_role':'infrastructure','reviewer':'tester','asset_id':first['asset_id']});self.assertEqual(second.status_code,200,second.text)
  # Updating a placed asset with linked duplicate evidence must preserve FK integrity.
  p['revision']=1;p['lon']=-71.291;r=self.post('/api/review',p);self.assertEqual(r.status_code,200,r.text)
  undo=self.post('/api/undo',{'id':'test:one','revision':2});self.assertEqual(undo.status_code,200,undo.text);self.assertEqual(undo.json()['restored']['lon'],-71.29)
 def test_reject_invalid_placement_and_csrf_and_private_files(self):
  p={'id':'test:two','revision':0,'decision':'accept','label':'fire hydrant','routing_role':'infrastructure','reviewer':'tester','lon':-71.29,'lat':42.30}
  p['revision']=(requests.get(self.url+'/api/observation?id=test:two').json().get('human') or {}).get('revision',0)
  self.assertEqual(self.post('/api/review',p).status_code,400)
  self.assertEqual(requests.post(self.url+'/api/review',json=p).status_code,403)
  for path in ['/.env','/data/wellesley/inventory.sqlite','/data/wellesley/images/../../../../.env']:
   self.assertEqual(requests.get(self.url+path).status_code,404)
 def test_alignment_review_keeps_source_coordinates_and_is_reversible(self):
  c=review_store.connect()
  with c:c.execute('insert into sequence_alignments values(?,?,?,?,?,?,?,?,?)',('test-alignment',-45,47,'Washington St','{}','proposed','','','now'))
  c.close();before=requests.get(self.url+'/api/observation?id=test:one').json();r=self.post('/api/alignment-review',{'sequence':'test-alignment','status':'approved','reviewer':'tester','note':'Synthetic test only: visual anchors checked'});self.assertEqual(r.status_code,200,r.text);after=requests.get(self.url+'/api/observation?id=test:one').json();self.assertEqual(before['camera_lon'],after['camera_lon']);self.assertEqual(before['camera_lat'],after['camera_lat'])
  r=self.post('/api/alignment-review',{'sequence':'test-alignment','status':'proposed','reviewer':'tester','note':'Synthetic test: undo correction'});self.assertEqual(r.status_code,200,r.text)
 def test_alignment_preview_is_limited_to_its_capture_interval(self):
  c=review_store.connect();statistics={'capture_start':'2026-01-01T00:00:00+00:00','capture_end':'2026-01-01T00:00:10+00:00'}
  with c:
   c.execute('insert into sequence_alignments values(?,?,?,?,?,?,?,?,?)',('bounded',-45,47,'Washington St',json.dumps(statistics),'proposed','','','now'))
   for i,date in [('within','2026-01-01T00:00:05+00:00'),('outside','2026-01-01T00:00:20+00:00')]:c.execute('insert into images(provider,id,lon,lat,captured,raw,rights) values(?,?,?,?,?,?,?)',('bounded',i,-71.29,42.30,date,json.dumps({'sequence':'bounded'}),'{}'))
  position_quality.export(c);data=json.loads((self.folder/'position-quality.json').read_text())['images'];self.assertIn('proposal',data['bounded:within']);self.assertNotIn('proposal',data['bounded:outside']);self.assertIn('outside_proposal_capture_interval',data['bounded:outside']['flags']);c.close()
 def test_image_navigation_skips_pending_and_moves_camera(self):
  c=review_store.connect()
  with c:
   for i,status,lat in [('nav1','scanned',42.30),('nav2','scanned',42.301),('nav3','pending',42.302)]:
    c.execute('insert into images(provider,id,lat,lon,captured,raw,rights,status) values(?,?,?,?,?,?,?,?)',('navigation',i,lat,-71.29,'2026-01-01T00:00:0'+i[-1]+'Z',json.dumps({'sequence':'nav-sequence'}),'{}',status))
  c.close();r=requests.get(self.url+'/api/image-neighbor',params={'provider':'navigation','image_id':'nav1','direction':1}).json();self.assertEqual(r['image']['image_id'],'nav2');self.assertEqual(r['image']['camera_lat'],42.301)
  back=requests.get(self.url+'/api/image-neighbor',params={'provider':'navigation','image_id':'nav2','direction':-1}).json();self.assertEqual(back['image']['image_id'],'nav1')
 def test_no_fake_ai_ground_truth(self):
  stats=requests.get(self.url+'/api/stats').json();self.assertEqual(stats['ai'],0)
  q=requests.get(self.url+'/api/queue?status=all&limit=1').json();self.assertEqual(len(q['items']),1);self.assertEqual(q['total'],2)

if __name__=='__main__':unittest.main()
