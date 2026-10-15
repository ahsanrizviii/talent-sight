import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api";
import Avatar from "../components/Avatar";
import CountUp from "../components/CountUp";
import Empty from "../components/Empty";
import Icon from "../components/Icon";
import type { Me, Overview, SetupCheck } from "../types";
import { lengthText, shortDateTime, untilText } from "../when";

// Where the hiring team starts the day: the next interview, what needs doing,
// how far each open job has got, and who is worth inviting next.

const plural = (count: number, word: string) => `${count} ${word}${count === 1 ? "" : "s"}`;

// The headline: the interview that matters most right now, or what to do when none is booked.
function Hero({ data }: { data: Overview | null }) {
  const next = data?.next_interview ?? null;

  let title = "Your hiring, right now";
  let lead = "";
  if (next?.status === "live") {
    title = `${next.candidate_name}'s interview is live`;
    lead = `${next.job_title}. Started ${untilText(next.started_at ?? next.scheduled_at)}.`;
  } else if (next) {
    title = `Next interview: ${next.candidate_name}`;
    lead = `${next.job_title} · ${shortDateTime(next.scheduled_at)}, ${untilText(next.scheduled_at)}. Read the profile before you join.`;
  } else if (data?.ready_total) {
    title = "No interviews booked";
    lead = `${plural(data.ready_total, "candidate")} passed screening and ${data.ready_total === 1 ? "is" : "are"} waiting for an invitation.`;
  } else if (data) {
    title = "No interviews booked";
    lead = "Screen the CVs of an open job to find candidates worth inviting.";
  }

  return (
    <div className="framed">
      <div className="card glass hero-card">
        <div>
          <h2>{title}</h2>
          {lead && <p className="lead">{lead}</p>}
          <div className="hero-buttons">
            {next?.status === "live" && (
              <>
                <Link className="button" to={`/interview/${next.id}`}>
                  Join now
                </Link>
                <Link className="button secondary" to={`/candidates/${next.candidate_id}`}>
                  Profile
                </Link>
              </>
            )}
            {next?.status === "scheduled" && (
              <>
                <Link className="button" to={`/candidates/${next.candidate_id}`}>
                  Read the profile
                </Link>
                <Link className="button secondary" to={`/interview/${next.id}`}>
                  Join the room
                </Link>
              </>
            )}
            {!next && data?.ready_total ? (
              <Link className="button" to="/candidates?stage=screened">
                See who to invite
              </Link>
            ) : null}
          </div>
        </div>
        <div className={data?.interviews_week ? "big-stat" : "big-stat none"}>
          <strong>{data ? <CountUp value={data.interviews_week} /> : "—"}</strong>
          <span>interviews in the next 7 days</span>
        </div>
      </div>
    </div>
  );
}

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
          <p>Everything open across {plural(data?.jobs_total ?? 0, "job")}.</p>
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

      <Hero data={data} />

      <div className="stats">
        <Link className="stat glass" to="/jobs">
          <div className="stat-value">{data ? <CountUp value={data.jobs_open} /> : "—"}</div>
          <div className="stat-label">Jobs open</div>
          <div className="stat-note">{data ? `${data.jobs_total} in total` : " "}</div>
        </Link>
        <Link className="stat glass" to="/candidates?stage=new">
          <div className="stat-value">{data ? <CountUp value={data.waiting_to_screen} /> : "—"}</div>
          <div className="stat-label">Waiting to screen</div>
          <div className="stat-note">{data?.waiting_to_screen ? "Needs a screening run" : "Nothing waiting"}</div>
        </Link>
        <Link className="stat glass" to="/candidates?stage=screened">
          <div className="stat-value">{data ? <CountUp value={data.ready_total} /> : "—"}</div>
          <div className="stat-label">Ready to invite</div>
          <div className="stat-note">Passed screening, no interview yet</div>
        </Link>
        <Link className="stat glass" to="/interviews">
          <div className="stat-value">{data ? <CountUp value={data.interviews_upcoming} /> : "—"}</div>
          <div className="stat-label">Interviews ahead</div>
          <div className="stat-note">{data ? `${data.interviews_done} held so far` : " "}</div>
        </Link>
      </div>

      <div className="board">
        <div>
          <div className="card glass">
            <div className="card-head">
              <h2>Open jobs</h2>
              <Link className="small" to="/jobs">
                All jobs
              </Link>
            </div>
            {data && data.jobs.length === 0 ? (
              <Empty title="No open jobs">Publish a job to start collecting CVs.</Empty>
            ) : (
              <ul className="job-progress">
                {(data?.jobs ?? []).map((job) => (
                  <li key={job.id}>
                    <div>
                      <Link className="job-progress-title" to={`/jobs/${job.id}/candidates`}>
                        {job.title}
                      </Link>
                      <span className="cell-sub">
                        {job.days_open === 0 ? "Opened today" : `Open ${plural(job.days_open, "day")}`}
                        {" · "}
                        {job.leader_name ? `Best so far: ${job.leader_name} (${job.leader_score})` : "Nobody ranked yet"}
                      </span>
                      <span className="job-progress-counts">
                        <span>
                          <b>{job.candidates}</b> CVs
                        </span>
                        <span>
                          <b>{job.passed}</b> passed
                        </span>
                        <span>
                          <b>{job.invited}</b> invited
                        </span>
                        <span>
                          <b>{job.interviewed}</b> interviewed
                        </span>
                      </span>
                    </div>
                    <Link className="button secondary small" to={job.next_link}>
                      {job.next_step}
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="card glass">
            <div className="card-head">
              <h2>Ready to invite</h2>
              <Link className="small" to="/candidates?stage=screened">
                See all
              </Link>
            </div>
            <p className="muted small card-note">
              Passed screening, no interview yet. Best first within each job: a score is only compared with others for the same job.
            </p>
            {data?.ready_to_invite.length ? (
              <ul className="mini">
                {data.ready_to_invite.map((person) => (
                  <li key={person.id}>
                    <span className="who">
                      <span className="rank-chip">#{person.rank}</span>
                      <span>
                        <Link to={`/candidates/${person.id}`}>{person.name}</Link>
                        <span className="cell-sub">
                          {person.job_title} · {person.met} requirement{person.met === 1 ? "" : "s"} met
                        </span>
                      </span>
                    </span>
                    <span className="row" style={{ gap: 14 }}>
                      <strong className="score-cell">{person.overall}</strong>
                      <Link className="button secondary small" to={`/candidates/${person.id}`}>
                        Review
                      </Link>
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted small">Nobody is waiting for an invitation.</p>
            )}
          </div>

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
              <p className="muted small">Nothing waiting. Every CV is screened and every interview is on track.</p>
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
                          {interview.status === "live"
                            ? `${interview.job_title} · live now`
                            : `${interview.job_title} · ${shortDateTime(interview.scheduled_at)} · ${untilText(interview.scheduled_at)}`}
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

          <div className="card glass">
            <div className="card-head">
              <h2>Recently interviewed</h2>
              <Link className="small" to="/interviews">
                History
              </Link>
            </div>
            {data?.recent_interviews.length ? (
              <ul className="mini">
                {data.recent_interviews.map((interview) => (
                  <li key={interview.id}>
                    <span className="who">
                      <Avatar name={interview.candidate_name} />
                      <span>
                        <Link to={`/candidates/${interview.candidate_id}`}>{interview.candidate_name}</Link>
                        <span className="cell-sub">
                          {interview.job_title} · {lengthText(interview.duration_seconds)} ·{" "}
                          {plural(interview.transcript_lines, "transcript line")}
                        </span>
                      </span>
                    </span>
                    <Link className="button secondary small" to={`/candidates/${interview.candidate_id}`}>
                      Review
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted small">No interviews held in the last 14 days.</p>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
