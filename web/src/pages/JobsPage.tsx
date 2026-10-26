import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { api, withQuery } from "../api";
import Empty from "../components/Empty";
import Icon from "../components/Icon";
import type { JobRow } from "../types";
import { shortDate } from "../when";

// Every role being hired for, as a grid of tiles. Each tile carries the state of its own
// pipeline, so nobody has to open a job to find out whether anything is waiting there.
export default function JobsPage() {
  const [params, setParams] = useSearchParams();
  const [jobs, setJobs] = useState<JobRow[] | null>(null);
  const [error, setError] = useState("");

  const status = params.get("status") ?? "";

  useEffect(() => {
    setJobs(null);
    api<JobRow[]>(withQuery("/workspace/jobs", { status }))
      .then(setJobs)
      .catch((err) => setError(err.message));
  }, [status]);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Jobs</h1>
          <p>The roles you are hiring for, and how far each one has got.</p>
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

      <div className="tabs glass" role="tablist">
        {[
          { value: "", label: "All" },
          { value: "published", label: "Published" },
          { value: "draft", label: "Drafts" },
        ].map((tab) => (
          <button
            key={tab.value || "all"}
            role="tab"
            aria-selected={status === tab.value}
            onClick={() => setParams(tab.value ? { status: tab.value } : {}, { replace: true })}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {error && <p className="error">{error}</p>}

      {jobs === null ? (
        <div className="card glass">
          <div className="skeleton" />
          <div className="skeleton" />
        </div>
      ) : jobs.length === 0 ? (
        <div className="card glass">
          <Empty
            title={status ? "No jobs here" : "No jobs yet"}
            action={
              <Link className="button" to="/jd-chat">
                Write one with AI
              </Link>
            }
          >
            A job profile holds the requirements every CV is checked against. Write one yourself,
            or describe the role and let the AI draft it.
          </Empty>
        </div>
      ) : (
        <div className="tile-grid">
          {jobs.map((job) => (
            <Link className="tile-card" to={`/jobs/${job.id}/candidates`} key={job.id}>
              <span className="tile-date">
                {shortDate(job.created_at)}
                <span className={job.status === "published" ? "badge pass" : "badge"}>
                  {job.status === "published" ? "Published" : "Draft"}
                </span>
              </span>

              <h2>{job.title}</h2>

              <span className="tile-label">Required skills</span>
              <div className="chips">
                {job.required_skills.slice(0, 4).map((skill) => (
                  <span className="chip" key={skill}>
                    {skill}
                  </span>
                ))}
                {job.required_skills.length > 4 && (
                  <span className="chip">+{job.required_skills.length - 4}</span>
                )}
              </div>

              {job.waiting > 0 && (
                <p className="tile-flag">
                  {job.waiting} CV{job.waiting === 1 ? "" : "s"} waiting to be screened
                </p>
              )}

              <div className="tile-foot">
                <div className="job-numbers">
                  <div>
                    <strong>{job.candidates}</strong>
                    CVs
                  </div>
                  <div>
                    <strong>{job.screened}</strong>
                    screened
                  </div>
                  <div>
                    <strong>{job.interviews}</strong>
                    interviews
                  </div>
                  <div>
                    <strong>{job.top_score ?? "—"}</strong>
                    top score
                  </div>
                </div>
                <span className="go" aria-hidden="true">
                  <Icon name="forward" />
                </span>
              </div>
            </Link>
          ))}
        </div>
      )}
    </>
  );
}
