-- applications.db schema. Versioned here since the live DB (applications.db)
-- is gitignored (contains personal application data) -- this file is the
-- reproducible source of truth. See ARCHITECTURE.md section 2.

CREATE TABLE applications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  company TEXT NOT NULL,
  role_title TEXT NOT NULL,
  jd_raw TEXT,
  jd_parsed_json TEXT,
  match_score REAL,
  resume_variant_path TEXT,
  cover_letter_path TEXT,
  -- Full tailor.py output (tailored_resume, diff_summary, validation_log,
  -- unaddressed_*, ats_scan_notes, score_before, score_after,
  -- overall_score_delta) as one JSON blob -- everything the review UI needs
  -- without re-deriving anything. diff_summary is user-facing; validation_log
  -- is an internal audit trail (references master_resume.yaml bullet ids) --
  -- a UI should hide/collapse it, not show it inline.
  tailor_result_json TEXT,
  status TEXT NOT NULL DEFAULT 'drafted'
    CHECK (status IN ('drafted','applied','outreach_sent','interview','rejected','ghosted','offer')),
  contact_name TEXT,
  contact_email TEXT,
  contact_source TEXT,
  contact_verified INTEGER DEFAULT 0,
  outreach_sent_at TEXT,
  response_received INTEGER DEFAULT 0,
  notes TEXT
);

CREATE TABLE resume_versions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  application_id INTEGER NOT NULL REFERENCES applications(id),
  diff_from_master TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  file_path TEXT NOT NULL
);

CREATE INDEX idx_applications_company ON applications(company);
CREATE INDEX idx_applications_status ON applications(status);
CREATE INDEX idx_resume_versions_application_id ON resume_versions(application_id);
