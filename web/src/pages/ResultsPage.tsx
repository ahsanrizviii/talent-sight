import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { api, withQuery } from "../api";
import Avatar from "../components/Avatar";
import Empty from "../components/Empty";
import Icon from "../components/Icon";
import RunBadge from "../components/RunBadge";
import type { Job, JobRow, ResultRow } from "../types";
import { clockTime, lengthText, shortDate } from "../when";
import "../hiring.css";

const SORTS = [
  { value: "latest", label: "Newest first" },
  { value: "score", label: "Interview score: highest first" },
  { value: "candidate", label: "Candidate name" },
  { value: "job", label: "Job" },
];

const FILTERS = ["q", "job_id", "round"];

// Every interview that took place, across every job, round and candidate: one row per interview,
// with its interview score and whether its answer analysis, score and quality review are done.
// A row opens that interview's results.
export default function ResultsPage() {
  const [params, setParams] = useSearchParams();
  const [rows, setRows] = useState<ResultRow[] | null>(null);
  const [jobs, setJobs] = useState<JobRow[]>([]);
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState("");

  const q = params.get("q") ?? "";
  const jobId = params.get("job_id") ?? "";
  const round = params.get("round") ?? "";
  const sort = params.get("sort") ?? "latest";
  const filtered = FILTERS.some((key) => params.get(key));

  function set(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key === "job_id") next.delete("round"); // rounds belong to one job
    setParams(next, { replace: true });
  }

  function clearFilters() {
    const next = new URLSearchParams(params);
    FILTERS.forEach((key) => next.delete(key));
    setParams(next, { replace: true });
  }

  useEffect(() => {
    api<JobRow[]>("/workspace/jobs").then(setJobs).catch(() => undefined);
  }, []);

  // The round filter lists the chosen job's own rounds.
  useEffect(() => {
    setJob(null);
    if (!jobId) return;
    api<Job>(`/jobs/${jobId}`).then(setJob).catch(() => undefined);
  }, [jobId]);

  useEffect(() => {
    setRows(null);
    setError("");
    api<ResultRow[]>(withQuery("/workspace/results", { q, job_id: jobId, round, sort }))
      .then(setRows)
      .catch((err) => setError(err.message));
  }, [q, jobId, round, sort]);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Results</h1>
          <p>The answer analysis, interview score and interview quality of every interview, for every job and round.</p>
        </div>
      </div>

      <div className="filters glass">
        <div className="search">
          <Icon name="search" />
          <input type="search" value={q} onChange={(event) => set("q", event.target.value)} placeholder="Candidate or job" aria-label="Search results" />
        </div>
        <select value={jobId} onChange={(event) => set("job_id", event.target.value)} aria-label="Job">
          <option value="">Every job</option>
          {jobs.map((item) => (
            <option key={item.id} value={item.id}>
              {item.title}
            </option>
          ))}
        </select>
        <select value={round} onChange={(event) => set("round", event.target.value)} aria-label="Round" disabled={!job}>
          <option value="">{job ? "Every round" : "Pick a job to filter by round"}</option>
          {job?.interview_rounds.map((item, index) => (
            <option key={index} value={index + 1}>
              Round {index + 1} · {item.name}
            </option>
          ))}
        </select>
        <label className="sort-select">
          <span className="muted small">Sort</span>
          <select value={sort} onChange={(event) => set("sort", event.target.value)} aria-label="Sort results">
            {SORTS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <span className="spacer result-count">{rows ? `${rows.length} interview${rows.length === 1 ? "" : "s"}` : "Loading…"}</span>
        {filtered && (
          <button className="button quiet small" type="button" onClick={clearFilters}>
            Clear filters
          </button>
        )}
      </div>

      {error && <p className="error">{error}</p>}

      <div className="card glass flush">
        {rows === null ? (
          <div style={{ padding: 18 }}>
            <div className="skeleton" />
            <div className="skeleton" />
          </div>
        ) : rows.length === 0 ? (
          <Empty title={filtered ? "No interviews match these filters" : "No interview has taken place yet"}>
            {filtered ? "Try another job or round, or clear the filters." : "Interviews appear here as soon as they have been held."}
          </Empty>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Candidate</th>
                <th>Job</th>
                <th>Round</th>
                <th>Held</th>
                <th className="right">Interview score</th>
                <th>Analysis</th>
                <th>Decision</th>
                <th className="right"></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.session_id}>
                  <td>
                    <span className="who">
                      <Avatar name={row.candidate_name} />
                      <Link to={`/results/${row.session_id}`}>{row.candidate_name}</Link>
                    </span>
                  </td>
                  <td className="muted">
                    <Link to={`/jobs/${row.job_id}/candidates?stage=interviews&round=${row.round_number}`}>{row.job_title}</Link>
                  </td>
                  <td className="nowrap">
                    Round {row.round_number} of {row.round_total}
                    <span className="cell-sub">{row.round_name}</span>
                  </td>
                  <td className="nowrap">
                    {shortDate(row.held_at)} at {clockTime(row.held_at)}
                    <span className="cell-sub">{lengthText(row.duration_seconds)}</span>
                  </td>
                  <td className="right score-cell">{row.interview_score ?? "—"}</td>
                  <td>
                    <span className="run-badges">
                      <RunBadge state={row.analysis_status} label="Answers" />
                      <RunBadge state={row.score_status} label="Score" />
                      <RunBadge state={row.quality_status} label="Quality" />
                    </span>
                  </td>
                  <td>
                    {row.decision === "passed" ? (
                      <span className="badge pass">Passed</span>
                    ) : row.decision === "rejected" ? (
                      <span className="badge">Not progressed</span>
                    ) : (
                      <span className="muted small">Open</span>
                    )}
                  </td>
                  <td className="right">
                    <Link className="button secondary small" to={`/results/${row.session_id}`}>
                      Open
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
