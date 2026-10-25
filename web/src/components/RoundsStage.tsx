import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { api } from "../api";
import Empty from "./Empty";
import RunBadge from "./RunBadge";
import SelectionDialog, { type Rule } from "./SelectionDialog";
import type { CloseResult, HiringSummary, RoundRow, RoundView } from "../types";
import { clockTime, shortDate } from "../when";

const pad = (n: number) => String(n).padStart(2, "0");
const isoDay = (date: Date) => `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;

const STATE_LABELS = { not_started: "Not started", open: "Open", closed: "Closed" };

function interviewState(row: RoundRow): { text: string; tone: string } {
  if (row.cancelled) return { text: "Cancelled", tone: "" };
  if (row.interview_status === "live") return { text: "Happening now", tone: "live" };
  if (row.attended) return { text: "Attended", tone: "pass" };
  if (new Date(row.scheduled_at).getTime() + 15 * 60_000 < Date.now()) return { text: "Did not start", tone: "stop" };
  return { text: `Booked ${shortDate(row.scheduled_at)} ${clockTime(row.scheduled_at)}`, tone: "accent" };
}

type Props = {
  jobId: string;
  summary: HiringSummary;
  round: number;
  onPickRound: (round: number) => void;
  onChange: () => void; // the round was closed: the stage bar's numbers change
  onGoToScreening: () => void;
};

// The Interviews stage of a job: one tab per round. Each round lists its candidates ranked by their
// interview score, with whether they attended and whether their analysis is done. When the round is
// over, "Close round" lets the hiring team choose who goes on (and invites them to the next round).
export default function RoundsStage({ jobId, summary, round, onPickRound, onChange, onGoToScreening }: Props) {
  const navigate = useNavigate();
  const [view, setView] = useState<RoundView | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [closing, setClosing] = useState(false);
  const [startDate, setStartDate] = useState(isoDay(new Date(Date.now() + 24 * 60 * 60 * 1000)));
  const [polling, setPolling] = useState(false);

  const load = useCallback(
    () =>
      api<RoundView>(`/jobs/${jobId}/rounds/${round}`)
        .then((answer) => {
          setView(answer);
          setError("");
          return answer;
        })
        .catch((err) => {
          setError(err.message);
          return null;
        }),
    [jobId, round],
  );

  useEffect(() => {
    setView(null);
    setMessage("");
    void load();
  }, [load]);

  // While analyses run, check every 4 seconds; stop when nothing is running any more.
  const running = !!view?.rows.some((r) => [r.analysis_status, r.score_status, r.quality_status].includes("running"));
  useEffect(() => {
    if (!running && !polling) return;
    const timer = window.setInterval(() => {
      void load().then((answer) => {
        const still = answer?.rows.some((r) => [r.analysis_status, r.score_status, r.quality_status].includes("running"));
        if (!still) setPolling(false);
      });
    }, 4000);
    return () => window.clearInterval(timer);
  }, [running, polling, load]);

  async function analyseAll() {
    setError("");
    setMessage("");
    try {
      const answer = await api<{ started: number }>(`/jobs/${jobId}/rounds/${round}/analyse`, { method: "POST" });
      setMessage(
        answer.started
          ? `Analysing ${answer.started} interview${answer.started === 1 ? "" : "s"}, one after the other. This page updates as each one finishes.`
          : "Every finished interview of this round is already analysed and scored.",
      );
      if (answer.started) {
        setPolling(true);
        window.setTimeout(() => void load(), 1500);
      }
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function close(ids: number[], rule: Rule, value: number | null) {
    if (!view) return;
    const result = await api<CloseResult>(`/jobs/${jobId}/rounds/${round}/close`, {
      method: "POST",
      body: JSON.stringify({ passed_ids: ids, rule, value, start_date: view.is_last ? null : startDate }),
    });
    setClosing(false);
    const parts = [`Round closed: ${result.passed} passed, ${result.rejected} will get a rejection e-mail.`];
    if (result.next_round) {
      parts.push(`${result.booked} invited to round ${result.next_round}.`);
      if (result.not_placed) parts.push(`${result.not_placed} could not be given a time: book them from their profile.`);
    } else if (result.passed) {
      parts.push("Those who passed are now in the Report stage.");
    }
    setMessage(parts.join(" "));
    await load();
    onChange();
  }

  const rounds = summary.rounds;

  return (
    <>
      <div className="tabs glass round-tabs" role="tablist" aria-label="Interview rounds">
        {rounds.map((item) => (
          <button key={item.number} role="tab" aria-selected={round === item.number} onClick={() => onPickRound(item.number)}>
            <span>
              Round {item.number} · {item.name}
            </span>
            <span className={`round-state round-state-${item.state}`}>{STATE_LABELS[item.state]}</span>
          </button>
        ))}
      </div>

      {error && <p className="error">{error}</p>}
      {message && <p className="success">{message}</p>}

      {!view ? (
        <div className="card glass">
          <div className="skeleton" />
          <div className="skeleton" />
        </div>
      ) : (
        <>
          <div className="card glass round-head">
            <div>
              <h2 style={{ margin: 0 }}>
                Round {view.number} of {view.total} · {view.name}{" "}
                <span className="badge">{view.type === "hr" ? "HR round" : "Technical round"}</span>
              </h2>
              {view.focus && <p className="muted small" style={{ margin: "4px 0 0" }}>{view.focus}</p>}
              <p className="small" style={{ margin: "8px 0 0" }}>
                {view.invited} invited · {view.waiting} still to come · {view.held} attended · {view.scored} scored
                {view.closure && ` · closed ${shortDate(view.closure.closed_at)}: ${view.closure.passed} passed, ${view.closure.rejected} not progressed`}
              </p>
            </div>
            {view.state === "open" && (
              <div className="row">
                <button className="button secondary" type="button" onClick={() => void analyseAll()} disabled={running}>
                  {running ? "Analysing…" : "Analyse finished interviews"}
                </button>
                <button
                  className="button"
                  type="button"
                  onClick={() => setClosing(true)}
                  disabled={view.waiting > 0}
                  title={view.waiting > 0 ? "Hold or cancel the remaining interviews first" : ""}
                >
                  Close round {view.number}
                </button>
              </div>
            )}
          </div>

          {view.state === "open" && view.waiting > 0 && (
            <p className="muted small">
              {view.waiting} interview{view.waiting === 1 ? " is" : "s are"} still booked or running. The round can be closed once every
              interview has been held or cancelled (Interviews page).
            </p>
          )}

          <div className="card glass flush">
            {view.rows.length === 0 ? (
              view.number === 1 ? (
                <Empty
                  title="Nobody invited to round 1 yet"
                  action={
                    <button className="button" type="button" onClick={onGoToScreening}>
                      Go to CV screening to invite the top candidates
                    </button>
                  }
                >
                  Invite the best-ranked candidates from the shortlist; their interviews appear here.
                </Empty>
              ) : (
                <Empty title={`Round ${view.number} has not started`}>
                  Close round {view.number - 1} first. Everyone who passes it is invited to this round.
                </Empty>
              )
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Candidate</th>
                    <th>Interview</th>
                    <th className="right">Interview score</th>
                    <th>Analysis</th>
                    <th className="right">CV score</th>
                    <th>Decision</th>
                  </tr>
                </thead>
                <tbody>
                  {view.rows.map((row) => {
                    const state = interviewState(row);
                    return (
                      <tr key={row.session_id} className="clickable" onClick={() => navigate(row.attended ? `/results/${row.session_id}` : `/candidates/${row.candidate_id}?tab=interview`)}>
                        <td className="muted num">{row.rank ?? ""}</td>
                        <td>
                          <Link to={row.attended ? `/results/${row.session_id}` : `/candidates/${row.candidate_id}?tab=interview`} onClick={(e) => e.stopPropagation()}>
                            {row.name}
                          </Link>
                          <span className="cell-sub">{row.email || "No e-mail address"}</span>
                        </td>
                        <td>
                          <span className={`badge ${state.tone}`}>{state.text}</span>
                        </td>
                        <td className="right score-cell">{row.score ?? "—"}</td>
                        <td>
                          {row.attended ? (
                            <span className="run-badges">
                              <RunBadge state={row.analysis_status} label="Answers" />
                              <RunBadge state={row.score_status} label="Score" />
                              <RunBadge state={row.quality_status} label="Quality" />
                            </span>
                          ) : (
                            <span className="muted small">—</span>
                          )}
                        </td>
                        <td className="right muted">{row.cv_score ?? "—"}</td>
                        <td>
                          {row.decision === "passed" ? (
                            <span className="badge pass">Passed</span>
                          ) : row.decision === "rejected" ? (
                            <span className="badge">Not progressed</span>
                          ) : (
                            <span className="muted small">Open</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        </>
      )}

      {closing && view && (
        <SelectionDialog
          title={`Close round ${view.number}: ${view.name}`}
          intro={
            <>
              Everyone in this round, ranked by their interview score. Choose who passes. Those who pass{" "}
              {view.is_last ? "go to the Report stage" : `are invited to round ${view.number + 1}`}; everyone else gets a polite rejection e-mail.
              Candidates whose interview was cancelled or never took place get an e-mail saying it could not go ahead, not a rejection
              after an interview.
            </>
          }
          items={view.rows.map((row) => ({
            id: row.candidate_id,
            name: row.name,
            sub: row.attended ? (row.score === null ? "attended, not scored yet" : undefined) : row.cancelled ? "cancelled" : "did not attend",
            score: row.score,
          }))}
          scoreLabel="Interview score"
          defaultMark={60}
          passWord={view.is_last ? "go to the Report stage" : `go to round ${view.number + 1}`}
          failWord="get a rejection e-mail"
          extra={
            !view.is_last && (
              <div className="field">
                <label htmlFor="next-day">First interview day of round {view.number + 1}</label>
                <input id="next-day" type="date" value={startDate} min={isoDay(new Date())} onChange={(e) => setStartDate(e.target.value)} />
              </div>
            )
          }
          extraReady={view.is_last || !!startDate}
          confirmLabel={(count) => `Close the round: ${count} pass`}
          onConfirm={close}
          onClose={() => setClosing(false)}
        />
      )}
    </>
  );
}
