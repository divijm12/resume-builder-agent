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
      <h2 className="mb-2.5 text-[11px] font-semibold uppercase tracking-wide text-[#6b7690]">{title}</h2>
      {children}
    </div>
  );
}

const TONE_COLORS = {
  green: { bg: "#0f2a1e", text: "#4ade80", border: "#1a4230" },
  red: { bg: "#2a1416", text: "#f87171", border: "#432026" },
  amber: { bg: "#2a2410", text: "#f2c94c", border: "#433a1a" },
};

function Pills({ items, tone }: { items: string[]; tone: "green" | "red" | "amber" }) {
  const c = TONE_COLORS[tone];
  if (items.length === 0) return <p className="text-sm text-[#4a5468]">None</p>;
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((item, i) => (
        <span
          key={i}
          className="rounded-full border px-2.5 py-1 text-xs"
          style={{ background: c.bg, color: c.text, borderColor: c.border }}
        >
          {item}
        </span>
      ))}
    </div>
  );
}

function DownloadIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M12 3v12m0 0l-4-4m4 4l4-4M4 19h16" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function PreviewIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path
        d="M1.5 12S5 5 12 5s10.5 7 10.5 7-3.5 7-10.5 7S1.5 12 1.5 12z"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}

function CloseIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M6 6l12 12M18 6L6 18" strokeLinecap="round" />
    </svg>
  );
}

function PdfPreviewModal({ url, title, onClose }: { url: string; title: string; onClose: () => void }) {
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-6"
      onClick={onClose}
    >
      <div
        className="flex h-full w-full max-w-4xl flex-col overflow-hidden rounded-lg border border-[#232b3a] bg-[#10141d]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-[#1c2431] px-4 py-3">
          <span className="text-sm font-medium text-[#e4e8f0]">{title}</span>
          <button
            onClick={onClose}
            className="rounded-md p-1 text-[#6b7690] hover:bg-[#1c2431] hover:text-[#e4e8f0]"
          >
            <CloseIcon />
          </button>
        </div>
        <iframe src={url} title={title} className="flex-1 bg-white" />
      </div>
    </div>
  );
}

export default function ApplicationDetail() {
  const { id } = useParams<{ id: string }>();
  const [app, setApp] = useState<ApplicationDetailType | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [savingStatus, setSavingStatus] = useState(false);
  const [preview, setPreview] = useState<{ url: string; title: string } | null>(null);

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

  if (error)
    return (
      <p className="rounded-md border border-[#3a1f22] bg-[#1a1013] p-3 text-sm text-[#f87171]">{error}</p>
    );
  if (!app) return <p className="text-sm text-[#6b7690]">Loading…</p>;

  const tr = app.tailor_result;
  const delta = tr?.overall_score_delta ?? 0;
  const deltaColor = delta > 0 ? "#4ade80" : delta < 0 ? "#f87171" : "#6b7690";

  return (
    <div className="mx-auto max-w-3xl">
      <Link to="/" className="mb-4 inline-block text-sm text-[#6b7690] hover:text-[#e4e8f0]">
        ← All applications
      </Link>

      <div className="mb-5 flex items-start justify-between rounded-lg border border-[#1c2431] bg-[#10141d] p-6">
        <div>
          <h1 className="text-xl font-semibold">{app.company}</h1>
          <p className="text-[#9db3c9]">{app.role_title}</p>
          <span className="mt-2 inline-block rounded-full border border-[#232b3a] bg-[#0c0f16] px-2.5 py-0.5 text-xs capitalize text-[#6b7690]">
            {app.mode} mode
          </span>
        </div>
        <select
          value={app.status}
          disabled={savingStatus}
          onChange={(e) => handleStatusChange(e.target.value)}
          className="rounded-md border border-[#232b3a] bg-[#0c0f16] px-3 py-1.5 text-sm text-[#e4e8f0] focus:border-[#4fd6f0] focus:outline-none"
        >
          {APPLICATION_STATUSES.map((s) => (
            <option key={s} value={s} className="bg-[#10141d]">
              {s}
            </option>
          ))}
        </select>
      </div>

      <div className="mb-6 flex flex-wrap gap-3">
        <button
          onClick={() => setPreview({ url: fileUrl(app.id, "pdf"), title: `${app.company} — Resume` })}
          className="flex items-center gap-2 rounded-md border border-[#232b3a] px-4 py-2 text-sm font-medium text-[#e4e8f0] hover:border-[#4fd6f0] hover:text-[#4fd6f0]"
        >
          <PreviewIcon /> Preview Resume (PDF)
        </button>
        <a
          href={fileUrl(app.id, "docx")}
          target="_blank"
          rel="noreferrer"
          className="flex items-center gap-2 rounded-md border border-[#232b3a] px-4 py-2 text-sm font-medium text-[#e4e8f0] hover:border-[#4fd6f0] hover:text-[#4fd6f0]"
        >
          <DownloadIcon /> Download Resume (Word)
        </a>
        {app.cover_letter_path && (
          <>
            <button
              onClick={() =>
                setPreview({ url: fileUrl(app.id, "cover_letter_pdf"), title: `${app.company} — Cover Letter` })
              }
              className="flex items-center gap-2 rounded-md border border-[#232b3a] px-4 py-2 text-sm font-medium text-[#e4e8f0] hover:border-[#4fd6f0] hover:text-[#4fd6f0]"
            >
              <PreviewIcon /> Preview Cover Letter (PDF)
            </button>
            <a
              href={fileUrl(app.id, "cover_letter_docx")}
              target="_blank"
              rel="noreferrer"
              className="flex items-center gap-2 rounded-md border border-[#232b3a] px-4 py-2 text-sm font-medium text-[#e4e8f0] hover:border-[#4fd6f0] hover:text-[#4fd6f0]"
            >
              <DownloadIcon /> Download Cover Letter (Word)
            </a>
          </>
        )}
      </div>

      {preview && <PdfPreviewModal url={preview.url} title={preview.title} onClose={() => setPreview(null)} />}

      {tr && (
        <>
          <Section title="Score">
            <div className="flex items-center gap-4 rounded-lg border border-[#1c2431] bg-[#10141d] px-6 py-4">
              <span className="font-mono text-2xl font-semibold text-[#6b7690]">
                {tr.score_before.overall_score.toFixed(0)}
              </span>
              <svg width="18" height="14" viewBox="0 0 24 24" fill="none" stroke="#4a5468" strokeWidth="2.5">
                <path d="M5 12h14M13 6l6 6-6 6" />
              </svg>
              <span className="font-mono text-2xl font-semibold text-[#4fd6f0]">
                {tr.score_after.overall_score.toFixed(0)}
              </span>
              <span
                className="ml-auto rounded-full px-2.5 py-1 font-mono text-xs font-semibold"
                style={{ color: deltaColor, background: "#0c0f16" }}
              >
                {delta > 0 ? "+" : ""}
                {delta.toFixed(0)}
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
              <p className="text-sm text-[#4a5468]">No changes recorded.</p>
            ) : (
              <ul className="space-y-1.5 text-sm text-[#b8c0d4]">
                {tr.diff_summary.map((line, i) => (
                  <li key={i} className="flex gap-2.5">
                    <span className="mt-2 h-1 w-1 flex-shrink-0 rounded-full bg-[#4fd6f0]" />
                    {line}
                  </li>
                ))}
              </ul>
            )}
          </Section>
        </>
      )}

      {app.jd_raw && (
        <Section title="Job description">
          <details>
            <summary className="cursor-pointer text-sm text-[#6b7690] hover:text-[#e4e8f0]">
              Show raw JD text
            </summary>
            <pre className="mt-2 max-h-96 overflow-y-auto whitespace-pre-wrap rounded-md border border-[#1c2431] bg-[#10141d] p-3 font-mono text-xs text-[#9db3c9]">
              {app.jd_raw}
            </pre>
          </details>
        </Section>
      )}

      {tr && tr.validation_log.length > 0 && (
        <div className="mb-6">
          <details>
            <summary className="cursor-pointer text-sm text-[#6b7690] hover:text-[#e4e8f0]">
              Show technical validation log
            </summary>
            <p className="mt-2 text-xs text-[#4a5468]">
              Internal guardrail activity (references master resume bullet ids) — kept for auditing, not
              meant to be polished reading.
            </p>
            <ul className="mt-1 space-y-1 font-mono text-xs text-[#4a5468]">
              {tr.validation_log.map((line, i) => (
                <li key={i}>— {line}</li>
              ))}
            </ul>
          </details>
        </div>
      )}
    </div>
  );
}
