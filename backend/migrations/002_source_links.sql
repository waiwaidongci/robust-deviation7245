-- Upgrade an existing archive to revocable same-source window links.
-- New databases receive these tables from SQLAlchemy metadata at startup;
-- this file documents and applies the same change for older instances.
CREATE TABLE IF NOT EXISTS link_heads (
  id INTEGER PRIMARY KEY,
  version INTEGER NOT NULL DEFAULT 0
);
INSERT INTO link_heads (id,version) SELECT 1,0 WHERE NOT EXISTS (SELECT 1 FROM link_heads WHERE id=1);
CREATE TABLE IF NOT EXISTS source_links (
  id SERIAL PRIMARY KEY,
  study_id INTEGER NOT NULL REFERENCES archive_studies(id),
  window_a_id INTEGER NOT NULL REFERENCES climate_windows(id),
  window_b_id INTEGER NOT NULL REFERENCES climate_windows(id),
  active BOOLEAN NOT NULL DEFAULT TRUE,
  created_by VARCHAR NOT NULL DEFAULT '',
  created_at VARCHAR NOT NULL DEFAULT '',
  removed_by VARCHAR NOT NULL DEFAULT '',
  removed_at VARCHAR NOT NULL DEFAULT '',
  CONSTRAINT uq_source_link_pair UNIQUE (window_a_id,window_b_id)
);
CREATE TABLE IF NOT EXISTS source_link_revisions (
  version INTEGER PRIMARY KEY,
  study_id INTEGER NOT NULL REFERENCES archive_studies(id),
  action VARCHAR NOT NULL,
  actor VARCHAR NOT NULL,
  links JSON NOT NULL DEFAULT '[]',
  created_at VARCHAR NOT NULL DEFAULT ''
);
ALTER TABLE deviation_runs ADD COLUMN IF NOT EXISTS link_version INTEGER;
ALTER TABLE deviation_runs ADD COLUMN IF NOT EXISTS conflict_version INTEGER;
ALTER TABLE deviation_runs ADD COLUMN IF NOT EXISTS conflict_blocked BOOLEAN DEFAULT FALSE;
ALTER TABLE deviation_runs ADD COLUMN IF NOT EXISTS conflict_report JSON;
CREATE INDEX IF NOT EXISTS source_links_study_active_idx ON source_links (study_id,active);
-- Legacy completed runs keep their frozen scores; link_version 0 marks rows
-- predating link awareness. Conflict fields are filled by the app on first read.
