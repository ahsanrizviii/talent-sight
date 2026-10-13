import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { api, withQuery } from "../api";
import Avatar from "../components/Avatar";
import Empty from "../components/Empty";
import Icon from "../components/Icon";
import StageBadge, { stageLabel } from "../components/StageBadge";
import type { JobRow, PersonRow, Stage } from "../types";
import { shortDate } from "../when";

const STAGES: Stage[] = ["new", "screened", "interview", "interviewed", "excluded", "problem"];

const SORTS = [
  { value: "score", label: "Highest score" },
  { value: "name", label: "Name" },
  { value: "added", label: "Newest first" },
  { value: "job", label: "Job" },
];

// Every candidate the company has, in one table. This is the page that answers
// "where is that person I spoke to last week" without remembering which job they applied for.
export default function PeoplePage() {
  const [params, setParams] = useSearchParams();
  const [rows, setRows] = useState<PersonRow[] | null>(null);
  const [jobs, setJobs] = useState<JobRow[]>([]);
  const [error, setError] = useState("");

  // Every filter lives in the address bar, so a filtered list can be bookmarked or sent to a colleague.
  const filters = useMemo(
    () => ({
      q: params.get("q") ?? "",
      job_id: params.get("job_id") ?? "",
      stage: params.get("stage") ?? "",
      source: params.get("source") ?? "",
      min_score: params.get("min_score") ?? "",
      sort: params.get("sort") ?? "score",
    }),
    [params],
  );

  const set = useCallback(
    (key: string, value: string) => {
      const next = new URLSearchParams(params);
      if (value) next.set(key, value);
      else next.delete(key);
      setParams(next, { replace: true });
    },
    [params, setParams],
  );

  useEffect(() => {
    api<JobRow[]>("/workspace/jobs").then(setJobs).catch(() => undefined);
  }, []);

  useEffect(() => {
    setRows(null);
    api<PersonRow[]>(withQuery("/workspace/candidates", filters))
      .then(setRows)
      .catch((err) => setError(err.message));
  }, [filters]);

  function downloadCsv() {
    const head = ["Name", "E-mail", "Job", "Stage", "Score", "Met", "Partly met", "Unmet", "Source", "Added"];
    const body = (rows ?? []).map((row) => [
      row.name,
      row.email,
      row.job_title,
      stageLabel(row.stage),
      row.overall ?? "",
      row.met,
      row.partially_met,
      row.unmet,
      row.source === "google_form" ? "Google Form" : "Upload",
      shortDate(row.created_at),
    ]);
    const csv = [head, ...body]
      .map((line) => line.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(","))
      .join("\n");

    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    link.download = `talentsight-candidates-${new Date().toISOString().slice(0, 10)}.csv`;
    link.click();
    URL.revokeObjectURL(link.href);
  }

  const filtered = Object.entries(filters).some(([key, value]) => value && key !== "sort");

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Candidates</h1>
          <p>Everyone who applied, across every job.</p>
        </div>
        <button className="button secondary" type="button" onClick={downloadCsv} disabled={!rows?.length}>
          <Icon name="download" />
          Download CSV
        </button>
      </div>

      <div className="filters glass">
        <div className="search">
          <Icon name="search" />
          <input
            type="search"
            value={filters.q}
            onChange={(event) => set("q", event.target.value)}
            placeholder="Name, e-mail or job"
            aria-label="Search candidates"
          />
        </div>

        <select value={filters.job_id} onChange={(event) => set("job_id", event.target.value)} aria-label="Job">
          <option value="">Every job</option>
          {jobs.map((job) => (
            <option key={job.id} value={job.id}>
              {job.title}
            </option>
          ))}
        </select>

        <select value={filters.stage} onChange={(event) => set("stage", event.target.value)} aria-label="Stage">
          <option value="">Every stage</option>
          {STAGES.map((stage) => (
            <option key={stage} value={stage}>
              {stageLabel(stage)}
            </option>
          ))}
        </select>

        <select value={filters.source} onChange={(event) => set("source", event.target.value)} aria-label="Came from">
          <option value="">Any source</option>
          <option value="upload">Uploaded</option>
          <option value="google_form">Google Form</option>
        </select>

        <select
          value={filters.min_score}
          onChange={(event) => set("min_score", event.target.value)}
          aria-label="Lowest score"
        >
          <option value="">Any score</option>
          <option value="80">80 and above</option>
          <option value="70">70 and above</option>
          <option value="60">60 and above</option>
        </select>

        <select value={filters.sort} onChange={(event) => set("sort", event.target.value)} aria-label="Sort by">
          {SORTS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>

        <span className="spacer result-count">
          {rows ? `${rows.length} candidate${rows.length === 1 ? "" : "s"}` : "Loading…"}
        </span>
        {filtered && (
          <button className="button quiet small" type="button" onClick={() => setParams({}, { replace: true })}>
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
            <div className="skeleton" />
          </div>
        ) : rows.length === 0 ? (
          <Empty title={filtered ? "Nothing matches those filters" : "No candidates yet"}>
            {filtered
              ? "Try a wider search, or clear the filters."
              : "Open a job and upload CVs, or import the applications from your Google Form."}
          </Empty>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Candidate</th>
                <th>Job</th>
                <th>Stage</th>
                <th className="right">Score</th>
                <th>Requirements</th>
                <th>Interview</th>
                <th>Added</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td>
                    <span className="who">
                      <Avatar name={row.name} />
                      <span>
                        <Link to={`/candidates/${row.id}`}>{row.name}</Link>
                        <span className="cell-sub">{row.email || row.cv_filename}</span>
                      </span>
                    </span>
                  </td>
                  <td>
                    <Link to={`/jobs/${row.job_id}/candidates`}>{row.job_title}</Link>
                    {row.rank !== null && <span className="cell-sub">#{row.rank} for this job</span>}
                  </td>
                  <td>
                    <StageBadge stage={row.stage} />
                  </td>
                  <td className="right score-cell">{row.overall ?? "—"}</td>
                  <td>
                    {row.met + row.partially_met + row.unmet > 0 ? (
                      <span className="verdict-counts">
                        <span className="verdict-met">{row.met} met</span>
                        <span className="verdict-partially_met">{row.partially_met} partly</span>
                        <span className="verdict-unmet">{row.unmet} unmet</span>
                      </span>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                  <td>
                    {row.interview_id ? (
                      <Link to={`/interview/${row.interview_id}`}>
                        {row.interview_status === "ended"
                          ? `${row.transcript_lines} transcript lines`
                          : row.interview_status === "live"
                            ? "Happening now"
                            : "Booked"}
                      </Link>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                  <td className="muted small nowrap">{shortDate(row.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
