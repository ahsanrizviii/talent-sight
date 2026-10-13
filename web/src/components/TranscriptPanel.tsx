import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { socketUrl } from "../api";
import { getToken } from "../auth";
import type { TranscriptSegment } from "../types";
import TranscriptLines from "./TranscriptLines";
import type { Previews } from "./TranscriptLines";

// The live transcript in the interviewer's room (Task 8.2.2). Interviewer only: the server checks
// the login, and the candidate's page never opens this connection (N9).
// On every (re)connect the server first sends everything said so far, so nothing is missed or doubled.

const RETRY_WAIT_SECONDS = [1, 2, 4, 8, 10];
const PING_SECONDS = 25;
type State = "connecting" | "live" | "reconnecting" | "ended" | "off";
const STATE_LABELS: Record<State, string> = {
  connecting: "Connecting...",
  live: "Live",
  reconnecting: "Reconnecting...",
  ended: "Interview ended",
  off: "Not available",
};

export default function TranscriptPanel({ sessionId, candidateName }: { sessionId: number; candidateName: string }) {
  const [lines, setLines] = useState<Map<number, TranscriptSegment>>(new Map());
  const [previews, setPreviews] = useState<Previews>({});
  const [state, setState] = useState<State>("connecting");
  const box = useRef<HTMLDivElement>(null);
  const followNewest = useRef(true); // false while the interviewer scrolls up to read

  useEffect(() => {
    let stopped = false;
    let socket: WebSocket | null = null;
    let failures = 0;
    let retryTimer: number | undefined;
    let pingTimer: number | undefined;

    function connect() {
      const ws = new WebSocket(socketUrl(`/ws/interviews/${sessionId}/transcript`));
      socket = ws;
      ws.onopen = () => ws.send(JSON.stringify({ token: getToken() }));
      ws.onmessage = (event) => {
        const message = JSON.parse(event.data);
        if (message.type === "history") {
          failures = 0;
          setLines(new Map(message.segments.map((s: TranscriptSegment) => [s.id, s])));
          setPreviews({});
          setState(message.status === "ended" ? "ended" : "live");
        } else if (message.type === "segment") {
          const segment: TranscriptSegment = message.segment;
          setLines((old) => new Map(old).set(segment.id, segment)); // same id = an improved version
          setPreviews((old) => ({ ...old, [segment.speaker]: undefined }));
        } else if (message.type === "partial") {
          setPreviews((old) => ({ ...old, [message.speaker]: message.text ? { text: message.text, start_ms: message.start_ms } : undefined }));
        } else if (message.type === "ended") {
          setPreviews({});
          setState("ended");
        }
      };
      ws.onclose = (event) => {
        window.clearInterval(pingTimer);
        if (stopped || socket !== ws) return;
        if (event.code === 4401 || event.code === 4404) {
          setState("off");
          return;
        }
        setState((old) => (old === "ended" ? old : "reconnecting"));
        const wait = RETRY_WAIT_SECONDS[Math.min(failures, RETRY_WAIT_SECONDS.length - 1)];
        failures += 1;
        retryTimer = window.setTimeout(connect, wait * 1000);
      };
      pingTimer = window.setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "ping" }));
      }, PING_SECONDS * 1000);
    }

    connect();
    return () => {
      stopped = true;
      window.clearTimeout(retryTimer);
      window.clearInterval(pingTimer);
      socket?.close(1000);
    };
  }, [sessionId]);

  // Keep the newest line in view, unless the interviewer has scrolled up.
  useLayoutEffect(() => {
    if (followNewest.current && box.current) box.current.scrollTop = box.current.scrollHeight;
  }, [lines, previews]);

  function onScroll() {
    const el = box.current;
    if (el) followNewest.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48;
  }

  const segments = [...lines.values()].sort((a, b) => a.start_ms - b.start_ms || a.id - b.id);

  return (
    <section className="card transcript">
      <div className="transcript-head">
        <h2>Transcript</h2>
        <span className={`transcript-state ${state}`}>{STATE_LABELS[state]}</span>
      </div>
      <div className="transcript-box" ref={box} onScroll={onScroll}>
        {segments.length === 0 && !previews.interviewer && !previews.candidate ? (
          <p className="muted small">Nothing said yet. Each line appears a moment after someone speaks.</p>
        ) : (
          <TranscriptLines segments={segments} candidateName={candidateName} previews={previews} />
        )}
      </div>
    </section>
  );
}