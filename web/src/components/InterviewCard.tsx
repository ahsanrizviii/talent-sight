import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import type { Interview } from "../types";
import Icon from "./Icon";
import InterviewSummary from "./InterviewSummary";
import RescheduleBox from "./RescheduleBox";
import SavedTranscript from "./SavedTranscript";

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

const dayAndTime = (iso: string) =>
  new Date(iso).toLocaleString([], { weekday: "short", day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit" });

// An interview that really took place: it has ended and someone started it.
const tookPlace = (interview: Interview) => interview.status === "ended" && !!interview.started_at;

// The one line shown on a folded interview: what happened and when.
function headline(interview: Interview): { state: string; when: string } {
  if (interview.status === "scheduled") return { state: "Scheduled", when: dayAndTime(interview.scheduled_at) };
  if (interview.status === "live") return { state: "Live now", when: interview.started_at ? dayAndTime(interview.started_at) : "" };
  if (interview.started_at) return { state: "Completed", when: dayAndTime(interview.started_at) };
  return { state: "Cancelled", when: `was planned for ${dayAndTime(interview.scheduled_at)}` };
}

type Props = { candidateId: number; candidateStatus: string };

// Every interview of one candidate (Tasks 7.1.2 and 7.1.3), oldest first, each named by its round.
// Each one keeps its own transcript and folds open or shut; its answer analysis, score and quality
// review are on the Results page. The newest one opens by default; booking a new interview folds
// the earlier ones away. A new interview is always for the round the candidate is in now.
export default function InterviewCard({ candidateId, candidateStatus }: Props) {
  const [interviews, setInterviews] = useState<Interview[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [open, setOpen] = useState<Record<number, boolean>>({});
  const [when, setWhen] = useState(() => toInputValue(new Date(Date.now() + 60 * 60 * 1000)));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const [moving, setMoving] = useState(false);

  useEffect(() => {
    setLoaded(false);
    api<Interview[]>(`/candidates/${candidateId}/interviews`)
      .then(setInterviews)
      .catch((err) => setError(err.message))
      .finally(() => setLoaded(true));
  }, [candidateId]);

  const latest = interviews.length > 0 ? interviews[interviews.length - 1] : null;
  const active = latest !== null && latest.status !== "ended";

  const isOpen = (interview: Interview) => open[interview.id] ?? interview.id === latest?.id;
  const toggle = (interview: Interview) => setOpen((old) => ({ ...old, [interview.id]: !isOpen(interview) }));
  const replace = (updated: Interview) =>
    setInterviews((list) => list.map((item) => (item.id === updated.id ? updated : item)));

  // Booking a new interview (always 1 hour). Moving one that is already booked is done by RescheduleBox.
  async function save() {
    setBusy(true);
    setError("");
    try {
      const body = JSON.stringify({ scheduled_at: new Date(when).toISOString() });
      const created = await api<Interview>(`/candidates/${candidateId}/interview`, { method: "POST", body });
      setInterviews((list) => [...list, created]);
      setOpen({}); // back to the default: the new one open, the earlier ones folded
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function sendAgain() {
    if (!latest) return;
    setBusy(true);
    setError("");
    try {
      replace(await api<Interview>(`/interviews/${latest.id}/invite`, { method: "POST" }));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function copyLink() {
    if (!latest) return;
    try {
      await navigator.clipboard.writeText(latest.invite_url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setError("Could not copy. Select the link and copy it yourself.");
    }
  }

  async function end() {
    if (!latest || !window.confirm("End this interview? The candidate's link will stop working.")) return;
    setBusy(true);
    setError("");
    try {
      replace(await api<Interview>(`/interviews/${latest.id}/end`, { method: "POST" }));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!loaded) return null;
  // Only screened candidates can be interviewed; an excluded or unreadable CV gets no card.
  if (candidateStatus !== "screened" && interviews.length === 0) return null;

  // The controls that only make sense for the newest interview while it is booked or running.
  function latestControls(interview: Interview) {
    const isActive = interview.status !== "ended";
    return (
      <>
        {isActive && (
          <div className="field">
            <label htmlFor="invite-link">Candidate's private link</label>
            <div className="row">
              <input
                id="invite-link"
                className="grow"
                readOnly
                value={interview.invite_url}
                onFocus={(event) => event.target.select()}
              />
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
        {interview.email_sent === true && (
          <p className="success">Invitation e-mail sent, with the interview in the candidate's calendar.</p>
        )}
        {interview.email_sent === false && <p className="error">{interview.email_error}</p>}
        {interview.calendar_added === true && <p className="success">Added to the company Google Calendar.</p>}
        {interview.calendar_added === false && <p className="error">{interview.calendar_error}</p>}

        {interview.status === "scheduled" && moving && (
          <>
            <h3 className="mini-head next">Move to another time</h3>
            <RescheduleBox
              sessionId={interview.id}
              currentAt={interview.scheduled_at}
              onMoved={(moved) => replace(moved)}
              onClose={() => setMoving(false)}
            />
          </>
        )}

        {isActive && (
          <div className="row">
            {interview.status === "scheduled" && !moving && (
              <button className="button secondary" onClick={() => setMoving(true)}>
                Reschedule
              </button>
            )}
            <Link className="button" to={`/interview/${interview.id}`}>
              {interview.status === "live" ? "Rejoin interview" : "Join interview"}
            </Link>
            {interview.status === "scheduled" && (
              <button className="button secondary" onClick={sendAgain} disabled={busy}>
                Send e-mail again
              </button>
            )}
            <button className="button danger" onClick={end} disabled={busy}>
              {interview.status === "live" ? "End interview" : "Cancel interview"}
            </button>
          </div>
        )}
      </>
    );
  }

  return (
    <div className="card glass">
      <div className="card-head">
        <h2>{interviews.length > 1 ? "Interviews" : "Interview"}</h2>
        {interviews.length > 1 && <span className="muted small">{interviews.length} interviews, the newest last</span>}
      </div>

      {interviews.map((interview, index) => {
        const opened = isOpen(interview);
        const { state, when: at } = headline(interview);
        const bodyId = `interview-record-${interview.id}`;
        return (
          <section key={interview.id} className={`interview-record${opened ? " open" : ""}`}>
            <button
              type="button"
              className="interview-toggle"
              aria-expanded={opened}
              aria-controls={bodyId}
              onClick={() => toggle(interview)}
            >
              <Icon name="forward" size={15} />
              <span className="interview-toggle-title">
                {interview.round_total > 1 ? `Round ${interview.round_number} · ${interview.round_name}` : `Interview ${index + 1}`}
              </span>
              <span className="interview-toggle-state">{state}</span>
              {at && <span className="muted small">{at}</span>}
            </button>

            {opened && (
              <div className="interview-record-body" id={bodyId}>
                <InterviewSummary interview={interview} />
                {tookPlace(interview) && (
                  <>
                    <SavedTranscript sessionId={interview.id} candidateName={interview.candidate_name} />
                    <div className="row">
                      <Link className="button secondary" to={`/results/${interview.id}`}>
                        See the answer analysis, score and quality review
                      </Link>
                    </div>
                  </>
                )}
                {interview.id === latest?.id && latestControls(interview)}
              </div>
            )}
          </section>
        );
      })}

      {candidateStatus === "screened" && !active && (
        <>
          {interviews.length > 0 && <h3 className="mini-head next">Book another interview</h3>}
          <div className="reschedule-fields">
            <div className="field">
              <label htmlFor="interview-time">{interviews.length > 0 ? "New date and time" : "Date and time"}</label>
              <input
                id="interview-time"
                type="datetime-local"
                value={when}
                onChange={(event) => setWhen(event.target.value)}
              />
            </div>
          </div>
          <div className="row">
            <button className="button" onClick={save} disabled={busy || !when}>
              {interviews.length > 0 ? "Schedule a new interview" : "Schedule interview"}
            </button>
          </div>
        </>
      )}
      {error && <p className="error">{error}</p>}
    </div>
  );
}