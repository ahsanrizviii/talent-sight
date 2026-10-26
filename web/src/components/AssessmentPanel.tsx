import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { api, apiBlob } from "../api";
import type { Assessment, AssessmentEvidence, AssessmentFinding, AssessmentReport } from "../types";
import VerdictBadge from "./VerdictBadge";
import "../assessment.css";

// The consolidated assessment of one candidate (Task 10.1.3). Interviewer only (N9).
// It joins the CV screening, the CV score and the interview answer analysis into one report.
// Every finding carries small evidence tags (R2, Q4 ...); pressing one shows the CV line or the
// transcript quote it rests on, so nothing has to be taken on trust (F6, traceability).

const POSITION_TONE = { strong_fit: "pass", possible_fit: "warn", weak_fit: "stop" } as const;

const INTERVIEW = {
  explored: { label: "Explored", tone: "pass" },
  weak: { label: "Weak evidence", tone: "warn" },
  not_explored: { label: "Not explored", tone: "stop" },
  documents: { label: "Checked at onboarding", tone: "" },
} as const;

export default function AssessmentPanel({ candidateId }: { candidateId: number }) {
  const [assessment, setAssessment] = useState<Assessment | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const [starting, setStarting] = useState(false);
  const [downloading, setDownloading] = useState(false);

  const load = useCallback(
    () =>
      api<Assessment | null>(`/candidates/${candidateId}/assessment`)
        .then((found) => {
          setAssessment(found);
          setLoaded(true);
        })
        .catch((err) => setError(err.message)),
    [candidateId],
  );

  useEffect(() => {
    setAssessment(null);
    setLoaded(false);
    load();
  }, [load]);

  // While the agent works, ask every 2 seconds how far it is.
  const running = assessment?.status === "running";
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(load, 2000);
    return () => window.clearInterval(timer);
  }, [running, load]);

  async function start() {
    setStarting(true);
    setError("");
    try {
      setAssessment(await api<Assessment>(`/candidates/${candidateId}/assessment`, { method: "POST" }));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setStarting(false);
    }
  }

    // The PDF is made by the API (Task 10.2.1); the browser saves it under the candidate's name.
  async function downloadPdf(name: string) {
    setDownloading(true);
    setError("");
    try {
      const file = await apiBlob(`/candidates/${candidateId}/assessment/pdf`);
      const link = document.createElement("a");
      link.href = URL.createObjectURL(file);
      link.download = `assessment-${name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || candidateId}.pdf`;
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(link.href), 1000);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setDownloading(false);
    }
  }

  if (!loaded && !error) return <p className="muted small">Loading the assessment…</p>;

  const done = assessment?.status === "done" ? assessment : null;

  return (
    <section className="card glass assessment">
      <div className="row between">
        <div>
          <h2>Consolidated assessment</h2>
          <p className="muted small" style={{ margin: 0 }}>
            CV screening, CV score and interview answers in one report.
          </p>
        </div>
        <div className="row">
         {done && (
            <button className="button secondary" onClick={() => downloadPdf(done.report.candidate.name)} disabled={downloading}>
              {downloading ? "Preparing…" : "Download PDF"}
            </button>
          )}
          <button className="button" onClick={start} disabled={running || starting}>
            {running ? "Assessing…" : assessment ? "Assess again" : "Assess candidate"}
          </button>
        </div>
      </div>

      {!assessment && (
        <p className="muted small">
          Needs a screened candidate and an analysed interview (Results page, “Analyse answers”). The position and the
          component scores are worked out by fixed rules; the AI writes the strengths, weaknesses and follow-ups, and
          each one points to the CV line or transcript quote behind it.
        </p>
      )}
      {error && <p className="error small">{error}</p>}
      {running && (
        <p className="as-step">
          <span className="as-spinner" aria-hidden="true" />
          {assessment?.step || "Working"}…
        </p>
      )}
      {assessment?.status === "failed" && <p className="error small">{assessment.error}</p>}
      {done?.outdated && (
        <div className="notice">The interview answers were analysed again after this report. Assess again to update it.</div>
      )}
      {done && <Report report={done.report} finishedAt={done.finished_at} />}
    </section>
  );
}

function Report({ report, finishedAt }: { report: AssessmentReport; finishedAt: string | null }) {
  const [shown, setShown] = useState<string | null>(null);
  const evidence = new Map(report.evidence.map((item) => [item.id, item]));

  // Pressing an evidence tag opens that item at the bottom and scrolls to it.
  function show(id: string) {
    setShown(id);
    window.setTimeout(() => document.getElementById(`ev-${id}`)?.scrollIntoView({ behavior: "smooth", block: "center" }), 0);
  }
  const tags = (ids: string[]) => <Tags ids={ids} evidence={evidence} onShow={show} />;
  const { position } = report;

  return (
    <>
      <div className="as-position">
        <div className={`as-verdict ${POSITION_TONE[position.code]}`}>
          <strong>{position.label}</strong>
          <span>
            {position.overall} <small>/ 100</small>
          </span>
        </div>
        <div className="grow">
          <p className="as-summary">
            {report.summary.text} {tags(report.summary.evidence)}
          </p>
          <ul className="as-reasons">
            {position.reasons.map((reason, i) => (
              <li key={i}>
                {reason}
                {i === position.reasons.length - 1 && position.evidence.length > 0 && <> {tags(position.evidence)}</>}
              </li>
            ))}
          </ul>
        </div>
      </div>

      <div className="as-block">
        <h4>Component scores</h4>
        {report.components.map((part) => (
          <div className="dimension" key={part.key}>
            <div className="dimension-head">
              <strong>
                {part.label} <span className="badge tiny">{part.source === "cv" ? "CV" : "Interview"}</span>
              </strong>
              <span className="muted small">
                {part.score}/100 · weight {part.weight}% · adds {part.contribution}
              </span>
            </div>
            <div className="bar">
              <div style={{ width: `${part.score}%` }} />
            </div>
            <div className="as-tags-line">{tags(part.evidence)}</div>
          </div>
        ))}
      </div>

      <div className="as-columns">
        <FindingList title="Strengths" items={report.strengths} tone="pass" tags={tags} />
        <FindingList title="Weaknesses" items={report.weaknesses} tone="stop" tags={tags} />
      </div>

      <div className="as-columns">
        <div className="as-block">
          <h4>Evidence gaps ({report.gaps.length})</h4>
          {report.gaps.length === 0 && <p className="muted small">Every requirement has evidence in the CV and the interview.</p>}
          <ul className="as-list">
            {report.gaps.map((gap, i) => (
              <li key={i} className="as-item warn">
                {gap.text} {gap.mandatory && <span className="badge tiny stop">must have</span>} {tags(gap.evidence)}
              </li>
            ))}
          </ul>
        </div>
        <FindingList title="Verify next" items={report.follow_ups} tone="follow" tags={tags} />
      </div>

      <div className="as-block">
        <h4>Requirements: CV and interview side by side</h4>
        <div className="as-table-wrap">
          <table className="as-table">
            <thead>
              <tr>
                <th>Requirement</th>
                <th>CV</th>
                <th>Interview</th>
                <th>Evidence</th>
              </tr>
            </thead>
            <tbody>
              {report.requirements.map((line) => (
                <tr key={line.n}>
                  <td>
                    {line.requirement}
                    {line.mandatory && <span className="cell-sub">must have</span>}
                  </td>
                  <td>{line.cv ? <VerdictBadge verdict={line.cv} /> : <span className="muted">—</span>}</td>
                  <td>
                    {line.interview ? (
                      <span className={`badge ${INTERVIEW[line.interview].tone}`}>
                        {INTERVIEW[line.interview].label}
                        {line.best_score !== null && ` · ${line.best_score}`}
                      </span>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                  <td>{tags([...(line.cv ? [`R${line.n}`] : []), ...(line.interview ? [`C${line.n}`] : [])])}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <details className="as-block as-evidence" open={shown !== null}>
        <summary>Evidence ({report.evidence.length}): what every tag points to</summary>
        <ol>
          {report.evidence.map((item) => (
            <EvidenceLine key={item.id} item={item} active={shown === item.id} />
          ))}
        </ol>
      </details>

    <p className="muted small as-foot">
        Interview held {new Date(report.interview.held_at).toLocaleDateString()}
        {finishedAt && ` · assessed ${new Date(finishedAt).toLocaleString()}`}.{" "}
        <Link to={`/jobs/${report.job.id}/compare`}>Compare with the other candidates for this job</Link>
      </p>
    </>
  );
}

function FindingList({
  title,
  items,
  tone,
  tags,
}: {
  title: string;
  items: AssessmentFinding[];
  tone: string;
  tags: (ids: string[]) => ReactNode;
}) {
  return (
    <div className="as-block">
      <h4>
        {title} ({items.length})
      </h4>
      {items.length === 0 && <p className="muted small">Nothing to report.</p>}
      <ul className="as-list">
        {items.map((item, i) => (
          <li key={i} className={`as-item ${tone}`}>
            {item.text} {tags(item.evidence)}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Tags({ ids, evidence, onShow }: { ids: string[]; evidence: Map<string, AssessmentEvidence>; onShow: (id: string) => void }) {
  return (
    <span className="as-tags">
      {ids.map((id) => {
        const item = evidence.get(id);
        return (
          <button
            key={id}
            type="button"
            className={`as-tag ${item?.source ?? ""}`}
            title={item ? `${item.label}: ${item.text}` : id}
            onClick={() => onShow(id)}
          >
            {id}
          </button>
        );
      })}
    </span>
  );
}

function EvidenceLine({ item, active }: { item: AssessmentEvidence; active: boolean }) {
  return (
    <li id={`ev-${item.id}`} className={active ? "active" : ""}>
      <span className={`as-tag ${item.source}`}>{item.id}</span>
      <div>
        <strong>{item.label}</strong>
        <span className="muted small">
          {" "}
          · {item.source === "cv" ? "CV" : "Interview"}
          {item.at && `, at ${item.at}`}
        </span>
        <p className="small">{item.text}</p>
      </div>
    </li>
  );
}