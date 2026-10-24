import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { api } from "../api";
import AssessmentPanel from "../components/AssessmentPanel";
import Avatar from "../components/Avatar";
import Breadcrumbs from "../components/Breadcrumbs";
import ClaimCheckPanel from "../components/ClaimCheckPanel";
import CvViewer from "../components/CvViewer";
import Icon from "../components/Icon";
import InterviewCard from "../components/InterviewCard";
import LitmusPanel from "../components/LitmusPanel";
import { LoadError, Loading } from "../components/PageState";
import ScorePanel from "../components/ScorePanel";
import StageBadge from "../components/StageBadge";
import VerdictBadge from "../components/VerdictBadge";
import type { CandidateDetail, PersonRow } from "../types";
import { shortDate } from "../when";

// Three tabs: what the CV says and how it scored, the interviews (one per round), and the report
// that brings them together. Each interview's analysis is on the Results page, and the first-day
// identity check on the Identity check page.
type Tab = "cv" | "interview" | "report";

const TABS: { value: Tab; label: string }[] = [
  { value: "cv", label: "Score & CV" },
  { value: "interview", label: "Interviews" },
  { value: "report", label: "Report" },
];

// Links made before the tabs were grouped (?tab=assessment, ?tab=litmus...) still open the right place:
// the tab that now holds it, scrolled to its section.
const LINKS: Record<string, { tab: Tab; section?: string }> = {
  cv: { tab: "cv" },
  score: { tab: "cv" },
  requirements: { tab: "cv", section: "requirements" },
  litmus: { tab: "cv", section: "litmus" },
  file: { tab: "cv", section: "cv-file" },
  interview: { tab: "interview" },
  report: { tab: "report" },
  assessment: { tab: "report" },
  claims: { tab: "report", section: "claims" },
  onboarding: { tab: "report" },
};

const KIND_LABELS = {
  skill: "Required skill",
  qualification: "Qualification",
  experience: "Experience",
  preferred: "Preferred skill",
};

const NOT_INVITABLE = ["uploaded", "queued", "unreadable", "failed", "excluded"];

export default function CandidatePage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const asked = LINKS[params.get("tab") ?? ""] ?? LINKS.cv;
  const [candidate, setCandidate] = useState<CandidateDetail | null>(null);
  const [neighbours, setNeighbours] = useState<PersonRow[]>([]);
  const [tab, setTab] = useState<Tab>(asked.tab);
  const [error, setError] = useState("");

  useEffect(() => {
    setCandidate(null);
    setTab(asked.tab);
    api<CandidateDetail>(`/candidates/${id}`)
      .then(setCandidate)
      .catch((err) => setError(err.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  // Everyone else who applied for the same job, best first, so a reviewer can go through them in order.
  useEffect(() => {
    if (!candidate) return;
    api<PersonRow[]>(`/workspace/candidates?job_id=${candidate.job_profile_id}&stage=all`)
      .then(setNeighbours)
      .catch(() => undefined);
  }, [candidate?.job_profile_id]);

  // A link that points to one section (for example ?tab=litmus) scrolls to it once the page is drawn.
  useEffect(() => {
    if (!candidate || !asked.section) return;
    const timer = window.setTimeout(
      () => document.getElementById(asked.section ?? "")?.scrollIntoView({ behavior: "smooth", block: "start" }),
      150,
    );
    return () => window.clearTimeout(timer);
  }, [candidate, asked.section]);

  async function remove() {
    if (!candidate || !window.confirm("Delete this candidate, their CV and all their results?")) return;
    try {
      await api(`/candidates/${id}`, { method: "DELETE" });
      navigate(`/jobs/${candidate.job_profile_id}/candidates`);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  if (!candidate) {
    return error ? (
      <LoadError message={error} back="/candidates" backLabel="Back to candidates" />
    ) : (
      <Loading label="Loading the candidate…" />
    );
  }

  const profile = candidate.profile;
  const hasProfile = !!profile.skills;
  const here = neighbours.findIndex((person) => person.id === candidate.id);
  const previous = here > 0 ? neighbours[here - 1] : null;
  const next = here >= 0 && here < neighbours.length - 1 ? neighbours[here + 1] : null;
  const me = here >= 0 ? neighbours[here] : null;
  const name = candidate.name || candidate.cv_filename;

  return (
    <>
      <Breadcrumbs
        items={[
          { label: "Jobs", to: "/jobs" },
          { label: me?.job_title ?? "This job", to: `/jobs/${candidate.job_profile_id}/candidates` },
          { label: name },
        ]}
      />

      <div className="page-head">
        <div className="who" style={{ alignItems: "flex-start", gap: 16 }}>
          <Avatar name={name} big />
          <div>
            <h1>{name}</h1>
            <p>{[candidate.email, candidate.phone].filter(Boolean).join("  ·  ") || "No contact details in the CV"}</p>
            <div className="row" style={{ gap: 10, marginTop: 8 }}>
              {me && <StageBadge stage={me.stage} />}
              {me?.rank !== null && me?.rank !== undefined && <span className="badge accent">#{me.rank} for this job</span>}
              {candidate.overall !== null && <span className="badge">Score {candidate.overall}</span>}
              <span className="badge">
                {candidate.source === "google_form" ? "Google Form" : "Uploaded"} · {shortDate(candidate.created_at)}
              </span>
              {candidate.text_method === "ocr" && <span className="badge warn">Read with OCR</span>}
            </div>
          </div>
        </div>

        <div className="row">
          {previous && (
            <Link className="button quiet small" to={`/candidates/${previous.id}`}>
              <Icon name="back" />
              {previous.name}
            </Link>
          )}
          {next && (
            <Link className="button secondary small" to={`/candidates/${next.id}`}>
              Next: {next.name}
            </Link>
          )}
        </div>
      </div>

      {error && <p className="error">{error}</p>}
      {candidate.status === "excluded" && (
        <div className="card notice">
          <strong>Excluded.</strong> {candidate.exclusion_reason}
        </div>
      )}
      {candidate.error && <div className="card notice stop">{candidate.error}</div>}

      <div className="tabs glass" role="tablist">
        {TABS.map((item) => (
          <button key={item.value} role="tab" aria-selected={tab === item.value} onClick={() => setTab(item.value)}>
            {item.label}
          </button>
        ))}
      </div>

      {tab === "cv" && (
        <>
          {candidate.score ? (
            <div className="split">
              <ScorePanel score={candidate.score} />
              <div className="card glass">
                <h2>What the AI read from the CV</h2>
                {!hasProfile ? <p className="muted">Not screened yet.</p> : <ProfileSummary profile={profile} />}
              </div>
            </div>
          ) : (
            <div className="card glass">
              <h2>Score</h2>
              <p className="muted">
                {candidate.status === "excluded"
                  ? "Excluded candidates are not scored: a must-have requirement is missing (see the requirements below)."
                  : "No score yet. Run the screening for this job and the four dimensions appear here with the reasoning behind each one."}
              </p>
              {candidate.status !== "excluded" && (
                <Link className="button secondary" to={`/jobs/${candidate.job_profile_id}/candidates`}>
                  Go to screening
                </Link>
              )}
            </div>
          )}

          <section id="requirements" className="card glass flush">
            <div className="card-head">
              <h2>Requirements</h2>
              <span className="result-count">{candidate.verdicts.length}</span>
            </div>
            {candidate.verdicts.length === 0 ? (
              <p className="muted" style={{ padding: "0 22px 18px" }}>
                The requirements are checked during screening. Nothing has been checked for this candidate yet.
              </p>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>Requirement</th>
                    <th>Verdict</th>
                    <th>Evidence found in the CV</th>
                  </tr>
                </thead>
                <tbody>
                  {candidate.verdicts.map((verdict, index) => (
                    <tr key={`${verdict.requirement}-${index}`}>
                      <td>
                        {verdict.requirement}
                        <span className="cell-sub">
                          {KIND_LABELS[verdict.kind]}
                          {verdict.mandatory && " · must have"}
                        </span>
                      </td>
                      <td>
                        <VerdictBadge verdict={verdict.verdict} />
                      </td>
                      <td className="small muted">{verdict.explanation}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          {hasProfile && (
            <section id="litmus">
              <LitmusPanel candidateId={candidate.id} />
            </section>
          )}

          <section id="cv-file">
            <CvViewer candidateId={candidate.id} filename={candidate.cv_filename} text={candidate.cv_text} />
          </section>
        </>
      )}

      {tab === "interview" && (
        <>
          {NOT_INVITABLE.includes(candidate.status) && (
            <div className="card glass">
              <p className="muted" style={{ margin: 0 }}>
                {candidate.status === "excluded"
                  ? "This candidate did not pass screening, so no interview can be booked."
                  : "Screen this candidate first. Candidates who pass screening can be invited from here."}
              </p>
            </div>
          )}
          <InterviewCard candidateId={candidate.id} candidateStatus={candidate.status} />
        </>
      )}

      {tab === "report" && (
        <>
          <AssessmentPanel candidateId={candidate.id} />
          <section id="claims">
            <ClaimCheckPanel candidateId={candidate.id} />
          </section>
        </>
      )}

      <div className="card glass danger-zone">
        <div className="row between">
          <div>
            <h2>Delete this candidate</h2>
            <p className="muted small" style={{ margin: 0 }}>
              Their CV file, score, requirement verdicts and interview transcript all go with them. This cannot be undone.
            </p>
          </div>
          <button className="button danger" onClick={remove}>
            Delete candidate
          </button>
        </div>
      </div>
    </>
  );
}

// What the AI read from the CV: experience, skills, work, education and the rest, as plain lists.
function ProfileSummary({ profile }: { profile: CandidateDetail["profile"] }) {
  return (
    <>
      <p className="muted">Total experience: {profile.total_experience_years ?? 0} years</p>

      <h3>Skills</h3>
      <div className="chips">
        {profile.skills?.length ? (
          profile.skills.map((skill, index) => (
            <span className="chip" key={index}>
              {skill}
            </span>
          ))
        ) : (
          <span className="muted">Nothing listed</span>
        )}
      </div>

      <h3>Work history</h3>
      <ul>
        {profile.work_history?.map((job, index) => (
          <li key={index}>
            <strong>{job.title}</strong>, {job.company} ({[job.start, job.end].filter(Boolean).join(" – ")}). {job.summary}
          </li>
        ))}
      </ul>

      <h3>Education</h3>
      <ul>
        {profile.education?.map((school, index) => (
          <li key={index}>
            {school.degree}, {school.institution} {school.year && `(${school.year})`}
          </li>
        ))}
      </ul>

      {!!profile.languages?.length && (
        <>
          <h3>Languages</h3>
          <p>{profile.languages.join(", ")}</p>
        </>
      )}

      {!!profile.certifications?.length && (
        <>
          <h3>Certifications</h3>
          <p>{profile.certifications.join(", ")}</p>
        </>
      )}

      {!!profile.projects?.length && (
        <>
          <h3>Projects</h3>
          <ul>
            {profile.projects.map((project, index) => (
              <li key={index}>
                <strong>{project.name}</strong>: {project.summary}
              </li>
            ))}
          </ul>
        </>
      )}
    </>
  );
}
