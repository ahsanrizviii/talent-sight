import { useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import HolidaysCard from "../components/HolidaysCard";
import ScheduleCard from "../components/ScheduleCard";
import type { CompanySettings, EmailPreview } from "../types";

// Settings for the company that uses TalentSight: its name and contact (used in every e-mail),
// a live preview of the invitation, and the public holidays that interviews must avoid.
export default function SettingsPage() {
  const [form, setForm] = useState<CompanySettings | null>(null);
  const [preview, setPreview] = useState<EmailPreview | null>(null);
  const [kind, setKind] = useState<"invite" | "cancel">("invite");
  const [version, setVersion] = useState(0); // goes up on every save, so the preview reloads
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    api<CompanySettings>("/company").then(setForm).catch((err) => setError(err.message));
  }, []);

  useEffect(() => {
    api<EmailPreview>(`/company/email-preview?kind=${kind}`).then(setPreview).catch(() => setPreview(null));
  }, [kind, version]);

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!form) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const saved = await api<CompanySettings>("/company", {
        method: "PUT",
        body: JSON.stringify({
          company_name: form.company_name,
          sender_name: form.sender_name,
          contact_name: form.contact_name,
          contact_email: form.contact_email,
        }),
      });
      setForm(saved);
      setVersion((v) => v + 1);
      setMessage("Saved. Every e-mail from now on uses these details.");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const change = (key: keyof CompanySettings) => (event: { target: { value: string } }) =>
    setForm((old) => (old ? { ...old, [key]: event.target.value } : old));

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Settings</h1>
          <p>Your company's details, the invitation e-mail, when interviews may be booked, and the holidays to avoid.</p>
        </div>
      </div>

      <div className="settings-grid">
        <form className="card glass" onSubmit={save}>
          <h2>Company</h2>
          {!form ? (
            <p className="muted">Loading…</p>
          ) : (
            <>
              <div className="field">
                <label htmlFor="company-name">Company name</label>
                <input id="company-name" value={form.company_name} onChange={change("company_name")} required maxLength={120} />
                <span className="hint">Shown in the subject, the e-mail and the calendar entry.</span>
              </div>
              <div className="field">
                <label htmlFor="sender-name">Sender name</label>
                <input id="sender-name" value={form.sender_name} onChange={change("sender_name")} maxLength={120} placeholder={`${form.company_name} Hiring`} />
                <span className="hint">The name candidates see in "From".</span>
              </div>
              <div className="field">
                <label htmlFor="contact-name">Contact person</label>
                <input id="contact-name" value={form.contact_name} onChange={change("contact_name")} maxLength={120} placeholder="e.g. Nadia Islam, HR" />
              </div>
              <div className="field">
                <label htmlFor="contact-email">Contact e-mail</label>
                <input id="contact-email" type="email" value={form.contact_email} onChange={change("contact_email")} placeholder="e.g. hr@yourcompany.com" />
                <span className="hint">Candidates' replies go here, and the e-mail says "For any question, contact …".</span>
              </div>

              <div className="from-box">
                <span className="muted small">Candidates will see</span>
                <strong>{form.from_line || "E-mail is not set up yet"}</strong>
                <span className="muted small">
                  The address after the name is the mailbox in SMTP_USER. To send from an address such as talentsight@yourcompany.com,
                  put that mailbox's SMTP login in .env.
                </span>
              </div>

              <div className="row">
                <button className="button" type="submit" disabled={busy}>
                  Save
                </button>
              </div>
              {message && <p className="success">{message}</p>}
            </>
          )}
          {error && <p className="error">{error}</p>}
        </form>

        <div className="card glass">
          <div className="row between">
            <h2>E-mail preview</h2>
            <div className="tabs" role="tablist" aria-label="Which e-mail">
              <button role="tab" aria-selected={kind === "invite"} onClick={() => setKind("invite")}>
                Invitation
              </button>
              <button role="tab" aria-selected={kind === "cancel"} onClick={() => setKind("cancel")}>
                Cancellation
              </button>
            </div>
          </div>
          {preview ? (
            <>
              <dl className="mail-head">
                <dt>From</dt>
                <dd>{preview.from}</dd>
                {preview.reply_to && (
                  <>
                    <dt>Reply to</dt>
                    <dd>{preview.reply_to}</dd>
                  </>
                )}
                <dt>Subject</dt>
                <dd>{preview.subject}</dd>
              </dl>
              {kind === "invite" && (
                <p className="muted small">
                  {preview.wording === "ai"
                    ? "The AI wrote the subject, the opening and the closing line. The date, time, link and rules are filled in by the system."
                    : "The fixed wording is shown (the AI is off or not available). The date, time, link and rules are filled in by the system."}
                </p>
              )}
              {/* sandbox="": the preview can show the e-mail but can never run anything */}
              <iframe className="mail-preview" title="E-mail preview" sandbox="" srcDoc={preview.html} />
            </>
          ) : (
            <p className="muted">Loading the preview…</p>
          )}
        </div>
      </div>

      <div className="settings-grid lower">
        <ScheduleCard />
        <HolidaysCard />
      </div>
    </>
  );
}
