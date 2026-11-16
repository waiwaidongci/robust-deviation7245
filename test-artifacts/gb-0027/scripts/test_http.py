import os
os.environ.update(DATABASE_URL='sqlite:////tmp/http.db',SEED_DEMO='false')
from fastapi.testclient import TestClient
import src.main as M
from src.services import run_service
run_service.queue.rpush=lambda *a,**k:1
run_service.queue.ping=lambda:True
with TestClient(M.app) as c:
    def login(email):
        r=c.post('/auth/login',json={'email':email,'password':'Shuangleng2026!'})
        return {'Authorization':'Bearer '+r.json()['token']}
    from scripts.seed_demo import seed
    seed()
    an=login('analyst@shuangleng.demo');adm=login('admin@shuangleng.demo');vw=login('viewer@shuangleng.demo')
    st=c.get('/studies',headers=an).json();sid=st[0]['id']
    wins=c.get(f'/studies/{sid}/windows',headers=an).json()
    tr=[w for w in wins if w['split']=='train'][:3];ca=[w for w in wins if w['split']=='cal'][:1]
    assert c.get(f'/studies/{sid}/links',headers=an).json()['version']==0
    r=c.post(f'/studies/{sid}/links',json={'study_id':sid,'window_a_id':tr[0]['id'],'window_b_id':tr[0]['id']},headers=an)
    assert r.status_code==422,r.text
    r=c.post(f'/studies/{sid}/links',json={'study_id':sid,'window_a_id':tr[0]['id'],'window_b_id':ca[0]['id']},headers=an)
    assert r.status_code==201,r.text;lid=r.json()['id']
    # viewer cannot mutate links
    assert c.post(f'/studies/{sid}/links',json={'study_id':sid,'window_a_id':tr[1]['id'],'window_b_id':ca[0]['id']},headers=vw).status_code==403
    # new run blocked
    r=c.post('/runs',json={'name':'被阻止研究','study_id':sid,'alpha':.05,'seed':2026},headers=an)
    assert r.status_code==409,r.text;print('409 detail:',r.json()['detail'][:70])
    # history re-verified via API
    runs=c.get('/runs',headers=an).json();run=runs[0]
    assert run['conflict_blocked'] is True and run['conflict_version']==1
    assert len(run['conflict_report']['chains'])==1
    chain=run['conflict_report']['chains'][0]
    print('chain via HTTP:',chain['chain_id'],chain['splits'],[w['code'] for w in chain['windows']])
    assert c.get(f"/runs/{run['id']}/export",headers=vw).status_code==403
    # revoke -> restored
    assert c.delete(f'/studies/{sid}/links/{lid}',headers=an).status_code==200
    assert c.post('/runs',json={'name':'恢复后研究','study_id':sid,'alpha':.05,'seed':2026},headers=an).status_code==202
    run2=[x for x in c.get('/runs',headers=an).json() if x['id']==run['id']][0]
    assert run2['conflict_blocked'] is False
    assert c.get(f"/runs/{run['id']}/export",headers=vw).status_code==200
    lst=c.get(f'/studies/{sid}/links',headers=an).json()
    assert lst['revoked'] and lst['revisions'][0]['version']==2
    # unknown study
    assert c.get('/studies/999/links',headers=an).status_code==404
    print('HTTP INTEGRATION PASSED')
