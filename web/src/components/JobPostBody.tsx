import JobPostView from "./JobPostView";

type Post = {
  title: string;
  description: string;
  required_skills: string[];
  preferred_skills: string[];
  qualifications: string[];
  min_experience_years: number;
};

type Apply = { apply_email: string; apply_url: string | null } | null;

// The job post exactly as a candidate reads it, with the "how to apply" part at the end.
// Shown to the hiring team on JobPostPage: the same text and apply details as the blog post.
export default function JobPostBody({ job, apply }: { job: Post; apply: Apply }) {
  return (
    <article className="job-post">
      <JobPostView {...job} />
      {apply && (apply.apply_url || apply.apply_email) && (
        <section className="apply-box">
          <h3>How to apply</h3>
          {apply.apply_url ? (
            <>
              <p className="muted">Fill in the short online form and attach your CV (PDF or DOCX).</p>
              <a className="button" href={apply.apply_url} target="_blank" rel="noreferrer">
                Apply with the online form ↗
              </a>
            </>
          ) : (
            <p>
              Send your CV to <a href={`mailto:${apply.apply_email}`}>{apply.apply_email}</a> with the job title in the subject.
            </p>
          )}
        </section>
      )}
    </article>
  );
}
