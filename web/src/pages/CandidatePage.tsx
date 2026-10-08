import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api } from "../api";
import VerdictBadge from "../components/VerdictBadge";
import type { CandidateDetail } from "../types";

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
      !window.confirm(
        "Delete this candidate, their CV and all their results?"
      )
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
        {" · "}
        {candidate.cv_filename}
        {candidate.text_method === "ocr" && " (read with OCR)"}
      </p>

      {candidate.status === "excluded" && (
        <div className="card notice">
          Excluded. {candidate.exclusion_reason}
        </div>
      )}
      {candidate.error && (
        <div className="card notice error">{candidate.error}</div>
      )}

      {candidate.verdicts.length > 0 && (
        <div className="card">
          <h2>Requirements</h2>
          <table>
            <thead>
              <tr>
                <th>Requirement</th>
                <th>Verdict</th>
                <th>Why</th>
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

      {profile.skills && (
        <div className="card">
          <h2>Profile</h2>
          <p className="muted">
            Total experience: {profile.total_experience_years ?? 0} years
          </p>

          <h3>Skills</h3>
          <p>{profile.skills.join(", ") || "—"}</p>

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
        </div>
      )}

      <button className="button danger" onClick={remove}>
        Delete candidate
      </button>
    </>
  );
}