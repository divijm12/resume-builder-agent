// Thin API client for the FastAPI backend. Plain fetch wrappers + types --
// no axios/react-query, the app is small enough that they'd add dependency
// weight without buying much. See LEARNING_LOG.md section 6 for what each
// of these HTTP calls actually is.

const API_BASE = "http://127.0.0.1:8000";

export interface JobStatus {
  status: "running" | "done" | "error";
  stage: string;
  application_id: number | null;
  error: string | null;
}

export interface ApplicationSummary {
  id: number;
  created_at: string;
  company: string;
  role_title: string;
  match_score: number | null;
  status: string;
  mode: "honest" | "aggressive";
}

export interface ScoreResult {
  overall_score: number;
  matched_skills: string[];
  missing_skills: string[];
  reword_opportunities: string[];
  hard_gaps: string[];
  top_missing_keywords: string[];
  red_flags: string[];
}

export interface TailorResult {
  tailored_resume: Record<string, unknown>;
  /** Plain-language, no internal ids -- safe to show directly. */
  diff_summary: string[];
  /** Internal audit trail (references master_resume.yaml bullet ids like
   * "b_004", raw guardrail rejection messages) -- keep collapsed/hidden in
   * the main view, don't show inline. */
  validation_log: string[];
  unaddressed_hard_gaps: string[];
  unaddressed_red_flags: string[];
  unaddressed_reword_opportunities: string[];
  ats_scan_notes: string[];
  score_before: ScoreResult;
  score_after: ScoreResult;
  overall_score_delta: number;
}

export interface JdParsed {
  role: string;
  company: string | null;
  seniority: string | null;
  must_have_skills: string[];
  nice_to_have: string[];
  responsibilities: string[];
  keywords: string[];
}

export interface ApplicationDetail extends ApplicationSummary {
  jd_raw: string | null;
  resume_variant_path: string | null;
  notes: string | null;
  jd_parsed: JdParsed | null;
  tailor_result: TailorResult | null;
}

export const APPLICATION_STATUSES = [
  "drafted",
  "applied",
  "outreach_sent",
  "interview",
  "rejected",
  "ghosted",
  "offer",
] as const;

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed: ${res.status}`);
  }
  return res.json();
}

export const TAILORING_MODES = [
  {
    value: "honest",
    label: "Honest",
    description: "Reorders and highlights the experience most relevant to each job.",
  },
  {
    value: "aggressive",
    label: "Aggressive",
    description: "Rewrites and tailors the content to match each job description.",
  },
] as const;

export function createJob(params: {
  jd_text: string;
  company?: string;
  role?: string;
  /** Only used for the tailoring stage -- ingest/scoring always run on a
   * fixed fast model server-side. See apply.py's run_pipeline docstring. */
  tailor_model?: string;
  mode?: string;
}): Promise<{ job_id: string }> {
  return request("/api/jobs", { method: "POST", body: JSON.stringify(params) });
}

export function getJob(jobId: string): Promise<JobStatus> {
  return request(`/api/jobs/${jobId}`);
}

export function listApplications(): Promise<ApplicationSummary[]> {
  return request("/api/applications");
}

export function getApplication(id: number): Promise<ApplicationDetail> {
  return request(`/api/applications/${id}`);
}

export function updateApplication(
  id: number,
  updates: { status?: string; notes?: string },
): Promise<{ ok: boolean }> {
  return request(`/api/applications/${id}`, { method: "PATCH", body: JSON.stringify(updates) });
}

export function fileUrl(id: number, type: "pdf" | "docx"): string {
  return `${API_BASE}/api/applications/${id}/file?type=${type}`;
}
