"""Shared review schema. Human labels and model predictions are stored separately."""
import json,sqlite3
from pathlib import Path
from wellesley_pipeline import ROOT,OUT,LABELS,now

def connect():
 c=sqlite3.connect(OUT/'inventory.sqlite',timeout=30);c.row_factory=sqlite3.Row;c.execute('pragma foreign_keys=ON');c.execute('pragma busy_timeout=30000')
 c.executescript('''
 CREATE TABLE IF NOT EXISTS human_reviews(observation_id TEXT PRIMARY KEY,decision TEXT NOT NULL,label TEXT NOT NULL,text TEXT DEFAULT '',lon REAL,lat REAL,uncertainty_m REAL,distance_m REAL,distance_basis TEXT,notes TEXT DEFAULT '',reviewer TEXT NOT NULL,asset_id TEXT,revision INTEGER NOT NULL,updated_at TEXT NOT NULL);
 CREATE TABLE IF NOT EXISTS review_events(id INTEGER PRIMARY KEY AUTOINCREMENT,observation_id TEXT NOT NULL,before_json TEXT,after_json TEXT NOT NULL,created_at TEXT NOT NULL);
 CREATE TABLE IF NOT EXISTS verifications(cache_key TEXT PRIMARY KEY,observation_id TEXT NOT NULL,model TEXT,prompt_version TEXT,input_hash TEXT,response TEXT,usage TEXT,elapsed REAL,created_at TEXT);
 CREATE TABLE IF NOT EXISTS verification_failures(cache_key TEXT PRIMARY KEY,observation_id TEXT,model TEXT,prompt_version TEXT,input_hash TEXT,raw_response TEXT,usage TEXT,error TEXT,elapsed REAL,created_at TEXT);
 CREATE INDEX IF NOT EXISTS verification_obs ON verifications(observation_id);
 CREATE TABLE IF NOT EXISTS benchmark_items(benchmark_id TEXT,item_id TEXT,kind TEXT,observation_id TEXT,provider TEXT,image_id TEXT,view_file TEXT,split TEXT,stratum TEXT,PRIMARY KEY(benchmark_id,item_id));
 CREATE INDEX IF NOT EXISTS obs_review_lookup ON observations(provider,image_id);
 ''')
 columns={r[1] for r in c.execute('pragma table_info(human_reviews)')}
 for field in ['visibility','occlusion','routing_role']:
  if field not in columns:c.execute('alter table human_reviews add column '+field+" TEXT DEFAULT 'unknown'")
 c.commit();return c

def observation(c,oid):
 row=c.execute('''select o.*,i.lon camera_lon,i.lat camera_lat,i.captured,i.raw,i.rights from observations o join images i on o.provider=i.provider and o.image_id=i.id where o.id=?''',(oid,)).fetchone()
 if not row:return None
 x=dict(row);x['box']=json.loads(x['box']);x['raw']=json.loads(x['raw']);x['rights']=json.loads(x['rights']);r=c.execute('select * from human_reviews where observation_id=?',(oid,)).fetchone();x['human']=dict(r) if r else None
 ai=c.execute('select model,prompt_version,response,elapsed,created_at from verifications where observation_id=? and prompt_version=? order by created_at desc limit 1',(oid,'routing-v2-regulatory-context-v3')).fetchone();x['ai']={**dict(ai),'response':json.loads(ai['response'])} if ai else None
 return x
