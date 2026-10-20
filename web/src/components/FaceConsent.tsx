import { useState } from "react";
import { api } from "../api";
import type { CandidateIdentity } from "../types";

// The candidate's choice about face matching, on their join page (Module 13, F7). Saying no is an
// equal choice and does not affect the interview. Only numbers are kept, never a photo (N16, N17).
type Props = { token: string; identity: CandidateIdentity; onChange: (next: CandidateIdentity) => void };

export default function FaceConsent({ token, identity, onChange }: Props) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function answer(consent: boolean) {
    setSaving(true);
    setError("");
    try {
      onChange(await api<CandidateIdentity>(`/invite/${token}/identity/consent`, { method: "POST", body: JSON.stringify({ consent }) }));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="consent-box">
      <h2>Identity check</h2>
      <p>During the interview, the interviewer will ask you to show a photo ID (national ID card or passport) to the camera.</p>
      <p>
        With your agreement, TalentSight also keeps a <strong>face template</strong> from three moments of this call. It is
        a list of numbers made from your face, never a photo. If you are hired, it is used once on your first working day
        to confirm that the same person joined. It is deleted after that check, after {identity.retention_days} days, or at
        once if you ask, whichever comes first.
      </p>
      <p className="muted small">Saying no does not affect your interview in any way.</p>
      {identity.consent === null ? (
        <div className="row consent-buttons">
          <button className="button" onClick={() => void answer(true)} disabled={saving}>
            I agree
          </button>
          <button className="button secondary" onClick={() => void answer(false)} disabled={saving}>
            Continue without it
          </button>
        </div>
      ) : (
        <p className="small">
          {identity.consent ? "You agreed to face matching." : "You chose not to use face matching."}{" "}
          <button className="button secondary small" onClick={() => void answer(!identity.consent)} disabled={saving}>
            {identity.consent ? "Withdraw my agreement" : "I agree after all"}
          </button>
        </p>
      )}
      {error && <p className="error small">{error}</p>}
    </div>
  );
}