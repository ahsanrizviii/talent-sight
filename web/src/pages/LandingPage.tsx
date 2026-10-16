import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { api } from "../api";
import { isLoggedIn } from "../auth";
import Icon from "../components/Icon";
import PublicFrame from "../components/PublicFrame";
import type { SignInOptions } from "../types";

const STEPS = [
  {
    title: "Write the job",
    text: "Describe the role in a few sentences. The AI drafts it against your hiring policies and you approve it.",
  },
  {
    title: "Read every CV",
    text: "Each one is checked against each requirement, with the line of evidence the AI used, and scored out of 100.",
  },
  {
    title: "Interview in the browser",
    text: "Video, with the transcript written as it is spoken and kept for whoever decides.",
  },
  {
    title: "Decide on evidence",
    text: "Scores, requirements and the interview in one place, so the reason for a decision is always in writing.",
  },
];

// The first page anyone sees. The whole screen is the dusk scene, with the two things a
// visitor can do sitting in the middle of it.
export default function LandingPage() {
  const navigate = useNavigate();
  const [options, setOptions] = useState<SignInOptions | null>(null);

  useEffect(() => {
    if (isLoggedIn()) navigate("/", { replace: true });
    api<SignInOptions>("/auth/options").then(setOptions).catch(() => undefined);
  }, [navigate]);

  return (
    <PublicFrame>
      <section className="hero">
        <h1 className="display">
          Hire on evidence,
          <br />
          not instinct
        </h1>
        <p className="lead">
          TalentSight reads every CV against the job you wrote, scores each candidate with the
          reasoning attached, and transcribes the interview as it happens.
        </p>

        <div className="hero-actions">
          <Link className="button big" to="/login">
            Log in
          </Link>
          {options?.signup_open !== false && (
            <Link className="button big ghost" to="/signup">
              Sign up
            </Link>
          )}
        </div>

        <p className="hero-note">
          {options?.signup_open
            ? "For the hiring team. You will need your company code."
            : "For the hiring team. Accounts are created by your administrator."}
        </p>
      </section>

      <section className="band" id="how-it-works">
        <div className="band-head">
          <h2>Four steps, one record</h2>
          <p>Everything the platform decides is written down and can be read back.</p>
        </div>

        <div className="tile-grid">
          {STEPS.map((step, index) => (
            <article className="tile-card" key={step.title}>
              <span className="tile-date">Step {index + 1}</span>
              <h3>{step.title}</h3>
              <p>{step.text}</p>
              <span className="go" aria-hidden="true">
                <Icon name="forward" />
              </span>
            </article>
          ))}
        </div>
      </section>
    </PublicFrame>
  );
}
