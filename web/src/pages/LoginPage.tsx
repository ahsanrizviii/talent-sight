import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";

import { api } from "../api";
import { saveToken } from "../auth";
import PublicFrame from "../components/PublicFrame";
import type { SignInOptions } from "../types";

type Mode = "login" | "signup";

// Logging in and opening an account. The dusk scene fills the screen and the form arrives as a
// glass panel sliding in from the right, so arriving here feels like a step forward rather than
// the page being swapped underneath you.
//
// Sign-up is only offered when the company has set a code, and it asks for that code: this tool
// holds people's CVs, so the door stays shut by default.
export default function LoginPage({ startOn = "login" }: { startOn?: Mode }) {
  const navigate = useNavigate();
  const [mode, setMode] = useState<Mode>(startOn);
  const [options, setOptions] = useState<SignInOptions | null>(null);

  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [companyCode, setCompanyCode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<SignInOptions>("/auth/options")
      .then((body) => {
        setOptions(body);
        if (!body.signup_open) setMode("login");
      })
      .catch(() => undefined);
  }, []);

  function choose(next: Mode) {
    setMode(next);
    setError("");
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const path = mode === "login" ? "/auth/login" : "/auth/signup";
      const body =
        mode === "login"
          ? { email, password }
          : { full_name: fullName, email, password, company_code: companyCode };
      const answer = await api<{ access_token: string }>(path, {
        method: "POST",
        body: JSON.stringify(body),
      });
      saveToken(answer.access_token);
      navigate("/");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const domains = options?.email_domains ?? [];

  return (
    <PublicFrame full footer={false}>
      <main className="gate">
        <div className="gate-words">
          <h1 className="display">
            Hire on evidence,
            <br />
            not instinct
          </h1>
          <p className="lead">
            Screen CVs, run the interview and read the transcript, all in one place.
          </p>
        </div>

        <form className="gate-panel glass slide-in" onSubmit={submit}>
          <h2>{mode === "login" ? "Welcome back" : "Create your account"}</h2>
          <p className="gate-sub">
            {mode === "login"
              ? `Log in to ${options?.company ?? "TalentSight"}.`
              : "For people on the hiring team."}
          </p>

          {options?.signup_open && (
            <div className="switch" role="group" aria-label="Log in or create an account">
              <button type="button" aria-pressed={mode === "login"} onClick={() => choose("login")}>
                Log in
              </button>
              <button type="button" aria-pressed={mode === "signup"} onClick={() => choose("signup")}>
                Sign up
              </button>
            </div>
          )}

          {mode === "signup" && (
            <div className="field">
              <label htmlFor="full_name">Your name</label>
              <input
                id="full_name"
                autoComplete="name"
                value={fullName}
                onChange={(event) => setFullName(event.target.value)}
                required
              />
            </div>
          )}

          <div className="field">
            <label htmlFor="email">Work e-mail</label>
            <input
              id="email"
              type="email"
              autoComplete="username"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
            />
            {mode === "signup" && domains.length > 0 && (
              <span className="hint">Use your {domains.map((d) => `@${d}`).join(" or ")} address.</span>
            )}
          </div>

          <div className="field">
            <label htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
            {mode === "signup" && <span className="hint">At least 8 characters.</span>}
          </div>

          {mode === "signup" && (
            <div className="field">
              <label htmlFor="company_code">Company code</label>
              <input
                id="company_code"
                value={companyCode}
                onChange={(event) => setCompanyCode(event.target.value)}
                required
              />
              <span className="hint">Your administrator has this code.</span>
            </div>
          )}

          {error && <p className="error small">{error}</p>}

          <button className="button wide big" type="submit" disabled={busy}>
            {busy
              ? mode === "login"
                ? "Logging in…"
                : "Creating your account…"
              : mode === "login"
                ? "Log in"
                : "Create account"}
          </button>

          <p className="gate-foot">
            <Link to="/welcome">What is TalentSight?</Link>
          </p>
        </form>
      </main>
    </PublicFrame>
  );
}
