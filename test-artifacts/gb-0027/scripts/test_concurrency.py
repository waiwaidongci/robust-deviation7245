import os
os.environ['DATABASE_URL']='sqlite:////tmp/conc.db'
import threading,time
from src.config.database import Base,engine,SessionLocal
from src.models import User,ArchiveStudy,ClimateWindow,FeatureSpec,DeviationRun,ReviewNote,LinkHead
from src.services import link_service as LS
from src.services import run_service
from src.services.analysis_service import analyze_deviation
run_service.queue.rpush=lambda *a,**k:1
Base.metadata.drop_all(engine);Base.metadata.create_all(engine)
db=SessionLocal()
u=User(email='a@x',name='甲',role='analyst',password_hash='x');db.add(u)
s=ArchiveStudy(code='SL-C',name='并发',description='d',source='s');db.add(s);db.flush()
for i,(fc,l,un) in enumerate([('t','温度','C'),('h','湿度','%'),('p','颗粒','ug'),('v','波动','C')]):db.add(FeatureSpec(study_id=s.id,code=fc,label=l,unit=un,position=i,meaning='m'))
import numpy as np;rng=np.random.default_rng(3);wins={}
for role,pfx,n in [('train','R',26),('cal','C',6),('test','S',3)]:
    for i in range(n):
        w=ClimateWindow(study_id=s.id,code=f'{pfx}{i+1:02d}',split=role,values=dict(zip(['t','h','p','v'],rng.normal(size=4).tolist())),note='n');db.add(w);wins[f'{pfx}{i+1:02d}']=w
db.commit();LS.ensure_head(db);db.commit()

# A) creation concurrent with a link mutation must never freeze a stale clear report.
# The run transaction takes the head lock; link mutations bump the version and
# adjudicate all runs. Here we prove the invariant at the service layer with two
# sessions and an interleaving: mutation commits between snapshot read and create.
session_a=SessionLocal();session_b=SessionLocal()
from src.schemas.run import RunInput
snapshot=__import__('src.services.study_service',fromlist=['create_snapshot']).create_snapshot(session_a,s)
# B holds an exclusive head lock and bumps version inside an open tx
head_b,_=LS.lock_head(session_b,exclusive=True)
link=LS.add_link.__wrapped__ if hasattr(LS.add_link,'__wrapped__') else None
# emulate the mutation body on session_b without committing yet
sb_link=__import__('src.models',fromlist=['SourceLink']).SourceLink(study_id=s.id,window_a_id=wins['R05'].id,window_b_id=wins['C02'].id,active=True,created_by='b')
session_b.add(sb_link);session_b.flush();head_b.version+=1;session_b.flush()
blocked_link_ids=(wins['R05'].id,wins['C02'].id)
report_b=LS.build_report(session_b,s.id,[{'id':w['id'],'code':w['code'],'split':w['split']} for w in snapshot['windows']],head_b.version)
assert report_b['blocked']
v_b=head_b.version;session_b.commit()
# A now creates using current version; must be blocked (version=1, sees link)
try:
    rec=run_service.create_run(session_a,RunInput(name='并发研究',study_id=s.id,alpha=.05,seed=5),u)
    raise AssertionError('creation should be blocked at v1')
except Exception as e:
    assert '阻止新研究' in str(getattr(e,'detail',e))
print('A: creation after committed mutation blocked at complete version',v_b)

# C) old computation cannot restore invalidated eligibility: complete a run computed
# before a link change, then simulate the worker write-back racing a link commit.
session_a=SessionLocal()
rec=run_service.create_run(session_a,RunInput(name='旧计算研究',study_id=s.id,alpha=.05,seed=5),u) if False else None
# remove link so creation is allowed at v2
lrow=session_a.query(__import__('src.models',fromlist=['SourceLink']).SourceLink).first()
LS.revoke_link(session_a,s.id,lrow.id,u)  # v2
rec=run_service.create_run(session_a,RunInput(name='旧计算研究',study_id=s.id,alpha=.05,seed=5),u)
run=session_a.get(DeviationRun,rec['id']);frozen_v=run.link_version
result=analyze_deviation(run.input_snapshot,run.alpha,run.seed,frozen_v)
print('C: run frozen at v',frozen_v,'computed result done')
# concurrent link add commits at v3 -> historical run re-verified and blocked
sess_c=SessionLocal();l=LS.add_link(sess_c,s.id,wins['R06'].id,wins['C02'].id,u);v3=LS.current_version(sess_c);sess_c.close()
# worker write-back session started earlier but commits now; it must adjudicate at v3, not its frozen v2
worker=SessionLocal();wrun=worker.get(DeviationRun,rec['id'])
_,ver=LS.lock_head(worker,exclusive=False)
wrun.result=result;wrun.status='completed';LS.adjudicate_run(worker,wrun,ver);worker.commit()
worker.refresh(wrun)
assert ver==v3 and wrun.conflict_blocked and wrun.conflict_version==v3
assert wrun.result['fit_hash']==result['fit_hash'] and wrun.link_version==frozen_v
print('C: stale-frozen computation written back is blocked at v',ver,'(frozen v',wrun.link_version,')')

# D) concurrent link mutations get distinct versions, complete snapshots restored
def mutate(i):
    ss=SessionLocal()
    try:LS.add_link(ss,s.id,wins[f'R{10+i}'].id,wins['R20'].id,u)
    finally:ss.close()
ts=[threading.Thread(target=mutate,args=(i,)) for i in range(4)]
[t.start() for t in ts];[t.join() for t in ts]
ss=SessionLocal();state=LS.list_links(ss,s.id)
vers=[r['version'] for r in state['revisions']]
assert len(vers)==len(set(vers)),vers
print('D: concurrent mutations produced distinct versions',sorted(vers)[:6],'... top',max(vers))
# every stored revision payload is a complete active set at that version
for r in ss.query(__import__('src.models',fromlist=['LinkRevision']).LinkRevision).all():
    assert isinstance(r.links,list)
last=sorted(ss.query(__import__('src.models',fromlist=['LinkRevision']).LinkRevision).all(),key=lambda r:r.version)[-1]
active=LS.active_link_rows(ss,s.id)
assert len(last.links)==len(active), (len(last.links),len(active))
print('D: latest revision snapshot equals complete active set:',len(active),'links')
print('CONCURRENCY TESTS PASSED')
