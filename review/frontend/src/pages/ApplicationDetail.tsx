import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  APPLICATION_STATUSES,
  fileUrl,
  getApplication,
  updateApplication,
  type ApplicationDetail as ApplicationDetailType,
} from "../api";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mb-6">
      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">{title}</h2>
      {children}
    </div>
  );
}

function Pills({ items, tone }: { items: string[]; tone: "green" | "red" | "amber" }) {
  const toneClass = {
    green: "bg-green-50 text-green-700 border-green-200",
    red: "bg-red-50 text-red-700 border-red-200",
    amber: "bg-amber-50 text-amber-700 border-amber-200",
  }[tone];
  if (items.length === 0) return <p className="text-sm text-slate-400">None</p>;
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((item, i) => (
        <span key={i} className={`rounded-full border px-2 py-0.5 text-xs ${toneClass}`}>
          {item}
        </span>
      ))}
    </div>
  );
}

export default function ApplicationDetail() {
  const { id } = useParams<{ id: string }>();
  const [app, setApp] = useState<ApplicationDetailType | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [savingStatus, setSavingStatus] = useState(false);

  useEffect(() => {
    if (!id) return;
    getApplication(Number(id))
      .then(setApp)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load"));
  }, [id]);

  async function handleStatusChange(newStatus: string) {
    if (!app) return;
    setSavingStatus(true);
    try {
      await updateApplication(app.id, { status: newStatus });
      setApp({ ...app, status: newStatus });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update status");
    } finally {
      setSavingStatus(false);
    }
  }

  if (error) return <p className="rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</p>;
  if (!app) return <p className="text-sm text-slate-500">Loading…</p>;

  const tr = app.tailor_result;

  return (
    <div className="mx-auto max-w-3xl">
      <Link to="/" className="mb-4 inline-block text-sm text-slate-500 hover:underline">
        ← All applications
      </Link>

      <div className="mb-6 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold">{app.company}</h1>
          <p className="text-slate-600">{app.role_title}</p>
        </div>
        <select
          value={app.status}
          disabled={savingStatus}
          onChange={(e) => handleStatusChange(e.target.value)}
          className="rounded-md border border-slate-300 px-3 py-1.5 text-sm"
        >
          {APPLICATION_STATUSES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </div>

      <div className="mb-6 flex gap-3">
        <a
          href={fileUrl(app.id, "pdf")}
          target="_blank"
          rel="noreferrer"
          className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium hover:bg-slate-50"
        >
          Open PDF
        </a>
        <a
          href={fileUrl(app.id, "docx")}
          target="_blank"
          rel="noreferrer"
          className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium hover:bg-slate-50"
        >
          Open Word doc
        </a>
      </div>

      {tr && (
        <>
          <Section title="Score">
            <div className="flex items-center gap-3">
              <span className="text-2xl font-semibold text-slate-400">
                {tr.score_before.overall_score.toFixed(0)}
              </span>
              <span className="text-slate-400">→</span>
              <span className="text-2xl font-semibold text-slate-900">
                {tr.score_after.overall_score.toFixed(0)}
              </span>
              <span
                className={`text-sm font-medium ${tr.overall_score_delta > 0 ? "text-green-600" : tr.overall_score_delta < 0 ? "text-red-600" : "text-slate-400"}`}
              >
                {tr.overall_score_delta > 0 ? "+" : ""}
                {tr.overall_score_delta.toFixed(0)}
              </span>
            </div>
          </Section>

          <Section title="Hard gaps (not covered, not faked)">
            <Pills items={tr.unaddressed_hard_gaps} tone="red" />
          </Section>

          <Section title="Red flags">
            <Pills items={tr.unaddressed_red_flags} tone="amber" />
          </Section>

          <Section title="Matched skills">
            <Pills items={tr.score_after.matched_skills} tone="green" />
          </Section>

          <Section title="What changed in this tailoring pass">
            {tr.diff_summary.length === 0 ? (
              <p className="text-sm text-slate-400">No changes recorded.</p>
            ) : (
              <ul className="list-disc space-y-1 pl-5 text-sm text-slate-700">
                {tr.diff_summary.map((line, i) => (
                  <li key={i}>{line}</li>
                ))}
              </ul>
            )}
          </Section>
        </>
      )}

      {app.jd_raw && (
        <Section title="Job description">
          <details>
            <summary className="cursor-pointer text-sm text-slate-500 hover:underline">
              Show raw JD text
            </summary>
            <pre className="mt-2 max-h-96 overflow-y-auto whitespace-pre-wrap rounded-md bg-slate-100 p-3 text-xs text-slate-700">
              {app.jd_raw}
            </pre>
          </details>
        </Section>
      )}
    </div>
  );
}
