import type { HiringSummary } from "../types";

export type JobStage = "screening" | "invitations" | "interviews" | "report" | "onboarding";

// The five stages of one job, from CV screening to onboarding, as one strip of tabs. Each shows how
// far that stage has got; a click opens it below.
export default function JobStageBar({
  summary,
  stage,
  onPick,
}: {
  summary: HiringSummary | null;
  stage: JobStage;
  onPick: (stage: JobStage) => void;
}) {
  const rounds = summary?.rounds ?? [];
  const current = rounds.find((r) => r.state !== "closed") ?? rounds[rounds.length - 1];
  const allClosed = rounds.length > 0 && rounds.every((r) => r.state === "closed");
  const emails = summary?.emails;

  const steps: { value: JobStage; label: string; text: string; done: boolean }[] = [
    {
      value: "screening",
      label: "CV screening",
      text: summary ? `${summary.passed_screening} of ${summary.cvs} passed` : "…",
      done: !!summary && summary.screened > 0,
    },
    {
      value: "invitations",
      label: "Invitations",
      text: emails ? `${emails.sent} sent${emails.failed ? ` · ${emails.failed} failed` : ""}${emails.queued ? ` · ${emails.queued} sending` : ""}` : "…",
      done: !!emails && emails.total > 0,
    },
    {
      value: "interviews",
      label: "Interviews",
      text: !current
        ? "…"
        : allClosed
          ? `All ${rounds.length} round${rounds.length === 1 ? "" : "s"} closed`
          : current.state === "not_started"
            ? `Round ${current.number} not started`
            : `Round ${current.number} of ${rounds.length}: ${current.held} of ${current.invited} held`,
      done: allClosed,
    },
    {
      value: "report",
      label: "Report",
      text: summary ? `${summary.finalists} passed all rounds${summary.undecided ? ` · ${summary.undecided} to decide` : ""}` : "…",
      done: !!summary && summary.finalists > 0 && summary.undecided === 0,
    },
    {
      value: "onboarding",
      label: "Onboarding",
      text: summary ? `${summary.selected} selected · ${summary.verified} verified` : "…",
      done: !!summary && summary.selected > 0 && summary.verified === summary.selected,
    },
  ];

  return (
    <ol className="steps glass stage-bar" role="tablist" aria-label="Hiring stages">
      {steps.map((step, index) => (
        <li key={step.value} className={`${step.done ? "done" : ""}${stage === step.value ? " current" : ""}`}>
          <button type="button" role="tab" aria-selected={stage === step.value} onClick={() => onPick(step.value)}>
            <span className="step-dot" aria-hidden="true">
              {step.done ? "✓" : index + 1}
            </span>
            <span className="step-text">
              <strong>{step.label}</strong>
              <span>{step.text}</span>
            </span>
          </button>
        </li>
      ))}
    </ol>
  );
}
