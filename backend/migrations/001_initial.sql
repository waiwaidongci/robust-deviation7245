-- Initial schema uses SQLAlchemy metadata; optional upgrade indexes:
CREATE INDEX IF NOT EXISTS window_study_split_idx ON climate_windows (study_id,split);
CREATE INDEX IF NOT EXISTS note_run_status_idx ON review_notes (run_id,status);
