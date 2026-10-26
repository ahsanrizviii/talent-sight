import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api";
import Empty from "./Empty";
import RunBadge from "./RunBadge";
import SelectionDialog from "./SelectionDialog";
import type { ReportRow } from "../types";

const DECISIONS = { onboarding: "Selected for onboarding", rejected: "Not selected" };

type Props = { jobId: string; onChange: () => void };

// The Report stage of a job: everyone who passed every interview round, with their CV score, their
// score in each round and their consolidated assessment (which brings all of it together, with the
// CV claim check). The hiring team picks who is selected for onboarding; the others are told kindly.
export default function ReportStage({ jobId, onChange }: Props) {
  const [rows, setRows] = useState<ReportRow[] | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [deciding, setDeciding] = useState(false);
  const [firstDay, setFirstDay] = useState("");
  const [polling, setPolling] = useState(false);

  const load = useCallback(
    () =>
      api<ReportRow[]>(`/jobs/${jobId}/report`)
        .then((answer) => {
          setRows(answer);
          return answer;
        })
        .catch((err) => {
          setError(err.message);
          return null;
        }),
    [jobId],
  );

  useEffect(() => {
    void load();
  }, [load]);

  const running = !!rows?.some((r) => r.assessment_status === "running" || r.claims_status === "running");
  useEffect(() => {
    if (!running && !polling) return;
    const timer = window.setInterval(() => {
      void load().then((answer) => {
        if (!answer?.some((r) => r.assessment_status === "running" || r.claims_status === "running")) setPolling(false);
      });
    }, 4000);
    return () => window.clearInterval(timer);
  }, [running, polling, load]);

  async function buildReports() {
    setError("");
    setMessage("");
    try {
      const answer = await api<{ started: number }>(`/jobs/${jobId}/report/assess`, { method: "POST" });
      setMessage(
        answer.started
          ? `Building ${answer.started} report${answer.started === 1 ? "" : "s"} and CV claim checks, one after the other.`
          : "Every report is already built.",
      );
      if (answer.started) {
        setPolling(true);
        window.setTimeout(() => void load(), 1500);
      }
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function decide(ids: number[]) {
    const result = await api<{ selected: number; rejected: number }>(`/jobs/${jobId}/report/decide`, {
      method: "POST",
      body: JSON.stringify({ selected_ids: ids, onboarding_date: firstDay || null }),
    });
    setDeciding(false);
    setMessage(
      `${result.selected} selected for onboarding and sent the onboarding e-mail. ${result.rejected} will get a rejection e-mail.`,
    );
    await load();
    onChange();
  }

  if (!rows) {
    return (
      <div className="card glass">
        {error ? <p className="error">{error}</p> : <div className="skeleton" />}
      </div>
    );
  }

  const open = rows.filter((r) => !r.decision);
  const roundNames = rows[0]?.round_scores ?? [];

  return (
    <>
      <div className="card glass round-head">
        <div>
          <h2 style={{ margin: 0 }}>Report</h2>
          <p className="muted small" style={{ margin: "4px 0 0" }}>
            Candidates who passed every round, ranked by their consolidated assessment (CV score, requirements, answers and coverage
            across all rounds).
          </p>
        </div>
        {open.length > 0 && (
          <div className="row">
            <button className="button secondary" type="button" onClick={() => void buildReports()} disabled={running}>
              {running ? "Building…" : "Build missing reports"}
            </button>
            <button className="button" type="button" onClick={() => setDeciding(true)}>
              Select for onboarding
            </button>
          </div>
        )}
      </div>

      {error && <p className="error">{error}</p>}
      {message && <p className="success">{message}</p>}

      <div className="card glass flush">
        {rows.length === 0 ? (
          <Empty title="Nobody has passed every round yet">
            Candidates appear here when they pass the last interview round of this job.
          </Empty>
        ) : (
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Candidate</th>
                <th className="right">CV</th>
                {roundNames.map((item) => (
                  <th key={item.number} className="right" title={item.name}>
                    R{item.number}
                  </th>
                ))}
                <th className="right">Report score</th>
                <th>CV claims</th>
                <th>Decision</th>
                <th className="right"></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.candidate_id}>
                  <td className="muted num">{row.rank ?? ""}</td>
                  <td>
                    <Link to={`/candidates/${row.candidate_id}?tab=report`}>{row.name}</Link>
                    <span className="cell-sub">{row.email}</span>
                  </td>
                  <td className="right muted">{row.cv_score ?? "—"}</td>
                  {row.round_scores.map((item) => (
                    <td key={item.number} className="right muted">
                      {item.score ?? "—"}
                    </td>
                  ))}
                  <td className="right score-cell">
                    {row.report_score ?? <RunBadge state={row.assessment_status} />}
                    {row.position && <span className="cell-sub">{row.position}</span>}
                  </td>
                  <td>
                    {row.claims_status === "done" ? (
                      row.claims_flagged ? (
                        <span className="badge warn">{row.claims_flagged} to follow up</span>
                      ) : (
                        <span className="badge pass">Nothing flagged</span>
                      )
                    ) : (
                      <RunBadge state={row.claims_status} />
                    )}
                  </td>
                  <td>
                    {row.decision ? (
                      <span className={row.decision === "onboarding" ? "badge pass" : "badge"}>{DECISIONS[row.decision]}</span>
                    ) : (
                      <span className="muted small">Waiting</span>
                    )}
                  </td>
                  <td className="right">
                    <Link className="button secondary small" to={`/candidates/${row.candidate_id}?tab=report`}>
                      See report
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {deciding && (
        <SelectionDialog
          title="Select for onboarding"
          intro="The candidates still waiting for a decision, ranked by their report score. Those you select get the onboarding e-mail; everyone else gets a polite rejection e-mail."
          items={open.map((row) => ({
            id: row.candidate_id,
            name: row.name,
            sub: row.report_score === null ? "no report yet" : row.position,
            score: row.report_score,
          }))}
          scoreLabel="Report score"
          defaultMark={70}
          passWord="are selected for onboarding"
          failWord="get a rejection e-mail"
          extra={
            <div className="field">
              <label htmlFor="first-day">First day at work (optional, shown in the e-mail)</label>
              <input id="first-day" type="date" value={firstDay} onChange={(e) => setFirstDay(e.target.value)} />
            </div>
          }
          confirmLabel={(count) => `Select ${count} for onboarding`}
          onConfirm={(ids) => decide(ids)}
          onClose={() => setDeciding(false)}
        />
      )}
    </>
  );
}
