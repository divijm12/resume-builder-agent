import { useEffect, useState } from "react";
import {
  confirmMasterResume,
  getMasterResumeSummary,
  uploadMasterResume,
  type MasterResumeSummary,
  type ParsedResumeResult,
} from "../api";

const MODELS = [
  { value: "claude-haiku-4-5", label: "Claude Haiku 4.5", hint: "cheap, faster" },
  { value: "claude-sonnet-5", label: "Claude Sonnet 5", hint: "more capable, recommended" },
];

export default function MasterResume() {
  const [summary, setSummary] = useState<MasterResumeSummary | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [model, setModel] = useState(MODELS[1].value);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [result, setResult] = useState<ParsedResumeResult | null>(null);
  const [editedYaml, setEditedYaml] = useState("");
  const [showRawText, setShowRawText] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    getMasterResumeSummary()
      .then(setSummary)
      .catch((err) => setSummaryError(err instanceof Error ? err.message : "Failed to load"));
  }, []);

  async function handleUpload() {
    if (!file) return;
    setUploading(true);
    setUploadError(null);
    setSaved(false);
    try {
      const res = await uploadMasterResume(file, model);
      setResult(res);
      setEditedYaml(res.draft_yaml);
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : "Failed to parse resume");
    } finally {
      setUploading(false);
    }
  }

  async function handleSave() {
    setSaving(true);
    setSaveError(null);
    try {
      await confirmMasterResume(editedYaml);
      setSaved(true);
      const refreshed = await getMasterResumeSummary();
      setSummary(refreshed);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <h1 className="mb-1 text-xl font-semibold text-[#e4e8f0]">Master resume</h1>
      <p className="mb-6 text-sm text-[#6b7690]">
        The one structured source of truth every tailored resume, cover letter, and outreach draft is built from.
        Upload a resume any time to replace it — nothing is saved until you review the parsed draft and confirm.
      </p>

      <div className="mb-6 rounded-lg border border-[#1c2431] bg-[#10141d] px-5 py-4">
        <div className="text-[10px] font-medium uppercase tracking-wide text-[#4a5468]">Currently using</div>
        {summaryError && <p className="mt-1 text-sm text-[#f87171]">{summaryError}</p>}
        {summary && !summary.exists && <p className="mt-1 text-sm text-[#6b7690]">No master resume yet.</p>}
        {summary && summary.exists && (
          <p className="mt-1 text-sm text-[#e4e8f0]">
            {summary.name} — {summary.experience_count} experience entries, {summary.project_count} projects,{" "}
            {summary.skill_count} skills
          </p>
        )}
      </div>

      <div className="mb-6 space-y-3 rounded-lg border border-[#1c2431] bg-[#10141d] px-5 py-4">
        <div className="text-[10px] font-medium uppercase tracking-wide text-[#4a5468]">
          Upload a resume (.pdf or .docx)
        </div>
        <input
          type="file"
          accept=".pdf,.docx"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          className="block w-full text-sm text-[#9db3c9] file:mr-3 file:rounded-md file:border file:border-[#232b3a] file:bg-transparent file:px-3 file:py-1.5 file:text-xs file:font-medium file:text-[#e4e8f0]"
        />
        <div className="flex items-center gap-3">
          <select
            value={model}
            onChange={(e) => setModel(e.target.value)}
            disabled={uploading}
            className="rounded-md border border-[#232b3a] bg-transparent px-2 py-1.5 font-mono text-xs text-[#e4e8f0] focus:outline-none disabled:opacity-60"
          >
            {MODELS.map((m) => (
              <option key={m.value} value={m.value} className="bg-[#10141d]">
                {m.label} — {m.hint}
              </option>
            ))}
          </select>
          <button
            onClick={handleUpload}
            disabled={!file || uploading}
            className="rounded-md border border-[#232b3a] px-4 py-2 text-sm font-medium text-[#e4e8f0] hover:border-[#4fd6f0] hover:text-[#4fd6f0] disabled:opacity-60"
          >
            {uploading ? "Parsing…" : "Upload & Parse"}
          </button>
        </div>
        {uploadError && <p className="text-sm text-[#f87171]">{uploadError}</p>}
      </div>

      {result && (
        <div className="space-y-4">
          {result.validation_log.length > 0 && (
            <div className="rounded-md border border-[#433a1a] bg-[#2a2410] px-4 py-3">
              <div className="text-xs font-medium text-[#f2c94c]">Worth a look before saving:</div>
              <ul className="mt-1 space-y-1 text-xs text-[#f2c94c]">
                {result.validation_log.map((line, i) => (
                  <li key={i}>— {line}</li>
                ))}
              </ul>
            </div>
          )}

          <div>
            <button onClick={() => setShowRawText((v) => !v)} className="text-xs text-[#6b7690] hover:text-[#e4e8f0]">
              {showRawText ? "Hide" : "Show"} raw extracted text (to sanity-check the parse)
            </button>
            {showRawText && (
              <pre className="mt-2 max-h-64 overflow-y-auto whitespace-pre-wrap rounded-md border border-[#1c2431] bg-[#0c0f16] p-3 font-mono text-xs text-[#6b7690]">
                {result.raw_text}
              </pre>
            )}
          </div>

          <div>
            <div className="mb-1 text-[10px] font-medium uppercase tracking-wide text-[#4a5468]">
              Review and edit the draft before saving
            </div>
            <textarea
              value={editedYaml}
              onChange={(e) => setEditedYaml(e.target.value)}
              rows={28}
              className="w-full resize-y rounded-md border border-[#1c2431] bg-[#10141d] px-3 py-2 font-mono text-xs text-[#e4e8f0] focus:border-[#4fd6f0] focus:outline-none"
            />
          </div>

          {saveError && <p className="text-sm text-[#f87171]">{saveError}</p>}
          {saved && <p className="text-sm text-[#4ade80]">Saved as your master resume.</p>}
          <button
            onClick={handleSave}
            disabled={saving}
            className="rounded-md border border-[#4fd6f0] px-4 py-2 text-sm font-medium text-[#4fd6f0] hover:bg-[#4fd6f0] hover:text-[#0c0f16] disabled:opacity-60"
          >
            {saving ? "Saving…" : "Save as my master resume"}
          </button>
        </div>
      )}
    </div>
  );
}
