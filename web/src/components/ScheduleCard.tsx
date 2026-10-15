import { useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import type { ScheduleRules } from "../types";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

// Settings: when interviews may be booked. "Invite top candidates" and "Show free times"
// both follow these rules. Interviews already booked keep their own time and length.
export default function ScheduleCard() {
  const [rules, setRules] = useState<ScheduleRules | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    api<ScheduleRules>("/schedule-rules").then(setRules).catch((err) => setError(err.message));
  }, []);

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!rules) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const saved = await api<ScheduleRules>("/schedule-rules", {
        method: "PUT",
        body: JSON.stringify({
          interview_minutes: rules.interview_minutes,
          gap_minutes: rules.gap_minutes,
          windows: rules.windows,
          work_days: rules.work_days,
        }),
      });
      setRules(saved);
      setMessage(`Saved. That gives ${saved.slots_per_day} interviews a day. Interviews already booked do not move.`);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const update = (change: Partial<ScheduleRules>) => setRules((old) => (old ? { ...old, ...change } : old));
  const setBlock = (index: number, key: "start" | "end", value: string) =>
    rules && update({ windows: rules.windows.map((b, i) => (i === index ? { ...b, [key]: value } : b)) });
  const toggleDay = (day: string) =>
    rules &&
    update({ work_days: rules.work_days.includes(day) ? rules.work_days.filter((d) => d !== day) : DAYS.filter((d) => d === day || rules.work_days.includes(d)) });

  return (
    <form className="card glass" onSubmit={save}>
      <h2>Interview schedule</h2>
      <p className="muted small">Used when inviting candidates and when suggesting free times.</p>
      {!rules ? (
        <p className="muted">Loading…</p>
      ) : (
        <>
          <div className="schedule-grid">
            <div className="field">
              <label htmlFor="rule-length">Interview length (minutes)</label>
              <input id="rule-length" type="number" min={10} max={240} step={5} value={rules.interview_minutes} onChange={(e) => update({ interview_minutes: Number(e.target.value) })} />
              <span className="hint">
                Quick picks:{" "}
                {[30, 45, 60, 90].map((m) => (
                  <button key={m} type="button" className="link-button" onClick={() => update({ interview_minutes: m })}>
                    {m}
                  </button>
                ))}
              </span>
            </div>
            <div className="field">
              <label htmlFor="rule-gap">Gap between interviews (minutes)</label>
              <input id="rule-gap" type="number" min={0} max={120} step={5} value={rules.gap_minutes} onChange={(e) => update({ gap_minutes: Number(e.target.value) })} />
            </div>
          </div>

          <div className="field">
            <label>Interview hours</label>
            {rules.windows.map((block, index) => (
              <div className="row hours-row" key={index}>
                <input type="time" value={block.start} onChange={(e) => setBlock(index, "start", e.target.value)} aria-label="From" />
                <span className="muted">to</span>
                <input type="time" value={block.end} onChange={(e) => setBlock(index, "end", e.target.value)} aria-label="Until" />
                {rules.windows.length > 1 && (
                  <button type="button" className="notice-close" aria-label="Remove these hours" onClick={() => update({ windows: rules.windows.filter((_, i) => i !== index) })}>
                    ×
                  </button>
                )}
              </div>
            ))}
            {rules.windows.length < 4 && (
              <button type="button" className="button quiet small" onClick={() => update({ windows: [...rules.windows, { start: "14:00", end: "17:00" }] })}>
                Add hours
              </button>
            )}
          </div>

          <div className="field">
            <label>Working days</label>
            <div className="chips">
              {DAYS.map((day) => (
                <label key={day} className={`chip day-chip ${rules.work_days.includes(day) ? "on" : ""}`}>
                  <input type="checkbox" checked={rules.work_days.includes(day)} onChange={() => toggleDay(day)} />
                  {day}
                </label>
              ))}
            </div>
          </div>

          <div className="row">
            <button className="button" type="submit" disabled={busy}>
              Save schedule
            </button>
            <span className="muted small">Now: {rules.slots_per_day} interviews a day</span>
          </div>
        </>
      )}
      {message && <p className="success">{message}</p>}
      {error && <p className="error">{error}</p>}
    </form>
  );
}
