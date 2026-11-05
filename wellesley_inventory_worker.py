"""Resumable Wellesley inventory worker. Retries after transient failures (e.g. the GPU scan worker holding the
SQLite write lock) instead of quitting; each run resumes from the stored per-cell cursors."""
import subprocess,sys,sqlite3,time
from pathlib import Path
root=Path(__file__).resolve().parent
for attempt in range(12):
 code=subprocess.run([sys.executable,str(root/'wellesley_pipeline.py'),'inventory','--limit','0'],cwd=root).returncode
 with sqlite3.connect(root/'data/wellesley/inventory.sqlite',timeout=60) as c:pending=c.execute('select count(*) from queries where done=0').fetchone()[0]
 print('attempt',attempt+1,'exit',code,'cells pending',pending,flush=True)
 if pending==0:break
 time.sleep(30 if code else 5)
