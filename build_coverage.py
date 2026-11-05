import duckdb, geopandas as gpd, pandas as pd, json, math
from collections import Counter
from pathlib import Path
D=Path('data'); c=duckdb.connect();df=c.execute("select * from 'data/panoramax_ma_bbox.parquet'").df()
df['lon']=[x['xmin'] for x in df.bbox];df['lat']=[x['ymin'] for x in df.bbox]
p=gpd.GeoDataFrame(df,geometry=gpd.points_from_xy(df.lon,df.lat),crs='EPSG:4326')
states=gpd.read_file('zip://data/states.zip').to_crs('EPSG:4326'); state=states.loc[states.STUSPS=='MA','geometry'].iloc[0]
p=p[p.geometry.within(state)].copy(); towns=gpd.read_file('zip://data/towns.zip').to_crs('EPSG:4326');p=gpd.sjoin(p,towns[['NAME','geometry']],how='left',predicate='within').drop(columns=['index_right']);p=p.drop_duplicates('id')
def asset(row):
 for a in row:
  if a.get('roles') and 'visual' in a['roles']:return a['href']
 return ''
def producer(row):
 return ', '.join(a.get('name') or '' for a in row)
p['image_url']=p.assets.apply(asset);p['producer']=p.providers.apply(producer);p['instance_url']=p.instance.apply(lambda i:i.get('url','') if isinstance(i,dict) else '');p['instance_name']=p.instance.apply(lambda i:i.get('name','') if isinstance(i,dict) else '');p['captured_at']=pd.to_datetime(p['datetime']).dt.strftime('%Y-%m-%dT%H:%M:%SZ');p['town']=p.NAME.fillna('Unassigned');p['year']=pd.to_datetime(p['datetime']).dt.year
cols=['id','collection','lat','lon','captured_at','town','license','producer','instance_name','instance_url','image_url','view:azimuth'];p[cols].to_csv(D/'panoramax_massachusetts_images.csv',index=False)
p['grid_x']=(p.lon/.02).apply(math.floor);p['grid_y']=(p.lat/.02).apply(math.floor)
features=[]
for (x,y),grp in p.groupby(['grid_x','grid_y']):
 grp=grp.sort_values('datetime',ascending=False,na_position='last');r=grp.iloc[0];years={str(int(k)):int(v) for k,v in grp.year.value_counts().sort_index().items() if pd.notna(k)}
 pr={'count':len(grp),'towns':', '.join(sorted(set(grp.town))),'years':years,'earliest':grp.captured_at.dropna().min() if grp.captured_at.notna().any() else None,'latest':r.captured_at if pd.notna(r.captured_at) else None,'id':r.id,'collection':r.collection,'instance_url':r.instance_url,'producer':r.producer,'license':r.license,'image_url':r.image_url}
 features.append({'type':'Feature','geometry':{'type':'Point','coordinates':[float(r.lon),float(r.lat)]},'properties':pr})
(D/'coverage_grid.geojson').write_text(json.dumps({'type':'FeatureCollection','features':features},ensure_ascii=False),encoding='utf-8')
p.groupby('town').agg(images=('id','count'),first=('captured_at','min'),last=('captured_at','max'),sequences=('collection','nunique')).sort_values('images',ascending=False).to_csv(D/'panoramax_towns.csv')
summary={'images':len(p),'towns':p.loc[p.town!='Unassigned','town'].nunique(),'sequences':p.collection.nunique(),'years':{str(int(k)):int(v) for k,v in p.year.value_counts().sort_index().items() if pd.notna(k)},'instances':p.instance_name.value_counts().to_dict(),'licenses':p.license.fillna('unknown').value_counts().to_dict(),'grid_cells':len(features),'earliest':p.captured_at.min(),'latest':p.captured_at.max(),'bbox_records':len(df),'unknown_date':int(p.captured_at.isna().sum())};(D/'coverage_summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8');print(json.dumps(summary,indent=2));print(p.groupby('town').size().sort_values(ascending=False).head(20).to_string())
