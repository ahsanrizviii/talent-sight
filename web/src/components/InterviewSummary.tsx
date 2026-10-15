import type { Interview } from "../types";

// The top of the interview card: what state the interview is in and, once it has run,
// who was there and for how long. Replaces the raw "joined ..., left ..." list.

type Visit = Interview["participants"][number];

const clock = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
const day = (iso: string) => new Date(iso).toLocaleDateString([], { weekday: "short", day: "numeric", month: "short", year: "numeric" });

function minutesText(seconds: number): string {
  const minutes = Math.max(1, Math.round(seconds / 60));
  if (minutes < 60) return `${minutes} min`;
  const rest = minutes % 60;
  return `${Math.floor(minutes / 60)} h${rest ? ` ${rest} min` : ""}`;
}

// One line per person: how many times they came in, from when to when, and a small bar
// that shows the moments they were in the room.
function Attendance({ interview }: { interview: Interview }) {
  const visits = interview.participants;
  const end = interview.ended_at ?? new Date().toISOString();
  const times = visits.flatMap((v) => [Date.parse(v.joined_at), Date.parse(v.left_at ?? end)]);
  const from = Math.min(...times);
  const span = Math.max(1, Math.max(...times) - from); // never divide by zero

  const people: { label: string; role: Visit["role"] }[] = [
    { label: interview.candidate_name || "Candidate", role: "candidate" },
    { label: "Interviewer", role: "interviewer" },
  ];

  return (
    <ul className="attendance">
      {people.map(({ label, role }) => {
        const mine = visits.filter((v) => v.role === role);
        if (mine.length === 0) {
          return (
            <li key={role}>
              <span className="who">{label}</span>
              <span className="when muted">Did not join</span>
            </li>
          );
        }
        const first = mine[0].joined_at;
        const last = mine[mine.length - 1].left_at ?? end;
        return (
          <li key={role}>
            <span className="who">{label}</span>
            <span className="when">
              {clock(first)} – {clock(last)}
              {mine.length > 1 && <span className="muted"> · came in {mine.length} times</span>}
            </span>
            <span className="presence" aria-hidden="true">
              {mine.map((v, i) => {
                const left = ((Date.parse(v.joined_at) - from) / span) * 100;
                const width = ((Date.parse(v.left_at ?? end) - Date.parse(v.joined_at)) / span) * 100;
                return <span key={i} className={`stay ${role}`} style={{ left: `${left}%`, width: `${Math.max(width, 2)}%` }} />;
              })}
            </span>
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
