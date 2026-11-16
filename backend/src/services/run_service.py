import csv,io
from redis import Redis
from fastapi import HTTPException
from ..models import DeviationRun,ReviewNote
from ..config.settings import REDIS_URL
from ..utils.serialize import record
from .study_service import get_study,create_snapshot
from .analysis_service import prepare_snapshot
from .link_service import lock_head,creation_report,conflict_message,adjudicate_run,apply_report,ensure_run_adjudicated
from .audit_service import log
queue=Redis.from_url(REDIS_URL,decode_responses=True)
def list_runs(db):
    # Legacy rows and rows from older app instances are re-verified lazily so
    # the archive always shows conflict state for the latest complete version.
    # Shared head lock: conflict writes cannot land on a version that a
    # concurrent link mutation is replacing (lost-update guard for display).
    _,version=lock_head(db,exclusive=False)
    rows=db.query(DeviationRun).order_by(DeviationRun.id.desc()).all()
    for row in rows:
        if row.conflict_version!=version or not row.conflict_report:adjudicate_run(db,row,version)
    db.commit()
    return [record(r) for r in rows]
def get_run(db,rid):
    row=db.get(DeviationRun,rid)
    if not row:raise HTTPException(404,"偏离研究不存在")
    lock_head(db,exclusive=False);ensure_run_adjudicated(db,row);db.commit()
    return row
def create_run(db,data,user):
    study=get_study(db,data.study_id);snapshot=create_snapshot(db,study)
    try:prepare_snapshot(snapshot)
    except ValueError as e:raise HTTPException(422,str(e))
    # Shared link-head lock: the frozen window set is adjudicated against one
    # complete link version, and a concurrent mutation cannot slip in between.
    _,version=lock_head(db,exclusive=False)
    report=creation_report(db,data.study_id,snapshot['windows'],version)
    if report['blocked']:raise HTTPException(409,conflict_message(report))
    row=DeviationRun(**data.model_dump(),input_snapshot=snapshot,owner=user.name,link_version=version);db.add(row);db.flush();apply_report(row,report);log(db,user.email,"deviation.enqueue",row.id);db.commit()
    try:queue.rpush('deviation:jobs',row.id)
    except Exception:row.status='failed';row.error='队列不可用，请重提';db.commit();raise HTTPException(503,row.error)
    return record(row)
def export_run(db,rid):
    row=get_run(db,rid)
    # Downloads adjudicate against the latest complete link version right before
    # streaming, so a revoked link only restores runs that now have no conflict.
    _,version=lock_head(db,exclusive=False)
    report=adjudicate_run(db,row,version)
    # Persist the verdict even when the download is refused, so the archive
    # records which complete version the run was last checked against.
    db.commit()
    if report['blocked']:raise HTTPException(403,'同源关联冲突未解除，获批下载已暂停：'+conflict_message(report))
    if row.status!='completed' or not db.query(ReviewNote).filter_by(run_id=rid,status='approved').first():raise HTTPException(403,'仅获批完成研究可导出')
    o=io.StringIO();w=csv.writer(o);features=row.result['features'];w.writerow(['window','split',*[f['code'] for f in features],'D_squared','cal_ge_count','upper_tail_p','preset_alpha','selected','cal_m','seed','fit_hash','input_hash'])
    for x in row.result['test']:v=x['window'];w.writerow([v['code'],v['split'],*[v['values'][f['code']] for f in features],x['d2'],x['cal_ge_count'],x['p'],row.alpha,x['selected'],row.result['counts']['cal'],row.seed,row.result['fit_hash'],row.result['input_hash']])
    return o.getvalue()
