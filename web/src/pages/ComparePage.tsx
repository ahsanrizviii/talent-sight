import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "../api";
import Empty from "../components/Empty";
import { LoadError, Loading } from "../components/PageState";
import Icon from "../components/Icon";
import VerdictBadge from "../components/VerdictBadge";
import type { ComparedCandidate, Comparison } from "../types";
import "../assessment.css";

// Side-by-side comparison of the assessed candidates for one job (Task 10.2.2).
// One column per candidate, one row per part of the assessment, so the same question can be
// answered across people at a glance. The best value in each score row is marked.

const MOST_COLUMNS = 4; // more than this no longer fits side by side
const POSITION_TONE = { strong_fit: "pass", possible_fit: "warn", weak_fit: "stop" } as const;
const INTERVIEW = {
  explored: { label: "Explored", tone: "pass" },
  weak: { label: "Weak", tone: "warn" },
  not_explored: { label: "Not explored", tone: "stop" },
} as const;

export default function ComparePage() {
  const { id } = useParams();
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [chosen, setChosen] = useState<number[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    api<Comparison>(`/jobs/${id}/assessments`)
      .then((found) => {
        setComparison(found);
        setChosen(found.candidates.slice(0, MOST_COLUMNS).map((c) => c.candidate_id)); // the best ones first
      })
      .catch((err) => setError(err.message));
  }, [id]);

  function toggle(candidateId: number) {
    setChosen((now) =>
      now.includes(candidateId) ? now.filter((x) => x !== candidateId) : now.length < MOST_COLUMNS ? [...now, candidateId] : now,
    );
  }

  if (error) return <LoadError message={error} back={`/jobs/${id}/candidates`} backLabel="Back to the job" />;
  if (!comparison) return <Loading label="Loading the comparison…" />;

  // Keep the ranking order (best first), whatever order they were picked in.
  const shown = comparison.candidates.filter((c) => chosen.includes(c.candidate_id));
  const componentRows = comparison.candidates[0]?.components ?? [];
  const best = (values: (number | undefined)[]) => Math.max(...values.map((v) => v ?? -1));

  return (
    <>
      <Link className="back-link" to={`/jobs/${id}/candidates`}>
        <Icon name="back" />
        Back to the job
      </Link>

      <div className="page-head">
        <div>
          <h1>Compare candidates</h1>
          <p>
            {comparison.job_title} · {comparison.candidates.length} assessed
            {comparison.waiting > 0 && ` · ${comparison.waiting} interviewed but not assessed yet`}
          </p>
        </div>
      </div>

      {comparison.candidates.length === 0 ? (
        <div className="card glass">
          <Empty title="Nobody to compare yet">
            Open an interviewed candidate, go to the Assessment tab and press “Assess candidate”. Every finished
            assessment for this job shows up here.
          </Empty>
        </div>
      ) : (
        <>
          <div className="card glass">
            <p className="eyebrow">Choose up to {MOST_COLUMNS}</p>
            <div className="chips">
              {comparison.candidates.map((c) => (
                <button
                  key={c.candidate_id}
                  type="button"
                  className={`chip cmp-pick ${chosen.includes(c.candidate_id) ? "on" : ""}`}
                  aria-pressed={chosen.includes(c.candidate_id)}
                  onClick={() => toggle(c.candidate_id)}
                >
                  {c.name} · {c.position.overall}
                </button>
              ))}
            </div>
          </div>

          <div className="card glass flush as-table-wrap">
            <table className="cmp-table">
              <thead>
                <tr>
                  <th />
                  {shown.map((c) => (
                    <th key={c.candidate_id}>
                      <Link to={`/candidates/${c.candidate_id}?tab=assessment`}>{c.name}</Link>
                      {c.outdated && <span className="cell-sub">report out of date</span>}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <tr>
                  <th>Position</th>
                  {shown.map((c) => (
                    <td key={c.candidate_id}>
                      <span className={`badge ${POSITION_TONE[c.position.code]}`}>{c.position.label}</span>
                      <strong className={`cmp-number ${c.position.overall === best(shown.map((x) => x.position.overall)) ? "best" : ""}`}>
                        {c.position.overall}
                      </strong>
                    </td>
                  ))}
                </tr>

                {componentRows.map((row) => {
                  const values = shown.map((c) => c.components.find((part) => part.key === row.key)?.score);
                  return (
                    <tr key={row.key}>
                      <th>{row.label}</th>
                      {shown.map((c, i) => (
                        <td key={c.candidate_id}>
                          {values[i] === undefined ? (
                            <span className="muted">—</span>
                          ) : (
                            <>
                              <span className={`cmp-number ${values[i] === best(values) ? "best" : ""}`}>{values[i]}</span>
                              <div className="bar">
                                <div style={{ width: `${values[i]}%` }} />
                              </div>
                            </>
                          )}
                        </td>
                      ))}
                    </tr>
                  );
                })}

                <tr className="cmp-section">
                  <th colSpan={shown.length + 1}>Requirements: CV / interview</th>
                </tr>
                {comparison.requirements.map((req) => (
                  <tr key={req.key}>
                    <th>
                      {req.requirement}
                      {req.mandatory && <span className="cell-sub">must have</span>}
                    </th>
                    {shown.map((c) => (
                      <td key={c.candidate_id}>
                        <RequirementCell line={c.requirements[req.key]} />
                      </td>
                    ))}
                  </tr>
                ))}

                <tr className="cmp-section">
                  <th colSpan={shown.length + 1}>Findings</th>
                </tr>
                <tr>
                  <th>Evidence gaps</th>
                  {shown.map((c) => (
                    <td key={c.candidate_id}>
                      {c.gaps}
                      {c.must_have_gaps > 0 && <span className="badge tiny stop">{c.must_have_gaps} must have</span>}
                    </td>
                  ))}
                </tr>
                <tr>
                  <th>Strengths</th>
                  {shown.map((c) => (
                    <td key={c.candidate_id}>
                      <Points items={c.strengths} />
                    </td>
                  ))}
                </tr>
                <tr>
                  <th>Weaknesses</th>
                  {shown.map((c) => (
                    <td key={c.candidate_id}>
                      <Points items={c.weaknesses} />
                    </td>
                  ))}
                </tr>
              </tbody>
            </table>
          </div>
          <p className="muted small">
            Each column links to the full report, where every point shows the CV line or transcript quote it rests on.
          </p>
        </>
      )}
    </>
  );
}

function RequirementCell({ line }: { line: ComparedCandidate["requirements"][string] | undefined }) {
  if (!line) return <span className="muted">—</span>;
  return (
    <div className="cmp-req">
      {line.cv ? <VerdictBadge verdict={line.cv} /> : <span className="muted small">no CV check</span>}
      {line.interview ? (
        <span className={`badge ${INTERVIEW[line.interview].tone}`}>
          {INTERVIEW[line.interview].label}
          {line.best_score !== null && ` · ${line.best_score}`}
        </span>
      ) : (
        <span className="muted small">not in the interview</span>
      )}
    </div>
  );
}

function Points({ items }: { items: string[] }) {
  if (items.length === 0) return <span className="muted">—</span>;
  return (
    <ul className="cmp-points">
      {items.map((text, i) => (
        <li key={i}>{text}</li>
      ))}
    </ul>
  );
}