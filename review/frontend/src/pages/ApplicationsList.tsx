import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { listApplications, type ApplicationSummary } from "../api";

const STATUS_COLORS: Record<string, string> = {
  drafted: "bg-slate-100 text-slate-700",
  applied: "bg-blue-100 text-blue-700",
  outreach_sent: "bg-indigo-100 text-indigo-700",
  interview: "bg-amber-100 text-amber-700",
  offer: "bg-green-100 text-green-700",
  rejected: "bg-red-100 text-red-700",
  ghosted: "bg-slate-100 text-slate-500",
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
        <h1 className="text-2xl font-semibold">Applications</h1>
        <Link
          to="/new"
          className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800"
        >
          + New application
        </Link>
      </div>

      {error && <p className="rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</p>}

      {applications && applications.length === 0 && (
        <p className="text-sm text-slate-500">
          No applications yet. Click "New application" to run the pipeline on a job description.
        </p>
      )}

      {applications && applications.length > 0 && (
        <table className="w-full overflow-hidden rounded-md border border-slate-200 text-sm">
          <thead className="bg-slate-100 text-left text-xs font-medium uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-4 py-2">Company</th>
              <th className="px-4 py-2">Role</th>
              <th className="px-4 py-2">Date</th>
              <th className="px-4 py-2">Score</th>
              <th className="px-4 py-2">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 bg-white">
            {applications.map((app) => (
              <tr key={app.id} className="hover:bg-slate-50">
                <td className="px-4 py-3">
                  <Link to={`/applications/${app.id}`} className="font-medium text-slate-900 hover:underline">
                    {app.company}
                  </Link>
                </td>
                <td className="px-4 py-3 text-slate-600">{app.role_title}</td>
                <td className="px-4 py-3 text-slate-500">{app.created_at.slice(0, 10)}</td>
                <td className="px-4 py-3 text-slate-600">
                  {app.match_score !== null ? app.match_score.toFixed(0) : "—"}
                </td>
                <td className="px-4 py-3">
                  <span
                    className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_COLORS[app.status] ?? "bg-slate-100 text-slate-700"}`}
                  >
                    {app.status}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
