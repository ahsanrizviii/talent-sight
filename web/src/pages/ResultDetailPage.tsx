import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "../api";
import Avatar from "../components/Avatar";
import Breadcrumbs from "../components/Breadcrumbs";
import InterviewQualityCard from "../components/InterviewQualityCard";
import InterviewScoreCard from "../components/InterviewScoreCard";
import InterviewSummary from "../components/InterviewSummary";
import { LoadError, Loading } from "../components/PageState";
import QaAnalysis from "../components/QaAnalysis";
import SavedTranscript from "../components/SavedTranscript";
import type { Interview } from "../types";
import { clockTime, shortDate } from "../when";

// The results of one interview: the transcript, the answer analysis (F5), the interview score (F9)
// and the interview quality review (F10). The analysis comes first: the score and the review are
// built on it.
export default function ResultDetailPage() {
  const { sessionId } = useParams();
  const [interview, setInterview] = useState<Interview | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setInterview(null);
    api<Interview>(`/interviews/${sessionId}`)
      .then(setInterview)
      .catch((err) => setError(err.message));
  }, [sessionId]);

  if (!interview) {
    return error ? <LoadError message={error} back="/results" backLabel="Back to the results" /> : <Loading label="Loading the interview…" />;
  }

  const held = interview.status === "ended" && !!interview.started_at;
  const roundText = `Round ${interview.round_number} of ${interview.round_total} · ${interview.round_name}`;

  return (
    <>
      <Breadcrumbs
        items={[
          { label: "Results", to: "/results" },
          { label: interview.job_title, to: `/jobs/${interview.job_id}/candidates?stage=interviews&round=${interview.round_number}` },
          { label: `${interview.candidate_name}, round ${interview.round_number}` },
        ]}
      />

      <div className="page-head">
        <div className="who" style={{ alignItems: "flex-start", gap: 16 }}>
          <Avatar name={interview.candidate_name} big />
          <div>
            <h1>{interview.candidate_name}</h1>
            <p>
              {interview.job_title} · {roundText}
            </p>
            <div className="row" style={{ gap: 10, marginTop: 8 }}>
              <span className="badge">
                {held && interview.started_at
                  ? `Held ${shortDate(interview.started_at)} at ${clockTime(interview.started_at)}`
                  : interview.status === "ended"
                    ? "Cancelled"
                    : `Booked for ${shortDate(interview.scheduled_at)} at ${clockTime(interview.scheduled_at)}`}
              </span>
            </div>
          </div>
        </div>
        <div className="row">
          <Link className="button secondary small" to={`/candidates/${interview.candidate_id}`}>
            Candidate profile
          </Link>
          <Link className="button secondary small" to={`/jobs/${interview.job_id}/candidates?stage=interviews&round=${interview.round_number}`}>
            Back to the round
          </Link>
        </div>
      </div>

      <div className="card glass">
        <InterviewSummary interview={interview} />
      </div>

      {held ? (
        <>
          <div className="card glass">
            <SavedTranscript sessionId={interview.id} candidateName={interview.candidate_name} />
          </div>
          <QaAnalysis sessionId={interview.id} candidateName={interview.candidate_name} />
          <InterviewScoreCard sessionId={interview.id} />
          <InterviewQualityCard sessionId={interview.id} />
        </>
      ) : (
        <div className="card glass">
          <p className="muted" style={{ margin: 0 }}>
            This interview has not taken place, so there is nothing to analyse yet.
          </p>
        </div>
      )}
    </>
  );
}
