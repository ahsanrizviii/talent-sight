import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { api, withQuery } from "../api";
import Avatar from "../components/Avatar";
import Empty from "../components/Empty";
import Icon from "../components/Icon";
import OnboardingCheckPanel from "../components/OnboardingCheckPanel";
import { CHECK_LABELS, CHECK_TONES } from "../checkStates";
import type { CheckState, JobRow, OnboardingRow } from "../types";
import { shortDate } from "../when";
import "../hiring.css";

const STATES: { value: "" | CheckState; label: string }[] = [
  { value: "", label: "Everyone" },
  { value: "waiting", label: "Not checked yet" },
  { value: "needs_decision", label: "Needs a decision" },
  { value: "verified", label: "Verified" },
  { value: "not_confirmed", label: "Not confirmed" },
];

// The first-day desk: everyone selected for onboarding, from every job. Pick a person, check their
// original photo ID, take their picture, and see whether they are the person who was interviewed.
// The result also shows on the job's Onboarding stage.
export default function IdentityCheckPage() {
  const [params, setParams] = useSearchParams();
  const [rows, setRows] = useState<OnboardingRow[] | null>(null);
  const [jobs, setJobs] = useState<JobRow[]>([]);
  const [error, setError] = useState("");

  const chosen = Number(params.get("candidate") ?? "") || null;
  const state = params.get("state") ?? "";
  const jobId = params.get("job_id") ?? "";
  const q = params.get("q") ?? "";

  function set(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  }

  const load = useCallback(() => {
    api<OnboardingRow[]>(withQuery("/workspace/identity-checks", { state, job_id: jobId, q }))
      .then(setRows)
      .catch((err) => setError(err.message));
  }, [state, jobId, q]);

  useEffect(() => {
    api<JobRow[]>("/workspace/jobs").then(setJobs).catch(() => undefined);
  }, []);

  useEffect(() => {
    setRows(null);
    setError("");
    load();
  }, [load]);

  // The list follows the check: refresh it every few seconds while a person is selected.
  useEffect(() => {
    if (!chosen) return;
    const timer = window.setInterval(load, 4000);
    return () => window.clearInterval(timer);
  }, [chosen, load]);

  const person = rows?.find((row) => row.candidate_id === chosen) ?? null;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Identity check</h1>
          <p>On a new hire's first day: confirm that the person who came is the person who was interviewed.</p>
        </div>
      </div>

      <div className="tabs glass" role="tablist">
        {STATES.map((item) => (
          <button key={item.value} role="tab" aria-selected={state === item.value} onClick={() => set("state", item.value)}>
            {item.label}
          </button>
        ))}
      </div>

      <div className="filters glass">
        <div className="search">
          <Icon name="search" />
          <input type="search" value={q} onChange={(event) => set("q", event.target.value)} placeholder="Name, e-mail or job" aria-label="Search" />
        </div>
        <select value={jobId} onChange={(event) => set("job_id", event.target.value)} aria-label="Job">
          <option value="">Every job</option>
          {jobs.map((job) => (
            <option key={job.id} value={job.id}>
              {job.title}
            </option>
          ))}
        </select>
        <span className="spacer result-count">{rows ? `${rows.length} ${rows.length === 1 ? "person" : "people"}` : "Loading…"}</span>
      </div>

      {error && <p className="error">{error}</p>}

      <div className="identity-layout">
        <div className="card glass flush">
          {rows === null ? (
            <div style={{ padding: 18 }}>
              <div className="skeleton" />
              <div className="skeleton" />
            </div>
          ) : rows.length === 0 ? (
            <Empty title="Nobody to check">
              People appear here once they are selected for onboarding in a job's Report stage.
            </Empty>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>New hire</th>
                  <th>Job</th>
                  <th>First day</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr
                    key={row.candidate_id}
                    className={row.candidate_id === chosen ? "chosen clickable" : "clickable"}
                    onClick={() => set("candidate", String(row.candidate_id))}
                  >
                    <td>
                      <span className="who">
                        <Avatar name={row.name} />
                        <span>
                          {row.name}
                          <span className="cell-sub">{row.email}</span>
                        </span>
                      </span>
                    </td>
                    <td className="muted">{row.job_title}</td>
                    <td className="nowrap">{row.onboarding_date ? shortDate(row.onboarding_date) : <span className="muted">Not set</span>}</td>
                    <td>
                      <span className={`badge ${CHECK_TONES[row.check_state]}`}>{CHECK_LABELS[row.check_state]}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div>
          {person ? (
            <>
              <div className="card glass">
                <div className="row between">
                  <div className="who">
                    <Avatar name={person.name} big />
                    <div>
                      <h2 style={{ margin: 0 }}>{person.name}</h2>
                      <p className="muted small" style={{ margin: 0 }}>
                        {person.job_title}
                        {person.report_score !== null && ` · report score ${person.report_score}`}
                      </p>
                    </div>
                  </div>
                  <Link className="button quiet small" to={`/candidates/${person.candidate_id}?tab=report`}>
                    See the report
                  </Link>
                </div>
              </div>
              <OnboardingCheckPanel key={person.candidate_id} candidateId={person.candidate_id} />
            </>
          ) : (
            <div className="card glass">
              <p className="muted" style={{ margin: 0 }}>
                Pick a person from the list to check their identity.
              </p>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
