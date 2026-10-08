import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "../api";
import Arrow from "../components/Arrow";
import JobPostView from "../components/JobPostView";
import PublicFrame from "../components/PublicFrame";
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
    <PublicFrame>
      <main className="content narrow post-page">
        <Link className="back-link" to="/careers">
          ← All open positions
        </Link>

        {error && <p className="error">{error}</p>}
        {!job && !error && <p className="muted">Loading...</p>}

        {job && (
          <article className="card">
            <JobPostView {...job} />

            <h3>How to apply</h3>

            {job.apply_url ? (
              <>
                <p>
                  <a
                    className="button arrow"
                    href={job.apply_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Apply now <Arrow />
                  </a>
                </p>
                <p className="muted small">
                  The application form asks you to sign in with Google, then upload
                  your CV as PDF or DOCX.
                </p>
              </>
            ) : (
              <p>
                Send your CV to{" "}
                <a href={`mailto:${job.apply_email}`}>{job.apply_email}</a>.
              </p>
            )}

            <p className="demo-note">
              Demo vacancy from the TalentSight training project. This is not a real
              job opening.
            </p>
          </article>
        )}
      </main>
    </PublicFrame>
  );
}