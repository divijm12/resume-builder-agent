import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { createJob, listApplications, TAILORING_MODES, type ApplicationSummary } from "../api";
import { useJobPolling } from "../hooks/useJobPolling";

const STAGE_LABELS: Record<string, string> = {
  starting: "Starting…",
  ingesting: "Parsing the job description…",
  scoring: "Scoring your resume against it…",
  tailoring: "Tailoring your resume (and rescoring it)…",
  rendering: "Rendering PDF + Word…",
  logging: "Saving to your application history…",
};

const STAGES: { key: string; label: string }[] = [
  { key: "ingesting", label: "Ingest" },
  { key: "scoring", label: "Score" },
  { key: "tailoring", label: "Tailor" },
  { key: "rendering", label: "Render" },
  { key: "logging", label: "Log" },
];

const MODELS = [
  { value: "claude-haiku-4-5", label: "Claude Haiku 4.5", hint: "cheap, default" },
  { value: "claude-sonnet-5", label: "Claude Sonnet 5", hint: "more capable, costs more" },
];

function ChevronDown() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#8fa0bf" strokeWidth="2.5">
      <path d="M6 9l6 6 6-6" />
    </svg>
  );
}

function Check() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#0c0f16" strokeWidth="3">
      <path d="M20 6L9 17l-5-5" />
    </svg>
  );
}

function StatTile({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <div className="rounded-lg border border-[#1c2431] bg-[#10141d] px-5 py-4">
      <div className="mb-2 text-[11px] uppercase tracking-wide text-[#6b7690]">{label}</div>
      <div className="font-mono text-2xl font-semibold" style={{ color: accent ?? "#e4e8f0" }}>
        {value}
      </div>
    </div>
  );
}

function AvgMatchGauge({ pct }: { pct: number | null }) {
  const r = 54;
  const circumference = 2 * Math.PI * r;
  const offset = pct === null ? circumference : circumference * (1 - pct / 100);
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-[#1c2431] bg-[#10141d] px-5 py-4">
      <div className="relative flex items-center justify-center">
        <svg width="104" height="104" viewBox="0 0 130 130">
          <circle cx="65" cy="65" r={r} fill="none" stroke="#1c2431" strokeWidth="10" />
          <circle
            cx="65"
            cy="65"
            r={r}
            fill="none"
            stroke="#4fd6f0"
            strokeWidth="10"
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={offset}
            transform="rotate(-90 65 65)"
          />
        </svg>
        <div className="absolute font-mono text-xl font-semibold">{pct !== null ? `${pct}%` : "—"}</div>
      </div>
      <div className="mt-2 text-[11px] uppercase tracking-wide text-[#6b7690]">Avg Match</div>
    </div>
  );
}

export default function NewApplication() {
  const navigate = useNavigate();
  const [jdText, setJdText] = useState("");
  const [company, setCompany] = useState("");
  const [role, setRole] = useState("");
  const [tailorModel, setTailorModel] = useState(MODELS[0].value);
  const [mode, setMode] = useState<"honest" | "aggressive">("aggressive");
  const [jobId, setJobId] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [applications, setApplications] = useState<ApplicationSummary[] | null>(null);

  const job = useJobPolling(jobId);

  useEffect(() => {
    listApplications()
      .then(setApplications)
      .catch(() => setApplications([]));
  }, []);

  useEffect(() => {
    if (job?.status === "done" && job.application_id) {
      navigate(`/applications/${job.application_id}`);
    }
  }, [job, navigate]);

  const submitting = jobId !== null && job?.status !== "error";
  const currentStageIndex = job ? STAGES.findIndex((s) => s.key === job.stage) : -1;

  const stats = applications
    ? {
        total: applications.length,
        avgMatch:
          applications.filter((a) => a.match_score !== null).length > 0
            ? Math.round(
                applications.reduce((sum, a) => sum + (a.match_score ?? 0), 0) /
                  applications.filter((a) => a.match_score !== null).length,
              )
            : null,
        interviews: applications.filter((a) => a.status === "interview" || a.status === "offer").length,
        thisWeek: applications.filter(
          (a) => Date.now() - new Date(a.created_at).getTime() < 7 * 24 * 60 * 60 * 1000,
        ).length,
      }
    : null;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitError(null);
    try {
      const { job_id } = await createJob({
        jd_text: jdText,
        company: company || undefined,
        role: role || undefined,
        tailor_model: tailorModel,
        mode,
      });
      setJobId(job_id);
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Failed to start the pipeline");
    }
  }

  return (
    <div>
      {/* stat strip */}
      <div className="mb-4 grid grid-cols-4 gap-3">
        <StatTile label="Applications" value={stats ? String(stats.total) : "—"} />
        <AvgMatchGauge pct={stats?.avgMatch ?? null} />
        <StatTile label="Interviews" value={stats ? String(stats.interviews) : "—"} />
        <StatTile
          label="This Week"
          value={stats && stats.thisWeek > 0 ? `+${stats.thisWeek}` : stats ? "0" : "—"}
          accent={stats && stats.thisWeek > 0 ? "#f088c9" : undefined}
        />
      </div>

      <form onSubmit={handleSubmit}>
        <div className="mb-4 grid grid-cols-[1.6fr_1fr] gap-3">
          {/* JD card */}
          <div className="rounded-lg border border-[#1c2431] bg-[#10141d] p-6">
            <div className="mb-3 flex items-center justify-between">
              <label className="text-xs uppercase tracking-wide text-[#6b7690]">Job Description</label>
              <span className="font-mono text-[11px] text-[#4a5468]">{jdText.length.toLocaleString()} chars</span>
            </div>
            <textarea
              required
              value={jdText}
              onChange={(e) => setJdText(e.target.value)}
              disabled={submitting}
              rows={10}
              className="mb-4 w-full resize-none rounded-md border border-[#232b3a] bg-[#0c0f16] p-3 text-sm leading-relaxed text-[#b8c0d4] placeholder-[#4a5468] focus:border-[#4fd6f0] focus:outline-none disabled:opacity-60"
              placeholder="Paste the full job posting text here…"
            />
            <div className="grid grid-cols-2 gap-3">
              <div className="rounded-md border border-[#1c2431] bg-[#0c0f16] px-3.5 py-2.5">
                <div className="mb-1 text-[10px] uppercase tracking-wide text-[#4a5468]">
                  Company <span className="normal-case text-[#3a4356]">(optional)</span>
                </div>
                <input
                  type="text"
                  value={company}
                  onChange={(e) => setCompany(e.target.value)}
                  disabled={submitting}
                  className="w-full bg-transparent text-sm text-[#e4e8f0] placeholder-[#4a5468] focus:outline-none disabled:opacity-60"
                  placeholder="Auto-extracted from JD"
                />
              </div>
              <div className="rounded-md border border-[#1c2431] bg-[#0c0f16] px-3.5 py-2.5">
                <div className="mb-1 text-[10px] uppercase tracking-wide text-[#4a5468]">
                  Role <span className="normal-case text-[#3a4356]">(optional)</span>
                </div>
                <input
                  type="text"
                  value={role}
                  onChange={(e) => setRole(e.target.value)}
                  disabled={submitting}
                  className="w-full bg-transparent text-sm text-[#e4e8f0] placeholder-[#4a5468] focus:outline-none disabled:opacity-60"
                  placeholder="Auto-extracted from JD"
                />
              </div>
            </div>
          </div>

          {/* mode + model */}
          <div className="flex flex-col gap-3">
            {TAILORING_MODES.map((m) => {
              const active = mode === m.value;
              return (
                <button
                  key={m.value}
                  type="button"
                  disabled={submitting}
                  onClick={() => setMode(m.value)}
                  className={`rounded-lg border p-4 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${
                    active ? "border-[#4fd6f0] bg-[#10202a]" : "border-[#232b3a] bg-[#0c0f16]"
                  }`}
                >
                  <div className="mb-1.5 flex items-center justify-between">
                    <span className={`text-sm font-semibold ${active ? "text-[#e4e8f0]" : "text-[#6b7690]"}`}>
                      {m.label}
                    </span>
                    <span
                      className="relative block h-[18px] w-[34px] rounded-full"
                      style={{ background: active ? "#4fd6f0" : "#1c2431" }}
                    >
                      <span
                        className="absolute top-[2px] h-[14px] w-[14px] rounded-full"
                        style={{
                          background: active ? "#0c0f16" : "#4a5468",
                          left: active ? "18px" : "2px",
                        }}
                      />
                    </span>
                  </div>
                  <div className={`text-xs leading-relaxed ${active ? "text-[#9db3c9]" : "text-[#4a5468]"}`}>
                    {m.description}
                  </div>
                </button>
              );
            })}

            <div className="rounded-lg border border-[#232b3a] bg-[#0c0f16] p-4">
              <div className="mb-1 text-[10px] uppercase tracking-wide text-[#4a5468]">Tailoring model</div>
              <div className="relative">
                <select
                  value={tailorModel}
                  onChange={(e) => setTailorModel(e.target.value)}
                  disabled={submitting}
                  className="w-full appearance-none bg-transparent font-mono text-sm text-[#e4e8f0] focus:outline-none disabled:opacity-60"
                >
                  {MODELS.map((m) => (
                    <option key={m.value} value={m.value} className="bg-[#10141d]">
                      {m.label} — {m.hint}
                    </option>
                  ))}
                </select>
                <div className="pointer-events-none absolute right-0 top-1">
                  <ChevronDown />
                </div>
              </div>
              <div className="mt-2 text-[10px] leading-relaxed text-[#4a5468]">
                Only affects tailoring -- parsing and scoring always run on a fast, fixed model.
              </div>
            </div>
          </div>
        </div>

        {submitError && (
          <p className="mb-4 rounded-md border border-[#3a1f22] bg-[#1a1013] p-3 text-sm text-[#f87171]">
            {submitError}
          </p>
        )}
        {job?.status === "error" && (
          <p className="mb-4 rounded-md border border-[#3a1f22] bg-[#1a1013] p-3 text-sm text-[#f87171]">
            Pipeline failed: {job.error}
          </p>
        )}

        {/* pipeline stepper */}
        <div className="flex items-center gap-7 rounded-lg border border-[#1c2431] bg-[#10141d] px-7 py-6">
          <div className="relative flex flex-1 items-center justify-between">
            <div className="absolute left-4 right-4 top-[15px] h-0.5 bg-[#1c2431]" />
            {submitting && currentStageIndex >= 0 && (
              <div
                className="absolute left-4 top-[15px] h-0.5 bg-[#4fd6f0] transition-all"
                style={{
                  width: `calc(${(currentStageIndex / (STAGES.length - 1)) * 100}% - ${
                    currentStageIndex === 0 ? "0px" : "2rem"
                  } + ${currentStageIndex === STAGES.length - 1 ? "2rem" : "0px"})`,
                }}
              />
            )}
            {STAGES.map((s, i) => {
              const done = submitting && currentStageIndex > i;
              const active = submitting && currentStageIndex === i;
              return (
                <div key={s.key} className="z-10 flex flex-col items-center gap-2.5">
                  <div
                    className="flex h-[30px] w-[30px] items-center justify-center rounded-full font-mono text-[11px]"
                    style={{
                      background: done || active ? (active ? "#f088c9" : "#4fd6f0") : "#1c2431",
                      color: done || active ? "#0c0f16" : "#4a5468",
                      boxShadow: active ? "0 0 0 4px rgba(240,136,201,0.15)" : undefined,
                    }}
                  >
                    {done ? <Check /> : i + 1}
                  </div>
                  <div
                    className="text-[11px]"
                    style={{ color: active ? "#e4e8f0" : done ? "#b8c0d4" : "#4a5468", fontWeight: active ? 600 : 400 }}
                  >
                    {s.label}
                  </div>
                </div>
              );
            })}
          </div>

          <button
            type="submit"
            disabled={submitting}
            className="flex flex-shrink-0 items-center gap-2 rounded-md bg-[#4fd6f0] px-6 py-3 text-sm font-bold text-[#0c0f16] transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {submitting ? (job ? (STAGE_LABELS[job.stage] ?? "Running…") : "Starting…") : "Run"}
            {!submitting && (
              <svg width="13" height="11" viewBox="0 0 24 24" fill="none" stroke="#0c0f16" strokeWidth="2.5">
                <path d="M5 12h14M13 6l6 6-6 6" />
              </svg>
            )}
          </button>
        </div>
      </form>
    </div>
  );
}
