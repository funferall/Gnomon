import time,json,torch
from pathlib import Path
from ultralytics import YOLOWorld
from PIL import Image
from wellesley_pipeline import LABELS
paths=sorted(Path('data/wellesley/views/mapillary').glob('*_front.jpg'));base=paths[0].name.replace('_front.jpg','');files=[Path('data/wellesley/views/mapillary')/(base+'_'+face+'.jpg') for face in ['front','right','back','left','up','down']];imgs=[Image.open(p).convert('RGB') for p in files];model=YOLOWorld('yolov8s-worldv2.pt');model.set_classes(LABELS);model.predict(imgs[:3],conf=.2,imgsz=1280,device=0,verbose=False);out=[]
for batch in [1,3,6]:
 runs=[];counts=[]
 for rep in range(3):
  torch.cuda.synchronize();start=time.perf_counter();n=0
  for k in range(0,6,batch):n+=sum(len(r.boxes) for r in model.predict(imgs[k:k+batch],conf=.2,imgsz=1280,device=0,verbose=False))
  torch.cuda.synchronize();runs.append(time.perf_counter()-start);counts.append(n)
 out.append({'views_per_batch':batch,'seconds_per_6_views':runs,'detections':counts})
print(json.dumps(out,indent=2));Path('data/wellesley/inference_microbenchmark.json').write_text(json.dumps(out,indent=2))
