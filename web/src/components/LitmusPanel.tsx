import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import "../assessment.css";
import "../claims.css";
import "../litmus.css";

// Litmus (F11): does this CV score rest on the CV, or on who the candidate is?
// Copies of the profile with one identity detail changed are scored again by the same AI, and plain
// code compares the scores. A result that is not steady waits for a person to acknowledge it.
// Interviewer only (N9). It never changes the score, the verdicts, the ranking or the stage.

export type LitmusOutcome = "steady" | "needs_review" | "inconclusive";

export type LitmusCopy = {
  key: string;
  label: string;
  changed: string;
  applicable: boolean;
  overall?: number | null;
  excluded?: boolean;
  overall_change?: number | null;
  dimension_changes?: Record<string, number>;
  verdict_changes?: { requirement: string; mandatory: boolean; from: string; to: string; within_noise: boolean }[];
  flagged?: boolean;
  reasons?: string[];
};

type RunSummary = { overall: number | null; scores: Record<string, number>; excluded: boolean };

export type LitmusCheck = {
  id: number;
  candidate_id: number;
  status: "queued" | "running" | "done" | "failed";
  step: string;
  error: string;
  started_at: string;
  finished_at: string | null;
  seconds: number | null;
  outdated: boolean;
  result: {
    outcome?: LitmusOutcome;
    flag_count?: number;
    reference?: RunSummary;
    repeat?: RunSummary;
    noise?: { dimensions: Record<string, number>; overall: number; gate_changed: boolean; noisy: boolean };
    variants?: LitmusCopy[];
    audit?: { model: string; prompt_version: string; temperature: number; seed: number };
  };
  review_status: "" | "pending" | "acknowledged";
  review_note: string;
  reviewed_by: string;
  reviewed_at: string | null;
  llm_calls: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
};

type HistoryItem = { id: number; status: string; outcome: string; review_status: string; started_at: string; cost_usd: number };

export const OUTCOMES: Record<LitmusOutcome, { label: string; tone: string; text: string }> = {
  steady: {
    label: "Steady",
    tone: "pass",
    text: "No copy moved more than chance allows. On this evidence, the score rests on the CV.",
  },
  needs_review: {
    label: "Needs review",
    tone: "warn",
    text: "At least one copy moved more than chance allows. Read the reasons below and acknowledge them.",
  },
  inconclusive: {
    label: "Inconclusive",
    tone: "",
    text: "The unchanged profile itself moved too much between two runs, so this check cannot tell an effect from chance.",
  },
};

const DIMENSIONS: Record<string, string> = {
  technical_skills: "Technical skills",
  experience: "Experience",
  qualifications: "Qualifications",
  jd_match: "JD match",
};

const VERDICTS: Record<string, string> = { met: "met", partially_met: "partly met", unmet: "unmet" };

export function signed(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  if (value === 0) return "0";
  return `${value > 0 ? "+" : "−"}${Math.abs(value)}`;
}

export default function LitmusPanel({ candidateId }: { candidateId: number }) {
  const [check, setCheck] = useState<LitmusCheck | null>(null);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const [starting, setStarting] = useState(false);

  const load = useCallback(
    () =>
      Promise.all([
        api<LitmusCheck | null>(`/candidates/${candidateId}/litmus`),
        api<HistoryItem[]>(`/candidates/${candidateId}/litmus/history`),
      ])
        .then(([found, earlier]) => {
          setCheck(found);
          setHistory(earlier);
          setLoaded(true);
        })
        .catch((err) => {
          setError(err.message);
          setLoaded(true);
        }),
    [candidateId],
  );

  useEffect(() => {
    setCheck(null);
    setLoaded(false);
    void load();
  }, [load]);

  // While the check works (or waits in the shortlist queue), ask every 2 seconds how far it is.
  const running = check?.status === "running" || check?.status === "queued";
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => void load(), 2000);
    return () => window.clearInterval(timer);
  }, [running, load]);

  async function start() {
    setStarting(true);
    setError("");
    try {
      setCheck(await api<LitmusCheck>(`/candidates/${candidateId}/litmus`, { method: "POST" }));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setStarting(false);
    }
  }

  if (!loaded && !error) return <p className="muted small">Loading Litmus…</p>;

  const done = check?.status === "done" ? check : null;
  const outcome = done?.result.outcome ? OUTCOMES[done.result.outcome] : null;
  const earlier = history.filter((item) => item.id !== check?.id);

  return (
    <section className="card glass assessment">
      <div className="row between">
        <div>
          <h2>Litmus</h2>
          <p className="muted small" style={{ margin: 0 }}>
            Does this CV score rest on the CV, or on who the candidate is?
          </p>
        </div>
        <button className="button" onClick={start} disabled={running || starting}>
          {running ? "Checking…" : check ? "Check again" : "Run Litmus"}
        </button>
      </div>

      <p className="cl-promise">
        Copies of the profile, each with one identity detail changed, are scored again by the same AI. Plain code
        compares the scores. Litmus never changes the score, the verdicts or the candidate’s stage.
      </p>

      {!check && (
        <p className="muted small">
          Needs a screened candidate. A check makes about 12 AI calls; what it used and cost is shown with the result.
        </p>
      )}
      {error && <p className="error small">{error}</p>}
      {running && (
        <p className="as-step">
          <span className="as-spinner" aria-hidden="true" />
          {check?.step || "Working"}…
        </p>
      )}
      {check?.status === "failed" && <p className="error small">{check.error}</p>}
      {done?.outdated && (
        <div className="notice">
          The candidate was screened again, or the job or its weights changed, after this check. Check again to update it.
        </div>
      )}

      {done && outcome && (
        <>
          <div className={`pl-outcome ${outcome.tone}`}>
            <span className={`badge ${outcome.tone}`}>{outcome.label}</span>
            <p>{outcome.text}</p>
          </div>

          <Noise check={done} />

          <table className="pl-table wide">
            <thead>
              <tr>
                <th>Copy</th>
                <th>What changed</th>
                <th className="right">Score</th>
                <th className="right">Change</th>
                <th>Result</th>
              </tr>
            </thead>
            <tbody>
              <tr className="pl-reference">
                <td>Unchanged profile</td>
                <td className="muted small">Nothing (the reference)</td>
                <td className="right num">{shown(done.result.reference)}</td>
                <td className="right num">—</td>
                <td />
              </tr>
              {(done.result.variants ?? []).map((copy) => (
                <CopyRow key={copy.key} copy={copy} />
              ))}
            </tbody>
          </table>

          <Review check={done} onSaved={(saved) => setCheck(saved)} />

          <p className="muted small as-foot">
            {done.llm_calls} AI calls · {(done.input_tokens + done.output_tokens).toLocaleString()} tokens · $
            {done.cost_usd.toFixed(4)}
            {done.seconds !== null && ` · ${Math.round(done.seconds)} s`}
            {done.result.audit && ` · ${done.result.audit.model} · prompt ${done.result.audit.prompt_version}`}
            {done.finished_at && ` · ${new Date(done.finished_at).toLocaleString()}`}
          </p>
        </>
      )}

      {earlier.length > 0 && (
        <details className="pl-history">
          <summary className="muted small">
            {earlier.length} earlier {earlier.length === 1 ? "check" : "checks"} (kept, never rewritten)
          </summary>
          <ul>
            {earlier.map((item) => (
              <li key={item.id} className="small">
                {new Date(item.started_at).toLocaleString()} ·{" "}
                {item.outcome ? OUTCOMES[item.outcome as LitmusOutcome]?.label ?? item.outcome : item.status}
                {item.review_status === "acknowledged" && " · acknowledged"} · ${item.cost_usd.toFixed(4)}
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}

function shown(run: RunSummary | { overall?: number | null; excluded?: boolean } | undefined): string {
  if (!run) return "—";
  if (run.excluded) return "Excluded";
  return run.overall === null || run.overall === undefined ? "—" : String(run.overall);
}

function Noise({ check }: { check: LitmusCheck }) {
  const noise = check.result.noise;
  if (!noise) return null;
  const widest = Math.max(0, ...Object.values(noise.dimensions));
  return (
    <p className="small pl-noise">
      <strong>Chance band.</strong> The unchanged profile was scored twice. It moved by {widest} points at most on one
      dimension ({noise.overall} overall)
      {noise.gate_changed ? ", and the must-have check changed between the two runs" : ""}. A copy is flagged only when
      it moves more than that plus one 5-point step.
    </p>
  );
}

function CopyRow({ copy }: { copy: LitmusCopy }) {
  if (!copy.applicable) {
    return (
      <tr className="pl-skip">
        <td>{copy.label}</td>
        <td className="muted small" colSpan={4}>
          Not applicable: the CV has nothing to change for this copy, so it was not run.
        </td>
      </tr>
    );
  }
  const moved = Object.entries(copy.dimension_changes ?? {}).filter(([, delta]) => delta !== 0);
  const verdicts = copy.verdict_changes ?? [];
  return (
    <>
      <tr className={copy.flagged ? "pl-flagged" : ""}>
        <td>{copy.label}</td>
        <td className="muted small">{copy.changed}</td>
        <td className="right num">{shown(copy)}</td>
        <td className={`right num pl-delta ${(copy.overall_change ?? 0) < 0 ? "down" : (copy.overall_change ?? 0) > 0 ? "up" : ""}`}>
          {signed(copy.overall_change)}
        </td>
        <td>
          <span className={`badge ${copy.flagged ? "warn" : "pass"}`}>{copy.flagged ? "Flagged" : "Steady"}</span>
        </td>
      </tr>
      {(copy.flagged || moved.length > 0 || verdicts.length > 0) && (
        <tr className="pl-detail">
          <td />
          <td colSpan={4}>
            {copy.reasons && copy.reasons.length > 0 && (
              <ul className="pl-reasons">
                {copy.reasons.map((reason, index) => (
                  <li key={index}>{reason}</li>
                ))}
              </ul>
            )}
            {moved.length > 0 && (
              <p className="muted small">
                Moved: {moved.map(([key, delta]) => `${DIMENSIONS[key] ?? key} ${signed(delta)}`).join(" · ")}
              </p>
            )}
            {verdicts.length > 0 && (
              <p className="muted small">
                Verdicts:{" "}
                {verdicts
                  .map(
                    (v) =>
                      `${v.requirement} ${VERDICTS[v.from]} → ${VERDICTS[v.to]}${v.within_noise ? " (also moved by chance)" : ""}`,
                  )
                  .join(" · ")}
              </p>
            )}
          </td>
        </tr>
      )}
    </>
  );
}

function Review({ check, onSaved }: { check: LitmusCheck; onSaved: (check: LitmusCheck) => void }) {
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  if (check.review_status === "acknowledged") {
    return (
      <div className="pl-review done">
        <strong>Acknowledged</strong> by {check.reviewed_by || "a team member"}
        {check.reviewed_at && ` on ${new Date(check.reviewed_at).toLocaleString()}`}
        <p className="small">{check.review_note}</p>
      </div>
    );
  }
  if (check.review_status !== "pending") return null;

  async function save() {
    setSaving(true);
    setError("");
    try {
      onSaved(await api<LitmusCheck>(`/litmus/${check.id}/review`, { method: "POST", body: JSON.stringify({ note }) }));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="pl-review">
      <label htmlFor={`pl-note-${check.id}`}>
        <strong>Your review.</strong> Say what you looked at and what you will do. This is kept with the check.
      </label>
      <textarea
        id={`pl-note-${check.id}`}
        rows={3}
        value={note}
        onChange={(event) => setNote(event.target.value)}
        placeholder="For example: read the flagged copy; the CV score stands, raised the prompt with the screening owner."
      />
      <div className="row between">
        {error ? <p className="error small">{error}</p> : <span />}
        <button className="button" onClick={save} disabled={saving || note.trim().length < 10}>
          {saving ? "Saving…" : "Acknowledge"}
        </button>
      </div>
    </div>
  );
}
