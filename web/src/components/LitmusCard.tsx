import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import "../assessment.css";
import "../litmus.css";
import { OUTCOMES, type LitmusOutcome } from "./LitmusPanel";

// Litmus (F11) for a whole job: how many of the checked candidates are steady, which kind of
// change moved scores most often, and who still waits for a review. One button checks the top of
// the shortlist, one candidate after another; candidates already checked and up to date are skipped.

type JobLitmus = {
  job_id: number;
  checked: number;
  in_progress: number;
  outcomes: Record<LitmusOutcome, number>;
  pass_rate: number | null;
  pending_review: number;
  copies: { key: string; label: string; runs: number; flags: number; average_move: number | null }[];
  candidates: {
    candidate_id: number;
    name: string;
    check_id: number;
    outcome: LitmusOutcome;
    review_status: "" | "pending" | "acknowledged";
    outdated: boolean;
    finished_at: string | null;
  }[];
  total_checks: number;
  total_cost_usd: number;
  shortlist_size: number;
};

export default function LitmusCard({ jobId, hasShortlist }: { jobId: string; hasShortlist: boolean }) {
  const [summary, setSummary] = useState<JobLitmus | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [starting, setStarting] = useState(false);

  const load = useCallback(
    () =>
      api<JobLitmus>(`/jobs/${jobId}/litmus`)
        .then(setSummary)
        .catch((err) => setError(err.message)),
    [jobId],
  );

  useEffect(() => {
    void load();
  }, [load]);

  // While checks are queued or running, ask every 3 seconds.
  const busy = (summary?.in_progress ?? 0) > 0;
  useEffect(() => {
    if (!busy) return;
    const timer = window.setInterval(() => void load(), 3000);
    return () => window.clearInterval(timer);
  }, [busy, load]);

  async function checkShortlist() {
    setStarting(true);
    setError("");
    setMessage("");
    try {
      const queued = await api<{ queued: number }>(`/jobs/${jobId}/litmus`, { method: "POST" });
      setMessage(`${queued.queued} ${queued.queued === 1 ? "check" : "checks"} queued. They run one after another.`);
      await load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setStarting(false);
    }
  }

  if (!summary) return error ? <p className="error small">{error}</p> : null;

  return (
    <section className="card glass">
      <div className="row between">
        <div>
          <h2>Litmus</h2>
          <p className="muted small" style={{ margin: 0 }}>
            Checks that the CV scores for this job rest on the CVs, not on who the candidates are.
          </p>
        </div>
        <button className="button secondary" onClick={checkShortlist} disabled={!hasShortlist || starting || busy}>
          {busy ? "Checking…" : starting ? "Starting…" : `Check the top ${summary.shortlist_size}`}
        </button>
      </div>

      {error && <p className="error small">{error}</p>}
      {message && <p className="success small">{message}</p>}
      {busy && (
        <p className="as-step">
          <span className="as-spinner" aria-hidden="true" />
          {summary.in_progress} {summary.in_progress === 1 ? "check" : "checks"} waiting or running…
        </p>
      )}

      {summary.checked === 0 ? (
        <p className="muted small">
          No candidate of this job has been checked yet. Check the top of the shortlist here, or one candidate from
          their own page (Litmus tab).
        </p>
      ) : (
        <>
          <div className="pl-stats">
            <div>
              <strong>{summary.pass_rate ?? "—"}%</strong>
              <span>steady ({summary.outcomes.steady} of {summary.checked})</span>
            </div>
            <div>
              <strong>{summary.outcomes.needs_review}</strong>
              <span>needed review</span>
            </div>
            <div>
              <strong>{summary.outcomes.inconclusive}</strong>
              <span>inconclusive</span>
            </div>
            <div>
              <strong>{summary.pending_review}</strong>
              <span>still waiting for a person</span>
            </div>
          </div>

          <table className="pl-table">
            <thead>
              <tr>
                <th>Kind of change</th>
                <th className="right">Checked</th>
                <th className="right">Flagged</th>
                <th className="right">Average move</th>
              </tr>
            </thead>
            <tbody>
              {summary.copies.map((copy) => (
                <tr key={copy.key} className={copy.flags ? "pl-flagged" : ""}>
                  <td>{copy.label}</td>
                  <td className="right num">{copy.runs}</td>
                  <td className="right num">{copy.flags}</td>
                  <td className="right num">{copy.average_move === null ? "—" : `${copy.average_move} pts`}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <ul className="pl-people">
            {summary.candidates.map((person) => (
              <li key={person.candidate_id}>
                <Link to={`/candidates/${person.candidate_id}?tab=litmus`}>{person.name}</Link>
                <span className={`badge ${OUTCOMES[person.outcome]?.tone ?? ""}`}>{OUTCOMES[person.outcome]?.label}</span>
                {person.review_status === "pending" && <span className="badge warn">Review waiting</span>}
                {person.review_status === "acknowledged" && <span className="muted small">acknowledged</span>}
                {person.outdated && <span className="muted small">outdated</span>}
              </li>
            ))}
          </ul>

          <p className="muted small as-foot">
            {summary.total_checks} {summary.total_checks === 1 ? "check" : "checks"} run for this job · $
            {summary.total_cost_usd.toFixed(4)} in total. The latest check of each candidate is counted.
          </p>
        </>
      )}
    </section>
  );
}
