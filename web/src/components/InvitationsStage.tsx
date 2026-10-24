import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api";
import Empty from "./Empty";
import type { EmailRow } from "../types";
import { clockTime, shortDate } from "../when";

const KINDS = { invitation: "Interview invitation", rejection: "Rejection", onboarding: "Onboarding" };
const STATES = { queued: "Sending…", sent: "Sent", failed: "Failed" };

type Props = { jobId: string; canInvite: boolean; onInvite: () => void; onChange: () => void };

// The Invitations stage of a job: every e-mail it has sent, for every round, with whether each one
// was sent, is still queued, or failed (and why). Failed ones can be tried again in one click.
export default function InvitationsStage({ jobId, canInvite, onInvite, onChange }: Props) {
  const [rows, setRows] = useState<EmailRow[] | null>(null);
  const [kind, setKind] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const load = useCallback(
    () =>
      api<EmailRow[]>(`/jobs/${jobId}/emails`)
        .then(setRows)
        .catch((err) => setError(err.message)),
    [jobId],
  );

  useEffect(() => {
    void load();
  }, [load]);

  // While e-mails are going out (about one a second), check again every 2 seconds. When the last
  // one has gone, the stage bar's numbers are refreshed once.
  const sending = !!rows?.some((row) => row.status === "queued");
  const wasSending = useRef(false);
  useEffect(() => {
    if (!sending) return;
    const timer = window.setInterval(() => void load(), 2000);
    return () => window.clearInterval(timer);
  }, [sending, load]);
  useEffect(() => {
    if (sending) {
      wasSending.current = true;
    } else if (wasSending.current) {
      wasSending.current = false;
      onChange();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sending]);

  async function retry() {
    setError("");
    setMessage("");
    try {
      const answer = await api<{ started: number }>(`/jobs/${jobId}/emails/retry`, { method: "POST" });
      setMessage(`Trying ${answer.started} e-mail${answer.started === 1 ? "" : "s"} again.`);
      window.setTimeout(() => void load(), 1000);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  const shown = (rows ?? []).filter((row) => !kind || row.kind === kind);
  const failed = (rows ?? []).filter((row) => row.status === "failed").length;
  const count = (state: EmailRow["status"]) => (rows ?? []).filter((row) => row.status === state).length;

  return (
    <>
      <div className="card glass round-head">
        <div>
          <h2 style={{ margin: 0 }}>Invitations and e-mails</h2>
          <p className="small" style={{ margin: "4px 0 0" }}>
            {rows ? `${rows.length} e-mails · ${count("sent")} sent · ${count("queued")} sending · ${count("failed")} failed` : "Loading…"}
          </p>
        </div>
        <div className="row">
          {failed > 0 && (
            <button className="button secondary" type="button" onClick={() => void retry()}>
              Try the {failed} failed again
            </button>
          )}
          {canInvite && (
            <button className="button" type="button" onClick={onInvite}>
              Invite top candidates to round 1
            </button>
          )}
        </div>
      </div>

      <div className="filters glass">
        <select value={kind} onChange={(event) => setKind(event.target.value)} aria-label="Kind of e-mail">
          <option value="">Every kind</option>
          <option value="invitation">Interview invitations</option>
          <option value="rejection">Rejections</option>
          <option value="onboarding">Onboarding</option>
        </select>
        <span className="spacer result-count">{shown.length} shown</span>
      </div>

      {error && <p className="error">{error}</p>}
      {message && <p className="success">{message}</p>}

      <div className="card glass flush">
        {rows === null ? (
          <div style={{ padding: 18 }}>
            <div className="skeleton" />
          </div>
        ) : shown.length === 0 ? (
          <Empty title="No e-mails yet">Invitations, rejections and onboarding e-mails of this job appear here as they go out.</Empty>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Candidate</th>
                <th>E-mail</th>
                <th>Round</th>
                <th>When</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((row) => {
                const at = row.sent_at ?? row.created_at;
                return (
                  <tr key={row.key}>
                    <td>
                      <Link to={`/candidates/${row.candidate_id}`}>{row.name}</Link>
                      <span className="cell-sub">{row.email || "No e-mail address"}</span>
                    </td>
                    <td>{KINDS[row.kind]}</td>
                    <td className="muted">{row.round_number ? `Round ${row.round_number} · ${row.round_name}` : row.round_name}</td>
                    <td className="nowrap muted">
                      {shortDate(at)} {clockTime(at)}
                    </td>
                    <td>
                      <span className={row.status === "sent" ? "badge pass" : row.status === "failed" ? "badge stop" : "badge accent"}>
                        {STATES[row.status]}
                      </span>
                      {row.error && <span className="cell-sub error">{row.error}</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
