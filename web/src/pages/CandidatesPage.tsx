import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "../api";
import Empty from "../components/Empty";
import Icon from "../components/Icon";
import InviteDialog from "../components/InviteDialog";
import JobPipeline from "../components/JobPipeline";
import { LoadError } from "../components/PageState";
import LitmusCard from "../components/LitmusCard";
import type { CandidateRow, ChatSummary, ImportResult, Job, JobVisit, ScreeningRun, UploadResult } from "../types";

type Tab = "ranked" | "excluded" | "other";
type Busy = "" | "upload" | "import" | "screen-new" | "screen-all";

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
  const [busy, setBusy] = useState<Busy>("");
  const [loaded, setLoaded] = useState(false); // false until the first list arrives, so "empty" is never shown too early
  const [loadError, setLoadError] = useState("");
  const [lostContact, setLostContact] = useState(false); // the progress check stopped getting answers
  const [visit, setVisit] = useState<JobVisit | null>(null);
  const [inviting, setInviting] = useState(false);
  const wasRunning = useRef(false);

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
      .catch((err) => setLoadError(err.message));
    api<ChatSummary[]>(`/jd-chat?job_id=${id}`)
      .then(setChats)
      .catch(() => undefined);
    load()
      .then(() => setLoaded(true))
      .catch((err) => setLoadError(err.message));
  }, [id, load]);

  // Opening the job counts as a visit; the answer says how many CVs are new since the last one.
  useEffect(() => {
    setVisit(null);
    api<JobVisit>(`/jobs/${id}/visit`, { method: "POST" })
      .then(setVisit)
      .catch(() => undefined); // the notice is a nice-to-have: never block the page for it
  }, [id]);

  // When a screening that was running on this page finishes, the ranking pops up with the
  // "invite the top candidates" inputs: that is what comes next.
  useEffect(() => {
    if (run?.status === "running") {
      wasRunning.current = true;
    } else if (wasRunning.current && run?.status === "done") {
      wasRunning.current = false;
      if (candidates.some((c) => c.status === "screened")) setInviting(true);
    }
  }, [run?.status, candidates]);

  // While a screening runs, ask every 2 seconds how far it is. A failed check is shown, not hidden.
  useEffect(() => {
    if (run?.status !== "running") return;
    const timer = window.setInterval(
      () =>
        load()
          .then(() => setLostContact(false))
          .catch(() => setLostContact(true)),
      2000,
    );
    return () => window.clearInterval(timer);
  }, [run?.status, load]);

  async function act(kind: Busy, work: () => Promise<string>) {
    setBusy(kind);
    setError("");
    setMessage("");
    try {
      setMessage(await work());
      await load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy("");
    }
  }

  function upload(event: FormEvent) {
    event.preventDefault();
    if (!files?.length) return;
    const form = event.target as HTMLFormElement;
    act("upload", async () => {
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
    act("import", async () => {
      const result = await api<ImportResult>(`/jobs/${id}/candidates/import`, { method: "POST" });
      const failed = result.failed.map((f) => `${f.filename} (${f.error})`).join(", ");
      return `${result.imported} new CV(s) imported, ${result.skipped} already here.${failed ? ` Refused: ${failed}` : ""}`;
    });
  }

  function startScreening(again: boolean) {
    act(again ? "screen-all" : "screen-new", async () => {
      await api<ScreeningRun>(`/jobs/${id}/screening${again ? "?again=true" : ""}`, { method: "POST" });
      return "Screening started. You can leave this page; it keeps running.";
    });
  }

  const ranked = candidates.filter((c) => c.status === "screened");
  const excluded = candidates.filter((c) => c.status === "excluded");
  const other = candidates.filter((c) => c.status !== "screened" && c.status !== "excluded");
  const shown = { ranked, excluded, other }[tab];
  const running = run?.status === "running";

  if (loadError) return <LoadError message={loadError} back="/jobs" backLabel="Back to jobs" />;

  return (
    <>
      <Link className="back-link" to="/jobs">
        <Icon name="back" />
        All jobs
      </Link>

      <div className="page-head">
        <div>
          <h1>{job?.title ?? "Job"}</h1>
          <p>
            {loaded
              ? `${candidates.length} CVs · ${ranked.length} passed screening · ${excluded.length} excluded`
              : "Loading the candidates…"}
          </p>
        </div>
        <div className="row">
          {ranked.length > 0 && (
            <button className="button" type="button" onClick={() => setInviting(true)}>
              Invite top candidates
            </button>
          )}
          <Link className="button secondary" to={`/jobs/${id}/compare`}>
            Compare candidates
          </Link>
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

      {visit && visit.new_cvs > 0 && (
        <div className="notice new-cvs" role="status">
          <Icon name="sparkle" />
          <span className="grow">
            <strong>
              {visit.new_cvs} new {visit.new_cvs === 1 ? "CV" : "CVs"}
            </strong>{" "}
            {visit.since
              ? `since you last opened this job (${new Date(visit.since).toLocaleString([], { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" })}).`
              : "for this job so far."}
          </span>
          <Link to={`/jobs/${id}/cvs${visit.since ? `?since=${encodeURIComponent(visit.since)}` : ""}`}>See them</Link>
          <button className="notice-close" aria-label="Close the notice" onClick={() => setVisit(null)}>
            ×
          </button>
        </div>
      )}

      {job && <JobPipeline job={job} candidates={candidates} />}

      {inviting && id && (
        <InviteDialog jobId={id} ranked={ranked} onClose={() => setInviting(false)} onSent={() => load().catch(() => undefined)} />
      )}

      <div className="card glass">
        <h2>Add CVs</h2>
        <form className="row" onSubmit={upload}>
          <input type="file" multiple accept=".pdf,.docx" onChange={(event) => setFiles(event.target.files)} aria-label="CV files" />
          <button className="button secondary" type="submit" disabled={!!busy || !files?.length}>
            {busy === "upload" ? "Uploading…" : "Upload CVs"}
          </button>
          <button className="button secondary" type="button" disabled={!!busy} onClick={importFromForm}>
            {busy === "import" ? "Importing…" : "Import from Google Form"}
          </button>
        </form>
        <p className="muted small">PDF or DOCX, up to 5 MB each and 25 files at once.</p>
        {busy === "upload" && <p className="muted small busy-note">Uploading and reading the files. A large batch can take a minute.</p>}
        {busy === "import" && <p className="muted small busy-note">Fetching the CVs from the Google Form. This can take a minute.</p>}

        <p className="eyebrow">Screening</p>
        <div className="row">
          <button className="button" type="button" disabled={!!busy || running} onClick={() => startScreening(false)}>
            {busy === "screen-new" ? "Starting…" : "Screen the new CVs"}
          </button>
          <button className="button secondary" type="button" disabled={!!busy || running} onClick={() => startScreening(true)}>
            {busy === "screen-all" ? "Starting…" : "Screen everyone again"}
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
            {running && lostContact && (
              <p className="error small">
                Lost contact with the server. The progress will update again when the connection is back.
              </p>
            )}
          </div>
        )}

        {error && <p className="error">{error}</p>}
        {message && <p className="success">{message}</p>}
      </div>

      <div className="tabs glass" role="tablist">
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

      <div className="card glass flush">
        {!loaded ? (
          <div className="pad" role="status" aria-busy="true">
            <span className="sr-only">Loading the candidates…</span>
            <div className="skeleton" />
            <div className="skeleton" />
          </div>
        ) : shown.length === 0 ? (
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

      {id && <LitmusCard jobId={id} hasShortlist={ranked.length > 0} />}
    </>
  );
}