import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { QaCoverage, QaDimensionKey, QaEvaluation, QaPair, QaTurn } from "../types";
import { elapsed } from "./TranscriptLines";
import "../qa-analysis.css";

// The answer analysis of one interview (Task 9.2.3). Interviewer only (N9).
// The interviewer starts it after the interview; the agent works in the background and this
// screen asks every 2 seconds how far it is (Q&A 42). Every score shows its reason and the
// transcript line it rests on, so nothing has to be taken on trust.

const DIMENSIONS: [QaDimensionKey, string][] = [
  ["relevance", "Relevance"],
  ["accuracy", "Accuracy"],
  ["completeness", "Completeness"],
  ["articulation", "Articulation"],
];

const COVERAGE: Record<QaCoverage["status"], { label: string; tone: string }> = {
  explored: { label: "Explored", tone: "pass" },
  weak: { label: "Weak evidence", tone: "warn" },
  not_explored: { label: "Not explored", tone: "stop" },
  documents: { label: "Checked at onboarding", tone: "" },
};

// 70 and above reads as a good answer, 50 to 70 as a maybe, below that as a weak one (like the CV score).
function tone(score: number): string {
  if (score >= 70) return "pass";
  if (score >= 50) return "warn";
  return "stop";
}

export default function QaAnalysis({ sessionId, candidateName = "Candidate" }: { sessionId: number; candidateName?: string }) {
  const [evaluation, setEvaluation] = useState<QaEvaluation | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const [starting, setStarting] = useState(false);

  const load = useCallback(
    () =>
      api<QaEvaluation | null>(`/interviews/${sessionId}/evaluation`)
        .then((found) => {
          setEvaluation(found);
          setLoaded(true);
        })
        .catch((err) => setError(err.message)),
    [sessionId],
  );

  useEffect(() => {
    setEvaluation(null);
    setLoaded(false);
    load();
  }, [load]);

  // While the agent works, ask every 2 seconds how far it is.
  const running = evaluation?.status === "running";
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(load, 2000);
    return () => window.clearInterval(timer);
  }, [running, load]);

  async function start() {
    setStarting(true);
    setError("");
    try {
      setEvaluation(await api<QaEvaluation>(`/interviews/${sessionId}/evaluation`, { method: "POST" }));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setStarting(false);
    }
  }

  if (!loaded && !error) return <p className="muted small">Loading the answer analysis…</p>;

  const done = evaluation?.status === "done" ? evaluation : null;

  return (
    <section className="qa-analysis">
      <div className="row between">
        <h3>Answer analysis</h3>
        <button className="button small" onClick={start} disabled={running || starting}>
          {running ? "Analysing…" : evaluation ? "Analyse again" : "Analyse answers"}
        </button>
      </div>

      {!evaluation && (
        <p className="muted small">
          The AI splits the transcript into questions and answers, links each one to the job's requirements and
          scores every answer for relevance, accuracy, completeness and articulation. Small talk is kept but not
          scored.
        </p>
      )}
      {error && <p className="error small">{error}</p>}
      {running && (
        <p className="qa-step">
          <span className="qa-spinner" aria-hidden="true" />
          {evaluation?.step || "Working"}…
        </p>
      )}
      {evaluation?.status === "failed" && <p className="error small">{evaluation.error}</p>}
      {done && <Result evaluation={done} candidateName={candidateName} />}
    </section>
  );
}

function Result({ evaluation, candidateName }: { evaluation: QaEvaluation; candidateName: string }) {
  const { summary, coverage, pairs } = evaluation;
  const turns = new Map(evaluation.turns.map((turn) => [turn.n, turn]));
  const requirementName = new Map(coverage.map((c) => [c.number, c.requirement]));
  const jobRelated = pairs.filter((pair) => pair.kind === "job_related");
  const smallTalk = pairs.filter((pair) => pair.kind === "small_talk");
  const hr = evaluation.round_type === "hr";

  return (
    <>
      <div className="qa-summary">
        <div>
          <strong className={summary.average === null ? "" : `qa-tone-${tone(summary.average)}`}>
            {summary.average ?? "–"}
          </strong>
          <span>average answer score</span>
        </div>
        <div>
          <strong>{summary.job_related}</strong>
          <span>job questions</span>
        </div>
        <div>
          <strong>{summary.small_talk}</strong>
          <span>small talk, not scored</span>
        </div>
        <div>
          <strong className={summary.not_explored ? "qa-tone-stop" : ""}>{summary.not_explored}</strong>
          <span>{hr ? "HR topics never explored" : "requirements never explored"}</span>
        </div>
      </div>

      {coverage.length > 0 && (
        <div className="qa-block">
          <h4>{hr ? "HR topic coverage" : "Requirement coverage"}</h4>
          {hr && <p className="muted small">This is an HR round: the answers are judged on HR topics, not on the job's technical requirements.</p>}
          <ul className="qa-coverage">
            {coverage.map((c) => (
              <li key={c.number}>
                <span className={`badge ${COVERAGE[c.status].tone}`}>{COVERAGE[c.status].label}</span>
                <span>
                  {c.requirement}
                  {!c.mandatory && !hr && c.status !== "documents" && <span className="muted small"> · preferred</span>}
                </span>
                <span className="muted small">
                  {c.status === "documents"
                    ? "a degree, certificate or written skill: checked with documents, not in the interview"
                    : c.status === "not_explored"
                    ? "no question touched it"
                    : `${c.pairs.length} ${c.pairs.length === 1 ? "answer" : "answers"}, best ${c.best_score ?? "–"}`}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="qa-block">
        <h4>Questions and answers ({jobRelated.length})</h4>
        {jobRelated.length === 0 && <p className="muted small">No job-related questions were found in this interview.</p>}
        {jobRelated.map((pair) => (
          <PairCard key={pair.id} pair={pair} turns={turns} requirementName={requirementName} candidateName={candidateName} />
        ))}
      </div>

      {smallTalk.length > 0 && (
        <details className="qa-block qa-small-talk">
          <summary>Small talk ({smallTalk.length}): kept in the record, not scored</summary>
          {smallTalk.map((pair) => (
            <Exchange key={pair.id} pair={pair} turns={turns} candidateName={candidateName} />
          ))}
        </details>
      )}

      {evaluation.finished_at && (
        <p className="muted small">
          Analysed {new Date(evaluation.finished_at).toLocaleString()}
          {evaluation.seconds !== null && ` in ${Math.max(1, Math.round(evaluation.seconds))} s`}.
        </p>
      )}
    </>
  );
}

function PairCard({
  pair,
  turns,
  requirementName,
  candidateName,
}: {
  pair: QaPair;
  turns: Map<number, QaTurn>;
  requirementName: Map<number, string>;
  candidateName: string;
}) {
  return (
    <article className="qa-pair">
      <div className="qa-pair-head">
        <span className="transcript-time">{elapsed(pair.start_ms)}</span>
        <strong className="grow">{pair.question}</strong>
        {pair.overall !== null && <span className={`badge ${tone(pair.overall)}`}>{pair.overall}</span>}
      </div>

      <div className="chips">
        {pair.parts > 1 && (
          <span className="badge">
            Part {pair.part} of {pair.parts}
          </span>
        )}
        {pair.follow_ups.length > 0 && (
          <span className="badge">
            {pair.follow_ups.length} follow-up{pair.follow_ups.length > 1 ? "s" : ""}
          </span>
        )}
        {pair.requirements.map((n) => (
          <span key={n} className="badge accent">
            {requirementName.get(n)}
          </span>
        ))}
      </div>

      {pair.scores && (
        <div className="qa-dimensions">
          {DIMENSIONS.map(([key, label]) => (
            <div key={key} className="qa-dimension">
              <div className="dimension-head">
                <strong>{label}</strong>
                <span className="muted small">{pair.scores![key].score}/100</span>
              </div>
              <div className="bar">
                <div style={{ width: `${pair.scores![key].score}%` }} />
              </div>
              <p className="small muted">{pair.scores![key].justification}</p>
            </div>
          ))}
        </div>
      )}

      {pair.evidence && (
        <blockquote className="qa-evidence">
          “{pair.evidence.quote}”
          <span>
            {candidateName}, at {elapsed(pair.evidence.start_ms)}
          </span>
        </blockquote>
      )}

      {pair.references.length > 0 && (
        <p className="muted small">
          Checked against:{" "}
          {pair.references.map((ref, i) => (
            <span key={i}>
              {i > 0 && " · "}
              {ref.skill}, {ref.heading}
            </span>
          ))}
        </p>
      )}

      <Exchange pair={pair} turns={turns} candidateName={candidateName} folded />
    </article>
  );
}

// The transcript lines behind a pair: the evidence the scores rest on.
function Exchange({
  pair,
  turns,
  candidateName,
  folded = false,
}: {
  pair: QaPair;
  turns: Map<number, QaTurn>;
  candidateName: string;
  folded?: boolean;
}) {
  const lines = (
    <ol className="transcript-lines qa-exchange">
      {pair.turns
        .map((n) => turns.get(n))
        .filter((turn): turn is QaTurn => Boolean(turn))
        .map((turn) => (
          <li key={turn.n} className={`transcript-line ${turn.speaker}`}>
            <span className="transcript-time">{elapsed(turn.start_ms)}</span>
            <div>
              <span className="transcript-speaker">{turn.speaker === "interviewer" ? "Interviewer" : candidateName}</span>
              <span className="transcript-text">{turn.text}</span>
            </div>
          </li>
        ))}
    </ol>
  );
  if (!folded) return lines;
  return (
    <details className="qa-lines">
      <summary>Show the exchange</summary>
      {lines}
    </details>
  );
}