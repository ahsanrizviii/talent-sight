import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { getToken } from "../auth";
import CandidatePanel from "../components/CandidatePanel";
import ChatPanel from "../components/ChatPanel";
import CvViewer from "../components/CvViewer";
import IdentityCheck from "../components/IdentityCheck";
import TranscriptPanel from "../components/TranscriptPanel";
import VideoRoom from "../components/VideoRoom";
import type { CandidateDetail, Interview, JoinInfo } from "../types";

type Side = "transcript" | "chat" | "cv";

// The interviewer's side of the video interview (Tasks 7.2.1 and 7.3.2). Under the video: the live
// transcript (Module 8), the question chat (Module 13) and the candidate's CV, in three tabs.
// Beside it: the identity check and the profile panel (F7), which stay in view while the
// interviewer listens.
export default function InterviewRoomPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [interview, setInterview] = useState<Interview | null>(null);
  const [candidate, setCandidate] = useState<CandidateDetail | null>(null);
  const [candidateError, setCandidateError] = useState("");
  const [error, setError] = useState("");
  const [showPanel, setShowPanel] = useState(true);
  const [side, setSide] = useState<Side>("transcript");
  const [cvOpened, setCvOpened] = useState(false); // the CV file is fetched the first time its tab opens

  useEffect(() => {
    api<Interview>(`/interviews/${id}`)
      .then(setInterview)
      .catch((err) => setError(err.message));
  }, [id]);

  // One read of the candidate feeds both the profile panel and the CV tab.
  useEffect(() => {
    if (!interview) return;
    api<CandidateDetail>(`/candidates/${interview.candidate_id}`)
      .then(setCandidate)
      .catch((err) => setCandidateError(err.message));
  }, [interview?.candidate_id]);

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

  function choose(next: Side) {
    setSide(next);
    if (next === "cv") setCvOpened(true);
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
          <div className="tabs glass room-tabs" role="tablist">
            <button role="tab" aria-selected={side === "transcript"} onClick={() => choose("transcript")}>
              Transcript
            </button>
            <button role="tab" aria-selected={side === "chat"} onClick={() => choose("chat")}>
              Question chat
            </button>
            <button role="tab" aria-selected={side === "cv"} onClick={() => choose("cv")}>
              CV
            </button>
          </div>
          {/* All stay mounted once opened, so switching tabs never drops the live transcript connection. */}
          <div hidden={side !== "transcript"}>
            <TranscriptPanel sessionId={interview.id} candidateName={interview.candidate_name} />
          </div>
          <div hidden={side !== "chat"}>
            <ChatPanel sessionId={interview.id} />
          </div>
          <div hidden={side !== "cv"} className="room-cv">
            {candidateError ? (
              <p className="error">{candidateError}</p>
            ) : !candidate ? (
              <p className="muted">Loading the CV...</p>
            ) : (
              cvOpened && (
                <CvViewer candidateId={candidate.id} filename={candidate.cv_filename} text={candidate.cv_text} />
              )
            )}
          </div>
        </div>
        {showPanel && (
          <div className="interview-side">
            <IdentityCheck sessionId={interview.id} />
            <CandidatePanel candidate={candidate} error={candidateError} />
          </div>
        )}
      </div>
    </>
  );
}