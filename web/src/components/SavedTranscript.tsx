import { useEffect, useState } from "react";
import { api } from "../api";
import type { Transcript } from "../types";
import TranscriptLines from "./TranscriptLines";

// The full transcript after the interview (Task 8.2.3). Interviewer only.
// Only text is kept: the audio itself was never stored (N16).
// startOpen is used where the reader already asked to see it, such as the Interviews page.
export default function SavedTranscript({
  sessionId,
  candidateName = "Candidate",
  startOpen = false,
}: {
  sessionId: number;
  candidateName?: string;
  startOpen?: boolean;
}) {
  const [transcript, setTranscript] = useState<Transcript | null>(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(startOpen);

  useEffect(() => {
    setTranscript(null);
    api<Transcript>(`/interviews/${sessionId}/transcript`)
      .then(setTranscript)
      .catch((err) => setError(err.message));
  }, [sessionId]);

  if (error) return <p className="error small">{error}</p>;
  if (!transcript) return <p className="muted small">Loading the transcript…</p>;
  if (transcript.segments.length === 0) {
    return <p className="muted small">No transcript: nothing was recognised in this interview.</p>;
  }

  return (
    <div className="saved-transcript">
      <div className="row between">
        <h3>Transcript ({transcript.segments.length} lines)</h3>
        <button className="button secondary small" onClick={() => setOpen(!open)}>
          {open ? "Hide transcript" : "Show transcript"}
        </button>
      </div>
      {open && (
        <div className="transcript-box tall">
          <TranscriptLines segments={transcript.segments} candidateName={candidateName} />
        </div>
      )}
    </div>
  );
}
