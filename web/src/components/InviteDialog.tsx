import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { api } from "../api";
import type { CandidateRow, HolidayStatus, InviteBatch, InviteTopResult } from "../types";

// The pop-up after screening: the ranking of everyone who passed, and two inputs, the first
// interview day and how many of the top candidates to invite. One click books a free 1-hour slot
// for each of them (weekends and public holidays are skipped) and e-mails them their private link.

const pad = (n: number) => String(n).padStart(2, "0");
const isoDay = (date: Date) => `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
const when = (iso: string) =>
  new Date(iso).toLocaleString([], { weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });

type Props = { jobId: string; ranked: CandidateRow[]; onClose: () => void; onSent: () => void };

export default function InviteDialog({ jobId, ranked, onClose, onSent }: Props) {
  const tomorrow = isoDay(new Date(Date.now() + 24 * 60 * 60 * 1000));
  const [startDate, setStartDate] = useState(tomorrow);
  const [top, setTop] = useState(Math.min(5, ranked.length));
  const [result, setResult] = useState<InviteTopResult | null>(null);
  const [batch, setBatch] = useState<InviteBatch | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [info, setInfo] = useState<HolidayStatus | null>(null);

  // How many holidays the planner will skip, or a warning when the holiday calendar was not read.
  useEffect(() => {
    api<HolidayStatus>(`/jobs/${jobId}/invite-info`).then(setInfo).catch(() => undefined);
  }, [jobId]);

  // Close with the Escape key, like any other pop-up.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // While e-mails are still going out (one a second), check again every second and a half.
  useEffect(() => {
    if (!batch || batch.queued === 0) return;
    const timer = window.setTimeout(() => {
      api<InviteBatch | null>(`/jobs/${jobId}/invite-batches/latest`).then((latest) => latest && setBatch(latest)).catch(() => undefined);
    }, 1500);
    return () => window.clearTimeout(timer);
  }, [batch, jobId]);

  async function send(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const answer = await api<InviteTopResult>(`/jobs/${jobId}/invite-top`, {
        method: "POST",
        body: JSON.stringify({ top, start_date: startDate }),
      });
      setResult(answer);
      setBatch(answer.batch);
      onSent();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function retry() {
    if (!batch) return;
    setError("");
    try {
      setBatch(await api<InviteBatch>(`/jobs/${jobId}/invite-batches/${batch.id}/retry`, { method: "POST" }));
    } catch (err) {
      setError((err as Error).message);
    }
  }

  const count = Math.max(1, Math.min(top || 1, ranked.length));

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal glass" role="dialog" aria-modal="true" aria-labelledby="invite-title" onClick={(event) => event.stopPropagation()}>
        <div className="modal-head">
          <h2 id="invite-title">{result ? "Invitations" : "Ranking"}</h2>
          <button className="notice-close" type="button" aria-label="Close" onClick={onClose}>
            ×
          </button>
        </div>

        {!result ? (
          <>
            <p className="muted small">
              {ranked.length} {ranked.length === 1 ? "candidate" : "candidates"} passed screening, best score first. The top {count}{" "}
              {count === 1 ? "is" : "are"} marked.
            </p>
            <div className="modal-table">
              <table>
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Candidate</th>
                    <th className="right">Score</th>
                    <th>Requirements</th>
                  </tr>
                </thead>
                <tbody>
                  {ranked.map((candidate, index) => (
                    <tr key={candidate.id} className={index < count ? "chosen" : ""}>
                      <td className="muted num">{candidate.rank ?? index + 1}</td>
                      <td>
                        {candidate.name || candidate.cv_filename}
                        <span className="cell-sub">{candidate.email || "No e-mail address"}</span>
                      </td>
                      <td className="right score-cell">{candidate.overall ?? "—"}</td>
                      <td>
                        <span className="verdict-counts">
                          <span className="verdict-met">{candidate.met} met</span>
                          <span className="verdict-partially_met">{candidate.partially_met} partly</span>
                          <span className="verdict-unmet">{candidate.unmet} unmet</span>
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <form className="invite-inputs" onSubmit={send}>
              <div className="field">
                <label htmlFor="first-day">First interview day</label>
                <input id="first-day" type="date" value={startDate} min={isoDay(new Date())} onChange={(e) => setStartDate(e.target.value)} required />
              </div>
              <div className="field">
                <label htmlFor="how-many">How many top candidates</label>
                <input
                  id="how-many"
                  type="number"
                  min={1}
                  max={ranked.length}
                  value={top}
                  onChange={(e) => setTop(Number(e.target.value))}
                  required
                />
              </div>
              <button className="button" type="submit" disabled={busy || !startDate || ranked.length === 0}>
                {busy ? "Sending…" : `Send invitations to the top ${count}`}
              </button>
            </form>
            <p className="muted small">
              Each interview is 1 hour, between 9:00 and 12:00 or 14:00 and 17:00, Monday to Friday, with 15 minutes between interviews.
              Weekends and public holidays are skipped. The best-ranked candidate gets the earliest time.
            </p>
            {info &&
              (info.calendar_problem ? (
                <p className="warn-line">⚠ Holiday calendar: {info.calendar_problem}</p>
              ) : (
                <p className="ok-line">✓ {info.holidays_ahead} upcoming public holidays from the government calendar are skipped.</p>
              ))}
          </>
        ) : (
          <>
            {batch ? (
              <p className={batch.failed ? "warn-line" : "ok-line"}>
                {batch.queued > 0
                  ? `Sending… ${batch.sent} of ${batch.total} e-mails sent.`
                  : batch.failed
                    ? `${batch.sent} of ${batch.total} e-mails sent. ${batch.failed} could not be sent.`
                    : `All ${batch.total} invitations sent.`}
              </p>
            ) : (
              <p className="warn-line">Nobody was invited.</p>
            )}

            {batch && (
              <ul className="delivery-list">
                {batch.deliveries.map((delivery) => (
                  <li key={delivery.session_id}>
                    <Link to={`/candidates/${delivery.candidate_id}`}>{delivery.name}</Link>
                    <span className="muted">{when(delivery.scheduled_at)}</span>
                    <span className={delivery.status === "failed" ? "error small" : delivery.status === "sent" ? "success small" : "muted small"}>
                      {delivery.status === "sent" ? "Sent" : delivery.status === "queued" ? "Sending…" : delivery.error || "Not sent"}
                    </span>
                  </li>
                ))}
              </ul>
            )}

            {result.skipped.length > 0 && (
              <p className="muted small">
                Not invited again: {result.skipped.map((s) => `${s.name} (${s.reason.toLowerCase().replace(/\.$/, "")})`).join(", ")}.
              </p>
            )}
            {result.not_placed > 0 && <p className="warn-line">{result.not_placed} could not be given a time within the next year.</p>}

            <div className="row">
              {batch && batch.failed > 0 && batch.queued === 0 && (
                <button className="button secondary" type="button" onClick={retry}>
                  Try the failed e-mails again
                </button>
              )}
              <Link className="button secondary" to="/interviews">
                See the interviews
              </Link>
              <button className="button" type="button" onClick={onClose}>
                Done
              </button>
            </div>
          </>
        )}
        {error && <p className="error">{error}</p>}
      </div>
    </div>
  );
}
