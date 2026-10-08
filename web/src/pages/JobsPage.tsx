import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api";
import type { Job } from "../types";

export default function JobsPage() {
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<Job[]>("/jobs")
      .then(setJobs)
      .catch((err) => setError(err.message));
  }, []);

  return (
    <>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h1>Job profiles</h1>
        <div className="row">
          <Link className="button secondary" to="/jobs/new">
            New job
          </Link>
          <Link className="button" to="/jd-chat">
            Write a job with AI
          </Link>
        </div>
      </div>

      {error && <p className="error">{error}</p>}
      {jobs === null && !error && <p className="muted">Loading...</p>}

      {jobs?.length === 0 && (
        <div className="card muted">
          No jobs yet. Create one, or let the AI write one.
        </div>
      )}

      {jobs && jobs.length > 0 && (
        <div className="card">
          <table>
            <thead>
              <tr>
                <th>Title</th>
                <th>Status</th>
                <th>Required skills</th>
                <th>Candidates</th>
                <th>Public page</th>
                <th>Blog</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => (
                <tr key={job.id}>
                  <td>
                    <Link to={`/jobs/${job.id}`}>{job.title}</Link>
                  </td>
                  <td>
                    <span className="badge">{job.status}</span>
                  </td>
                  <td>{job.required_skills.join(", ")}</td>
                  <td>
                    <Link to={`/jobs/${job.id}/candidates`}>Open</Link>
                  </td>
                  <td>
                    {job.slug ? (
                      <a
                        href={`/careers/${job.slug}`}
                        target="_blank"
                        rel="noreferrer"
                      >
                        Open
                      </a>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td>
                    {job.blog_url ? (
                      <a href={job.blog_url} target="_blank" rel="noreferrer">
                        View on blog
                      </a>
                    ) : (
                      "—"
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}