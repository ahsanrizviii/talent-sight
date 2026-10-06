import { useEffect, useState } from "react";

import { api } from "../api";

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
    <div className="card">
      <h1>TalentSight</h1>
      <p>
        API status:{" "}
        <strong className={status === "ok" ? "success" : "error"}>{status}</strong>
      </p>
      {email && <p className="muted">Logged in as {email}</p>}
    </div>
  );
}