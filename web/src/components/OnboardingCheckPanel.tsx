import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { grabFrame } from "../camera";
import type { OnboardingStart, OnboardingState } from "../types";
import "../assessment.css";

// The onboarding-day identity check (Module 13, F7). HR checks the original photo ID first. Then the
// new hire looks at this computer's camera and turns their head the way the screen asks, so a held-up
// photo or a replayed video does not pass, and a fresh picture is compared with the face templates from
// the interview. Anything but a match waits for a person's decision. Nothing is ever called fraud.

type Phase = "idle" | "front" | "turn" | "sending";

const OUTCOMES = {
  match: { label: "Face matches the interview", tone: "pass" },
  low_confidence: { label: "Low confidence: review needed", tone: "warn" },
  no_templates: { label: "No face templates on file: review needed", tone: "warn" },
};

export default function OnboardingCheckPanel({ candidateId }: { candidateId: number }) {
  const [state, setState] = useState<OnboardingState | null>(null);
  const [error, setError] = useState("");
  const [idChecked, setIdChecked] = useState(false);
  const [phase, setPhase] = useState<Phase>("idle");
  const [direction, setDirection] = useState<"left" | "right">("left");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const frontRef = useRef("");

  const load = useCallback(
    () =>
      api<OnboardingState>(`/candidates/${candidateId}/onboarding-check`)
        .then(setState)
        .catch((err) => setError(err.message)),
    [candidateId],
  );

  useEffect(() => {
    void load();
  }, [load]);

  const stopCamera = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }, []);

  // The camera is switched off when leaving the page.
  useEffect(() => stopCamera, [stopCamera]);

  // Show the camera once the video element is on screen.
  useEffect(() => {
    const video = videoRef.current;
    if (phase !== "idle" && video && streamRef.current && video.srcObject !== streamRef.current) {
      video.srcObject = streamRef.current;
      void video.play().catch(() => {});
    }
  }, [phase]);

  async function begin() {
    setError("");
    try {
      streamRef.current = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480 }, audio: false });
    } catch {
      setError("The camera could not be opened. Allow the camera in the browser and try again.");
      return;
    }
    try {
      const started = await api<OnboardingStart>(`/candidates/${candidateId}/onboarding-check/start`, {
        method: "POST",
        body: JSON.stringify({ original_id_checked: idChecked }),
      });
      setDirection(started.direction);
      frontRef.current = "";
      setPhase("front");
    } catch (err) {
      stopCamera();
      setError((err as Error).message);
    }
  }

  function takeFront() {
    const shot = grabFrame(videoRef.current);
    if (!shot) {
      setError("The camera picture is not ready yet. Try again in a moment.");
      return;
    }
    setError("");
    frontRef.current = shot;
    setPhase("turn");
  }

  async function takeTurned() {
    const shot = grabFrame(videoRef.current);
    if (!shot) {
      setError("The camera picture is not ready yet. Try again in a moment.");
      return;
    }
    setPhase("sending");
    setError("");
    try {
      setState(
        await api<OnboardingState>(`/candidates/${candidateId}/onboarding-check/finish`, {
          method: "POST",
          body: JSON.stringify({ front: frontRef.current, turned: shot }),
        }),
      );
      stopCamera();
      setPhase("idle");
      setIdChecked(false);
    } catch (err) {
      setError((err as Error).message);
      if ((err as { status?: number }).status === 422) {
        setPhase("front"); // same challenge: take the two pictures again
      } else {
        stopCamera();
        setPhase("idle");
      }
    }
  }

  function cancel() {
    stopCamera();
    setPhase("idle");
    setError("");
  }

  async function decide(decision: "confirmed" | "not_confirmed") {
    setBusy(true);
    setError("");
    try {
      setState(
        await api<OnboardingState>(`/candidates/${candidateId}/onboarding-check/decision`, {
          method: "POST",
          body: JSON.stringify({ decision, note }),
        }),
      );
      setNote("");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function deleteFaceData() {
    if (!window.confirm("Delete this candidate's face templates now? The onboarding check will then have nothing to compare with.")) return;
    setBusy(true);
    setError("");
    try {
      await api(`/candidates/${candidateId}/face-templates`, { method: "DELETE" });
      await load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!state) return <p className="muted small">{error || "Loading the onboarding check…"}</p>;

  const check = state.check;
  const outcome = check && check.status === "done" && check.outcome ? OUTCOMES[check.outcome] : null;

  return (
    <section className="card glass assessment">
      <h2>Onboarding check</h2>
      <p className="muted small" style={{ margin: 0 }}>
        On the new hire’s first day: confirm that the person who joined is the person who was interviewed.
      </p>
      <p className="ob-note">
        The photo ID check by a person is the real check. Face matching is advice only and can be wrong, more often for
        some groups of people. A result that is not a match goes to a person to review, never to an automatic decision.
      </p>
      <p className="small">
        Face templates on file: <strong>{state.templates_on_file}</strong> (kept for at most {state.retention_days} days)
      </p>

      {outcome && check && (
        <div className="ob-result">
          <span className={`badge ${outcome.tone}`}>{outcome.label}</span>
          {check.best_score !== null && <span className="muted small"> · similarity {check.best_score}</span>}
          <p className="muted small">
            Checked by {check.checked_by}
            {check.checked_at ? ` on ${new Date(check.checked_at).toLocaleString()}` : ""}. Original photo ID checked first.
          </p>
          {check.decision && (
            <p className="small">
              Decision: <strong>{check.decision === "confirmed" ? "Identity confirmed" : "Not confirmed"}</strong> by {check.decided_by}
              {check.decision_note ? ` · “${check.decision_note}”` : ""}
            </p>
          )}
          {check.needs_review && (
            <div className="ob-review">
              <p className="small">
                Check the original photo ID again and talk to the new hire. Then record your decision.
              </p>
              <textarea
                value={note}
                onChange={(event) => setNote(event.target.value)}
                maxLength={500}
                rows={2}
                placeholder="What you checked (optional)"
                aria-label="Decision note"
              />
              <div className="row ob-buttons">
                <button className="button" onClick={() => void decide("confirmed")} disabled={busy}>
                  Identity confirmed
                </button>
                <button className="button secondary" onClick={() => void decide("not_confirmed")} disabled={busy}>
                  Not confirmed
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {phase === "idle" ? (
        <div className="ob-start">
          <label className="id-check">
            <input type="checkbox" checked={idChecked} onChange={(event) => setIdChecked(event.target.checked)} />
            I have checked the new hire’s original photo ID, in person or on a live call, and the name matches
          </label>
          <button className="button" onClick={() => void begin()} disabled={!idChecked}>
            {check ? "Run the check again" : "Start the onboarding check"}
          </button>
        </div>
      ) : (
        <div className="ob-camera">
          <video ref={videoRef} className="ob-video" autoPlay playsInline muted />
          <p className="ob-instruction">
            {phase === "front" && "Ask the new hire to look straight at the camera."}
            {phase === "turn" && `Now ask them to turn their head to their ${direction}.`}
            {phase === "sending" && "Comparing…"}
          </p>
          <div className="row ob-buttons">
            {phase === "front" && (
              <button className="button" onClick={takeFront}>
                Take the first picture
              </button>
            )}
            {phase === "turn" && (
              <button className="button" onClick={() => void takeTurned()}>
                Take the second picture
              </button>
            )}
            <button className="button secondary" onClick={cancel} disabled={phase === "sending"}>
              Cancel
            </button>
          </div>
          <p className="muted small">The pictures are compared and then thrown away. Only the result is kept.</p>
        </div>
      )}

      {error && <p className="error small">{error}</p>}
      {state.templates_on_file > 0 && phase === "idle" && (
        <button className="ob-delete" onClick={() => void deleteFaceData()} disabled={busy}>
          Delete face data now
        </button>
      )}
    </section>
  );
}