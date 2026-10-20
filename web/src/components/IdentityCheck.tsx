import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { IdentityState } from "../types";

// The interviewer's identity box in the interview room (Module 13, F7). Interviewer only (N9).
// The human check is the real one: the interviewer looks at the photo ID on camera and compares the
// name with the CV. Face matching is only extra, and only with the candidate's consent.
export default function IdentityCheck({ sessionId }: { sessionId: number }) {
  const [state, setState] = useState<IdentityState | null>(null);
  const [idChecked, setIdChecked] = useState(false);
  const [nameMatches, setNameMatches] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(
    () =>
      api<IdentityState>(`/interviews/${sessionId}/identity`)
        .then(setState)
        .catch((err) => setError(err.message)),
    [sessionId],
  );

  // Checked every 15 seconds, so the consent answer and the pictures taken show up during the call.
  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 15000);
    return () => window.clearInterval(timer);
  }, [load]);

  const savedChecked = state?.id_checked ?? false;
  const savedName = state?.name_matches ?? false;
  useEffect(() => {
    setIdChecked(savedChecked);
    setNameMatches(savedName);
  }, [savedChecked, savedName]);

  async function save() {
    setSaving(true);
    setError("");
    try {
      setState(
        await api<IdentityState>(`/interviews/${sessionId}/identity/id-check`, {
          method: "POST",
          body: JSON.stringify({ id_checked: idChecked, name_matches: idChecked && nameMatches }),
        }),
      );
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  }

  if (!state) {
    return <aside className="card glass panel">{error ? <p className="error small">{error}</p> : <p className="muted small">Loading identity…</p>}</aside>;
  }

  const changed = idChecked !== state.id_checked || (idChecked && nameMatches) !== state.name_matches;
  const consent =
    state.consent === null
      ? "the candidate has not answered yet."
      : state.consent
        ? `agreed; ${state.templates} of 3 pictures taken (kept as numbers only).`
        : "the candidate said no. Rely on the photo ID.";

  return (
    <aside className="card glass panel identity-panel">
      <h2>Identity</h2>
      {state.state === "confirmed" ? (
        <p className="success small">Photo ID checked and the name matches{state.checked_by ? ` (${state.checked_by})` : ""}.</p>
      ) : (
        <div className="notice stop small">
          {state.state === "name_mismatch"
            ? "The name on the photo ID does not match the CV. Ask the candidate about it before going on."
            : "Identity not confirmed yet. Ask the candidate to hold their photo ID up to the camera and compare the name with the CV."}
        </div>
      )}
      <label className="id-check">
        <input
          type="checkbox"
          checked={idChecked}
          onChange={(event) => {
            setIdChecked(event.target.checked);
            if (!event.target.checked) setNameMatches(false);
          }}
        />
        I saw the candidate’s photo ID on camera
      </label>
      <label className="id-check">
        <input type="checkbox" checked={nameMatches} disabled={!idChecked} onChange={(event) => setNameMatches(event.target.checked)} />
        The name on the ID matches the CV
      </label>
      <button className="button small" onClick={() => void save()} disabled={saving || !changed}>
        {saving ? "Saving…" : "Save"}
      </button>
      <p className="muted small identity-consent">Face matching: {consent}</p>
      {error && <p className="error small">{error}</p>}
    </aside>
  );
}