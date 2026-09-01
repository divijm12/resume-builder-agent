// Home page ("/"): every logged application in one table, read-only --
// all the actual pipeline/review actions live on ApplicationDetail.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { listApplications, type ApplicationSummary } from "../api";

const STATUS_COLORS: Record<string, { bg: string; text: string }> = {
  drafted: { bg: "#1c2431", text: "#8fa0bf" },
  applied: { bg: "#10202a", text: "#4fd6f0" },
  outreach_sent: { bg: "#1a1e3a", text: "#9d9dfa" },
  interview: { bg: "#2a2410", text: "#f2c94c" },
  offer: { bg: "#0f2a1e", text: "#4ade80" },
  rejected: { bg: "#2a1416", text: "#f87171" },
  ghosted: { bg: "#161a24", text: "#6b7690" },
};

export default function ApplicationsList() {
  const [applications, setApplications] = useState<ApplicationSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listApplications()
      .then(setApplications)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load"));
  }, []);

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-xl font-semibold">Applications</h1>
        <Link
          to="/new"
          className="rounded-md bg-[#4fd6f0] px-4 py-2 text-sm font-bold text-[#0c0f16] transition-opacity hover:opacity-90"
        >
          + New application
        </Link>
      </div>

      {error && (
        <p className="rounded-md border border-[#3a1f22] bg-[#1a1013] p-3 text-sm text-[#f87171]">{error}</p>
      )}

      {applications && applications.length === 0 && (
        <div className="rounded-lg border border-[#1c2431] bg-[#10141d] p-8 text-center text-sm text-[#6b7690]">
          No applications yet. Click "+ New application" to run the pipeline on a job description.
        </div>
      )}

      {applications && applications.length > 0 && (
        <div className="overflow-hidden rounded-lg border border-[#1c2431]">
          <table className="w-full text-sm">
            <thead className="bg-[#10141d] text-left text-[11px] uppercase tracking-wide text-[#6b7690]">
              <tr>
                <th className="px-5 py-3 font-medium">Company</th>
                <th className="px-5 py-3 font-medium">Role</th>
                <th className="px-5 py-3 font-medium">Date</th>
                <th className="px-5 py-3 font-medium">Score</th>
                <th className="px-5 py-3 font-medium">Resume</th>
                <th className="px-5 py-3 font-medium">Mode</th>
                <th className="px-5 py-3 font-medium">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#1c2431] bg-[#0c0f16]">
              {applications.map((app) => {
                const colors = STATUS_COLORS[app.status] ?? STATUS_COLORS.drafted;
                return (
                  <tr key={app.id} className="transition-colors hover:bg-[#10141d]">
                    <td className="px-5 py-3.5">
                      <Link to={`/applications/${app.id}`} className="font-medium text-[#e4e8f0] hover:text-[#4fd6f0]">
                        {app.company}
                      </Link>
                    </td>
                    <td className="px-5 py-3.5 text-[#9db3c9]">{app.role_title}</td>
                    <td className="px-5 py-3.5 font-mono text-[#6b7690]">{app.created_at.slice(0, 10)}</td>
                    <td className="px-5 py-3.5 font-mono font-semibold text-[#e4e8f0]">
                      {app.match_score !== null ? `${app.match_score.toFixed(0)}%` : "—"}
                    </td>
                    <td className="px-5 py-3.5 text-[#6b7690]">{app.resume_name ?? "—"}</td>
                    <td className="px-5 py-3.5 capitalize text-[#6b7690]">{app.mode}</td>
                    <td className="px-5 py-3.5">
                      <span
                        className="rounded-full px-2.5 py-1 text-xs font-medium"
                        style={{ background: colors.bg, color: colors.text }}
                      >
                        {app.status}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
