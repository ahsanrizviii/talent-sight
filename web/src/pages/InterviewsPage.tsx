import { Fragment, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { api, withQuery } from "../api";
import Avatar from "../components/Avatar";
import Empty from "../components/Empty";
import Icon from "../components/Icon";
import RescheduleBox from "../components/RescheduleBox";
import SavedTranscript from "../components/SavedTranscript";
import type { InterviewRow, JobRow } from "../types";
import { clockTime, lengthText, shortDate, untilText } from "../when";

type State = "upcoming" | "live" | "not_ended" | "past" | "all";

const TABS: { value: State; label: string }[] = [
  { value: "upcoming", label: "Coming up" },
  { value: "live", label: "Happening now" },
  { value: "not_ended", label: "Not ended" },
  { value: "past", label: "Finished" },
  { value: "all", label: "All" },
];

// Filters other than the tab and the sort, kept in the address bar so a filtered list can be shared.
const FILTERS = ["q", "job_id", "date_from", "date_to", "hide_test_calls"];

const SORTS = [
  { value: "", label: "Usual order" },
  { value: "soonest", label: "Time: soonest first" },
  { value: "latest", label: "Time: latest first" },
  { value: "candidate", label: "Candidate name" },
  { value: "job", label: "Job" },
  { value: "score", label: "Score: highest first" },
  { value: "state", label: "State" },
];

// Every interview in one place: what is next, what is running, and the transcripts of
// everything that has already happened. Booked interviews can be moved from here.
export default function InterviewsPage() {
  const [params, setParams] = useSearchParams();
  const [rows, setRows] = useState<InterviewRow[] | null>(null);
  const [jobs, setJobs] = useState<JobRow[]>([]);
  const [open, setOpen] = useState<number | null>(null);
  const [moving, setMoving] = useState<number | null>(null);
  const [reload, setReload] = useState(0);
  const [error, setError] = useState("");

  const state = (params.get("state") as State) || "upcoming";
  const q = params.get("q") ?? "";
  const sort = params.get("sort") ?? "";
  const jobId = params.get("job_id") ?? "";
  const dateFrom = params.get("date_from") ?? "";
  const dateTo = params.get("date_to") ?? "";
  const hideTestCalls = params.get("hide_test_calls") === "true";
  const filtered = FILTERS.some((key) => params.get(key));

  function set(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
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

  useEffect(() => {
    setRows(null);
    setError("");
    api<InterviewRow[]>(
      withQuery("/workspace/interviews", {
        state,
        q,
        sort,
        job_id: jobId,
        date_from: dateFrom,
        date_to: dateTo,
        hide_test_calls: hideTestCalls ? "true" : "",
      }),
    )
      .then(setRows)
      .catch((err) => setError(err.message));
  }, [state, q, sort, jobId, dateFrom, dateTo, hideTestCalls, reload]);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Interviews</h1>
          <p>Join a call, check the time, or read what was said.</p>
        </div>
      </div>

      <div className="tabs glass" role="tablist">
        {TABS.map((tab) => (
          <button
            key={tab.value}
            role="tab"
            aria-selected={state === tab.value}
            onClick={() => set("state", tab.value)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="filters glass">
        <div className="search">
          <Icon name="search" />
          <input
            type="search"
            value={q}
            onChange={(event) => set("q", event.target.value)}
            placeholder="Candidate or job"
            aria-label="Search interviews"
          />
        </div>
        <select value={jobId} onChange={(event) => set("job_id", event.target.value)} aria-label="Job">
          <option value="">Every job</option>
          {jobs.map((job) => (
            <option key={job.id} value={job.id}>
              {job.title}
            </option>
          ))}
        </select>
        <label className="date-filter">
          <span className="muted small">From</span>
          <input type="date" value={dateFrom} max={dateTo || undefined} onChange={(event) => set("date_from", event.target.value)} />
        </label>
        <label className="date-filter">
          <span className="muted small">To</span>
          <input type="date" value={dateTo} min={dateFrom || undefined} onChange={(event) => set("date_to", event.target.value)} />
        </label>
        <label className="check-filter">
          <input
            type="checkbox"
            checked={hideTestCalls}
            onChange={(event) => set("hide_test_calls", event.target.checked ? "true" : "")}
          />
          <span className="small">Hide test calls</span>
        </label>
        <label className="sort-select">
          <span className="muted small">Sort</span>
          <select value={sort} onChange={(event) => set("sort", event.target.value)} aria-label="Sort interviews">
            {SORTS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <span className="spacer result-count">
          {rows ? `${rows.length} interview${rows.length === 1 ? "" : "s"}` : "Loading…"}
        </span>
        {filtered && (
          <button className="button quiet small" type="button" onClick={clearFilters}>
            Clear filters
          </button>
        )}
      </div>
      {hideTestCalls && (
        <p className="muted small filter-note">Test calls are calls that ended in under two minutes with nothing said.</p>
      )}

      {error && <p className="error">{error}</p>}

      <div className="card glass flush">
        {rows === null ? (
          <div style={{ padding: 18 }}>
            <div className="skeleton" />
            <div className="skeleton" />
          </div>
        ) : rows.length === 0 ? (
          <Empty
            title={
              filtered
                ? "No interviews match these filters"
                : state === "past"
                  ? "No interviews have finished yet"
                  : state === "not_ended"
                    ? "Every call was ended properly"
                    : "Nothing booked"
            }
          >
            {filtered
              ? "Try another job or a wider date range, or clear the filters."
              : "Open a candidate who passed screening and schedule their interview from their page."}
          </Empty>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Candidate</th>
                <th>Job</th>
                <th>When</th>
                <th>State</th>
                <th>Transcript</th>
                <th className="right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <Fragment key={row.id}>
                  <tr>
                    <td>
                      <span className="who">
                        <Avatar name={row.candidate_name} />
                        <Link to={`/candidates/${row.candidate_id}`}>{row.candidate_name}</Link>
                      </span>
                    </td>
                    <td className="muted">{row.job_title}</td>
                    <td className="nowrap">
                      {shortDate(row.scheduled_at)} at {clockTime(row.scheduled_at)}
                      <span className="cell-sub">
                        {row.status === "ended" ? lengthText(row.duration_seconds) : untilText(row.scheduled_at)}
                      </span>
                    </td>
                    <td>
                      {row.forgotten ? (
                        <span className="badge stop" title="Still open long after its planned end. Open the room and end it.">
                          Not ended
                        </span>
                      ) : row.status === "live" ? (
                        <span className="badge live">Happening now</span>
                      ) : row.status === "ended" ? (
                        <span className="badge">Finished</span>
                      ) : row.overdue ? (
                        <span className="badge stop">Did not start</span>
                      ) : (
                        <span className="badge accent">Booked</span>
                      )}
                    </td>
                    <td>
                      {row.transcript_lines ? (
                        <button
                          className="button quiet small"
                          type="button"
                          onClick={() => setOpen(open === row.id ? null : row.id)}
                          aria-expanded={open === row.id}
                        >
                          {open === row.id ? "Hide" : `${row.transcript_lines} lines`}
                        </button>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                    <td className="right">
                      <span className="row-actions">
                        {row.status === "scheduled" && (
                          <button className="button quiet small" type="button" onClick={() => setMoving(moving === row.id ? null : row.id)} aria-expanded={moving === row.id}>
                            {moving === row.id ? "Close" : "Reschedule"}
                          </button>
                        )}
                        <Link
                          className={row.status === "live" && !row.forgotten ? "button small" : "button secondary small"}
                          to={`/interview/${row.id}`}
                        >
                          {row.forgotten
                            ? "Open and end it"
                            : row.status === "live"
                              ? "Join now"
                              : row.status === "ended"
                                ? "Open"
                                : "Open room"}
                        </Link>
                      </span>
                    </td>
                  </tr>
                  {moving === row.id && (
                    <tr className="reschedule-row">
                      <td colSpan={6}>
                        <RescheduleBox
                          sessionId={row.id}
                          currentAt={row.scheduled_at}
                          onMoved={() => setReload((n) => n + 1)}
                          onClose={() => setMoving(null)}
                        />
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {open !== null && (
        <div className="card glass">
          <SavedTranscript sessionId={open} startOpen />
        </div>
      )}
    </>
  );
}
