"""Idempotent upgrade for archives created before source links existed."""
from sqlalchemy import inspect,text
from .database import engine

RUN_COLUMNS={"link_version":"INTEGER","conflict_version":"INTEGER","conflict_blocked":"BOOLEAN","conflict_report":"JSON"}

def upgrade_schema():
    insp=inspect(engine)
    tables=set(insp.get_table_names())
    with engine.begin() as conn:
        if "link_heads" in tables:
            conn.execute(text("INSERT INTO link_heads (id,version) SELECT 1,0 WHERE NOT EXISTS (SELECT 1 FROM link_heads WHERE id=1)"))
        if "deviation_runs" in tables:
            existing={c["name"] for c in insp.get_columns("deviation_runs")}
            for name,kind in RUN_COLUMNS.items():
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE deviation_runs ADD COLUMN {name} {kind}"))
