from sqlalchemy import JSON,Boolean,ForeignKey,UniqueConstraint
from sqlalchemy.orm import Mapped,mapped_column
from ..config.database import Base
from ..utils.clock import now

class LinkHead(Base):
    """Single row holding the global, monotonically increasing link version."""
    __tablename__="link_heads"
    id:Mapped[int]=mapped_column(primary_key=True)
    version:Mapped[int]=mapped_column(default=0,nullable=False)

class SourceLink(Base):
    """Revocable same-source edge between two windows of one study."""
    __tablename__="source_links"
    __table_args__=(UniqueConstraint("window_a_id","window_b_id"),)
    id:Mapped[int]=mapped_column(primary_key=True)
    study_id:Mapped[int]=mapped_column(ForeignKey("archive_studies.id"))
    window_a_id:Mapped[int]=mapped_column(ForeignKey("climate_windows.id"))
    window_b_id:Mapped[int]=mapped_column(ForeignKey("climate_windows.id"))
    active:Mapped[bool]=mapped_column(Boolean,default=True,nullable=False)
    created_by:Mapped[str]=mapped_column(default="")
    created_at:Mapped[str]=mapped_column(default=now)
    removed_by:Mapped[str]=mapped_column(default="")
    removed_at:Mapped[str]=mapped_column(default="")

class LinkRevision(Base):
    """Immutable complete link-set snapshot for one study at a global version."""
    __tablename__="source_link_revisions"
    version:Mapped[int]=mapped_column(primary_key=True)
    study_id:Mapped[int]=mapped_column(ForeignKey("archive_studies.id"))
    action:Mapped[str]
    actor:Mapped[str]
    links:Mapped[list]=mapped_column(JSON,default=list)
    created_at:Mapped[str]=mapped_column(default=now)
