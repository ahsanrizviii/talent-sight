import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import type { CandidateDetail } from "../types";

// The interviewer's side panel during the interview (Task 7.3.2): who they are talking to,
// how the CV scored, and the highlights worth asking about. It is only used on the interviewer's
// page and it reads an interviewer-only endpoint, so a candidate can never see it (N9).
export default function CandidatePanel({ candidateId }: { candidateId: number }) {
  const [candidate, setCandidate] = useState<CandidateDetail | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<CandidateDetail>(`/candidates/${candidateId}`)
      .then(setCandidate)
      .catch((err) => setError(err.message));
  }, [candidateId]);

  if (error) return <aside className="card glass panel"><p className="error small">{error}</p></aside>;
  if (!candidate) return <aside className="card glass panel"><p className="muted small">Loading profile...</p></aside>;

  const profile = candidate.profile;
  const roles = (profile.work_history ?? []).slice(0, 2);
  const degree = profile.education?.[0];

  return (
    <aside className="card glass panel">
      <h2>{candidate.name || candidate.cv_filename}</h2>
      <p className="muted small">{candidate.email || "No e-mail"}</p>
      <p className="muted small">{candidate.phone || "No phone number"}</p>

      <h3>Before the interview</h3>
      {candidate.score ? (
        <>
          <div className="row panel-score">
            <span className="score-total">{candidate.score.overall}</span>
            <span className="muted small">out of 100</span>
          </div>
          {candidate.score.dimensions.map((d) => (
            <div className="panel-dimension" key={d.dimension}>
              <div className="panel-dimension-head">
                <span>{d.label}</span>
                <span className="muted">{d.score}</span>
              </div>
              <div className="bar">
                <div style={{ width: `${d.score}%` }} />
              </div>
            </div>
          ))}
          <p className="muted small">
            Requirements: {candidate.met} met · {candidate.partially_met} partly · {candidate.unmet} unmet
          </p>
        </>
      ) : (
        <p className="muted small">This candidate has not been scored.</p>
      )}

      <h3>CV highlights</h3>
      <p className="small">{profile.total_experience_years ?? 0} years of experience</p>
      {!!profile.skills?.length && (
        <div className="chips">
          {profile.skills.slice(0, 10).map((skill) => (
            <span className="badge" key={skill}>
              {skill}
            </span>
          ))}
        </div>
      )}
      {roles.length > 0 && (
        <ul className="small">
          {roles.map((role, i) => (
            <li key={i}>
              <strong>{role.title}</strong>, {role.company}
            </li>
          ))}
        </ul>
      )}
      {degree && (
        <p className="small">
          {degree.degree}, {degree.institution}
        </p>
      )}
      {!!profile.certifications?.length && <p className="small muted">Certifications: {profile.certifications.slice(0, 3).join(", ")}</p>}

      <p className="small">
        <Link to={`/candidates/${candidate.id}`} target="_blank">
          Open the full profile
        </Link>
      </p>
    </aside>
  );
}