import duckdb, time
url='https://api.panoramax.xyz/data/geoparquet/panoramax.parquet'
c=duckdb.connect();t=time.time();print('Starting remote extract...',flush=True)
c.execute("COPY (SELECT id, bbox, collection, datetime, license, \"view:azimuth\", assets, providers, links, instance FROM read_parquet(?) WHERE bbox.xmin >= -73.51 AND bbox.xmax <= -69.85 AND bbox.ymin >= 41.20 AND bbox.ymax <= 42.90) TO 'data/panoramax_ma_bbox.parquet' (FORMAT PARQUET)",[url])
print('seconds',round(time.time()-t), 'rows', c.execute("select count(*) from 'data/panoramax_ma_bbox.parquet'").fetchone()[0],flush=True)
