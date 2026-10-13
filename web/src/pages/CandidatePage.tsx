import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api } from "../api";
import Avatar from "../components/Avatar";
import CvViewer from "../components/CvViewer";
import Icon from "../components/Icon";
import InterviewCard from "../components/InterviewCard";
import ScorePanel from "../components/ScorePanel";
import StageBadge from "../components/StageBadge";
import VerdictBadge from "../components/VerdictBadge";
import type { CandidateDetail, PersonRow } from "../types";
import { shortDate } from "../when";

type Tab = "score" | "requirements" | "interview" | "cv";

const KIND_LABELS = {
  skill: "Required skill",
  qualification: "Qualification",
  experience: "Experience",
  preferred: "Preferred skill",
};

// One candidate, everything about them, in four tabs: the score and why, the requirements
// one by one, the interview and its transcript, and the CV as it arrived.
export default function CandidatePage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [candidate, setCandidate] = useState<CandidateDetail | null>(null);
  const [neighbours, setNeighbours] = useState<PersonRow[]>([]);
  const [tab, setTab] = useState<Tab>("score");
  const [error, setError] = useState("");

  useEffect(() => {
    setCandidate(null);
    setTab("score");
    api<CandidateDetail>(`/candidates/${id}`)
      .then(setCandidate)
      .catch((err) => setError(err.message));
  }, [id]);

  // The other candidates for the same job, so a reviewer can go through a shortlist in order.
  useEffect(() => {
    if (!candidate) return;
    api<PersonRow[]>(`/workspace/candidates?job_id=${candidate.job_profile_id}`)
      .then(setNeighbours)
      .catch(() => undefined);
  }, [candidate?.job_profile_id]);

  async function remove() {
    if (!candidate || !window.confirm("Delete this candidate, their CV and all their results?")) return;
    try {
      await api(`/candidates/${id}`, { method: "DELETE" });
      navigate(`/jobs/${candidate.job_profile_id}/candidates`);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  if (error) return <p className="error">{error}</p>;
  if (!candidate) {
    return (
      <div className="card">
        <div className="skeleton" />
        <div className="skeleton" />
      </div>
    );
  }

  const profile = candidate.profile;
  const hasProfile = !!profile.skills;
  const here = neighbours.findIndex((person) => person.id === candidate.id);
  const previous = here > 0 ? neighbours[here - 1] : null;
  const next = here >= 0 && here < neighbours.length - 1 ? neighbours[here + 1] : null;
  const me = here >= 0 ? neighbours[here] : null;

  const TABS: { value: Tab; label: string }[] = [
    { value: "score", label: "Score" },
    { value: "requirements", label: `Requirements (${candidate.verdicts.length})` },
    { value: "interview", label: "Interview" },
    { value: "cv", label: "CV" },
  ];

  return (
    <>
      <Link className="back-link" to={`/jobs/${candidate.job_profile_id}/candidates`}>
        <Icon name="back" />
        All candidates for this job
      </Link>

      <div className="page-head">
        <div className="who" style={{ alignItems: "flex-start", gap: 16 }}>
          <Avatar name={candidate.name || candidate.cv_filename} big />
          <div>
          <h1>{candidate.name || candidate.cv_filename}</h1>
          <p>
            {[candidate.email, candidate.phone].filter(Boolean).join("  ·  ") || "No contact details in the CV"}
          </p>
          <div className="row" style={{ gap: 10, marginTop: 8 }}>
            {me && <StageBadge stage={me.stage} />}
            {me?.rank !== null && me?.rank !== undefined && (
              <span className="badge accent">#{me.rank} for this job</span>
            )}
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

      {candidate.status === "excluded" && (
        <div className="card notice">
          <strong>Excluded.</strong> {candidate.exclusion_reason}
        </div>
      )}
      {candidate.error && <div className="card notice stop">{candidate.error}</div>}

      <div className="tabs" role="tablist">
        {TABS.map((item) => (
          <button key={item.value} role="tab" aria-selected={tab === item.value} onClick={() => setTab(item.value)}>
            {item.label}
          </button>
        ))}
      </div>

      {tab === "score" &&
        (candidate.score ? (
          <div className="split">
            <ScorePanel score={candidate.score} />
            <div className="card">
              <h2>What the AI read from the CV</h2>
              {!hasProfile ? (
                <p className="muted">Not screened yet.</p>
              ) : (
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
                        <strong>{job.title}</strong>, {job.company} ({[job.start, job.end].filter(Boolean).join(" – ")}).{" "}
                        {job.summary}
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
              )}
            </div>
          </div>
        ) : (
          <div className="card">
            <p className="muted">
              No score yet. Run the screening for this job and the four dimensions appear here with the
              reasoning behind each one.
            </p>
            <Link className="button secondary" to={`/jobs/${candidate.job_profile_id}/candidates`}>
              Go to screening
            </Link>
          </div>
        ))}

      {tab === "requirements" && (
        <div className="card flush">
          {candidate.verdicts.length === 0 ? (
            <p className="muted" style={{ padding: 18 }}>
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
        </div>
      )}

      {tab === "interview" && <InterviewCard candidateId={candidate.id} candidateStatus={candidate.status} />}

      {tab === "cv" && (
        <CvViewer candidateId={candidate.id} filename={candidate.cv_filename} text={candidate.cv_text} />
      )}

      <div className="card">
        <div className="row between">
          <div>
            <h2>Delete this candidate</h2>
            <p className="muted small" style={{ margin: 0 }}>
              Their CV file, score, requirement verdicts and interview transcript all go with them. This
              cannot be undone.
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
