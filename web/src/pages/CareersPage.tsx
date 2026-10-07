import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import Arrow from "../components/Arrow";
import PublicFrame from "../components/PublicFrame";
import type { PublicJobSummary } from "../types";

export default function CareersPage() {
  const [jobs, setJobs] = useState<PublicJobSummary[] | null>(null);

  useEffect(() => {
    api<PublicJobSummary[]>("/public/jobs")
      .then(setJobs)
      .catch(() => setJobs([]));
  }, []);

  return (
    <PublicFrame>
      <section className="hero hero-short">
        <p className="eyebrow">Careers</p>
        <h1 className="display">Find your next role.</h1>
        <p className="lead">Open positions, published by our hiring team.</p>
      </section>

      <main className="content">
        {jobs === null && <p className="muted center">Loading...</p>}

        {jobs?.length === 0 && (
          <div className="card muted center">There are no open positions right now.</div>
        )}

        <div className="job-grid">
          {jobs?.map((job) => (
            <Link className="card job-card" key={job.slug} to={`/careers/${job.slug}`}>
              <h2>{job.title}</h2>
              <p className="muted">Minimum experience: {job.min_experience_years} years</p>
              <span className="card-more">
                View role <Arrow />
              </span>
            </Link>
          ))}
        </div>
      </main>
    </PublicFrame>
  );
}
