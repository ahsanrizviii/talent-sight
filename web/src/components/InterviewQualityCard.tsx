import { useAgentRun } from "../useAgentRun";
import type { QualityMeasures, QualityResult } from "../types";
import "../assessment.css";
import "../review.css";

// How well the interview itself was run (Module 13, F10). Interviewer only (N9).
// It reviews the interview, not the candidate, and never changes the score or the stage.

const KIND_TONE: Record<string, string> = { open: "pass", probing: "pass", closed: "warn", leading: "stop", unclear: "warn", unrated: "" };

type Tile = { key: keyof QualityMeasures; label: string; unit: string };
const TILES: Tile[] = [
  { key: "interviewer_talk_pct", label: "Interviewer talk time", unit: "%" },
  { key: "questions", label: "Job questions", unit: "" },
  { key: "follow_ups", label: "Follow-up questions", unit: "" },
  { key: "coverage_pct", label: "Requirements explored", unit: "%" },
];

export default function InterviewQualityCard({ sessionId }: { sessionId: number }) {
  const { run, loaded, error, starting, running, start } = useAgentRun<QualityResult>(`/interviews/${sessionId}/quality`);

  if (!loaded) return <p className="muted small">Loading the interview review…</p>;
  const done = run?.status === "done" ? run.result : null;

  return (
    <section className="card glass assessment review-card">
      <div className="row between">
        <div>
          <h2>Interview quality</h2>
          <p className="muted small" style={{ margin: 0 }}>
            How the interview was run: talk time, questions and coverage. It reviews the interview, not the candidate.
          </p>
        </div>
        <button className="button secondary" onClick={() => void start()} disabled={running || starting}>
          {running ? "Reviewing…" : run ? "Review again" : "Review the interview"}
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
        <div className="notice">The answers were analysed again after this review. Review again to update it.</div>
      )}

      {done && (
        <>
          <div className="rv-tiles">
            {TILES.map((tile) => {
              const average = done.compare.average[tile.key];
              return (
                <div className="rv-tile" key={tile.key}>
                  <strong>
                    {done.measures[tile.key]}
                    {tile.unit}
                  </strong>
                  <span>{tile.key === "coverage_pct" && done.round_type === "hr" ? "HR topics explored" : tile.label}</span>
                  {average !== undefined && (
                    <small>
                      Round average {average}
                      {tile.unit}
                    </small>
                  )}
                </div>
              );
            })}
          </div>

          {done.summary && <p className="rv-summary">{done.summary}</p>}

          {done.personal.length > 0 && (
            <div className="notice stop">
              <strong>Questions that touch a personal matter.</strong> These must not be asked in an interview:
              <ul className="rv-plain">
                {done.personal.map((item) => (
                  <li key={item.turn}>
                    at {item.at}: “{item.text}”
                  </li>
                ))}
              </ul>
            </div>
          )}

          <h3 className="rv-head">Recommendations</h3>
          <ul className="rv-recs">
            {done.recommendations.map((item, i) => (
              <li key={i}>
                {item.text}
                <span className="muted small"> · {item.at ? `at ${item.at}` : "whole interview"}</span>
              </li>
            ))}
          </ul>

          <h3 className="rv-head">The job questions</h3>
          <ul className="rv-questions">
            {done.questions.map((item) => (
              <li key={item.id}>
                <div className="rv-q-head">
                  <span className={`badge ${KIND_TONE[item.kind] ?? ""}`}>{item.label}</span>
                  <span className="muted small">at {item.at}</span>
                </div>
                <p className="rv-q">{item.question}</p>
                {item.note && <p className="muted small rv-note">{item.note}</p>}
              </li>
            ))}
          </ul>

          <p className="muted small as-foot">
            {done.measures.minutes} minutes · longest answer {done.measures.longest_answer_s} s · average answer{" "}
            {done.measures.average_answer_s} s · {done.measures.small_talk} small-talk exchanges.{" "}
            {done.compare.interviews > 0
              ? `Compared with ${done.compare.interviews} other reviewed interview${done.compare.interviews === 1 ? "" : "s"} in the same round of this job.`
              : "No other interview in this round has been reviewed yet."}
          </p>
        </>
      )}
    </section>
  );
}