import { Fragment, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { api, withQuery } from "../api";
import Avatar from "../components/Avatar";
import Empty from "../components/Empty";
import Icon from "../components/Icon";
import RescheduleBox from "../components/RescheduleBox";
import SavedTranscript from "../components/SavedTranscript";
import type { InterviewRow } from "../types";
import { clockTime, lengthText, shortDate, untilText } from "../when";

type State = "upcoming" | "live" | "past" | "all";

const TABS: { value: State; label: string }[] = [
  { value: "upcoming", label: "Coming up" },
  { value: "live", label: "Happening now" },
  { value: "past", label: "Finished" },
  { value: "all", label: "All" },
];

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
  const [open, setOpen] = useState<number | null>(null);
  const [moving, setMoving] = useState<number | null>(null);
  const [reload, setReload] = useState(0);
  const [error, setError] = useState("");

  const state = (params.get("state") as State) || "upcoming";
  const q = params.get("q") ?? "";
  const sort = params.get("sort") ?? "";

  function set(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  }

  useEffect(() => {
    setRows(null);
    api<InterviewRow[]>(withQuery("/workspace/interviews", { state, q, sort }))
      .then(setRows)
      .catch((err) => setError(err.message));
  }, [state, q, sort, reload]);

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
      </div>

      {error && <p className="error">{error}</p>}

      <div className="card glass flush">
        {rows === null ? (
          <div style={{ padding: 18 }}>
            <div className="skeleton" />
            <div className="skeleton" />
          </div>
        ) : rows.length === 0 ? (
          <Empty title={state === "past" ? "No interviews have finished yet" : "Nothing booked"}>
            Open a candidate who passed screening and schedule their interview from their page.
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
                      {row.status === "live" ? (
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
                          className={row.status === "live" ? "button small" : "button secondary small"}
                          to={`/interview/${row.id}`}
                        >
                          {row.status === "live" ? "Join now" : row.status === "ended" ? "Open" : "Open room"}
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
                          durationMinutes={row.duration_minutes}
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
