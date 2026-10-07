import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import Arrow from "../components/Arrow";

export default function HomePage() {
  const [status, setStatus] = useState("checking...");
  const [email, setEmail] = useState("");

  useEffect(() => {
    api<{ status: string }>("/health")
      .then((body) => setStatus(body.status))
      .catch(() => setStatus("cannot reach the API"));
    api<{ email: string }>("/auth/me").then((me) => setEmail(me.email));
  }, []);

  return (
    <>
      <section className="welcome">
        <p className="eyebrow">Dashboard</p>
        <h1 className="display small">Welcome back.</h1>
        <p className="status">
          <span className={status === "ok" ? "dot ok" : "dot"} />
          API status: <strong className={status === "ok" ? "success" : "error"}>{status}</strong>
        </p>
        {email && <p className="muted">Logged in as {email}</p>}
      </section>

      <div className="tiles">
        <Link className="card tile" to="/jobs">
          <h2>Job profiles</h2>
          <p className="muted">Create, edit and publish the roles you are hiring for.</p>
          <span className="card-more">
            Open <Arrow />
          </span>
        </Link>
        <Link className="card tile" to="/jd-chat">
          <h2>Write a job with AI</h2>
          <p className="muted">Turn a short brief into a job post that follows the hiring policies.</p>
          <span className="card-more">
            Start <Arrow />
          </span>
        </Link>
      </div>
    </>
  );
}
