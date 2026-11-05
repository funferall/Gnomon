import argparse, json, time, webbrowser
from pathlib import Path
import requests

BASE = 'https://panoramax.openstreetmap.fr/api'
DEFAULT = '-71.8040,42.2672,-71.8030,42.2677'
OUT = Path('data/observations.geojson')
from asset_taxonomy import LABELS as CLASSES

def search(bbox, limit):
    vals = [float(x) for x in bbox.split(',')]
    if len(vals) != 4 or not (-73.6 <= vals[0] < vals[2] <= -69.8 and 41 <= vals[1] < vals[3] <= 43):
        raise ValueError('bbox must be west,south,east,north inside the Massachusetts region')
    if (vals[2]-vals[0]) * (vals[3]-vals[1]) > .01:
        raise ValueError('Pilot searches are limited to 0.01 square degrees')
    r = requests.get(BASE+'/search', params={'bbox': bbox, 'limit':limit}, timeout=60, headers={'User-Agent':'RoadsideResearchPrototype/0.1'}); r.raise_for_status()
    return r.json().get('features', [])

def main():
    parser=argparse.ArgumentParser(description='Map Panoramax camera observations, not surveyed asset locations.')
    parser.add_argument('--bbox',default=DEFAULT,help='west,south,east,north')
    parser.add_argument('--limit',type=int,default=10,choices=range(1,51),metavar='1..50')
    parser.add_argument('--inventory',action='store_true',help='Retrieve metadata only; do not run detection')
    parser.add_argument('--confidence',type=float,default=.15)
    args=parser.parse_args()
    images=search(args.bbox,args.limit)
    print(f'Found {len(images)} images in first API page; ordering and completeness are not guaranteed.')
    if not args.inventory:
        try: from ultralytics import YOLOWorld
        except ImportError: raise SystemExit('Install dependencies: python -m pip install -r requirements.txt')
        model=YOLOWorld('yolov8s-worldv2.pt'); model.set_classes(CLASSES)
    features=[]
    for i,img in enumerate(images,1):
        p=img.get('properties',{}); assets=img.get('assets',{}); url=assets.get('sd',{}).get('href'); license_url=next((x.get('href') for x in img.get('links',[]) if x.get('rel')=='license'),None)
        base={'image_id':img['id'],'collection':img.get('collection'),'captured_at':p.get('datetime'),'producer':p.get('geovisio:producer'),'heading':p.get('view:azimuth'),'image_url':url,'license':license_url,'source':'Panoramax OSM France','location_type':'camera position; asset location unknown'}
        observations=[]
        status = 'inventory_only' if args.inventory else ('failed' if not url else 'scanned')
        if not args.inventory and url:
            try:
                r=requests.get(url,timeout=60); r.raise_for_status()
                from PIL import Image
                from io import BytesIO
                im=Image.open(BytesIO(r.content)).convert('RGB')
                result=model.predict(im,conf=args.confidence,verbose=False)[0]
                for box in result.boxes:
                    observations.append({'label':CLASSES[int(box.cls.item())],'confidence':round(float(box.conf.item()),3),'bbox_xyxy':[round(float(x),1) for x in box.xyxy[0]],'image_width':im.width,'image_height':im.height})
            except Exception as e:
                status = 'failed'
                print(f'Image {img["id"]} failed: {e}')
            time.sleep(.2)
        features.append({'type':'Feature','geometry':img['geometry'],'properties':{**base,'scan_status':status,'detections':observations}})
        print(f'{i}/{len(images)} {img["id"]}: {len(observations)} detections')
    OUT.parent.mkdir(exist_ok=True); OUT.write_text(json.dumps({'type':'FeatureCollection','features':features},indent=2),encoding='utf-8')
    print(f'Wrote {OUT}. Serve with: python -m http.server 8000, then http://localhost:8000')
if __name__=='__main__': main()

