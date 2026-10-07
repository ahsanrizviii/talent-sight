import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import type { PublicJobSummary } from "../types";

export default function CareersPage() {
  const [jobs, setJobs] = useState<PublicJobSummary[] | null>(null);

  useEffect(() => {
    api<PublicJobSummary[]>("/public/jobs")
      .then(setJobs)
      .catch(() => setJobs([]));
  }, []);

  return (
    <main className="content">
      <h1>Careers</h1>

      {jobs === null && <p className="muted">Loading...</p>}

      {jobs?.length === 0 && (
        <p className="muted">There are no open positions right now.</p>
      )}

      {jobs?.map((job) => (
        <div className="card" key={job.slug}>
          <h2>
            <Link to={`/careers/${job.slug}`}>{job.title}</Link>
          </h2>
          <p className="muted">
            Minimum experience: {job.min_experience_years} years
          </p>
        </div>
      ))}
    </main>
  );
}