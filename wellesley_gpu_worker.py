"""GPU candidate-extraction worker. Stop cleanly by creating data/wellesley/STOP."""
import sqlite3,time,shutil
from wellesley_pipeline import db,scan
from pathlib import Path
ROOT=Path(__file__).resolve().parent
PY=Path('C:/Users/mmulq/miniconda3/envs/TDA/python.exe')
OUT=ROOT/'data/wellesley'
idle=0
for batch in range(10000):
 if (OUT/'STOP').exists():print('Stopped by STOP file',flush=True);break
 if shutil.disk_usage(ROOT).free<10*1024**3:print('Stopped: less than 10 GiB free',flush=True);break
 with sqlite3.connect(OUT/'inventory.sqlite') as c:pending=c.execute("select count(*) from images where status='pending'").fetchone()[0]
 if not pending:
  idle+=1
  if idle>=30:print('No new pending images for five minutes; worker exited',flush=True);break
  time.sleep(10);continue
 idle=0
 try:
  connection=db()
  scan(connection,25)
  connection.close()
 except sqlite3.OperationalError as error:
  print('Database busy; retrying batch',flush=True);time.sleep(5);continue
 except Exception as error:
  print('Worker stopped',type(error).__name__,flush=True);break
