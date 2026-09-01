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
  -- Human-readable label of whichever named resume (data/master_resumes/)
  -- was used to score/tailor this application -- e.g. "Main Resume",
  -- "Data-focused". A plain string snapshot, not a foreign key, so it
  -- stays meaningful even if that named resume is later edited or
  -- deleted from the library. NULL for applications logged before this
  -- library existed (a single implicit resume, no name to record).
  resume_name TEXT,
  cover_letter_path TEXT,
  -- Full tailor.py output (tailored_resume, diff_summary, validation_log,
  -- unaddressed_*, ats_scan_notes, score_before, score_after,
  -- overall_score_delta) as one JSON blob -- everything the review UI needs
  -- without re-deriving anything. diff_summary is user-facing; validation_log
  -- is an internal audit trail (references master_resume.yaml bullet ids) --
  -- a UI should hide/collapse it, not show it inline.
  tailor_result_json TEXT,
  -- Tailoring mode used for this application -- see agents/tailor.py MODES.
  -- "aggressive": selects/reorders/relabels AND rewords bullets (default).
  -- "honest": only selects/reorders/relabels, bullet text never touched.
  -- Neither mode fabricates; this only affects reword intensity.
  mode TEXT NOT NULL DEFAULT 'aggressive' CHECK (mode IN ('honest','aggressive')),
  status TEXT NOT NULL DEFAULT 'drafted'
    CHECK (status IN ('drafted','applied','outreach_sent','interview','rejected','ghosted','offer')),
  contact_name TEXT,
  contact_email TEXT,
  contact_source TEXT,
  contact_verified INTEGER DEFAULT 0,
  -- Path to a generated, hand-editable outreach email draft (Stage 6,
  -- agents/draft_outreach.py) -- overwritten in place on regeneration,
  -- unlike resume_variant_path/cover_letter_path which are never
  -- overwritten (this is a scratch draft, not the submitted artifact).
  outreach_draft_path TEXT,
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
