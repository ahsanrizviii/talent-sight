import { useEffect, useState } from "react";
import { api } from "../api";
import type { Interview } from "../types";

// A <input type="datetime-local"> wants "2026-10-12T15:30" in the browser's own time zone.
function toInputValue(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

type Props = { candidateId: number; candidateStatus: string };

// Schedule, move or end the interview of one screened candidate (Task 7.1.2).
export default function InterviewCard({ candidateId, candidateStatus }: Props) {
  const [interview, setInterview] = useState<Interview | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [when, setWhen] = useState(() => toInputValue(new Date(Date.now() + 60 * 60 * 1000)));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api<Interview | null>(`/candidates/${candidateId}/interview`)
      .then(setInterview)
      .catch((err) => setError(err.message))
      .finally(() => setLoaded(true));
  }, [candidateId]);

  const active = interview !== null && interview.status !== "ended";

  async function save() {
    setBusy(true);
    setError("");
    try {
      const body = JSON.stringify({ scheduled_at: new Date(when).toISOString() });
      const result = active
        ? await api<Interview>(`/interviews/${interview.id}`, { method: "PATCH", body })
        : await api<Interview>(`/candidates/${candidateId}/interview`, { method: "POST", body });
      setInterview(result);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
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
    <div className="card">
      <h2>Interview</h2>

      {interview && (
        <p>
          <span className="badge">{interview.status}</span>{" "}
          {interview.status === "ended" && interview.ended_at
            ? `Ended ${new Date(interview.ended_at).toLocaleString()}`
            : `Scheduled for ${new Date(interview.scheduled_at).toLocaleString()}`}
        </p>
      )}

      {candidateStatus === "screened" && (interview === null || interview.status !== "live") && (
        <div className="field">
          <label htmlFor="interview-time">{active ? "Move to another time" : "Date and time"}</label>
          <input id="interview-time" type="datetime-local" value={when} onChange={(event) => setWhen(event.target.value)} />
        </div>
      )}

      <div className="row">
        {candidateStatus === "screened" && (interview === null || interview.status !== "live") && (
          <button className="button" onClick={save} disabled={busy || !when}>
            {active ? "Reschedule" : interview ? "Schedule a new interview" : "Schedule interview"}
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