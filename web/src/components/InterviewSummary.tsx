import type { Interview } from "../types";

// The top of the interview card: what state the interview is in and, once it has run,
// when it ran, how long it took and who took part.

type Visit = Interview["participants"][number];

const clock = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
const day = (iso: string) => new Date(iso).toLocaleDateString([], { weekday: "short", day: "numeric", month: "short", year: "numeric" });

function minutesText(seconds: number): string {
  const minutes = Math.max(1, Math.round(seconds / 60));
  if (minutes < 60) return `${minutes} min`;
  const rest = minutes % 60;
  return `${Math.floor(minutes / 60)} h${rest ? ` ${rest} min` : ""}`;
}

// Who took part: just the names. Someone who never came in is marked so.
function Attendance({ interview }: { interview: Interview }) {
  const people: { label: string; role: Visit["role"] }[] = [
    { label: interview.candidate_name || "Candidate", role: "candidate" },
    { label: "Interviewer", role: "interviewer" },
  ];
  return (
    <ul className="people-list">
      {people.map(({ label, role }) => {
        const came = interview.participants.some((v) => v.role === role);
        return (
          <li key={role} className={came ? "" : "muted"}>
            {label}
            {!came && " (did not join)"}
          </li>
        );
      })}
    </ul>
  );
}

export default function InterviewSummary({ interview }: { interview: Interview }) {
  if (interview.status === "scheduled") {
    return (
      <div className="interview-head">
        <span className="badge accent">Scheduled</span>
        <span>
          {day(interview.scheduled_at)}, {clock(interview.scheduled_at)}
        </span>
      </div>
    );
  }

  if (interview.status === "live") {
    return (
      <>
        <div className="interview-head">
          <span className="badge live">Live now</span>
          {interview.started_at && <span>Started at {clock(interview.started_at)}</span>}
        </div>
        {interview.participants.length > 0 && <Attendance interview={interview} />}
      </>
    );
  }

  // Ended. With no start time, it was cancelled before anyone came in.
  if (!interview.started_at) {
    return (
      <div className="interview-head">
        <span className="badge stop">Cancelled</span>
        <span className="muted">
          Was planned for {day(interview.scheduled_at)}, {clock(interview.scheduled_at)}
        </span>
      </div>
    );
  }

  return (
    <>
      <div className="interview-head">
        <span className="badge pass">Completed</span>
      </div>
      <dl className="facts">
        <div>
          <dt>Date</dt>
          <dd>{day(interview.started_at)}</dd>
        </div>
        <div>
          <dt>Time</dt>
          <dd>
            {clock(interview.started_at)}
            {interview.ended_at && ` – ${clock(interview.ended_at)}`}
          </dd>
        </div>
        <div>
          <dt>Length</dt>
          <dd>{interview.duration_seconds !== null ? minutesText(interview.duration_seconds) : "—"}</dd>
        </div>
      </dl>
      {interview.participants.length > 0 && (
        <>
          <h3 className="mini-head">Who was there</h3>
          <Attendance interview={interview} />
        </>
      )}
    </>
  );
}
