import { useEffect, useState } from "react";

import { api } from "../api";

// Shows whether the browser can reach the API, and the API can reach the database.
export default function HomePage() {
  const [status, setStatus] = useState("checking...");

  useEffect(() => {
    api<{ status: string }>("/health")
      .then((body) => setStatus(body.status))
      .catch(() => setStatus("cannot reach the API"));
  }, []);

  return (
    <div className="card">
      <h1>TalentSight</h1>
      <p>
        API status:{" "}
        <strong className={status === "ok" ? "success" : "error"}>{status}</strong>
      </p>
    </div>
  );
}