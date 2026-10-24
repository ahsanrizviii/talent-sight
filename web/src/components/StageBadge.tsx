import type { Stage } from "../types";

// Where a candidate stands, in one word, so a whole pipeline can be read down a column.
const LABELS: Record<Stage, string> = {
  new: "Waiting to screen",
  screened: "Passed screening",
  excluded: "Excluded",
  interview: "Interview booked",
  interviewed: "Interviewed",
  finalist: "Passed all rounds",
  onboarding: "Selected",
  rejected: "Not progressed",
  problem: "Needs a look",
};

export default function StageBadge({ stage }: { stage: Stage }) {
  return <span className={`stage stage-${stage}`}>{LABELS[stage] ?? stage}</span>;
}

export function stageLabel(stage: Stage): string {
  return LABELS[stage] ?? stage;
}
