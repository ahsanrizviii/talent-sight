import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import Icon from "../components/Icon";
import JobPostBody from "../components/JobPostBody";
import { LoadError, Loading } from "../components/PageState";
import type { Job, PublicJob } from "../types";

// Step 1 of the pipeline: the job as it is posted on the blog, with Edit on top.
export default function JobPostPage() {
  const { id } = useParams();
  const [job, setJob] = useState<Job | null>(null);
  const [apply, setApply] = useState<PublicJob | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<Job>(`/jobs/${id}`)
      .then((found) => {
        setJob(found);
        // The apply details (form link, careers e-mail) are the ones the blog post shows.
        if (found.status === "published" && found.slug) {
          api<PublicJob>(`/public/jobs/${found.slug}`).then(setApply).catch(() => setApply(null));
        }
      })
      .catch((err) => setError(err.message));
  }, [id]);

  if (error) return <LoadError message={error} back={`/jobs/${id}/candidates`} backLabel="Back to the job" />;
  if (!job) return <Loading label="Loading the job post…" />;

  const published = job.status === "published" && job.slug;

  return (
    <>
      <Link className="back-link" to={`/jobs/${id}/candidates`}>
        <Icon name="back" />
        Back to the job
      </Link>

      <div className="page-head">
        <div>
          <h1>Job post</h1>
          <p>{published ? "The job as it is posted on the blog for candidates." : "A preview. Candidates cannot see this job yet."}</p>
        </div>
        <div className="row">
          <Link className="button" to={`/jobs/${id}`}>
            Edit the job
          </Link>
          {job.blog_url && (
            <a className="button quiet" href={job.blog_url} target="_blank" rel="noreferrer">
              Blog post ↗
            </a>
          )}
        </div>
      </div>

      <div className="post-status">
        <span className={published ? "badge pass" : "badge warn"}>{published ? "Published" : "Draft"}</span>
        <span className="muted small">Created {new Date(job.created_at).toLocaleDateString([], { day: "numeric", month: "short", year: "numeric" })}</span>
      </div>

      {!published && (
        <div className="notice">Publish the job from the edit page to post it on the blog.</div>
      )}

      <div className="card glass">
        <JobPostBody job={job} apply={apply} />
      </div>
    </>
  );
}
