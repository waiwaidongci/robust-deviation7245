import os,sqlite3
os.environ['DATABASE_URL']='sqlite:////tmp/legacy.db'
if os.path.exists('/tmp/legacy.db'):os.remove('/tmp/legacy.db')
c=sqlite3.connect('/tmp/legacy.db')
c.executescript('''
CREATE TABLE archive_studies (id INTEGER PRIMARY KEY, code VARCHAR UNIQUE NOT NULL, name VARCHAR NOT NULL, description TEXT NOT NULL, source VARCHAR NOT NULL, default_alpha FLOAT NOT NULL);
CREATE TABLE climate_windows (id INTEGER PRIMARY KEY, study_id INTEGER NOT NULL REFERENCES archive_studies(id), code VARCHAR NOT NULL, split VARCHAR NOT NULL, "values" JSON NOT NULL, note TEXT NOT NULL, UNIQUE(study_id,code));
CREATE TABLE feature_specs (id INTEGER PRIMARY KEY, study_id INTEGER NOT NULL, code VARCHAR NOT NULL, label VARCHAR NOT NULL, unit VARCHAR NOT NULL, position INTEGER NOT NULL, meaning TEXT NOT NULL, UNIQUE(study_id,code), UNIQUE(study_id,position));
CREATE TABLE deviation_runs (id INTEGER PRIMARY KEY, name VARCHAR NOT NULL, study_id INTEGER NOT NULL, alpha FLOAT NOT NULL, seed INTEGER NOT NULL, input_snapshot JSON NOT NULL, status VARCHAR NOT NULL, result JSON NOT NULL, error TEXT NOT NULL, owner VARCHAR NOT NULL, created_at VARCHAR NOT NULL);
CREATE TABLE review_notes (id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL, title VARCHAR NOT NULL, interpretation TEXT NOT NULL, proposal TEXT NOT NULL, status VARCHAR NOT NULL, owner VARCHAR NOT NULL, reviewer VARCHAR NOT NULL, review_note TEXT NOT NULL, created_at VARCHAR NOT NULL);
CREATE TABLE users (id INTEGER PRIMARY KEY, email VARCHAR UNIQUE NOT NULL, name VARCHAR NOT NULL, role VARCHAR NOT NULL, password_hash VARCHAR NOT NULL);
CREATE TABLE audits (id INTEGER PRIMARY KEY, actor VARCHAR NOT NULL, action VARCHAR NOT NULL, target VARCHAR NOT NULL, created_at VARCHAR NOT NULL);
''')
c.execute("INSERT INTO archive_studies VALUES (1,'SL-OLD','旧档','d','s',0.05)")
import json
c.execute("INSERT INTO climate_windows VALUES (1,1,'W01','train',?, 'n')",(json.dumps({'t':1,'h':2,'p':3,'v':4}),))
c.execute("INSERT INTO climate_windows VALUES (2,1,'W02','test',?, 'n')",(json.dumps({'t':1,'h':2,'p':3,'v':4}),))
c.execute("INSERT INTO feature_specs VALUES (1,1,'t','温度','C',0,'m')")
snap=json.dumps({'study':{'id':1},'features':[{'code':'t'}],'windows':[{'id':1,'code':'W01','split':'train','values':{'t':1}},{'id':2,'code':'W02','split':'test','values':{'t':1}}]})
c.execute("INSERT INTO deviation_runs VALUES (1,'旧研究',1,0.05,2026,?,'completed',?,'','old','2026-01-01')",(snap,json.dumps({'fit_hash':'oldhash','features':[{'code':'t'}],'counts':{'cal':1},'input_hash':'ih','test':[{'window':{'code':'W02','split':'test','values':{'t':1}},'d2':4.2,'p':0.01,'cal_ge_count':0,'selected':True}]})))
c.execute("INSERT INTO review_notes VALUES (1,1,'旧建议','旧解释文本是','旧方案文本是','approved','o','r','同意','2026-01-01')")
c.commit();c.close()
from src.config.database import Base,engine,SessionLocal
from src.config.upgrade import upgrade_schema
from src.models import DeviationRun
from src.services.link_service import add_link,revoke_link,current_version
from src.services.run_service import export_run
from src.models import User
import numpy as np
Base.metadata.create_all(engine);upgrade_schema();upgrade_schema()  # idempotent
db=SessionLocal()
cols={r[1] for r in sqlite3.connect('/tmp/legacy.db').execute('PRAGMA table_info(deviation_runs)')}
assert {'link_version','conflict_version','conflict_blocked','conflict_report'}<=cols,cols
print('columns added:',sorted(c for c in cols if c.startswith(('link','conflict'))))
u=User(email='n@x',name='新',role='analyst',password_hash='x');db.add(u);db.commit()
run=db.get(DeviationRun,1)
assert run.link_version is None and run.conflict_blocked is None
assert export_run(db,1).startswith('window'),'legacy approved export still works when no conflict'
print('legacy export ok before any link')
l=add_link(db,1,1,2,u)
db.close();db=SessionLocal();run=db.get(DeviationRun,1);db.refresh(run)
assert run.link_version==0 and run.conflict_blocked and run.conflict_version==1
assert run.result['fit_hash']=='oldhash' and run.result['test'][0]['d2']==4.2
print('legacy run blocked at v1, original result JSON untouched')
from fastapi import HTTPException
try:export_run(db,1);raise AssertionError
except HTTPException as e:assert e.status_code==403
revoke_link(db,1,l.id,u);db.close();db=SessionLocal();run=db.get(DeviationRun,1);db.refresh(run)
assert not run.conflict_blocked and run.result['fit_hash']=='oldhash'
print('legacy restored after revoke; scores unchanged')
print('UPGRADE TEST PASSED')
