from pydantic import BaseModel,ConfigDict,Field
class LinkInput(BaseModel):
    model_config=ConfigDict(extra="forbid")
    study_id:int
    window_a_id:int
    window_b_id:int
class LinkOutput(BaseModel):
    model_config=ConfigDict(from_attributes=True)
    id:int
    window_a_id:int
    window_b_id:int
    a_code:str
    b_code:str
    a_split:str
    b_split:str
    created_by:str
    created_at:str
class GroupWindow(BaseModel):
    model_config=ConfigDict(from_attributes=True)
    id:int
    code:str
    split:str
class LinkGroup(BaseModel):
    windows:list[GroupWindow]
    splits:list[str]
    cross_split:bool
    edges:list[int]
class RevokedLink(BaseModel):
    id:int
    a_code:str
    b_code:str
    removed_by:str
    removed_at:str
class LinkRevisionOutput(BaseModel):
    version:int
    action:str
    actor:str
    created_at:str
    link_count:int
class LinkState(BaseModel):
    study_id:int
    version:int
    links:list[LinkOutput]
    groups:list[LinkGroup]
    revoked:list[RevokedLink]
    revisions:list[LinkRevisionOutput]
