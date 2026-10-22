import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import type { CandidateRow, Job } from "../types";

type Step = {
  label: string;
  done: boolean;
  value: string;
  note: string;
  to?: string;
  href?: string;
};

// The hiring pipeline of one job, step by step:
// job description -> posted -> CVs collected -> screened -> ranked.
// Pass `candidates` when the page already has them; otherwise they are loaded here.
export default function JobPipeline({
  job,
  candidates,
}: {
  job: Job;
  candidates?: CandidateRow[];
}) {
  const [loaded, setLoaded] = useState<CandidateRow[]>([]);

  useEffect(() => {
    if (candidates) return;
    api<CandidateRow[]>(`/jobs/${job.id}/candidates`)
      .then(setLoaded)
      .catch(() => setLoaded([]));
  }, [job.id, candidates]);

  const list = candidates ?? loaded;
  const fromForm = list.filter((c) => c.source === "google_form").length;
  const ranked = list.filter((c) => c.status === "screened");
  const excluded = list.filter((c) => c.status === "excluded").length;
  const screened = ranked.length + excluded;
  const top = ranked.find((c) => c.rank === 1) ?? ranked[0];
  const candidatesPage = `/jobs/${job.id}/candidates`;
  const published = job.status === "published";

  const steps: Step[] = [
    {
      label: "Job description",
      done: job.description.trim().length > 0,
      value: job.description.trim() ? "Written" : "Empty",
      note: `${job.required_skills.length} required skills · min ${job.min_experience_years} years`,
      to: `/jobs/${job.id}/post`,
    },
    {
      label: "Posted",
      done: published,
      value: !published ? "Not yet" : job.blog_url ? "On the blog ↗" : "Published",
      note: job.blog_url ? "Open the blog post ↗" : published ? "Published" : "Publish the job to post it",
      href: job.blog_url ?? undefined,
    },
    {
      label: "CVs",
      done: list.length > 0,
      value: `${list.length} received`,
      note: `${list.length - fromForm} uploaded · ${fromForm} from the Google Form`,
      to: `/jobs/${job.id}/cvs`,
    },
    {
      label: "Screened",
      done: screened > 0,
      value: `${screened} of ${list.length}`,
      note: `${excluded} excluded on a mandatory requirement`,
      to: candidatesPage,
    },
    {
      label: "Ranked",
      done: ranked.length > 0,
      value: top ? `Top: ${top.name || top.cv_filename}` : `${ranked.length} ranked`,
      note: top
        ? `Top: ${top.name || top.cv_filename}${top.overall !== null ? ` (${top.overall})` : ""}`
        : "No ranked candidates yet",
      to: candidatesPage,
    },
  ];

  // One thin strip instead of five big tiles: each step is a dot (a tick when done), its name and
  // its value. The longer note is the step's tooltip.
  return (
    <ol className="steps glass" aria-label="Hiring pipeline">
      {steps.map((step, index) => {
        const body = (
          <>
            <span className="step-dot" aria-hidden="true">
              {step.done ? "✓" : index + 1}
            </span>
            <span className="step-text">
              <strong>{step.label}</strong>
              <span>{step.value}</span>
            </span>
          </>
        );
        return (
          <li key={step.label} className={step.done ? "done" : ""} title={step.note}>
            {step.href ? (
              <a href={step.href} target="_blank" rel="noreferrer">
                {body}
              </a>
            ) : step.to ? (
              <Link to={step.to}>{body}</Link>
            ) : (
              <div>{body}</div>
            )}
          </li>
        );
      })}
    </ol>
  );
}
