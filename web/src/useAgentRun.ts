import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import type { AgentRun } from "./types";

// Starts a background review of an interview, then asks every 2 seconds how far it is (Module 13).
// Used by the interview quality card and the interview score card.
export function useAgentRun<R>(path: string) {
  const [run, setRun] = useState<AgentRun<R> | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const [starting, setStarting] = useState(false);

  const load = useCallback(
    () =>
      api<AgentRun<R> | null>(path)
        .then((found) => {
          setRun(found);
          setLoaded(true);
        })
        .catch((err) => {
          setError(err.message);
          setLoaded(true);
        }),
    [path],
  );

  useEffect(() => {
    setRun(null);
    setLoaded(false);
    void load();
  }, [load]);

  const running = run?.status === "running";
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => void load(), 2000);
    return () => window.clearInterval(timer);
  }, [running, load]);

  async function start() {
    setStarting(true);
    setError("");
    try {
      setRun(await api<AgentRun<R>>(path, { method: "POST" }));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setStarting(false);
    }
  }

  return { run, loaded, error, starting, running, start };
}