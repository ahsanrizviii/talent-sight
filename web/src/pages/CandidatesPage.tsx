import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "../api";
import type {
  CandidateRow,
  ImportResult,
  Job,
  ScreeningRun,
  UploadResult,
} from "../types";

type Tab = "ranked" | "excluded" | "other";

const STATUS_LABELS: Record<string, string> = {
  uploaded: "Waiting for screening",
  queued: "In the queue",
  unreadable: "Unreadable file",
  failed: "Screening failed",
};

export default function CandidatesPage() {
  const { id } = useParams();
  const [job, setJob] = useState<Job | null>(null);
  const [candidates, setCandidates] = useState<CandidateRow[]>([]);
  const [run, setRun] = useState<ScreeningRun | null>(null);
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
    act(async () => {
      const body = new FormData();
      Array.from(files).forEach((file) => body.append("files", file));
      const results = await api<UploadResult[]>(`/jobs/${id}/candidates`, {
        method: "POST",
        body,
      });
      setFiles(null);
      (event.target as HTMLFormElement).reset();
      const refused = results.filter((r) => !r.ok);
      const added = `${results.length - refused.length} CV(s) added.`;
      return refused.length
        ? `${added} Refused: ${refused
            .map((r) => `${r.filename} (${r.error})`)
            .join(", ")}`
        : added;
    });
  }

  function importFromForm() {
    act(async () => {
      const result = await api<ImportResult>(`/jobs/${id}/candidates/import`, {
        method: "POST",
      });
      const failed = result.failed
        .map((f) => `${f.filename} (${f.error})`)
        .join(", ");
      return `${result.imported} new CV(s) imported, ${result.skipped} already here.${
        failed ? ` Refused: ${failed}` : ""
      }`;
    });
  }

  function startScreening(again: boolean) {
    act(async () => {
      await api<ScreeningRun>(`/jobs/${id}/screening${again ? "?again=true" : ""}`, {
        method: "POST",
      });
      return "Screening started. You can leave this page; it keeps running.";
    });
  }

  const ranked = candidates.filter((c) => c.status === "screened");
  const excluded = candidates.filter((c) => c.status === "excluded");
  const other = candidates.filter(
    (c) => c.status !== "screened" && c.status !== "excluded"
  );
  const shown = { ranked, excluded, other }[tab];
  const running = run?.status === "running";

  return (
    <>
      <p>
        <Link className="back-link" to={`/jobs/${id}`}>
          ← {job?.title ?? "Job"}
        </Link>
      </p>

      <h1>Candidates</h1>

      <div className="card">
        <p className="eyebrow">Add CVs</p>
        <form className="row" onSubmit={upload}>
          <input
            type="file"
            multiple
            accept=".pdf,.docx"
            onChange={(e) => setFiles(e.target.files)}
            aria-label="CV files"
          />
          <button
            className="button secondary"
            type="submit"
            disabled={busy || !files?.length}
          >
            Upload CVs
          </button>
          <button
            className="button secondary"
            type="button"
            disabled={busy}
            onClick={importFromForm}
          >
            Import from Google Form
          </button>
        </form>
        <p className="muted small">
          PDF or DOCX, up to 5 MB each and 25 files at once.
        </p>

        <p className="eyebrow">Screening</p>
        <div className="row">
          <button
            className="button"
            type="button"
            disabled={busy || running}
            onClick={() => startScreening(false)}
          >
            Run screening
          </button>
          <button
            className="button secondary"
            type="button"
            disabled={busy || running}
            onClick={() => startScreening(true)}
          >
            Screen all again
          </button>
        </div>

        {run && (
          <div className="progress-block">
            <div className="progress" aria-label="Screening progress">
              <div
                style={{
                  width: `${run.total ? (100 * run.done) / run.total : 0}%`,
                }}
              />
            </div>
            <p className="muted small">
              {running
                ? "Screening"
                : run.status === "done"
                  ? "Last screening"
                  : "Last screening was interrupted"}
              : {run.done} of {run.total} CVs
              {run.failed ? `, ${run.failed} failed` : ""}
              {run.seconds !== null && ` · took ${Math.round(run.seconds)} s`}
            </p>
          </div>
        )}

        {error && <p className="error">{error}</p>}
        {message && <p className="success">{message}</p>}
      </div>

      <div className="tabs" role="tablist">
        <button
          role="tab"
          aria-selected={tab === "ranked"}
          onClick={() => setTab("ranked")}
        >
          Ranked ({ranked.length})
        </button>
        <button
          role="tab"
          aria-selected={tab === "excluded"}
          onClick={() => setTab("excluded")}
        >
          Excluded ({excluded.length})
        </button>
        <button
          role="tab"
          aria-selected={tab === "other"}
          onClick={() => setTab("other")}
        >
          Not screened ({other.length})
        </button>
      </div>

      <div className="card">
        {shown.length === 0 ? (
          <p className="muted">No candidates here.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>{tab === "ranked" ? "#" : ""}</th>
                <th>Candidate</th>
                <th>Requirements</th>
                <th>{tab === "excluded" ? "Reason" : "Status"}</th>
                <th>From</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((c, index) => (
                <tr key={c.id}>
                  <td className="muted">{tab === "ranked" ? index + 1 : ""}</td>
                  <td>
                    <Link to={`/candidates/${c.id}`}>
                      {c.name || c.cv_filename}
                    </Link>
                    <div className="muted small">
                      {c.email || c.cv_filename}
                    </div>
                  </td>
                  <td>
                    {c.met + c.partially_met + c.unmet > 0 ? (
                      <span className="verdict-counts">
                        <span className="verdict-met">{c.met} met</span>
                        <span className="verdict-partially_met">
                          {c.partially_met} partial
                        </span>
                        <span className="verdict-unmet">{c.unmet} unmet</span>
                      </span>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className={tab === "excluded" ? "small" : ""}>
                    {tab === "excluded"
                      ? c.exclusion_reason
                      : (STATUS_LABELS[c.status] ?? "Screened")}
                    {c.error && <div className="error small">{c.error}</div>}
                  </td>
                  <td className="muted small">
                    {c.source === "google_form" ? "Google Form" : "Upload"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}