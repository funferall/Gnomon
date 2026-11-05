import requests,concurrent.futures,pathlib
D=pathlib.Path('data/tiger_roads');D.mkdir(exist_ok=True)
codes=[f'{i:03}' for i in range(1,28,2)]
def f(c):
 p=D/f'tl_2024_25{c}_roads.zip';url='https://www2.census.gov/geo/tiger/TIGER2024/ROADS/'+p.name
 try:
  if not p.exists():
   r=requests.get(url,timeout=90);r.raise_for_status();p.write_bytes(r.content)
  return c,p.stat().st_size
 except Exception as e:return c,type(e).__name__
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
 for x in pool.map(f,codes):print(*x,flush=True)
