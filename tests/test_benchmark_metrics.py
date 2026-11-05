import tempfile,unittest,sqlite3,json
from pathlib import Path
import wellesley_pipeline,review_store,review_server,benchmark_assets
class BenchmarkMetrics(unittest.TestCase):
 def test_full_frame_recall_and_uncertainty(self):
  old1=wellesley_pipeline.OUT;old2=review_store.OUT
  with tempfile.TemporaryDirectory() as folder:
   wellesley_pipeline.OUT=Path(folder);review_store.OUT=Path(folder)
   try:
    c=wellesley_pipeline.db();c.execute('insert into images(provider,id,raw,rights) values(?,?,?,?)',('test','1','{}','{}'));c.commit();c.close();review_server.setup();c=review_store.connect()
    for n,label,b in [(0,'fire hydrant',[0,0,10,10]),(1,'traffic sign',[90,90,100,100])]:c.execute('insert into observations(id,provider,image_id,label,score,box) values(?,?,?,?,?,?)',(str(n),'test','1',label,.5,json.dumps({'xyxy':b,'view_file':'test.jpg'})))
    c.execute('insert into benchmark_items values(?,?,?,?,?,?,?,?,?)',('test','frame','frame_audit',None,'test','1','test.jpg','test','full-view'))
    truth=[{'label':'fire hydrant','box':[0,0,10,10]},{'label':'traffic sign','box':[20,20,30,30]}];c.execute('insert into frame_labels values(?,?,?,?,?)',('test','frame',json.dumps(truth),'tester','now'));c.commit()
    result=benchmark_assets.frame_metrics(c,'test');rows={r['class']:r for r in result['detector_metrics'] if r['iou']==.5};self.assertEqual(rows['fire hydrant']['precision'],1);self.assertEqual(rows['traffic sign']['recall'],0);self.assertEqual(rows['traffic sign']['fp'],1);self.assertEqual(rows['traffic sign']['fn'],1);self.assertIsNone(benchmark_assets.wilson(0,0));self.assertGreater(benchmark_assets.wilson(10,10)[0],.7);c.close()
   finally:wellesley_pipeline.OUT=old1;review_store.OUT=old2
if __name__=='__main__':unittest.main()
