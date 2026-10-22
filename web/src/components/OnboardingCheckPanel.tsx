import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { grabFrame } from "../camera";
import type { OnboardingCheckInfo, OnboardingStart } from "../types";
import "../assessment.css";
import "../onboarding.css";

// The onboarding-day identity check (Module 13, F7), in three steps:
//   1. What is on file: the face templates kept from the interview (numbers, never pictures).
//   2. Take the photo: HR checks the original photo ID, then the new hire looks at the camera and,
//      when asked, turns their head. The second picture is taken by itself after a short countdown,
//      so a held-up photo or a replayed video does not pass, and HR presses only one button.
//   3. The result: "Same person" ends the check. Anything else waits for a person's decision.
// Nothing is ever called fraud, and the pictures are thrown away once compared.

type OnboardingState = {
  templates_on_file: number;
  templates_taken_at: string | null;
  templates_expire_at: string | null;
  templates_interview_at: string | null;
  interview_held: boolean;
  consent: boolean | null;
  retention_days: number;
  check: OnboardingCheckInfo | null;
};

type Phase = "idle" | "front" | "turn" | "sending";

const COUNTDOWN = 3; // seconds between "turn your head" and the second picture

const day = (iso: string | null) =>
  iso ? new Date(iso).toLocaleDateString([], { day: "numeric", month: "short", year: "numeric" }) : "";

export default function OnboardingCheckPanel({ candidateId }: { candidateId: number }) {
  const [state, setState] = useState<OnboardingState | null>(null);
  const [error, setError] = useState("");
  const [idChecked, setIdChecked] = useState(false);
  const [phase, setPhase] = useState<Phase>("idle");
  const [direction, setDirection] = useState<"left" | "right">("left");
  const [count, setCount] = useState(COUNTDOWN);
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

  // One button: the first picture now, then the head turn with a countdown, then the second picture.
  function takePhoto() {
    const shot = grabFrame(videoRef.current);
    if (!shot) {
      setError("The camera picture is not ready yet. Try again in a moment.");
      return;
    }
    setError("");
    frontRef.current = shot;
    setCount(COUNTDOWN);
    setPhase("turn");
  }

  const sendTurned = useCallback(async () => {
    const shot = grabFrame(videoRef.current);
    if (!shot) {
      setError("The camera picture is not ready yet. Take the photo again.");
      setPhase("front");
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
        setPhase("front"); // the same challenge: take the photo again
      } else {
        stopCamera();
        setPhase("idle");
      }
    }
  }, [candidateId, stopCamera]);

  // The countdown for the head turn. At zero the second picture is taken and sent.
  useEffect(() => {
    if (phase !== "turn") return;
    if (count <= 0) {
      void sendTurned();
      return;
    }
    const timer = window.setTimeout(() => setCount((left) => left - 1), 1000);
    return () => window.clearTimeout(timer);
  }, [phase, count, sendTurned]);

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

  const check = state.check?.status === "done" ? state.check : null;
  const onFile = state.templates_on_file > 0;
  const finished = !!check && (check.outcome === "match" || !!check.decision);
  const step = finished ? 3 : check ? 3 : phase !== "idle" ? 2 : onFile ? 2 : 1;

  return (
    <section className="card glass assessment">
      <h2>Onboarding check</h2>
      <p className="muted small" style={{ margin: 0 }}>
        On the new hire’s first day: confirm that the person who joined is the person who was interviewed.
      </p>

      <ol className="ob-steps" aria-label="Steps">
        <li className={step > 1 || onFile ? "done" : "current"}>1 · On file</li>
        <li className={step === 2 ? "current" : step > 2 ? "done" : ""}>2 · Take the photo</li>
        <li className={step === 3 ? (finished ? "done" : "current") : ""}>3 · Result</li>
      </ol>

      {/* ---------- 1. What is on file ---------- */}
      <div className={`ob-block ${onFile ? "ok" : ""}`}>
        <h3>On file</h3>
        {onFile ? (
          <p>
            <strong>
              {state.templates_on_file} face {state.templates_on_file === 1 ? "template" : "templates"}
            </strong>{" "}
            from the interview{state.templates_interview_at ? ` on ${day(state.templates_interview_at)}` : ""}, stored as
            numbers, never as pictures. Kept until {day(state.templates_expire_at)} at the latest.
          </p>
        ) : check ? (
          <p className="muted">The face data was deleted when the check finished, as planned.</p>
        ) : !state.interview_held ? (
          <p className="muted">
            Nothing yet. Face templates are taken during the interview, and only if the candidate agrees.
          </p>
        ) : state.consent === false ? (
          <p className="muted">The candidate did not agree to face matching. Check the original photo ID only.</p>
        ) : (
          <p className="muted">No face templates are on file (none were taken, or they were deleted).</p>
        )}
      </div>

      {/* ---------- 3. The result (shown above the camera once there is one) ---------- */}
      {check && check.outcome === "match" && (
        <div className="ob-done">
          <span className="ob-tick" aria-hidden="true">
            ✓
          </span>
          <div>
            <strong>Same person. Identity confirmed.</strong>
            <p className="small">
              The new hire matches the person interviewed
              {check.best_score !== null ? ` (similarity ${check.best_score})` : ""}. Checked by {check.checked_by}
              {check.checked_at ? ` on ${new Date(check.checked_at).toLocaleString()}` : ""}, after the original photo ID.
              Nothing else to do.
            </p>
          </div>
        </div>
      )}

      {check && check.outcome !== "match" && (
        <div className={`ob-block ${check.decision === "confirmed" ? "ok" : "warn"}`}>
          <h3>Result</h3>
          <p>
            <strong>
              {check.outcome === "no_templates" ? "Nothing to compare with." : "The face does not clearly match."}
            </strong>{" "}
            {check.best_score !== null && <span className="muted small">Similarity {check.best_score}. </span>}
            <span className="muted small">
              Face matching can be wrong, more often for some groups of people, so a person decides.
            </span>
          </p>
          {check.decision ? (
            <p className="small">
              Decision: <strong>{check.decision === "confirmed" ? "Identity confirmed" : "Not confirmed"}</strong> by{" "}
              {check.decided_by}
              {check.decision_note ? ` · “${check.decision_note}”` : ""}
            </p>
          ) : (
            <div className="ob-review">
              <p className="small">Check the original photo ID again and talk to the new hire. Then record your decision.</p>
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

      {/* ---------- 2. Take the photo ---------- */}
      {phase === "idle" ? (
        !finished && (
          <div className="ob-block">
            <h3>Take the photo</h3>
            <label className="id-check">
              <input type="checkbox" checked={idChecked} onChange={(event) => setIdChecked(event.target.checked)} />
              I have checked the new hire’s original photo ID, in person or on a live call, and the name matches
            </label>
            <button className="button" onClick={() => void begin()} disabled={!idChecked}>
              {check ? "Run the check again" : "Open the camera"}
            </button>
          </div>
        )
      ) : (
        <div className="ob-camera">
          <video ref={videoRef} className="ob-video" autoPlay playsInline muted />
          <p className="ob-instruction">
            {phase === "front" && "Ask the new hire to look straight at the camera, then take the photo."}
            {phase === "turn" && (
              <>
                Now ask them to turn their head to their <strong>{direction}</strong>…{" "}
                <span className="ob-count">{count > 0 ? count : "now"}</span>
              </>
            )}
            {phase === "sending" && "Comparing with the interview…"}
          </p>
          <div className="row ob-buttons">
            {phase === "front" && (
              <button className="button" onClick={takePhoto}>
                Take the photo
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

      <p className="ob-note">
        The photo ID check by a person is the real check. Face matching is advice only, and a result that is not a match
        always goes to a person.
      </p>
      {onFile && phase === "idle" && (
        <button className="ob-delete" onClick={() => void deleteFaceData()} disabled={busy}>
          Delete face data now
        </button>
      )}
    </section>
  );
}
