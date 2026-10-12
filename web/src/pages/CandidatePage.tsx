import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api } from "../api";
import CvViewer from "../components/CvViewer";
import ScorePanel from "../components/ScorePanel";
import VerdictBadge from "../components/VerdictBadge";
import type { CandidateDetail } from "../types";
import InterviewCard from "../components/InterviewCard";

const KIND_LABELS = {
  skill: "Required skill",
  qualification: "Qualification",
  experience: "Experience",
  preferred: "Preferred skill",
};

export default function CandidatePage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [candidate, setCandidate] = useState<CandidateDetail | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<CandidateDetail>(`/candidates/${id}`)
      .then(setCandidate)
      .catch((err) => setError(err.message));
  }, [id]);

  async function remove() {
    if (
      !candidate ||
      !window.confirm("Delete this candidate, their CV and all their results?")
    )
      return;
    try {
      await api(`/candidates/${id}`, { method: "DELETE" });
      navigate(`/jobs/${candidate.job_profile_id}/candidates`);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  if (error) return <p className="error">{error}</p>;
  if (!candidate) return <p className="muted">Loading...</p>;

  const profile = candidate.profile;
  const hasProfile = !!profile.skills;

  return (
    <>
      <p>
        <Link
          className="back-link"
          to={`/jobs/${candidate.job_profile_id}/candidates`}
        >
          ← All candidates
        </Link>
      </p>

      <h1>{candidate.name || candidate.cv_filename}</h1>

      <p className="muted">
        {[candidate.email, candidate.phone].filter(Boolean).join(" · ") ||
          "No contact details found"}
        {candidate.text_method === "ocr" && " · CV read with OCR"}
        {" · "}
        {candidate.source === "google_form" ? "Applied through the Google Form" : "Uploaded"}
      </p>

      {candidate.status === "excluded" && (
        <div className="card notice">Excluded. {candidate.exclusion_reason}</div>
      )}
      {candidate.error && (
        <div className="card notice error">{candidate.error}</div>
      )}

      {candidate.score && <ScorePanel score={candidate.score} />}
      
      <InterviewCard candidateId={candidate.id} candidateStatus={candidate.status} />

      {candidate.verdicts.length > 0 && (
        <div className="card">
          <h2>Requirements</h2>
          <p className="muted small">
            Each requirement of the job, checked against the CV by meaning, with the evidence the AI found.
          </p>
          <table>
            <thead>
              <tr>
                <th>Requirement</th>
                <th>Verdict</th>
                <th>Evidence</th>
              </tr>
            </thead>
            <tbody>
              {candidate.verdicts.map((v) => (
                <tr key={v.requirement}>
                  <td>
                    {v.requirement}
                    <div className="muted small">
                      {KIND_LABELS[v.kind]}
                      {v.mandatory && " · mandatory"}
                    </div>
                  </td>
                  <td>
                    <VerdictBadge verdict={v.verdict} />
                  </td>
                  <td className="small">{v.explanation}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="split">
        <CvViewer
          candidateId={candidate.id}
          filename={candidate.cv_filename}
          text={candidate.cv_text}
        />

        <div className="card">
          <h2>What the AI read from the CV</h2>
          {!hasProfile ? (
            <p className="muted">Not screened yet.</p>
          ) : (
            <>
              <p className="muted">
                Total experience: {profile.total_experience_years ?? 0} years
              </p>

              <h3>Skills</h3>
              <p>{profile.skills?.join(", ") || "—"}</p>

              <h3>Work history</h3>
              <ul>
                {profile.work_history?.map((w, i) => (
                  <li key={i}>
                    <strong>{w.title}</strong>, {w.company} (
                    {[w.start, w.end].filter(Boolean).join(" – ")}). {w.summary}
                  </li>
                ))}
              </ul>

              <h3>Education</h3>
              <ul>
                {profile.education?.map((e, i) => (
                  <li key={i}>
                    {e.degree}, {e.institution} {e.year && `(${e.year})`}
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
                    {profile.projects.map((p, i) => (
                      <li key={i}>
                        <strong>{p.name}</strong>: {p.summary}
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </>
          )}
        </div>
      </div>

      <button className="button danger" onClick={remove}>
        Delete candidate
      </button>
    </>
  );
}