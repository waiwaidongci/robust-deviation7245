from pathlib import Path
import os,json,subprocess,sys,time,sqlite3
os.environ.update(DATABASE_URL='sqlite:////tmp/wk.db',SEED_DEMO='false',REDIS_URL='redis://127.0.0.1:1/0')
if os.path.exists('/tmp/wk.db'):os.remove('/tmp/wk.db')
from src.config.database import Base,engine,SessionLocal
Base.metadata.create_all(engine)
from scripts.seed_demo import seed
seed()
from src.models import DeviationRun,User
from src.services.link_service import add_link,revoke_link,current_version
db=SessionLocal()
u=db.query(User).filter_by(role='analyst').first()
from src.schemas.run import RunInput
from src.services import run_service
Stub=type('Q',(),{'rpush':lambda *a,**k:1,'blpop':lambda *a,**k:None,'ping':lambda *a,**k:True})()
run_service.queue=Stub
rec=run_service.create_run(db,RunInput(name='worker研究',study_id=1,alpha=.05,seed=2026),u)
rid=rec['id'];print('created run',rid,'frozen v',rec['link_version'])
db.close()
# Run exactly one iteration of the real worker loop code
import subprocess,textwrap
src=Path('src/worker.py').read_text()
src=src.replace('from .','from src.')
src=src.replace('Path("/artifacts").mkdir(exist_ok=True)','Path("/tmp/artifacts").mkdir(exist_ok=True)')
src=src.replace('Path("/artifacts/heartbeat")','Path("/tmp/artifacts/heartbeat")')
src=src.replace('Path(f"/artifacts/run-{run.id}.json")','Path(f"/tmp/artifacts/run-{run.id}.json")')
src=src.replace('while True:','for _once in range(1):')
src=src.replace('job=queue.blpop("deviation:jobs",timeout=2)','job=("deviation:jobs","%d")'%rid)
src=src.replace('if not job:continue','if not job:raise SystemExit')
Path('/tmp/wk_run.py').write_text(src)
r=subprocess.run([sys.executable,'/tmp/wk_run.py'],capture_output=True,text=True,env={**os.environ,'PYTHONPATH':'/workspace/backend'})
if r.returncode:print(r.stderr[-1500:]);raise SystemExit(1)
db=SessionLocal();run=db.get(DeviationRun,rid);db.refresh(run)
print('status',run.status,'error',run.error);assert run.status=='completed' and run.result['fit']['support_count']>0
assert run.conflict_blocked is False and run.conflict_version==0
print('worker write-back completed at v',run.conflict_version,'support',run.result['fit']['support_count'])
# Link conflicts the completed run -> conflict set at latest version, result untouched
hash_before=run.result['fit_hash'];test_before=json.dumps(run.result['test'],sort_keys=True)
wins={w.code:w for w in __import__('src.models',fromlist=['ClimateWindow']).ClimateWindow.__table__.c and db.query(__import__('src.models',fromlist=['ClimateWindow']).ClimateWindow).filter_by(study_id=1)}
l=add_link(db,1,wins['SL-01-W001'].id,wins['SL-01-W201'].id,u);db.refresh(run)
assert run.conflict_blocked and run.conflict_version==1
assert run.result['fit_hash']==hash_before and json.dumps(run.result['test'],sort_keys=True)==test_before
print('post-completion link conflicts run; result JSON byte-identical')
revoke_link(db,1,l.id,u);db.refresh(run);assert not run.conflict_blocked
print('WORKER PIPELINE PASSED')
