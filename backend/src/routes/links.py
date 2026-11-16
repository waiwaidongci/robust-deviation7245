from fastapi import APIRouter,Depends,HTTPException
from sqlalchemy.orm import Session
from ..config.database import get_db
from ..controllers.dependencies import current_user,roles
from ..constants.roles import Role
from ..schemas.link import LinkInput,LinkState
from ..services.link_service import list_links,add_link,revoke_link
from ..utils.serialize import record
router=APIRouter(tags=["links"])
@router.get("/studies/{sid}/links",response_model=LinkState)
def index(sid:int,db:Session=Depends(get_db),user=Depends(current_user)):return list_links(db,sid)
@router.post("/studies/{sid}/links",status_code=201)
def create(sid:int,data:LinkInput,db:Session=Depends(get_db),user=Depends(roles(Role.ADMIN,Role.ANALYST))):
    if data.study_id!=sid:raise HTTPException(422,"研究编号与路径不一致")
    return record(add_link(db,sid,data.window_a_id,data.window_b_id,user))
@router.delete("/studies/{sid}/links/{lid}")
def revoke(sid:int,lid:int,db:Session=Depends(get_db),user=Depends(roles(Role.ADMIN,Role.ANALYST))):
    return record(revoke_link(db,sid,lid,user))
