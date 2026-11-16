from sqlalchemy import Text,JSON,ForeignKey,Double
from sqlalchemy.orm import Mapped,mapped_column
from ..config.database import Base
from ..utils.clock import now
class DeviationRun(Base):
    __tablename__="deviation_runs"
    id:Mapped[int]=mapped_column(primary_key=True)
    name:Mapped[str]
    study_id:Mapped[int]=mapped_column(ForeignKey("archive_studies.id"))
    alpha:Mapped[float]=mapped_column(Double)
    seed:Mapped[int]
    input_snapshot:Mapped[dict]=mapped_column(JSON)
    status:Mapped[str]=mapped_column(default="queued")
    result:Mapped[dict]=mapped_column(JSON,default=dict)
    error:Mapped[str]=mapped_column(Text,default="")
    owner:Mapped[str]
    created_at:Mapped[str]=mapped_column(default=now)
    # Source-link adjudication. link_version is the complete link version frozen at
    # creation; conflict_* always describe the latest complete version evaluated.
    link_version:Mapped[int|None]=mapped_column(nullable=True)
    conflict_version:Mapped[int|None]=mapped_column(nullable=True)
    conflict_blocked:Mapped[bool|None]=mapped_column(nullable=True,default=False)
    conflict_report:Mapped[dict|None]=mapped_column(JSON,nullable=True)
