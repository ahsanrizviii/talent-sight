import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "../api";
import Empty from "../components/Empty";
import Icon from "../components/Icon";
import JobPipeline from "../components/JobPipeline";
import type { CandidateRow, ChatSummary, ImportResult, Job, ScreeningRun, UploadResult } from "../types";

type Tab = "ranked" | "excluded" | "other";

const STATUS_LABELS: Record<string, string> = {
  uploaded: "Waiting to be screened",
  queued: "In the queue",
  unreadable: "The file could not be read",
  failed: "Screening failed",
};

// One job's own pipeline: add CVs, screen them, and read the shortlist that comes out.
export default function CandidatesPage() {
  const { id } = useParams();
  const [job, setJob] = useState<Job | null>(null);
  const [candidates, setCandidates] = useState<CandidateRow[]>([]);
  const [run, setRun] = useState<ScreeningRun | null>(null);
  const [chats, setChats] = useState<ChatSummary[]>([]);
  const [files, setFiles] = useState<FileList | null>(null);
  const [tab, setTab] = useState<Tab>("ranked");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const [list, latest] = await Promise.all([
      api<CandidateRow[]>(`/jobs/${id}/candidates`),
      api<ScreeningRun | null>(`/jobs/${id}/screening`),
    ]);
    setCandidates(list);
    setRun(latest);
  }, [id]);

  useEffect(() => {
    api<Job>(`/jobs/${id}`)
      .then(setJob)
      .catch((err) => setError(err.message));
    api<ChatSummary[]>(`/jd-chat?job_id=${id}`)
      .then(setChats)
      .catch(() => undefined);
    load().catch((err) => setError(err.message));
  }, [id, load]);

  useEffect(() => {
    if (run?.status !== "running") return;
    const timer = window.setInterval(() => load().catch(() => undefined), 2000);
    return () => window.clearInterval(timer);
  }, [run?.status, load]);

  async function act(work: () => Promise<string>) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      setMessage(await work());
      await load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function upload(event: FormEvent) {
    event.preventDefault();
    if (!files?.length) return;
    const form = event.target as HTMLFormElement;
    act(async () => {
      const body = new FormData();
      Array.from(files).forEach((file) => body.append("files", file));
      const results = await api<UploadResult[]>(`/jobs/${id}/candidates`, { method: "POST", body });
      setFiles(null);
      form.reset();
      const refused = results.filter((result) => !result.ok);
      const added = `${results.length - refused.length} CV(s) added.`;
      return refused.length
        ? `${added} Refused: ${refused.map((r) => `${r.filename} (${r.error})`).join(", ")}`
        : added;
    });
  }

  function importFromForm() {
    act(async () => {
      const result = await api<ImportResult>(`/jobs/${id}/candidates/import`, { method: "POST" });
      const failed = result.failed.map((f) => `${f.filename} (${f.error})`).join(", ");
      return `${result.imported} new CV(s) imported, ${result.skipped} already here.${failed ? ` Refused: ${failed}` : ""}`;
    });
  }

  function startScreening(again: boolean) {
    act(async () => {
      await api<ScreeningRun>(`/jobs/${id}/screening${again ? "?again=true" : ""}`, { method: "POST" });
      return "Screening started. You can leave this page; it keeps running.";
    });
  }

  const ranked = candidates.filter((c) => c.status === "screened");
  const excluded = candidates.filter((c) => c.status === "excluded");
  const other = candidates.filter((c) => c.status !== "screened" && c.status !== "excluded");
  const shown = { ranked, excluded, other }[tab];
  const running = run?.status === "running";

  return (
    <>
      <Link className="back-link" to="/jobs">
        <Icon name="back" />
        All jobs
      </Link>

      <div className="page-head">
        <div>
          <h1>{job?.title ?? "Job"}</h1>
          <p>{candidates.length} CVs · {ranked.length} passed screening · {excluded.length} excluded</p>
        </div>
        <div className="row">
          <Link className="button secondary" to={`/jobs/${id}`}>
            Edit the job
          </Link>
          {chats[0] && (
            <Link className="button quiet" to={`/jd-chat/${chats[0].thread_id}`}>
              <Icon name="sparkle" />
              How this job was written
            </Link>
          )}
        </div>
      </div>

      {job && <JobPipeline job={job} candidates={candidates} />}

      <div className="card">
        <h2>Add CVs</h2>
        <form className="row" onSubmit={upload}>
          <input type="file" multiple accept=".pdf,.docx" onChange={(event) => setFiles(event.target.files)} aria-label="CV files" />
          <button className="button secondary" type="submit" disabled={busy || !files?.length}>
            Upload CVs
          </button>
          <button className="button secondary" type="button" disabled={busy} onClick={importFromForm}>
            Import from Google Form
          </button>
        </form>
        <p className="muted small">PDF or DOCX, up to 5 MB each and 25 files at once.</p>

        <p className="eyebrow">Screening</p>
        <div className="row">
          <button className="button" type="button" disabled={busy || running} onClick={() => startScreening(false)}>
            Screen the new CVs
          </button>
          <button className="button secondary" type="button" disabled={busy || running} onClick={() => startScreening(true)}>
            Screen everyone again
          </button>
        </div>

        {run && (
          <div className="progress-block">
            <div className="progress" aria-label="Screening progress">
              <div style={{ width: `${run.total ? (100 * run.done) / run.total : 0}%` }} />
            </div>
            <p className="muted small">
              {running ? "Screening" : run.status === "done" ? "Last screening" : "The last screening was interrupted"}:{" "}
              {run.done} of {run.total} CVs
              {run.failed ? `, ${run.failed} failed` : ""}
              {run.seconds !== null && ` · took ${Math.round(run.seconds)} s`}
            </p>
          </div>
        )}

        {error && <p className="error">{error}</p>}
        {message && <p className="success">{message}</p>}
      </div>

      <div className="tabs" role="tablist">
        <button role="tab" aria-selected={tab === "ranked"} onClick={() => setTab("ranked")}>
          Shortlist ({ranked.length})
        </button>
        <button role="tab" aria-selected={tab === "excluded"} onClick={() => setTab("excluded")}>
          Excluded ({excluded.length})
        </button>
        <button role="tab" aria-selected={tab === "other"} onClick={() => setTab("other")}>
          Not screened ({other.length})
        </button>
      </div>

      <div className="card flush">
        {shown.length === 0 ? (
          <Empty title={tab === "ranked" ? "No shortlist yet" : "Nothing here"}>
            {tab === "ranked"
              ? "Upload CVs above and run the screening. Everyone who meets the must-have requirements appears here, best score first."
              : "Nothing in this group."}
          </Empty>
        ) : (
          <table>
            <thead>
              <tr>
                <th>{tab === "ranked" ? "#" : ""}</th>
                <th>Candidate</th>
                {tab === "ranked" && <th className="right">Score</th>}
                <th>Requirements</th>
                <th>{tab === "excluded" ? "Why" : "State"}</th>
                <th>From</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((candidate) => (
                <tr key={candidate.id}>
                  <td className="muted num">{candidate.rank ?? ""}</td>
                  <td>
                    <Link to={`/candidates/${candidate.id}`}>{candidate.name || candidate.cv_filename}</Link>
                    <span className="cell-sub">{candidate.email || candidate.cv_filename}</span>
                  </td>
                  {tab === "ranked" && <td className="right score-cell">{candidate.overall ?? "—"}</td>}
                  <td>
                    {candidate.met + candidate.partially_met + candidate.unmet > 0 ? (
                      <span className="verdict-counts">
                        <span className="verdict-met">{candidate.met} met</span>
                        <span className="verdict-partially_met">{candidate.partially_met} partly</span>
                        <span className="verdict-unmet">{candidate.unmet} unmet</span>
                      </span>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                  <td className={tab === "excluded" ? "small muted" : ""}>
                    {tab === "excluded" ? candidate.exclusion_reason : (STATUS_LABELS[candidate.status] ?? "Screened")}
                    {candidate.error && <span className="cell-sub error">{candidate.error}</span>}
                  </td>
                  <td className="muted small">{candidate.source === "google_form" ? "Google Form" : "Upload"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
