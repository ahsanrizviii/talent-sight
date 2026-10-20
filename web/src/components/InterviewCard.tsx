import { useEffect, useState } from "react";
import { api } from "../api";
import type { Interview } from "../types";
import { Link } from "react-router-dom";
import InterviewSummary from "./InterviewSummary";
import RescheduleBox from "./RescheduleBox";
import QaAnalysis from "./QaAnalysis";
import SavedTranscript from "./SavedTranscript";
import InterviewQualityCard from "./InterviewQualityCard";

// "localhost" and "127.0.0.1" mean "this computer", so a link containing them is useless to
// anyone else: their own machine has no TalentSight on it. The card says so rather than
// letting an interviewer e-mail a link that cannot work.
function localOnly(url: string): boolean {
  return /\/\/(localhost|127\.0\.0\.1|0\.0\.0\.0)(:|\/)/.test(url);
}

// A <input type="datetime-local"> wants "2026-10-12T15:30" in the browser's own time zone.
function toInputValue(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

type Props = { candidateId: number; candidateStatus: string };

// Schedule, move or end the interview of one screened candidate (Tasks 7.1.2 and 7.1.3).
export default function InterviewCard({ candidateId, candidateStatus }: Props) {
  const [interview, setInterview] = useState<Interview | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [when, setWhen] = useState(() => toInputValue(new Date(Date.now() + 60 * 60 * 1000)));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const [moving, setMoving] = useState(false);

  useEffect(() => {
    api<Interview | null>(`/candidates/${candidateId}/interview`)
      .then(setInterview)
      .catch((err) => setError(err.message))
      .finally(() => setLoaded(true));
  }, [candidateId]);

  const active = interview !== null && interview.status !== "ended";

  // Booking a new interview (always 1 hour). Moving one that is already booked is done by RescheduleBox.
  async function save() {
    setBusy(true);
    setError("");
    try {
      const body = JSON.stringify({ scheduled_at: new Date(when).toISOString() });
      setInterview(await api<Interview>(`/candidates/${candidateId}/interview`, { method: "POST", body }));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function sendAgain() {
    if (!interview) return;
    setBusy(true);
    setError("");
    try {
      setInterview(await api<Interview>(`/interviews/${interview.id}/invite`, { method: "POST" }));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function copyLink() {
    if (!interview) return;
    try {
      await navigator.clipboard.writeText(interview.invite_url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setError("Could not copy. Select the link and copy it yourself.");
    }
  }

  async function end() {
    if (!interview || !window.confirm("End this interview? The candidate's link will stop working.")) return;
    setBusy(true);
    setError("");
    try {
      setInterview(await api<Interview>(`/interviews/${interview.id}/end`, { method: "POST" }));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!loaded) return null;
  // Only screened candidates can be interviewed; an excluded or unreadable CV gets no card.
  if (candidateStatus !== "screened" && !interview) return null;

  return (
    <div className="card glass">
      <h2>Interview</h2>

      {interview && <InterviewSummary interview={interview} />}
      {interview?.status === "ended" && interview.started_at && <SavedTranscript sessionId={interview.id} candidateName={interview.candidate_name} />}
      {interview?.status === "ended" && interview.started_at && <InterviewQualityCard sessionId={interview.id} />}
      {interview?.status === "ended" && interview.started_at && <QaAnalysis sessionId={interview.id} candidateName={interview.candidate_name} />}
      {active && (
        <div className="field">
          <label htmlFor="invite-link">Candidate's private link</label>
          <div className="row">
            <input id="invite-link" className="grow" readOnly value={interview.invite_url} onFocus={(event) => event.target.select()} />
            <button className="button secondary" onClick={copyLink}>
              {copied ? "Copied" : "Copy"}
            </button>
          </div>
          {localOnly(interview.invite_url) && (
            <p className="demo-note">
            This link only opens on this computer, because the site is running on localhost. To invite
            someone on another device, set PUBLIC_BASE_URL to the site's public https address.
            </p>
          )}
        </div>
      )}
      {interview?.email_sent === true && (
        <p className="success">Invitation e-mail sent, with the interview in the candidate's calendar.</p>
      )}
      {interview?.email_sent === false && <p className="error">{interview.email_error}</p>}
      {interview?.calendar_added === true && <p className="success">Added to the company Google Calendar.</p>}
      {interview?.calendar_added === false && <p className="error">{interview.calendar_error}</p>}

      {interview?.status === "scheduled" && moving && (
        <>
          <h3 className="mini-head next">Move to another time</h3>
          <RescheduleBox
            sessionId={interview.id}
            currentAt={interview.scheduled_at}
            onMoved={(moved) => setInterview(moved)}
            onClose={() => setMoving(false)}
          />
        </>
      )}

      {candidateStatus === "screened" && interview?.status === "ended" && <h3 className="mini-head next">Book another interview</h3>}
      {candidateStatus === "screened" && !active && (
        <div className="reschedule-fields">
          <div className="field">
            <label htmlFor="interview-time">{interview ? "New date and time" : "Date and time"}</label>
            <input id="interview-time" type="datetime-local" value={when} onChange={(event) => setWhen(event.target.value)} />
          </div>
        </div>
      )}

      <div className="row">
        {candidateStatus === "screened" && !active && (
          <button className="button" onClick={save} disabled={busy || !when}>
            {interview ? "Schedule a new interview" : "Schedule interview"}
          </button>
        )}
        {interview?.status === "scheduled" && !moving && (
          <button className="button secondary" onClick={() => setMoving(true)}>
            Reschedule
          </button>
        )}
        {active && (
          <Link className="button" to={`/interview/${interview.id}`}>
            {interview.status === "live" ? "Rejoin interview" : "Join interview"}
          </Link>
        )}
        {interview?.status === "scheduled" && (
          <button className="button secondary" onClick={sendAgain} disabled={busy}>
            Send e-mail again
          </button>
        )}
        {active && (
          <button className="button danger" onClick={end} disabled={busy}>
            {interview.status === "live" ? "End interview" : "Cancel interview"}
          </button>
        )}
      </div>
      {error && <p className="error">{error}</p>}
    </div>
  );
}