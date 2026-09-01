import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  APPLICATION_STATUSES,
  draftOutreach,
  fileUrl,
  findContact,
  getApplication,
  sendOutreach,
  updateApplication,
  type ApplicationDetail as ApplicationDetailType,
  type ContactCandidate,
  type OutreachDraftResult,
  type OutreachEmailType,
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
  blue: { bg: "#0f2029", text: "#4fd6f0", border: "#1a3a43" },
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

function PersonIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="8" r="4" />
      <path d="M4 21c0-4.4 3.6-8 8-8s8 3.6 8 8" strokeLinecap="round" />
    </svg>
  );
}

function VerifiedBadge({ verified }: { verified: boolean }) {
  const c = verified ? TONE_COLORS.green : TONE_COLORS.amber;
  return (
    <span
      className="rounded-full border px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide"
      style={{ background: c.bg, color: c.text, borderColor: c.border }}
    >
      {verified ? "Verified" : "Unverified"}
    </span>
  );
}

function RelevanceBadge({ label }: { label: string }) {
  const c = TONE_COLORS.blue;
  return (
    <span
      className="rounded-full border px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide"
      style={{ background: c.bg, color: c.text, borderColor: c.border }}
    >
      {label}
    </span>
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

function SendConfirmModal({
  toEmail,
  subject,
  bodyText,
  validationLog,
  sending,
  error,
  onCancel,
  onConfirm,
}: {
  toEmail: string;
  subject: string;
  bodyText: string;
  validationLog: string[];
  sending: boolean;
  error: string | null;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onCancel();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onCancel]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-6" onClick={onCancel}>
      <div
        className="flex max-h-full w-full max-w-lg flex-col overflow-hidden rounded-lg border border-[#232b3a] bg-[#10141d]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="border-b border-[#1c2431] px-5 py-3.5">
          <span className="text-sm font-medium text-[#e4e8f0]">Send this email?</span>
        </div>
        <div className="overflow-y-auto px-5 py-4">
          <div className="text-xs text-[#4a5468]">To</div>
          <div className="mb-3 font-mono text-sm text-[#e4e8f0]">{toEmail}</div>
          <div className="text-xs text-[#4a5468]">Subject</div>
          <div className="mb-3 text-sm text-[#e4e8f0]">{subject}</div>
          <div className="text-xs text-[#4a5468]">Body</div>
          <p className="whitespace-pre-wrap text-sm text-[#9db3c9]">{bodyText}</p>
          {validationLog.length > 0 && (
            <div className="mt-4 rounded-md border border-[#433a1a] bg-[#2a2410] px-3 py-2.5">
              <div className="text-xs font-medium text-[#f2c94c]">Before you send -- worth a look:</div>
              <ul className="mt-1 space-y-1 text-xs text-[#f2c94c]">
                {validationLog.map((line, i) => (
                  <li key={i}>— {line}</li>
                ))}
              </ul>
            </div>
          )}
          {error && <p className="mt-3 text-sm text-[#f87171]">{error}</p>}
        </div>
        <div className="flex items-center justify-end gap-2 border-t border-[#1c2431] px-5 py-3.5">
          <button
            onClick={onCancel}
            disabled={sending}
            className="rounded-md border border-[#232b3a] px-4 py-2 text-sm font-medium text-[#e4e8f0] hover:border-[#4fd6f0] hover:text-[#4fd6f0] disabled:opacity-60"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            disabled={sending}
            className="rounded-md border border-[#f87171] px-4 py-2 text-sm font-medium text-[#f87171] hover:bg-[#f87171] hover:text-[#10141d] disabled:opacity-60"
          >
            {sending ? "Sending…" : "Confirm Send"}
          </button>
        </div>
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
  const [contactSearching, setContactSearching] = useState(false);
  // Kept in state even after a contact is saved -- "See other options" reuses
  // this without another Hunter.io call; only "Search again" fetches fresh.
  // This is in-memory only (lost on reload/navigation, not written to the DB),
  // so it's really about avoiding a pointless round-trip and instant re-display,
  // not primarily about credits -- Hunter's own account already dedupes an
  // identical Domain Search for the same company within a billing period, so a
  // real repeat search often wouldn't have cost anything extra anyway. See
  // https://help.hunter.io/en/articles/1911656 (confirmed after the user
  // noticed their own Hunter dashboard showed fewer credits used than the
  // number of raw requests this code was making before this comment existed).
  const [contactCandidates, setContactCandidates] = useState<ContactCandidate[] | null>(null);
  const [contactMessage, setContactMessage] = useState<string | null>(null);
  const [showCandidates, setShowCandidates] = useState(false);
  const [savingContact, setSavingContact] = useState(false);
  const [drafting, setDrafting] = useState(false);
  const [outreachResult, setOutreachResult] = useState<OutreachDraftResult | null>(null);
  const [outreachError, setOutreachError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [emailType, setEmailType] = useState<OutreachEmailType>("cold");
  const [jobLink, setJobLink] = useState("");
  // Editable copies of the generated draft -- what actually gets copied/sent
  // is whatever's here, not outreachResult's original text, so hand-edits
  // before sending are real. Reset from outreachResult on every new draft.
  const [editedSubject, setEditedSubject] = useState("");
  const [editedBody, setEditedBody] = useState("");
  const [showSendConfirm, setShowSendConfirm] = useState(false);
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);

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

  async function handleFindContact() {
    if (!app) return;
    setContactSearching(true);
    setContactMessage(null);
    try {
      const result = await findContact(app.id);
      if (result.error) {
        setContactMessage(result.error);
        setContactCandidates([]);
      } else {
        setContactCandidates(result.contacts);
        setContactMessage(result.message);
      }
    } catch (err) {
      setContactMessage(err instanceof Error ? err.message : "Failed to search for a contact");
      setContactCandidates([]);
    } finally {
      setContactSearching(false);
      setShowCandidates(true);
    }
  }

  async function handleUseContact(candidate: ContactCandidate) {
    if (!app || !candidate.email) return;
    setSavingContact(true);
    try {
      await updateApplication(app.id, {
        contact_name: candidate.name ?? undefined,
        contact_email: candidate.email,
        contact_source: candidate.source,
        contact_verified: candidate.verified,
      });
      setApp({
        ...app,
        contact_name: candidate.name,
        contact_email: candidate.email,
        contact_source: candidate.source,
        contact_verified: candidate.verified ? 1 : 0,
      });
      setShowCandidates(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save contact");
    } finally {
      setSavingContact(false);
    }
  }

  async function handleDraftOutreach() {
    if (!app) return;
    if (emailType === "referral" && !jobLink.trim()) return;
    setDrafting(true);
    setOutreachError(null);
    setCopied(false);
    try {
      const result = await draftOutreach(app.id, emailType, emailType === "referral" ? jobLink.trim() : undefined);
      setOutreachResult(result);
      setEditedSubject(result.subject);
      setEditedBody(result.body_text);
      setApp({ ...app, outreach_draft_path: result.draft_path });
    } catch (err) {
      setOutreachError(err instanceof Error ? err.message : "Failed to draft outreach email");
    } finally {
      setDrafting(false);
    }
  }

  async function handleCopyOutreach() {
    await navigator.clipboard.writeText(`Subject: ${editedSubject}\n\n${editedBody}`);
    setCopied(true);
  }

  async function handleConfirmSend() {
    if (!app) return;
    setSending(true);
    setSendError(null);
    try {
      const result = await sendOutreach(app.id, editedSubject, editedBody);
      setApp({ ...app, outreach_sent_at: result.sent_at, status: "outreach_sent" });
      setShowSendConfirm(false);
    } catch (err) {
      setSendError(err instanceof Error ? err.message : "Failed to send email");
    } finally {
      setSending(false);
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
          <span className="mt-2 inline-flex items-center gap-2">
            <span className="rounded-full border border-[#232b3a] bg-[#0c0f16] px-2.5 py-0.5 text-xs capitalize text-[#6b7690]">
              {app.mode} mode
            </span>
            {app.resume_name && (
              <span className="rounded-full border border-[#232b3a] bg-[#0c0f16] px-2.5 py-0.5 text-xs text-[#6b7690]">
                Resume: {app.resume_name}
              </span>
            )}
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

      <Section title="Hiring contact">
        {(app.jd_parsed?.hiring_manager_name || app.jd_parsed?.team_name) && (
          <div className="mb-4 rounded-lg border border-[#1c2431] bg-[#10141d] px-4 py-3 text-xs text-[#9db3c9]">
            <span className="text-[10px] font-medium uppercase tracking-wide text-[#4a5468]">
              Named directly in the JD
            </span>
            <div className="mt-1 space-y-0.5">
              {app.jd_parsed.hiring_manager_name && (
                <div>
                  Reports to{" "}
                  <span className="font-medium text-[#e4e8f0]">{app.jd_parsed.hiring_manager_name}</span>
                  {app.jd_parsed.hiring_manager_title ? ` (${app.jd_parsed.hiring_manager_title})` : ""}
                </div>
              )}
              {app.jd_parsed.team_name && (
                <div>
                  Team: <span className="font-medium text-[#e4e8f0]">{app.jd_parsed.team_name}</span>
                </div>
              )}
            </div>
          </div>
        )}
        {showCandidates ? (
          <div className="space-y-3">
            <p className="text-[11px] text-[#4a5468]">
              Contacts from Hunter.io for this company. Recruiters, people in a department close to this role, and
              anyone the JD named directly are boosted to the top and labeled below — everyone else is still shown,
              just unlabeled.
            </p>
            {contactMessage && <p className="text-sm text-[#6b7690]">{contactMessage}</p>}
            {(contactCandidates ?? []).map((c, i) => (
              <div
                key={i}
                className="flex items-center justify-between rounded-lg border border-[#1c2431] bg-[#10141d] px-5 py-3.5"
              >
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-[#e4e8f0]">{c.name || "Unknown name"}</span>
                    <VerifiedBadge verified={c.verified} />
                    {c.relevance_label && <RelevanceBadge label={c.relevance_label} />}
                  </div>
                  <div className="mt-0.5 text-xs text-[#9db3c9]">{c.title || "Title unknown"}</div>
                  <div className="mt-0.5 font-mono text-xs text-[#6b7690]">{c.email}</div>
                </div>
                <button
                  onClick={() => handleUseContact(c)}
                  disabled={savingContact}
                  className="flex-shrink-0 rounded-md border border-[#232b3a] px-3 py-1.5 text-xs font-medium text-[#e4e8f0] hover:border-[#4fd6f0] hover:text-[#4fd6f0] disabled:opacity-60"
                >
                  Use this contact
                </button>
              </div>
            ))}
            <button
              onClick={() => setShowCandidates(false)}
              className="text-xs text-[#6b7690] hover:text-[#e4e8f0]"
            >
              {app.contact_email ? "Back" : "Cancel"}
            </button>
          </div>
        ) : app.contact_email ? (
          <div className="flex items-center justify-between rounded-lg border border-[#1c2431] bg-[#10141d] px-5 py-4">
            <div>
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-[#e4e8f0]">{app.contact_name || "Unnamed contact"}</span>
                <VerifiedBadge verified={!!app.contact_verified} />
              </div>
              <div className="mt-0.5 text-sm text-[#9db3c9]">{app.contact_email}</div>
              <div className="mt-1 text-[11px] text-[#4a5468]">via {app.contact_source}</div>
            </div>
            <div className="flex flex-shrink-0 items-center gap-4">
              {contactCandidates && contactCandidates.length > 0 && (
                <button
                  onClick={() => setShowCandidates(true)}
                  className="text-xs text-[#6b7690] hover:text-[#4fd6f0]"
                >
                  See other options
                </button>
              )}
              <button
                onClick={handleFindContact}
                disabled={contactSearching}
                className="text-xs text-[#6b7690] hover:text-[#4fd6f0] disabled:opacity-60"
              >
                {contactSearching ? "Searching…" : "Search again"}
              </button>
            </div>
          </div>
        ) : (
          <button
            onClick={handleFindContact}
            disabled={contactSearching}
            className="flex items-center gap-2 rounded-md border border-[#232b3a] px-4 py-2 text-sm font-medium text-[#e4e8f0] hover:border-[#4fd6f0] hover:text-[#4fd6f0] disabled:opacity-60"
          >
            <PersonIcon /> {contactSearching ? "Searching…" : "Find hiring contact"}
          </button>
        )}
      </Section>

      <Section title="Outreach draft">
        <p className="mb-3 text-[11px] text-[#4a5468]">
          A short email draft, editable right here before you copy or send it — every send requires an explicit
          confirmation showing the exact final text first.
        </p>
        {outreachError && <p className="mb-3 text-sm text-[#f87171]">{outreachError}</p>}
        {app.outreach_sent_at && (
          <p className="mb-3 text-sm text-[#4ade80]">
            Sent to {app.contact_email} on {new Date(app.outreach_sent_at).toLocaleString()}
          </p>
        )}
        <div className="mb-3 flex items-center gap-1.5">
          <button
            onClick={() => setEmailType("cold")}
            className={`rounded-md border px-3 py-1.5 text-xs font-medium ${
              emailType === "cold"
                ? "border-[#4fd6f0] text-[#4fd6f0]"
                : "border-[#232b3a] text-[#6b7690] hover:text-[#e4e8f0]"
            }`}
          >
            Cold email
          </button>
          <button
            onClick={() => setEmailType("referral")}
            className={`rounded-md border px-3 py-1.5 text-xs font-medium ${
              emailType === "referral"
                ? "border-[#4fd6f0] text-[#4fd6f0]"
                : "border-[#232b3a] text-[#6b7690] hover:text-[#e4e8f0]"
            }`}
          >
            Ask for referral
          </button>
        </div>
        {emailType === "referral" && (
          <input
            type="url"
            value={jobLink}
            onChange={(e) => setJobLink(e.target.value)}
            placeholder="Paste the job posting link (required)"
            className="mb-3 w-full rounded-md border border-[#232b3a] bg-[#10141d] px-3 py-2 text-sm text-[#e4e8f0] placeholder:text-[#4a5468] focus:border-[#4fd6f0] focus:outline-none"
          />
        )}
        {outreachResult && (
          <div className="mb-3 space-y-3 rounded-lg border border-[#1c2431] bg-[#10141d] px-5 py-4">
            <div>
              <span className="text-[10px] font-medium uppercase tracking-wide text-[#4a5468]">Subject</span>
              <input
                value={editedSubject}
                onChange={(e) => setEditedSubject(e.target.value)}
                className="mt-0.5 w-full rounded-md border border-[#1c2431] bg-transparent px-2 py-1 text-sm text-[#e4e8f0] focus:border-[#4fd6f0] focus:outline-none"
              />
            </div>
            <div>
              <span className="text-[10px] font-medium uppercase tracking-wide text-[#4a5468]">Body</span>
              <textarea
                value={editedBody}
                onChange={(e) => setEditedBody(e.target.value)}
                rows={10}
                className="mt-0.5 w-full resize-y rounded-md border border-[#1c2431] bg-transparent px-2 py-1.5 text-sm text-[#9db3c9] focus:border-[#4fd6f0] focus:outline-none"
              />
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={handleCopyOutreach}
                className="rounded-md border border-[#232b3a] px-3 py-1.5 text-xs font-medium text-[#e4e8f0] hover:border-[#4fd6f0] hover:text-[#4fd6f0]"
              >
                {copied ? "Copied" : "Copy"}
              </button>
              {app.contact_email ? (
                <button
                  onClick={() => setShowSendConfirm(true)}
                  className="rounded-md border border-[#232b3a] px-3 py-1.5 text-xs font-medium text-[#e4e8f0] hover:border-[#4fd6f0] hover:text-[#4fd6f0]"
                >
                  {app.outreach_sent_at ? "Send again" : "Send email"}
                </button>
              ) : (
                <span className="text-xs text-[#4a5468]">Find and save a contact first to enable sending</span>
              )}
            </div>
            {outreachResult.validation_log.length > 0 && (
              <details>
                <summary className="cursor-pointer text-sm text-[#6b7690] hover:text-[#e4e8f0]">
                  Show technical validation log
                </summary>
                <p className="mt-2 text-xs text-[#4a5468]">
                  Internal guardrail activity (references master resume bullet ids) — kept for auditing, not
                  meant to be polished reading.
                </p>
                <ul className="mt-1 space-y-1 font-mono text-xs text-[#4a5468]">
                  {outreachResult.validation_log.map((line, i) => (
                    <li key={i}>— {line}</li>
                  ))}
                </ul>
              </details>
            )}
          </div>
        )}
        <button
          onClick={handleDraftOutreach}
          disabled={drafting || (emailType === "referral" && !jobLink.trim())}
          className="flex items-center gap-2 rounded-md border border-[#232b3a] px-4 py-2 text-sm font-medium text-[#e4e8f0] hover:border-[#4fd6f0] hover:text-[#4fd6f0] disabled:opacity-60"
        >
          {drafting
            ? "Drafting…"
            : outreachResult
              ? "Regenerate"
              : emailType === "referral"
                ? "Draft referral email"
                : "Draft outreach email"}
        </button>
      </Section>

      {showSendConfirm && outreachResult && app.contact_email && (
        <SendConfirmModal
          toEmail={app.contact_email}
          subject={editedSubject}
          bodyText={editedBody}
          validationLog={outreachResult.validation_log}
          sending={sending}
          error={sendError}
          onCancel={() => {
            setShowSendConfirm(false);
            setSendError(null);
          }}
          onConfirm={handleConfirmSend}
        />
      )}

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
