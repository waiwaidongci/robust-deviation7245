import os
os.environ['DATABASE_URL']='sqlite:////tmp/links.db'
os.environ['SEED_DEMO']='false'
import numpy as np
from fastapi import HTTPException
from src.config.database import Base,engine,SessionLocal
from src.models import User,ArchiveStudy,ClimateWindow,FeatureSpec,DeviationRun,ReviewNote,LinkHead
from src.services import run_service
from src.services.analysis_service import analyze_deviation
from src.services.study_service import create_snapshot
from src.services.link_service import add_link,revoke_link,list_links,adjudicate_run,ensure_run_adjudicated,current_version,build_report,frozen_windows
from src.services.audit_service import log
run_service.queue.rpush=lambda *a,**k:1

Base.metadata.drop_all(engine);Base.metadata.create_all(engine)
db=SessionLocal()
rng=np.random.default_rng(7)
user=User(email='a@x',name='研究员甲',role='analyst',password_hash='x');admin=User(email='b@x',name='负责人乙',role='admin',password_hash='x')
db.add_all([user,admin]);study=ArchiveStudy(code='SL-T',name='测试',description='d',source='s');db.add(study);db.flush()
for i,(fc,l,u) in enumerate([('t','温度','C'),('h','湿度','%'),('p','颗粒','ug'),('v','波动','C')]):
    db.add(FeatureSpec(study_id=study.id,code=fc,label=l,unit=u,position=i,meaning='m'))
wins={}
for role,n in [('train',30),('cal',10),('test',5)]:
    for i in range(n):
        code=f'{"R" if role=="train" else "C" if role=="cal" else "S"}{i+1:02d}'
        vals=dict(zip(['t','h','p','v'],(rng.normal(size=4)).tolist()))
        w=ClimateWindow(study_id=study.id,code=code,split=role,values=vals,note='n');db.add(w);wins[code]=w
db.commit()
def snap():return create_snapshot(db,db.get(ArchiveStudy,study.id))
def mkrun(name='研究样本'):
    from src.schemas.run import RunInput
    rec=run_service.create_run(db,RunInput(name=name,study_id=study.id,alpha=.05,seed=5),user)
    return db.get(DeviationRun,rec['id'])
def blocked(run):return run.conflict_report['blocked']
r1=mkrun();r1.result=analyze_deviation(r1.input_snapshot,.05,5,0);r1.status='completed';db.commit()
base_result=str(r1.result);base_hash=r1.result['input_hash'];base_fit=r1.result['fit_hash']
db.add(ReviewNote(run_id=r1.id,title='补测建议',interpretation='独立解释文本',proposal='独立补测方案文本',status='approved',owner='a',reviewer='b',review_note='同意归档'));db.commit()
assert run_service.export_run(db,r1.id).startswith('window')
print('baseline export ok, v',current_version(db))

# 1. cross-split link blocks new runs and clashes existing run
l1=add_link(db,study.id,wins['R05'].id,wins['C02'].id,user)
db.refresh(r1)
assert r1.conflict_blocked and r1.conflict_version==1, r1.conflict_report
try:mkrun('blocked');raise AssertionError('should block')
except HTTPException as e:assert e.status_code==409,(e.status_code,e.detail);print('create blocked:',e.detail[:80])
try:run_service.export_run(db,r1.id);raise AssertionError('export should pause')
except HTTPException as e:assert e.status_code==403;print('export paused:',e.detail[:60])
assert str(r1.result)==base_result and r1.result['fit_hash']==base_fit,'result must not be rewritten'
print('results immutable under conflict ok')

# 2. revoke restores only because no conflict remains
revoke_link(db,study.id,l1.id,user);db.refresh(r1)
assert not r1.conflict_blocked and r1.conflict_version==2
assert run_service.export_run(db,r1.id).startswith('window');print('revoke restored export at v',r1.conflict_version)

# 3. transitive chain: T05-C02, C02-S01 => group spans train/cal/test
l1=add_link(db,study.id,wins['R05'].id,wins['C02'].id,user)
l2=add_link(db,study.id,wins['C02'].id,wins['S01'].id,user)
db.refresh(r1);assert blocked(r1)
group=[g for g in list_links(db,study.id)['groups'] if any(w['code']=='R05' for w in g['windows'])][0]
assert {w['code'] for w in group['windows']}=={'R05','C02','S01'} and group['cross_split']
print('transitive group merges:',[w['code'] for w in group['windows']])
# revoke only the indirect edge: still cross (T05 train + C02 cal)
revoke_link(db,study.id,l2.id,user);db.refresh(r1);assert blocked(r1),'must stay blocked'
print('revoking one edge keeps conflict while group still crosses splits')
# remove the remaining edge: restored
revoke_link(db,study.id,l1.id,user);db.refresh(r1);assert not blocked(r1)
print('both revoked => restored at v',r1.conflict_version)

# 4. chain through a window outside frozen set still merges frozen members
# T01-W1 -> chain via T02..? use windows outside frozen by dirtying snapshot? all frozen.
# Instead verify a legacy run holding a reduced frozen set (old archive) is judged through intermediates.
legacy=DeviationRun(name='legacy',study_id=study.id,alpha=.05,seed=5,status='completed',owner='old',
    input_snapshot={'study':{'id':study.id},'features':[],'windows':[{'id':wins['R07'].id,'code':'R07','split':'train'},{'id':wins['C03'].id,'code':'C03','split':'cal'}]},
    result={'frozen':'payload'})
db.add(legacy);db.commit()
a=add_link(db,study.id,wins['R07'].id,wins['R09'].id,user)
b=add_link(db,study.id,wins['R09'].id,wins['C03'].id,user)
db.refresh(legacy);assert legacy.conflict_blocked and legacy.conflict_version==current_version(db)
assert legacy.result=={'frozen':'payload'},'legacy result payload untouched'
chain=legacy.conflict_report['chains'][0];assert chain['frozen_count']==2
print('legacy run re-verified through intermediate:',[w['code'] for w in chain['windows']])
revoke_link(db,study.id,a.id,user);revoke_link(db,study.id,b.id,user);db.refresh(legacy);assert not legacy.conflict_blocked
print('legacy restored after revoke; result payload unchanged')

# 5. old-archive row with NULL link columns is upgraded on read
old=DeviationRun(name='pre-link',study_id=study.id,alpha=.05,seed=5,status='completed',owner='old',input_snapshot=snap(),result={})
db.add(old);db.commit()
legacy_links=[l for l in db.query(LinkHead)]
assert old.link_version is None
c=add_link(db,study.id,wins['R11'].id,wins['C04'].id,user);cver=current_version(db)
rows={r.id:r for r in db.query(DeviationRun).all()}
ensure_run_adjudicated(db,rows[old.id]);db.commit();db.refresh(old)
assert old.link_version==0 and old.conflict_blocked and old.conflict_version==cver
print('legacy NULL columns upgraded: link_version=0, adjudicated at v',cver)
revoke_link(db,study.id,c.id,user)

# 6. invalid link operations
try:add_link(db,study.id,wins['R01'].id,wins['R01'].id,user);raise AssertionError
except HTTPException as e:assert e.status_code==422
l=add_link(db,study.id,wins['R01'].id,wins['R02'].id,user)
try:add_link(db,study.id,wins['R02'].id,wins['R01'].id,user);raise AssertionError
except HTTPException as e:assert e.status_code==409;print('duplicate pair 409 ok')
try:add_link(db,study.id,wins['R01'].id,999999,user);raise AssertionError
except HTTPException as e:assert e.status_code==404;print('foreign window 404 ok')
revoke_link(db,study.id,l.id,user)
try:revoke_link(db,study.id,l.id,user);raise AssertionError
except HTTPException as e:assert e.status_code==404

# 7. version monotonic and input hash independent of links
r2=mkrun('second');db.refresh(r2)
assert r2.link_version==current_version(db)
assert analyze_deviation(snap(),.05,5)['input_hash']==base_hash
print('input hash independent of link version; run froze v',r2.link_version)
print('ALL LINK TESTS PASSED')
db.close()
