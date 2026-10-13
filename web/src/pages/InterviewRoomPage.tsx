import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { getToken } from "../auth";
import CandidatePanel from "../components/CandidatePanel";
import TranscriptPanel from "../components/TranscriptPanel";
import VideoRoom from "../components/VideoRoom";
import type { Interview, JoinInfo } from "../types";

// The interviewer's side of the video interview (Tasks 7.2.1 and 7.3.2).
export default function InterviewRoomPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [interview, setInterview] = useState<Interview | null>(null);
  const [error, setError] = useState("");
  const [showPanel, setShowPanel] = useState(true);

  useEffect(() => {
    api<Interview>(`/interviews/${id}`)
      .then(setInterview)
      .catch((err) => setError(err.message));
  }, [id]);

  const join = useCallback(() => api<JoinInfo>(`/interviews/${id}/join`, { method: "POST" }), [id]);

  // Closing the tab counts as leaving. keepalive lets the request finish while the page is closing.
  useEffect(() => {
    const onPageHide = () => void api(`/interviews/${id}/leave`, { method: "POST", keepalive: true }).catch(() => {});
    window.addEventListener("pagehide", onPageHide);
    return () => window.removeEventListener("pagehide", onPageHide);
  }, [id]);

  const backTo = interview ? `/candidates/${interview.candidate_id}` : "/jobs";

  async function leave() {
    await api(`/interviews/${id}/leave`, { method: "POST" }).catch(() => {});
    navigate(backTo);
  }

  async function end() {
    if (!window.confirm("End the interview for everyone? The candidate's link will stop working.")) return;
    try {
      await api(`/interviews/${id}/end`, { method: "POST" });
      navigate(backTo);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  if (error) {
    return (
      <>
        <p className="error">{error}</p>
        <Link className="back-link" to="/jobs">
          ← Back
        </Link>
      </>
    );
  }
  if (!interview) return <p className="muted">Loading...</p>;

  return (
    <>
      <div className="row between">
        <div>
          <h1>Interview with {interview.candidate_name}</h1>
          <p className="muted">
            {interview.job_title} · {new Date(interview.scheduled_at).toLocaleString()}
          </p>
        </div>
        <button className="button secondary" onClick={() => setShowPanel(!showPanel)}>
          {showPanel ? "Hide profile" : "Show profile"}
        </button>
      </div>
      {/* The video room is always the first child, so hiding the panel never restarts the call. */}
      <div className={`interview-layout ${showPanel ? "" : "no-panel"}`}>
        <div className="interview-main">
          <VideoRoom
            join={join}
            remoteLabel="Candidate"
            onLeave={leave}
            onEnd={end}
            speech={{ path: `/ws/interviews/${id}/audio`, token: getToken() }}
          />
          <TranscriptPanel sessionId={interview.id} candidateName={interview.candidate_name} />
        </div>
        {showPanel && <CandidatePanel candidateId={interview.candidate_id} />}
      </div>
    </>
  );
}