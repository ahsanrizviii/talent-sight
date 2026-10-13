import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { api } from "../api";
import { isLoggedIn } from "../auth";
import Arrow from "../components/Arrow";
import Icon from "../components/Icon";
import PublicFrame from "../components/PublicFrame";
import type { SignInOptions } from "../types";

// The first page a visitor sees. It says what the tool does and sends them to log in
// or to open an account.
export default function LandingPage() {
  const navigate = useNavigate();
  const [options, setOptions] = useState<SignInOptions | null>(null);

  useEffect(() => {
    if (isLoggedIn()) navigate("/", { replace: true });
    api<SignInOptions>("/auth/options").then(setOptions).catch(() => undefined);
  }, [navigate]);

  return (
    <PublicFrame>
      <main className="hero">
        <div className="hero-grid">
          <div>
            <h1 className="display">
              Hire on evidence,
              <br />
              not instinct.
            </h1>
            <p className="lead">
              TalentSight reads every CV against the job you actually wrote, scores each candidate
              on four dimensions with the reasoning attached, runs the video interview and writes
              the transcript as it happens.
            </p>

            <ul className="proof">
              <li>
                <Icon name="check" />
                Every CV checked against every requirement, with the line of evidence the AI used
              </li>
              <li>
                <Icon name="check" />
                One score out of 100 you can take apart: skills, experience, qualifications, fit
              </li>
              <li>
                <Icon name="check" />
                Interviews in the browser, transcribed live and kept for whoever decides
              </li>
            </ul>
          </div>

          <div className="auth">
            <h2>{options?.company ?? "TalentSight"} hiring</h2>
            <p>For the recruiters and hiring managers on your team.</p>
            <div style={{ display: "grid", gap: 10, marginTop: 20 }}>
              <Link className="button arrow wide" to="/login">
                Log in <Arrow />
              </Link>
              {options?.signup_open && (
                <Link className="button secondary wide" to="/signup">
                  Create an account
                </Link>
              )}
            </div>
            <p className="small muted" style={{ marginTop: 16, marginBottom: 0 }}>
              {options?.signup_open
                ? "You need the company code from your administrator to open an account."
                : "Accounts are created by your administrator."}
            </p>
          </div>
        </div>
      </main>
    </PublicFrame>
  );
}
