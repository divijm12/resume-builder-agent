import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { createJob } from "../api";
import { useJobPolling } from "../hooks/useJobPolling";

const STAGE_LABELS: Record<string, string> = {
  starting: "Starting…",
  ingesting: "Parsing the job description…",
  scoring: "Scoring your resume against it…",
  tailoring: "Tailoring your resume (and rescoring it)…",
  rendering: "Rendering PDF + Word…",
  logging: "Saving to your application history…",
};

const MODELS = [
  { value: "claude-haiku-4-5", label: "Claude Haiku 4.5 (cheap, default)" },
  { value: "claude-sonnet-5", label: "Claude Sonnet 5 (more capable, costs more)" },
];

export default function NewApplication() {
  const navigate = useNavigate();
  const [jdText, setJdText] = useState("");
  const [company, setCompany] = useState("");
  const [role, setRole] = useState("");
  const [model, setModel] = useState(MODELS[0].value);
  const [jobId, setJobId] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const job = useJobPolling(jobId);

  useEffect(() => {
    if (job?.status === "done" && job.application_id) {
      navigate(`/applications/${job.application_id}`);
    }
  }, [job, navigate]);

  const submitting = jobId !== null && job?.status !== "error";

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitError(null);
    try {
      const { job_id } = await createJob({
        jd_text: jdText,
        company: company || undefined,
        role: role || undefined,
        model,
      });
      setJobId(job_id);
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Failed to start the pipeline");
    }
  }

  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="mb-1 text-2xl font-semibold">New application</h1>
      <p className="mb-6 text-sm text-slate-500">
        Paste a job description below. This runs the full pipeline (parse → score → tailor →
        render) against real Anthropic API credits.
      </p>

      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="mb-1 block text-sm font-medium">Job description</label>
          <textarea
            required
            value={jdText}
            onChange={(e) => setJdText(e.target.value)}
            disabled={submitting}
            rows={14}
            className="w-full rounded-md border border-slate-300 p-3 font-mono text-sm focus:border-slate-500 focus:outline-none disabled:bg-slate-100"
            placeholder="Paste the full job posting text here…"
          />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="mb-1 block text-sm font-medium">
              Company <span className="text-slate-400">(optional override)</span>
            </label>
            <input
              type="text"
              value={company}
              onChange={(e) => setCompany(e.target.value)}
              disabled={submitting}
              className="w-full rounded-md border border-slate-300 p-2 text-sm disabled:bg-slate-100"
              placeholder="Auto-extracted from the JD if blank"
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium">
              Role <span className="text-slate-400">(optional override)</span>
            </label>
            <input
              type="text"
              value={role}
              onChange={(e) => setRole(e.target.value)}
              disabled={submitting}
              className="w-full rounded-md border border-slate-300 p-2 text-sm disabled:bg-slate-100"
              placeholder="Auto-extracted from the JD if blank"
            />
          </div>
        </div>

        <div>
          <label className="mb-1 block text-sm font-medium">Model</label>
          <select
            value={model}
            onChange={(e) => setModel(e.target.value)}
            disabled={submitting}
            className="w-full rounded-md border border-slate-300 p-2 text-sm disabled:bg-slate-100"
          >
            {MODELS.map((m) => (
              <option key={m.value} value={m.value}>
                {m.label}
              </option>
            ))}
          </select>
        </div>

        {submitError && (
          <p className="rounded-md bg-red-50 p-3 text-sm text-red-700">{submitError}</p>
        )}

        {job?.status === "error" && (
          <p className="rounded-md bg-red-50 p-3 text-sm text-red-700">
            Pipeline failed: {job.error}
          </p>
        )}

        {submitting && job?.status === "running" && (
          <div className="flex items-center gap-2 rounded-md bg-slate-100 p-3 text-sm text-slate-700">
            <span className="h-2 w-2 animate-pulse rounded-full bg-slate-500" />
            {STAGE_LABELS[job.stage] ?? job.stage}
          </div>
        )}

        <button
          type="submit"
          disabled={submitting}
          className="w-full rounded-md bg-slate-900 py-2.5 text-sm font-medium text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400"
        >
          {submitting ? "Running…" : "Run pipeline"}
        </button>
      </form>
    </div>
  );
}
