import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import JobPostView from "../components/JobPostView";
import type { PublicJob } from "../types";

export default function JobPostPage() {
  const { slug } = useParams();
  const [job, setJob] = useState<PublicJob | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<PublicJob>(`/public/jobs/${slug}`)
      .then(setJob)
      .catch((err) => setError(err.message));
  }, [slug]);

  return (
    <main className="content">
      <p>
        <Link to="/careers">All open positions</Link>
      </p>

      {error && <p className="error">{error}</p>}

    {job && (
    <div className="card">
        <JobPostView {...job} />
        <p className="muted">
        Demo vacancy from the TalentSight training project. This is not a real job opening.
        </p>
        <h3>How to apply</h3>
        <p>
        Send your CV to{" "}
        <a href={`mailto:${job.apply_email}`}>{job.apply_email}</a>.
        </p>
    </div>
    )}
    </main>
  );
}