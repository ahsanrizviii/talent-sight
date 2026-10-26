import { useAgentRun } from "../useAgentRun";
import type { InterviewScoreResult } from "../types";
import "../assessment.css";
import "../review.css";

// The interview's own score in six parts (Module 13, F9). Interviewer only (N9).
// Kept apart from the CV score: it never changes that score, the assessment or the stage.
export default function InterviewScoreCard({ sessionId }: { sessionId: number }) {
  const { run, loaded, error, starting, running, start } = useAgentRun<InterviewScoreResult>(`/interviews/${sessionId}/interview-score`);

  if (!loaded) return <p className="muted small">Loading the interview score…</p>;
  const done = run?.status === "done" ? run.result : null;

  return (
    <section className="card glass assessment review-card">
      <div className="row between">
        <div>
          <h2>Interview score</h2>
          <p className="muted small" style={{ margin: 0 }}>
            The interview scored as a whole, in six parts. Separate from the CV score.
          </p>
        </div>
        <button className="button secondary" onClick={() => void start()} disabled={running || starting}>
          {running ? "Scoring…" : run ? "Score again" : "Score the interview"}
        </button>
      </div>

      {!run && <p className="muted small">Needs the analysed answers above (“Analyse answers”).</p>}
      {error && <p className="error small">{error}</p>}
      {running && (
        <p className="as-step">
          <span className="as-spinner" aria-hidden="true" />
          {run?.step || "Working"}…
        </p>
      )}
      {run?.status === "failed" && <p className="error small">{run.error}</p>}
      {run?.status === "done" && run.outdated && (
        <div className="notice">The answers were analysed again after this score. Score again to update it.</div>
      )}

      {done && (
        <>
          <div className="rv-overall">
            <strong>{done.overall}</strong>
            <span className="muted">out of 100, from {done.answers} answered job question{done.answers === 1 ? "" : "s"}</span>
          </div>

          <ul className="rv-parts">
            {done.dimensions.map((part) => (
              <li key={part.key}>
                <div className="rv-part-head">
                  <span className="rv-part-name">{part.label}</span>
                  <span className="muted small">weight {part.weight}%</span>
                  <span className="rv-part-score">{part.score}</span>
                </div>
                <div className="bar" aria-hidden="true">
                  <div style={{ width: `${part.score}%` }} />
                </div>
                <p className="small rv-part-reason">
                  {part.reason}
                  {part.by === "code" && <span className="muted"> · worked out from coverage, not by the AI</span>}
                </p>
                {part.evidence && (
                  <blockquote className="rv-quote">
                    “{part.evidence.text}”<span className="muted small"> · candidate, at {part.evidence.at}</span>
                  </blockquote>
                )}
              </li>
            ))}
          </ul>

          <p className="muted small as-foot">
            Every part is in steps of 5. The overall score is the weighted average, worked out by plain code with fixed
            weights, so the same parts always give the same total.
          </p>
        </>
      )}
    </section>
  );
}