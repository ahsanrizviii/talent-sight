import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api";
import Avatar from "../components/Avatar";
import CountUp from "../components/CountUp";
import Empty from "../components/Empty";
import Icon from "../components/Icon";
import StageBadge from "../components/StageBadge";
import type { Me, Overview, SetupCheck } from "../types";
import { shortDateTime, untilText } from "../when";

// Where the hiring team starts the day: how the pipeline stands, what needs doing,
// and who is being interviewed next.
export default function DashboardPage() {
  const [data, setData] = useState<Overview | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState("");
  const [missing, setMissing] = useState<SetupCheck[]>([]);

  useEffect(() => {
    // probe=false only reads the settings, so the dashboard stays instant.
    api<SetupCheck[]>("/setup/checks?probe=false")
      .then((checks) => setMissing(checks.filter((check) => !check.ok && !check.optional)))
      .catch(() => undefined);
    api<Overview>("/workspace/overview").then(setData).catch((err) => setError(err.message));
    api<Me>("/auth/me").then(setMe).catch(() => undefined);
  }, []);

  if (error) return <p className="error">{error}</p>;

  const widest = Math.max(1, ...(data?.funnel.map((step) => step.value) ?? [1]));

  return (
    <>
      <div className="page-head">
        <div>
          <h1>{me?.name ? `Good to see you, ${me.name.split(" ")[0]}` : "Dashboard"}</h1>
          <p>Everything open across {data?.jobs_total ?? 0} job{data?.jobs_total === 1 ? "" : "s"}.</p>
        </div>
        <div className="row">
          <Link className="button secondary" to="/jobs/new">
            <Icon name="plus" />
            New job
          </Link>
          <Link className="button" to="/jd-chat">
            <Icon name="sparkle" />
            Write a job with AI
          </Link>
        </div>
      </div>

      {missing.length > 0 && (
        <div className="card notice">
          <div>
            <strong>Not ready to invite candidates yet.</strong>{" "}
            Still to set up: {missing.map((check) => check.label).join(", ")}.
          </div>
        </div>
      )}

      <div className="framed">
        <div className="card glass hero-card">
          <div>
            <h2>{data ? `${data.passed_screening} candidates are through screening` : "Your hiring, right now"}</h2>
            <p className="lead">
              {data?.waiting_to_screen
                ? `${data.waiting_to_screen} more ${data.waiting_to_screen === 1 ? "CV is" : "CVs are"} waiting to be read. Everything the AI found is on the candidate's own page, with the evidence beside it.`
                : "Every CV has been read and scored against the job you wrote. Open a candidate to see the evidence behind each number."}
            </p>
          </div>
          <div className={data?.average_score ? "big-stat" : "big-stat none"}>
            <strong>{data ? <CountUp value={data.average_score} decimals={1} /> : "—"}</strong>
            <span>average score, out of 100</span>
          </div>
        </div>
      </div>

      <div className="stats">
        <Link className="stat glass" to="/jobs">
          <div className="stat-value">{data ? <CountUp value={data.jobs_open} /> : "—"}</div>
          <div className="stat-label">Jobs open</div>
          <div className="stat-note">{data ? `${data.jobs_total} in total` : " "}</div>
        </Link>
        <Link className="stat glass" to="/candidates">
          <div className="stat-value">{data ? <CountUp value={data.candidates_total} /> : "—"}</div>
          <div className="stat-label">Candidates</div>
          <div className="stat-note">{data ? `${data.passed_screening} passed screening` : " "}</div>
        </Link>
        <Link className="stat glass" to="/candidates?stage=new">
          <div className="stat-value">{data ? <CountUp value={data.waiting_to_screen} /> : "—"}</div>
          <div className="stat-label">Waiting to screen</div>
          <div className="stat-note">{data?.waiting_to_screen ? "Needs a screening run" : "Nothing waiting"}</div>
        </Link>
        <Link className="stat glass" to="/interviews">
          <div className="stat-value">{data ? <CountUp value={data.interviews_upcoming} /> : "—"}</div>
          <div className="stat-label">Interviews ahead</div>
          <div className="stat-note">{data ? `${data.interviews_done} already done` : " "}</div>
        </Link>
      </div>

      <div className="board">
        <div>
          <div className="card glass">
            <div className="card-head">
              <h2>Where everyone is</h2>
              <Link className="small" to="/candidates">
                All candidates
              </Link>
            </div>
            {data && data.candidates_total === 0 ? (
              <Empty title="No CVs yet">
                Create a job, publish it, then upload CVs or import them from your Google Form.
              </Empty>
            ) : (
              <ol className="funnel">
                {(data?.funnel ?? []).map((step) => (
                  <li key={step.label}>
                    <span>{step.label}</span>
                    <span className="funnel-track">
                      <span className="funnel-fill" style={{ width: `${(100 * step.value) / widest}%` }} />
                    </span>
                    <span className="right">{step.value}</span>
                  </li>
                ))}
              </ol>
            )}
          </div>

          <div className="card glass">
            <div className="card-head">
              <h2>Leading candidates</h2>
              <Link className="small" to="/candidates?sort=score">
                Ranked list
              </Link>
            </div>
            {data?.top_candidates.length ? (
              <ul className="mini">
                {data.top_candidates.map((person) => (
                  <li key={person.id}>
                    <span className="who">
                      <Avatar name={person.name} />
                      <span>
                        <Link to={`/candidates/${person.id}`}>{person.name}</Link>
                        <span className="cell-sub">{person.job_title}</span>
                      </span>
                    </span>
                    <span className="row" style={{ gap: 14 }}>
                      <StageBadge stage={person.stage} />
                      <strong className="score-cell">{person.overall}</strong>
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted small">Scores appear here once a screening run has finished.</p>
            )}
          </div>
        </div>

        <div>
          <div className="card glass">
            <div className="card-head">
              <h2>Needs you</h2>
            </div>
            {data?.todo.length ? (
              <ul className="todo">
                {data.todo.map((item) => (
                  <li key={item.text}>
                    <span className={item.tone === "warn" ? "warn" : ""}>{item.text}</span>
                    <Link className="button secondary small" to={item.to}>
                      {item.action}
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted small">Nothing waiting. Every CV is screened and every job is published.</p>
            )}
          </div>

          <div className="card glass">
            <div className="card-head">
              <h2>Next interviews</h2>
              <Link className="small" to="/interviews">
                All interviews
              </Link>
            </div>
            {data?.upcoming.length ? (
              <ul className="mini">
                {data.upcoming.map((interview) => (
                  <li key={interview.id}>
                    <span className="who">
                      <Avatar name={interview.candidate_name} />
                      <span>
                      <Link to={`/candidates/${interview.candidate_id}`}>{interview.candidate_name}</Link>
                      <span className="cell-sub">
                        {shortDateTime(interview.scheduled_at)} · {untilText(interview.scheduled_at)}
                      </span>
                      </span>
                    </span>
                    <Link
                      className={interview.status === "live" ? "button small" : "button secondary small"}
                      to={`/interview/${interview.id}`}
                    >
                      {interview.status === "live" ? "Join now" : "Open"}
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted small">No interviews booked. Open a candidate who passed screening to book one.</p>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
