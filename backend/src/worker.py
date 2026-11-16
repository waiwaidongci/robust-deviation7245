import json,time,traceback
from pathlib import Path
from .config.database import Base,engine,SessionLocal
from .models import DeviationRun
from .constants.status import RunStatus
from .services.run_service import queue
from .services.analysis_service import analyze_deviation
from .services.link_service import lock_head,adjudicate_run,ensure_head
from .config.upgrade import upgrade_schema
from .services.audit_service import log
Base.metadata.create_all(engine);upgrade_schema();Path("/artifacts").mkdir(exist_ok=True)
with SessionLocal() as _s:ensure_head(_s);_s.commit()
while True:
    Path("/artifacts/heartbeat").write_text(str(time.time()))
    job=queue.blpop("deviation:jobs",timeout=2)
    if not job:continue
    with SessionLocal() as db:
        run=db.get(DeviationRun,int(job[1]))
        if not run or run.status!=RunStatus.QUEUED:continue
        run.status=RunStatus.RUNNING;db.commit()
        try:
            result=analyze_deviation(run.input_snapshot,run.alpha,run.seed,run.link_version or 0)
        except Exception as e:
            run.status=RunStatus.FAILED;run.error=str(e)
            _,version=lock_head(db,exclusive=False);adjudicate_run(db,run,version);db.commit();traceback.print_exc();continue
        # Write-back takes the shared link-head lock and adjudicates against one
        # complete version. A link change after this point re-verifies the run
        # itself, and an old computation can never publish a stale clear state.
        _,version=lock_head(db,exclusive=False)
        run.result=result;run.status=RunStatus.COMPLETED
        Path(f"/artifacts/run-{run.id}.json").write_text(json.dumps(result,ensure_ascii=False));log(db,"worker","deviation.completed",run.id)
        adjudicate_run(db,run,version)
        db.commit()
