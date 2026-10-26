import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api, apiBlob } from "../api";
import Empty from "../components/Empty";
import Icon from "../components/Icon";
import type { CandidateRow, Job } from "../types";

const STATE: Record<string, string> = {
  uploaded: "Not screened yet",
  queued: "In the queue",
  screened: "Passed screening",
  excluded: "Excluded",
  unreadable: "File could not be read",
  failed: "Screening failed",
};

const received = (iso: string) =>
  new Date(iso).toLocaleString([], { day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit" });

// Step 3 of the pipeline: every CV this job received, in the order it arrived.
// ?since=<time> (from the "new CVs" notice) marks the ones that came after that moment.
export default function JobCvsPage() {
  const { id } = useParams();
  const [params] = useSearchParams();
  const since = params.get("since");
  const [job, setJob] = useState<Job | null>(null);
  const [rows, setRows] = useState<CandidateRow[] | null>(null);
  const [newestFirst, setNewestFirst] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    api<Job>(`/jobs/${id}`).then(setJob).catch((err) => setError(err.message));
    api<CandidateRow[]>(`/jobs/${id}/candidates`).then(setRows).catch((err) => setError(err.message));
  }, [id]);

  // Opens the CV in a new tab (the file needs the login, so it is fetched first).
  async function openCv(candidateId: number) {
    const tab = window.open("", "_blank");
    try {
      const blob = await apiBlob(`/candidates/${candidateId}/cv`);
      const url = URL.createObjectURL(blob);
      if (tab) tab.location.href = url;
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (err) {
      tab?.close();
      setError((err as Error).message);
    }
  }

  const sorted = [...(rows ?? [])].sort((a, b) => {
    const diff = Date.parse(a.created_at) - Date.parse(b.created_at);
    return newestFirst ? -diff : diff;
  });
  const isNew = (row: CandidateRow) => since !== null && Date.parse(row.created_at) > Date.parse(since);
  const fromForm = (rows ?? []).filter((r) => r.source === "google_form").length;

  return (
    <>
      <Link className="back-link" to={`/jobs/${id}/candidates`}>
        <Icon name="back" />
        Back to the job
      </Link>

      <div className="page-head">
        <div>
          <h1>CVs received</h1>
          <p>
            {job?.title ?? "Job"} · {rows?.length ?? 0} CVs · {(rows?.length ?? 0) - fromForm} uploaded · {fromForm} from the Google Form
          </p>
        </div>
        <div className="tabs glass" role="tablist" aria-label="Order">
          <button role="tab" aria-selected={newestFirst} onClick={() => setNewestFirst(true)}>
            Newest first
          </button>
          <button role="tab" aria-selected={!newestFirst} onClick={() => setNewestFirst(false)}>
            Oldest first
          </button>
        </div>
      </div>

      {error && <p className="error">{error}</p>}

      <div className="card glass flush">
        {rows === null ? (
          <p className="muted pad">Loading…</p>
        ) : rows.length === 0 ? (
          <Empty title="No CVs yet">Upload CVs or import them from the Google Form on the job page.</Empty>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Received</th>
                <th>Candidate</th>
                <th>CV file</th>
                <th>From</th>
                <th>State</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((row) => (
                <tr key={row.id} className={isNew(row) ? "is-new" : ""}>
                  <td className="nowrap">
                    {received(row.created_at)}
                    {isNew(row) && <span className="badge accent tiny">New</span>}
                  </td>
                  <td>
                    <Link to={`/candidates/${row.id}`}>{row.name || "Name not read yet"}</Link>
                    {row.email && <span className="cell-sub">{row.email}</span>}
                  </td>
                  <td>
                    <button className="link-button" onClick={() => openCv(row.id)} title="Open the CV in a new tab">
                      {row.cv_filename}
                    </button>
                  </td>
                  <td>{row.source === "google_form" ? "Google Form" : "Upload"}</td>
                  <td className="small">{STATE[row.status] ?? row.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <p className="muted small">For CVs from the Google Form, the time shown is when they were imported into TalentSight.</p>
    </>
  );
}
