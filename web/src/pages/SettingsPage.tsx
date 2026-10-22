import { useEffect, useState, type FormEvent } from "react";

import { api } from "../api";
import Breadcrumbs from "../components/Breadcrumbs";
import type { CompanySettings, SetupCheck } from "../types";

// Settings, opened from the account menu: the company details every e-mail and calendar entry uses,
// and a check that e-mail, the public link, video and the calendar really work. Secrets such as
// passwords and API keys are never shown or changed here: they stay in the .env file.
export default function SettingsPage() {
  return (
    <>
      <Breadcrumbs items={[{ label: "Dashboard", to: "/" }, { label: "Settings" }]} />
      <div className="page-head">
        <div>
          <h1>Settings</h1>
          <p>Your company details, and whether every connected service is working.</p>
        </div>
      </div>
      <div className="settings-grid">
        <CompanyForm />
        <div>
          <SetupChecks />
          <TestEmail />
        </div>
      </div>
    </>
  );
}

function CompanyForm() {
  const [form, setForm] = useState<CompanySettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    api<CompanySettings>("/company")
      .then(setForm)
      .catch((err) => setError(err.message));
  }, []);

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!form) return;
    setSaving(true);
    setMessage("");
    setError("");
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
      setMessage("Saved. New e-mails and calendar entries use these details.");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  }

  if (!form) return <section className="card glass">{error ? <p className="error">{error}</p> : <p className="muted">Loading…</p>}</section>;

  const change = (key: keyof CompanySettings) => (event: { target: { value: string } }) =>
    setForm({ ...form, [key]: event.target.value });

  return (
    <section className="card glass">
      <h2>Company</h2>
      <form onSubmit={save}>
        <div className="field">
          <label htmlFor="company_name">Company name</label>
          <input id="company_name" value={form.company_name} onChange={change("company_name")} required minLength={2} />
        </div>
        <div className="field">
          <label htmlFor="sender_name">Sender name in e-mails</label>
          <input id="sender_name" value={form.sender_name} onChange={change("sender_name")} placeholder={`${form.company_name} Hiring`} />
          <span className="hint">Empty means “{form.company_name} Hiring”.</span>
        </div>
        <div className="field">
          <label htmlFor="contact_name">Contact person</label>
          <input id="contact_name" value={form.contact_name} onChange={change("contact_name")} />
        </div>
        <div className="field">
          <label htmlFor="contact_email">Contact e-mail</label>
          <input id="contact_email" type="email" value={form.contact_email} onChange={change("contact_email")} />
          <span className="hint">Shown to candidates for questions about their interview.</span>
        </div>
        <p className="muted small">
          Candidates see: <strong>{form.from_line || "e-mail is switched off"}</strong>
          {form.sending_address && ` (the mailbox is set in the .env file)`}
        </p>
        <button className="button" type="submit" disabled={saving}>
          {saving ? "Saving…" : "Save"}
        </button>
        {message && <p className="success small">{message}</p>}
        {error && <p className="error small">{error}</p>}
      </form>
    </section>
  );
}

function SetupChecks() {
  const [checks, setChecks] = useState<SetupCheck[] | null>(null);
  const [testing, setTesting] = useState(false);
  const [tested, setTested] = useState(false);
  const [error, setError] = useState("");

  function run(probe: boolean) {
    setError("");
    if (probe) setTesting(true);
    api<SetupCheck[]>(`/setup/checks?probe=${probe}`)
      .then((found) => {
        setChecks(found);
        if (probe) setTested(true);
      })
      .catch((err) => setError(err.message))
      .finally(() => setTesting(false));
  }

  useEffect(() => run(false), []);

  return (
    <section className="card glass">
      <div className="row between">
        <h2>Connected services</h2>
        <button className="button secondary small" type="button" onClick={() => run(true)} disabled={testing}>
          {testing ? "Testing…" : "Test the connections"}
        </button>
      </div>
      <p className="muted small">
        {tested ? "Each service was really contacted just now." : "Read from the settings. Test the connections to really contact each one."}
      </p>
      {error && <p className="error small">{error}</p>}
      {!checks ? (
        <p className="muted small">Loading…</p>
      ) : (
        <ul className="checks">
          {checks.map((check) => (
            <li key={check.key}>
              <span className={`badge ${check.ok ? "pass" : check.optional ? "" : "stop"}`}>
                {check.ok ? "Working" : check.optional ? "Off" : "Not working"}
              </span>
              <div>
                <strong>{check.label}</strong>
                {check.optional && <span className="muted small"> · optional</span>}
                <p className="small muted">{check.detail}</p>
                {!check.ok && check.fix && <p className="small">{check.fix}</p>}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function TestEmail() {
  const [to, setTo] = useState("");
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState<{ sent: boolean; error: string } | null>(null);

  async function send(event: FormEvent) {
    event.preventDefault();
    setSending(true);
    setResult(null);
    try {
      setResult(await api<{ sent: boolean; error: string }>("/setup/test-email", { method: "POST", body: JSON.stringify({ to }) }));
    } catch (err) {
      setResult({ sent: false, error: (err as Error).message });
    } finally {
      setSending(false);
    }
  }

  return (
    <section className="card glass">
      <h2>Send a test e-mail</h2>
      <form className="row" onSubmit={send}>
        <input type="email" value={to} onChange={(event) => setTo(event.target.value)} placeholder="you@company.com" required aria-label="Send the test to" />
        <button className="button secondary" type="submit" disabled={sending || to.length < 3}>
          {sending ? "Sending…" : "Send"}
        </button>
      </form>
      {result && (result.sent ? <p className="success small">Sent. Check the inbox.</p> : <p className="error small">{result.error}</p>)}
    </section>
  );
}
