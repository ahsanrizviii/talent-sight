import type { Speaker, TranscriptSegment } from "../types";

// The lines of a transcript: time since the start, who spoke, what they said (Module 8).
// Used live in the interview room (Task 8.2.2) and after the interview (Task 8.2.3).

// 75 000 ms -> "01:15"; past an hour -> "1:02:03" (Q&A 31: elapsed time).
export function elapsed(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const hours = Math.floor(total / 3600);
  const two = (n: number) => String(n).padStart(2, "0");
  const clock = `${two(Math.floor((total % 3600) / 60))}:${two(total % 60)}`;
  return hours ? `${hours}:${clock}` : clock;
}

// Words someone is still saying: shown in grey, not saved yet.
export type Previews = Partial<Record<Speaker, { text: string; start_ms: number }>>;

type Props = {
  segments: TranscriptSegment[];
  candidateName: string;
  previews?: Previews;
};

export default function TranscriptLines({ segments, candidateName, previews = {} }: Props) {
  const name = (speaker: Speaker) => (speaker === "interviewer" ? "Interviewer" : candidateName || "Candidate");
  const speaking = (["interviewer", "candidate"] as const).filter((speaker) => previews[speaker]?.text);

  return (
    <ol className="transcript-lines">
      {segments.map((segment) => (
        <li key={segment.id} className={`transcript-line ${segment.speaker}`}>
          <span className="transcript-time">{elapsed(segment.start_ms)}</span>
          <div>
            <span className="transcript-speaker">{name(segment.speaker)}</span>
            <span className="transcript-text">{segment.text}</span>
          </div>
        </li>
      ))}
      {speaking.map((speaker) => (
        <li key={`preview-${speaker}`} className={`transcript-line ${speaker} preview`}>
          <span className="transcript-time">{elapsed(previews[speaker]!.start_ms)}</span>
          <div>
            <span className="transcript-speaker">{name(speaker)}</span>
            <span className="transcript-text">{previews[speaker]!.text}…</span>
          </div>
        </li>
      ))}
    </ol>
  );
}