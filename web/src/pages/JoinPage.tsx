import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api";
import SkyScene from "../components/SkyScene";
import VideoRoom from "../components/VideoRoom";
import type { InviteInfo, JoinInfo } from "../types";

// The candidate's page, opened from the link in the e-mail (Task 7.2.2).
// No account and no menu: the private link is the only key, and the page shows nothing but the interview.
type Stage = "loading" | "invalid" | "ready" | "in" | "ended";

export default function JoinPage() {
  const { token } = useParams();
  const [stage, setStage] = useState<Stage>("loading");
  const [info, setInfo] = useState<InviteInfo | null>(null);
  const [note, setNote] = useState("");
  const [now, setNow] = useState(() => Date.now());

  const load = useCallback(
    async (afterLeaving: boolean) => {
      try {
        setInfo(await api<InviteInfo>(`/invite/${token}`));
        setStage("ready");
        if (afterLeaving) setNote("You left the interview. You can come back while it is still open.");
      } catch {
        // After leaving, a refused link means the interviewer ended it. Before, it was never valid.
        setStage(afterLeaving ? "ended" : "invalid");
      }
    },
    [token],
  );

  useEffect(() => {
    void load(false);
  }, [load]);

  // The button switches on by itself when the room opens.
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 10_000);
    return () => clearInterval(timer);
  }, []);

  // Closing the tab counts as leaving.
  useEffect(() => {
    const onPageHide = () => void api(`/invite/${token}/leave`, { method: "POST", keepalive: true }).catch(() => {});
    window.addEventListener("pagehide", onPageHide);
    return () => window.removeEventListener("pagehide", onPageHide);
  }, [token]);

  const join = useCallback(() => api<JoinInfo>(`/invite/${token}/join`, { method: "POST" }), [token]);

  async function leave() {
    await api(`/invite/${token}/leave`, { method: "POST" }).catch(() => {});
    setStage("loading");
    await load(true);
  }

  const opensAt = info ? new Date(info.opens_at).getTime() : 0;
  const open = info !== null && now >= opensAt;
  const when = info ? new Date(info.scheduled_at).toLocaleString([], { dateStyle: "full", timeStyle: "short" }) : "";

  return (
    <>
      <SkyScene variant="calm" />
      <header className="topbar">
        <span className="brand">TalentSight</span>
      </header>
      <main className="content narrow">
        {stage === "loading" && <p className="muted">Loading...</p>}

        {stage === "invalid" && (
          <div className="card">
            <h1>This link is not valid</h1>
            <p className="muted">The invite link is wrong, has expired, or the interview has ended. Please contact the person who invited you.</p>
          </div>
        )}

        {stage === "ended" && (
          <div className="card">
            <h1>The interview has ended</h1>
            <p className="muted">Thank you for your time. You can close this page.</p>
          </div>
        )}

        {stage === "ready" && info && (
          <div className="card">
            <h1>{info.candidate_name ? `Hello ${info.candidate_name}` : "Hello"}</h1>
            <p>
              Your video interview for <strong>{info.job_title}</strong> is on <strong>{when}</strong>.
            </p>
            <ul className="muted">
              <li>Use a quiet place with good light.</li>
              <li>When the browser asks, allow the camera and the microphone.</li>
              <li>The interview is a video call with one interviewer. Nothing is recorded.</li>
            </ul>
            {note && <p className="success">{note}</p>}
            {open ? (
              <button className="button" onClick={() => setStage("in")}>
                Join interview
              </button>
            ) : (
              <>
                <button className="button" disabled>
                  Join interview
                </button>
                <p className="muted small">The room opens at {new Date(info.opens_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}. This page turns it on by itself.</p>
              </>
            )}
          </div>
        )}

        {stage === "in" && <VideoRoom join={join} remoteLabel="Interviewer" onLeave={leave} />}
      </main>
    </>
  );
}