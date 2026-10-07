import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { saveToken } from "../auth";
import Arrow from "../components/Arrow";
import PublicFrame from "../components/PublicFrame";

export default function LoginPage() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const body = await api<{ access_token: string }>("/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      saveToken(body.access_token);
      navigate("/");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <PublicFrame>
      <main className="hero">
        <h1 className="display">
          Hire on evidence,
          <br />
          not instinct.
        </h1>
        <p className="lead">
          Screen CVs, run interviews and turn both into one evidence-backed assessment.
        </p>

        <form className="card login-card" onSubmit={submit}>
          <p className="eyebrow">Interviewer login</p>
          <div className="field">
            <label htmlFor="email">E-mail</label>
            <input
              id="email"
              type="email"
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>
          <div className="field">
            <label htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>
          {error && <p className="error">{error}</p>}
          <button className="button arrow wide" type="submit" disabled={busy}>
            {busy ? "Logging in..." : "Log in"} <Arrow />
          </button>
        </form>
      </main>
    </PublicFrame>
  );
}
