import { useEffect, useState } from "react";
import { api, withQuery } from "../api";
import type { Interview } from "../types";

// Moving one interview to another time, for example when the candidate asks for it.
// It suggests free times that follow every rule, warns when a chosen time breaks one
// (weekend, holiday, outside the hours, a clash), and e-mails the candidate the new time.
// The private link stays the same.

const LENGTHS = [30, 45, 60, 90];

function toInputValue(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

const slotText = (iso: string) =>
  new Date(iso).toLocaleString([], { weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });

type Props = {
  sessionId: number;
  currentAt: string;
  durationMinutes: number;
  onMoved: (interview: Interview) => void;
  onClose?: () => void;
};

export default function RescheduleBox({ sessionId, currentAt, durationMinutes, onMoved, onClose }: Props) {
  const [when, setWhen] = useState(() => toInputValue(new Date(currentAt)));
  const [minutes, setMinutes] = useState(durationMinutes);
  const [free, setFree] = useState<string[] | null>(null);
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState("");
  const [error, setError] = useState("");

  // Check the chosen time against the rules a moment after it changes.
  useEffect(() => {
    if (!when) return;
    const timer = window.setTimeout(() => {
      api<{ problem: string }>(withQuery(`/interviews/${sessionId}/time-check`, { at: new Date(when).toISOString(), duration_minutes: minutes }))
        .then((answer) => setProblem(answer.problem))
        .catch(() => setProblem(""));
    }, 300);
    return () => window.clearTimeout(timer);
  }, [when, minutes, sessionId]);

  async function suggest() {
    setError("");
    try {
      setFree(await api<string[]>(withQuery(`/interviews/${sessionId}/free-times`, { count: 6, duration_minutes: minutes, start: new Date().toISOString() })));
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function move() {
    if (problem && !window.confirm(`${problem} Move the interview to this time anyway?`)) return;
    setBusy(true);
    setError("");
    setResult("");
    try {
      const moved = await api<Interview>(`/interviews/${sessionId}`, {
        method: "PATCH",
        body: JSON.stringify({ scheduled_at: new Date(when).toISOString(), duration_minutes: minutes }),
      });
      setResult(moved.email_sent === false ? `Moved. The e-mail was not sent: ${moved.email_error}` : "Moved. The candidate was e-mailed the new time.");
      onMoved(moved);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="reschedule">
      <div className="reschedule-fields">
        <div className="field">
          <label htmlFor={`move-${sessionId}`}>New date and time</label>
          <input id={`move-${sessionId}`} type="datetime-local" value={when} onChange={(event) => setWhen(event.target.value)} />
        </div>
        <div className="field">
          <label htmlFor={`length-${sessionId}`}>Length</label>
          <select id={`length-${sessionId}`} value={minutes} onChange={(event) => setMinutes(Number(event.target.value))}>
            {[...new Set([...LENGTHS, durationMinutes])].sort((a, b) => a - b).map((m) => (
              <option key={m} value={m}>
                {m} minutes
              </option>
            ))}
          </select>
        </div>
      </div>

      {problem ? <p className="warn-line">⚠ {problem} You can still choose it if the candidate asked for this time.</p> : when && <p className="ok-line">✓ This time follows the interview rules.</p>}

      <div className="row">
        <button className="button quiet small" type="button" onClick={suggest}>
          Show free times
        </button>
        {free?.map((slot) => (
          <button key={slot} className="chip slot-chip" type="button" onClick={() => setWhen(toInputValue(new Date(slot)))}>
            {slotText(slot)}
          </button>
        ))}
        {free?.length === 0 && <span className="muted small">No free time found.</span>}
      </div>

      <div className="row">
        <button className="button" type="button" onClick={move} disabled={busy || !when}>
          Move and e-mail the candidate
        </button>
        {onClose && (
          <button className="button quiet" type="button" onClick={onClose}>
            Close
          </button>
        )}
      </div>
      {result && <p className="success">{result}</p>}
      {error && <p className="error">{error}</p>}
    </div>
  );
}
