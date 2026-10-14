import { useEffect, useState, type FormEvent } from "react";

import { api } from "../api";
import Icon from "../components/Icon";
import type { SetupCheck } from "../types";
import "../setup.css";

// Everything an interview depends on, checked for real: this is how the hiring team finds out that
// a candidate on another device can get in, or that an e-mail will arrive, BEFORE inviting anyone.
export default function SetupPage() {
  const [checks, setChecks] = useState<SetupCheck[] | null>(null);
  const [error, setError] = useState("");
  const [testTo, setTestTo] = useState("");
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ sent: boolean; error: string } | null>(null);

  async function run() {
    setChecks(null);
    setError("");
    try {
      setChecks(await api<SetupCheck[]>("/setup/checks"));
    } catch (err) {
      setError((err as Error).message);
    }
  }

  useEffect(() => {
    run();
  }, []);

  async function sendTest(event: FormEvent) {
    event.preventDefault();
    setTesting(true);
    setTestResult(null);
    try {
      setTestResult(
        await api<{ sent: boolean; error: string }>("/setup/test-email", {
          method: "POST",
          body: JSON.stringify({ to: testTo }),
        }),
      );
    } catch (err) {
      setTestResult({ sent: false, error: (err as Error).message });
    } finally {
      setTesting(false);
    }
  }

  const required = checks?.filter((check) => !check.optional) ?? [];
  const ready = checks !== null && required.every((check) => check.ok);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Setup check</h1>
          <p>Each line below really connects to the service, so a green tick means it works.</p>
        </div>
        <button className="button secondary" onClick={run} disabled={checks === null}>
          Check again
        </button>
      </div>

      {error && <p className="error">{error}</p>}

      {checks && (
        <div className={ready ? "card notice" : "card notice stop"}>
          <div>
            {ready
              ? "Everything an interview needs is working. Candidates on any device can join."
              : "Something an interview needs is not working yet. Candidates may not receive the e-mail, or may not be able to join."}
          </div>
        </div>
      )}

      <div className="card glass flush">
        {checks === null && !error && (
          <div style={{ padding: 22 }}>
            <div className="skeleton" />
            <div className="skeleton" />
            <p className="muted small" style={{ marginTop: 12 }}>
              Connecting to each service. This can take a few seconds.
            </p>
          </div>
        )}
        {checks?.map((check) => (
          <div className="check" key={check.key}>
            <span className={check.ok ? "check-mark ok" : check.optional ? "check-mark off" : "check-mark bad"} aria-hidden="true">
              {check.ok ? <Icon name="check" size={15} /> : "!"}
            </span>
            <div className="grow">
              <h3>
                {check.label} {check.optional && <span className="badge">Optional</span>}
              </h3>
              <p className="muted">{check.detail}</p>
              {check.fix && <p className="check-fix">{check.fix}</p>}
            </div>
          </div>
        ))}
      </div>

      <div className="card glass">
        <h2>Send a test e-mail</h2>
        <p className="muted small" style={{ marginBottom: 14 }}>
          Send one to yourself and check it arrives, in the inbox and not in spam. Candidates get their invitation the same way.
        </p>
        <form className="row" onSubmit={sendTest}>
          <input
            className="grow"
            type="email"
            required
            placeholder="you@yourcompany.com"
            value={testTo}
            onChange={(event) => setTestTo(event.target.value)}
            aria-label="E-mail address for the test"
          />
          <button className="button" type="submit" disabled={testing || !testTo}>
            {testing ? "Sending…" : "Send test e-mail"}
          </button>
        </form>
        {testResult?.sent && <p className="success small">Sent. Look in your inbox, and in spam, in the next minute.</p>}
        {testResult && !testResult.sent && <p className="error small">{testResult.error}</p>}
      </div>
    </>
  );
}
