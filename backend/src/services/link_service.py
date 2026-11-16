"""Same-source window links and complete-link-version adjudication.

A link is a revocable undirected edge between two windows of one study. Every
active link set forms connected components; a component counts as one source
group (indirect links merge transitively). A run is blocked when one source
group contains frozen windows assigned to more than one of train/cal/test.

All decisions (run creation, worker write-back, download) are taken against a
complete link version: the link head row is locked for the duration of the
transaction so that the version number and the active edge set cannot be read
from different revisions. Scores, p values and stored result payloads are never
rewritten by adjudication - only the conflict fields on the run change.
"""
from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models import ClimateWindow, DeviationRun, LinkHead, LinkRevision, SourceLink
from ..utils.clock import now
from .audit_service import log

HEAD_ID = 1
SPLITS = ("train", "cal", "test")


def ensure_head(db: Session):
    head = db.get(LinkHead, HEAD_ID)
    if head is None:
        head = LinkHead(id=HEAD_ID, version=0)
        db.add(head)
        db.flush()
    return head


def lock_head(db: Session, exclusive: bool = False):
    """Take the link-head lock and return (head, version).

    ``exclusive`` serializes link mutations; shared mode serializes decisions
    against mutations. The lock is held until the caller's transaction ends,
    so a creation cannot commit on a version that a concurrent mutation is
    already replacing.
    """
    ensure_head(db)
    head = db.query(LinkHead).filter_by(id=HEAD_ID).with_for_update(read=not exclusive).one()
    return head, head.version


def current_version(db: Session) -> int:
    return ensure_head(db).version


def active_link_rows(db: Session, study_id: int):
    return (
        db.query(SourceLink)
        .filter_by(study_id=study_id, active=True)
        .order_by(SourceLink.id)
        .all()
    )


def _ordered(a: int, b: int):
    return (a, b) if a <= b else (b, a)


def _window_map(db: Session, study_id: int):
    return {
        w.id: {"id": w.id, "code": w.code, "split": w.split}
        for w in db.query(ClimateWindow).filter_by(study_id=study_id).all()
    }


def frozen_windows(run: DeviationRun):
    return [
        {"id": w["id"], "code": w["code"], "split": w["split"]}
        for w in (run.input_snapshot or {}).get("windows", [])
    ]


def _components(window_ids, edges):
    parent = {w: w for w in window_ids}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in edges:
        if a in parent and b in parent:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra
    groups = {}
    for w in window_ids:
        groups.setdefault(find(w), []).append(w)
    for root in groups:
        groups[root].sort()
    return sorted(groups.values(), key=lambda g: g[0])


def build_report(db: Session, study_id: int, frozen, version: int):
    """Evaluate one frozen window set against the complete active link set.

    The graph is built over all current windows of the study, so a chain that
    runs through a window outside the frozen set still connects its frozen
    members. Only splits of frozen members decide the conflict.
    """
    windows = _window_map(db, study_id)
    links = active_link_rows(db, study_id)
    edges = [(l.window_a_id, l.window_b_id) for l in links]
    by_edge = {(l.window_a_id, l.window_b_id): l.id for l in links}
    frozen_ids = {w["id"] for w in frozen if w["id"] in windows}
    frozen_split = {w["id"]: w["split"] for w in frozen if w["id"] in windows}
    frozen_code = {w["id"]: w["code"] for w in frozen if w["id"] in windows}
    chains = []
    for index, comp in enumerate(_components(list(windows), edges), start=1):
        members = [wid for wid in comp if wid in frozen_ids]
        splits = sorted({frozen_split[wid] for wid in members}, key=SPLITS.index)
        if len(members) < 2 or len(splits) < 2:
            continue
        member_set = set(comp)
        comp_edges = [
            {"id": by_edge[(a, b)], "a": windows[a]["code"], "b": windows[b]["code"]}
            for a, b in edges
            if (a, b) in by_edge and a in member_set and b in member_set
        ]
        chains.append(
            {
                "chain_id": f"CHAIN-{index}",
                "splits": splits,
                "frozen_count": len(members),
                "windows": [
                    {
                        "id": wid,
                        "code": windows[wid]["code"],
                        "split": windows[wid]["split"],
                        "frozen": wid in frozen_ids,
                        "frozen_code": frozen_code.get(wid, ""),
                    }
                    for wid in comp
                ],
                "edges": comp_edges,
            }
        )
    return {
        "version": version,
        "study_id": study_id,
        "blocked": bool(chains),
        "chains": chains,
        "active_link_count": len(links),
        "frozen_window_count": len(frozen_ids),
        "code_map": {str(wid): windows[wid]["code"] for wid in windows},
        "split_map": {str(wid): windows[wid]["split"] for wid in windows},
    }


def apply_report(run: DeviationRun, report: dict):
    run.conflict_version = report["version"]
    run.conflict_blocked = report["blocked"]
    run.conflict_report = report


def adjudicate_run(db: Session, run: DeviationRun, version: int | None = None):
    """Re-evaluate a run's frozen windows at the current complete version."""
    if version is None:
        version = current_version(db)
    report = build_report(db, run.study_id, frozen_windows(run), version)
    apply_report(run, report)
    return report


def adjudicate_all(db: Session, version: int | None = None):
    """Re-verify every historical run; only conflict fields are touched."""
    if version is None:
        version = current_version(db)
    for run in db.query(DeviationRun).order_by(DeviationRun.id):
        adjudicate_run(db, run, version)


def ensure_run_adjudicated(db: Session, run: DeviationRun):
    """Lazy upgrade for legacy rows created before link versioning existed."""
    if run.link_version is None:
        run.link_version = 0
    if run.conflict_version is None or run.conflict_blocked is None or not run.conflict_report:
        adjudicate_run(db, run)
    return run.conflict_report


def conflict_message(report: dict):
    parts = []
    for chain in report["chains"]:
        codes = "、".join(
            f"{w['code']}({w['split']})" for w in chain["windows"] if w["frozen"]
        )
        parts.append(f"{chain['chain_id']} 跨 {'/'.join(chain['splits'])}：{codes}")
    return "同源关联组跨训练/校准/测试，阻止新研究；" + "；".join(parts)


def creation_report(db: Session, study_id: int, windows, version: int):
    frozen = [{"id": w["id"], "code": w["code"], "split": w["split"]} for w in windows]
    return build_report(db, study_id, frozen, version)


def list_links(db: Session, study_id: int):
    _, version = lock_head(db, exclusive=False)
    if not db.query(ClimateWindow).filter_by(study_id=study_id).first():
        from ..models import ArchiveStudy
        if not db.get(ArchiveStudy, study_id):
            raise HTTPException(404, "研究不存在")
    links = active_link_rows(db, study_id)
    windows = _window_map(db, study_id)
    history = (
        db.query(SourceLink)
        .filter_by(study_id=study_id)
        .order_by(SourceLink.id.desc())
        .all()
    )
    edges = [(l.window_a_id, l.window_b_id) for l in links]
    groups = []
    for comp in _components(list(windows), edges):
        if len(comp) < 2:
            continue
        splits = sorted({windows[w]["split"] for w in comp if w in windows}, key=SPLITS.index)
        member_set = set(comp)
        groups.append(
            {
                "windows": [windows[w] for w in comp if w in windows],
                "splits": splits,
                "cross_split": len(splits) > 1,
                "edges": [
                    l.id
                    for l in links
                    if l.window_a_id in member_set and l.window_b_id in member_set
                ],
            }
        )
    return {
        "study_id": study_id,
        "version": version,
        "links": [
            {
                "id": l.id,
                "window_a_id": l.window_a_id,
                "window_b_id": l.window_b_id,
                "a_code": windows.get(l.window_a_id, {}).get("code", ""),
                "b_code": windows.get(l.window_b_id, {}).get("code", ""),
                "a_split": windows.get(l.window_a_id, {}).get("split", ""),
                "b_split": windows.get(l.window_b_id, {}).get("split", ""),
                "created_by": l.created_by,
                "created_at": l.created_at,
            }
            for l in links
        ],
        "groups": groups,
        "revoked": [
            {
                "id": l.id,
                "a_code": windows.get(l.window_a_id, {}).get("code", ""),
                "b_code": windows.get(l.window_b_id, {}).get("code", ""),
                "removed_by": l.removed_by,
                "removed_at": l.removed_at,
            }
            for l in history
            if not l.active
        ],
        "revisions": [
            {
                "version": r.version,
                "action": r.action,
                "actor": r.actor,
                "created_at": r.created_at,
                "link_count": len(r.links or []),
            }
            for r in db.query(LinkRevision)
            .filter_by(study_id=study_id)
            .order_by(LinkRevision.version.desc())
            .limit(20)
        ],
    }


def _window_of_study(db: Session, study_id: int, wid: int):
    row = db.get(ClimateWindow, wid)
    if not row or row.study_id != study_id:
        raise HTTPException(404, "窗口不存在或不属于该来源研究")
    return row


def add_link(db: Session, study_id: int, a_id: int, b_id: int, user):
    if a_id == b_id:
        raise HTTPException(422, "同源关联需要两个不同编号的窗口")
    lock_head(db, exclusive=True)
    _window_of_study(db, study_id, a_id)
    _window_of_study(db, study_id, b_id)
    a, b = _ordered(a_id, b_id)
    existing = db.query(SourceLink).filter_by(window_a_id=a, window_b_id=b).first()
    if existing and existing.active:
        raise HTTPException(409, "这两个窗口已存在同源关联")
    if existing:
        existing.active = True
        existing.removed_by = ""
        existing.removed_at = ""
        existing.created_by = user.email
        existing.created_at = now()
        link = existing
    else:
        link = SourceLink(
            study_id=study_id,
            window_a_id=a,
            window_b_id=b,
            active=True,
            created_by=user.email,
        )
        db.add(link)
    db.flush()
    _commit_revision(db, study_id, "link.add", user, f"{a}-{b}")
    return link


def revoke_link(db: Session, study_id: int, link_id: int, user):
    lock_head(db, exclusive=True)
    link = db.get(SourceLink, link_id)
    if not link or link.study_id != study_id or not link.active:
        raise HTTPException(404, "有效同源关联不存在")
    link.active = False
    link.removed_by = user.email
    link.removed_at = now()
    _commit_revision(db, study_id, "link.revoke", user, f"{link.window_a_id}-{link.window_b_id}")
    return link


def _commit_revision(db: Session, study_id: int, action: str, user, target: str):
    head = ensure_head(db)
    head.version += 1
    db.flush()
    links = active_link_rows(db, study_id)
    db.add(
        LinkRevision(
            version=head.version,
            study_id=study_id,
            action=action,
            actor=user.email,
            links=[[l.window_a_id, l.window_b_id] for l in links],
        )
    )
    # Every link change re-verifies all historical runs at the new complete
    # version; scores stay frozen, only conflict state is recomputed.
    adjudicate_all(db, head.version)
    log(db, user.email, action, target)
    db.commit()
    return head.version
