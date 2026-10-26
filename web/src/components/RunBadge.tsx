import type { RunState } from "../types";

// The state of one piece of AI work (an answer analysis, a score, a review, a report) as a small badge.
const LABELS: Record<Exclude<RunState, "">, string> = {
  running: "Working…",
  done: "Done",
  failed: "Failed",
};

export default function RunBadge({ state, label }: { state: RunState; label?: string }) {
  if (!state) return <span className="badge quiet">{label ? `${label}: not run` : "Not run"}</span>;
  const tone = state === "done" ? "pass" : state === "failed" ? "stop" : "accent";
  return <span className={`badge ${tone}`}>{label ? `${label}: ${LABELS[state].toLowerCase()}` : LABELS[state]}</span>;
}
