import type { CheckState } from "./types";

// The first-day identity check of a new hire, in words and as a badge colour.
export const CHECK_LABELS: Record<CheckState, string> = {
  waiting: "Not checked yet",
  in_progress: "Check in progress",
  verified: "Verified",
  not_confirmed: "Not confirmed",
  needs_decision: "Needs a person's decision",
};

export const CHECK_TONES: Record<CheckState, string> = {
  waiting: "",
  in_progress: "accent",
  verified: "pass",
  not_confirmed: "stop",
  needs_decision: "warn",
};
