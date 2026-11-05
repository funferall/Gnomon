import subprocess,sys,sqlite3
from pathlib import Path
root=Path(__file__).resolve().parent
for attempt in range(4):
 code=subprocess.run([sys.executable,str(root/'wellesley_pipeline.py'),'inventory','--limit','0'],cwd=root).returncode
 if code:break
 with sqlite3.connect(root/'data/wellesley/inventory.sqlite') as c:pending=c.execute('select count(*) from queries where done=0').fetchone()[0]
 if pending==0:break
