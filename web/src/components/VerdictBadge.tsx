import type { Verdict } from "../types";

const LABELS = { met: "Met", partially_met: "Partially met", unmet: "Unmet" };

export default function VerdictBadge({ verdict }: { verdict: Verdict["verdict"] }) {
  return <span className={`badge verdict-${verdict}`}>{LABELS[verdict]}</span>;
}