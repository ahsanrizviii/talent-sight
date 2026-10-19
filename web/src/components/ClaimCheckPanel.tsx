import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { CheckedClaim, ClaimCheck, ClaimStatus } from "../types";
import "../assessment.css";
import "../claims.css";

// CV claims checked against the interview (Module 13, F8). Interviewer only (N9).
// Each claim from the CV gets one of four results, kept clearly apart: backed up, a possible
// contradiction, mentioned but not shown, or not discussed. They are prompts for a person to
// follow up, never accusations, and they never change the score or the position.

const TONE: Record<ClaimStatus, string> = {
  contradicted: "stop",
  unsubstantiated: "warn",
  not_discussed: "quiet",
  supported: "pass",
};

const ORDER: ClaimStatus[] = ["contradicted", "unsubstantiated", "not_discussed", "supported"];

const NAMES: Record<ClaimStatus, string> = {
  contradicted: "Possible contradiction",
  unsubstantiated: "Mentioned, not shown",
  not_discussed: "Not discussed",
  supported: "Backed up",
};

const KINDS = { role: "Role", experience: "Experience", project: "Project", certification: "Certification", skill: "Skill" };

export default function ClaimCheckPanel({ candidateId }: { candidateId: number }) {
  const [check, setCheck] = useState<ClaimCheck | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const [starting, setStarting] = useState(false);
  const [only, setOnly] = useState<ClaimStatus | null>(null);

  const load = useCallback(
    () =>
      api<ClaimCheck | null>(`/candidates/${candidateId}/claim-check`)
        .then((found) => {
          setCheck(found);
          setLoaded(true);
        })
        .catch((err) => setError(err.message)),
    [candidateId],
  );

  useEffect(() => {
    setCheck(null);
    setLoaded(false);
    setOnly(null);
    load();
  }, [load]);

  // While the agent works, ask every 2 seconds how far it is.
  const running = check?.status === "running";
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(load, 2000);
    return () => window.clearInterval(timer);
  }, [running, load]);

  async function start() {
    setStarting(true);
    setError("");
    try {
      setCheck(await api<ClaimCheck>(`/candidates/${candidateId}/claim-check`, { method: "POST" }));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setStarting(false);
    }
  }

  if (!loaded && !error) return <p className="muted small">Loading the claim check…</p>;

  const done = check?.status === "done" ? check : null;
  const shown = done ? done.claims.filter((claim) => !only || claim.status === only) : [];

  return (
    <section className="card glass assessment">
      <div className="row between">
        <div>
          <h2>CV claims</h2>
          <p className="muted small" style={{ margin: 0 }}>
            What the CV says, compared with what the candidate said in the interview.
          </p>
        </div>
        <button className="button" onClick={start} disabled={running || starting}>
          {running ? "Checking…" : check ? "Check again" : "Check CV claims"}
        </button>
      </div>

      <p className="cl-promise">
        These are prompts for you to follow up. They are not accusations, and they never change the score, the
        assessment or the candidate’s stage.
      </p>

      {!check && (
        <p className="muted small">
          Needs a screened candidate and an analysed interview (Interview tab, “Analyse answers”). The roles, projects,
          certifications, total experience and job skills in the CV are each compared with the candidate’s own words.
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
        <div className="notice">The interview answers were analysed again after this check. Check again to update it.</div>
      )}

      {done && (
        <>
          <div className="cl-counts" role="group" aria-label="Show only">
            {ORDER.map((status) => (
              <button
                key={status}
                type="button"
                className={`cl-count ${TONE[status]}`}
                aria-pressed={only === status}
                onClick={() => setOnly(only === status ? null : status)}
              >
                <strong>{done.summary[status] ?? 0}</strong>
                <span>{NAMES[status]}</span>
              </button>
            ))}
          </div>

          {shown.length === 0 && <p className="muted small">No claims with this result.</p>}
          <ul className="cl-list">
            {shown.map((claim) => (
              <ClaimLine key={claim.id} claim={claim} turns={done.turns} />
            ))}
          </ul>

          <p className="muted small as-foot">
            {done.summary.claims} claims checked
            {done.finished_at && ` · ${new Date(done.finished_at).toLocaleString()}`}. Quotes are the candidate’s own
            words from the saved transcript.
          </p>
        </>
      )}
    </section>
  );
}

function ClaimLine({ claim, turns }: { claim: CheckedClaim; turns: ClaimCheck["turns"] }) {
  const [open, setOpen] = useState(false);
  const others = claim.turns.filter((n) => n !== claim.evidence?.turn);
  const byN = new Map(turns.map((turn) => [turn.n, turn]));

  return (
    <li className={`cl-item ${TONE[claim.status]}`}>
      <div className="cl-head">
        <span className={`badge ${TONE[claim.status] === "quiet" ? "" : TONE[claim.status]}`}>{claim.label}</span>
        <span className="muted small">{KINDS[claim.kind]}</span>
      </div>
      <p className="cl-claim">{claim.claim}</p>
      <p className="small cl-note">{claim.note}</p>

      {claim.evidence && (
        <blockquote className="cl-quote">
          “{claim.evidence.quote}”<span className="muted small"> · candidate, at {claim.evidence.at}</span>
        </blockquote>
      )}

      {claim.follow_up && (
        <p className="cl-follow">
          <span>Ask in a follow-up</span> {claim.follow_up}
        </p>
      )}

      {others.length > 0 && (
        <>
          <button type="button" className="cl-more" onClick={() => setOpen(!open)} aria-expanded={open}>
            {open ? "Hide" : "Show"} the other {others.length === 1 ? "turn" : `${others.length} turns`} that were compared
          </button>
          {open && (
            <ul className="cl-turns">
              {others.map((n) => {
                const turn = byN.get(n);
                return turn ? (
                  <li key={n}>
                    <span className="muted small">{clock(turn.start_ms)}</span> {turn.text}
                  </li>
                ) : null;
              })}
            </ul>
          )}
        </>
      )}
    </li>
  );
}

function clock(ms: number): string {
  const seconds = Math.max(0, Math.floor(ms / 1000));
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}