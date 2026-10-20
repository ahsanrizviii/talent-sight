import { useEffect } from "react";
import { api } from "../api";
import { grabFrame } from "../camera";

// Sends three camera frames during the interview, only after the candidate agreed (Module 13, F7).
// The frames come from the candidate's own video tile. The server keeps numbers, never pictures,
// and stops at three, so rejoining the call does not add more.
const MOMENTS_SECONDS = [20, 180, 360]; // early, middle and later in the call
const RETRY_SECONDS = 15; // camera off or no face found: try again a little later
const MAX_TRIES = 6;

export default function FaceFrames({ token }: { token: string }) {
  useEffect(() => {
    let stopped = false;
    const timers: number[] = [];

    async function capture(tries: number) {
      if (stopped) return;
      const image = grabFrame(document.querySelector<HTMLVideoElement>(".tile.local video"));
      try {
        if (!image) throw new Error("No picture yet");
        await api(`/invite/${token}/identity/frame`, { method: "POST", body: JSON.stringify({ image }) });
      } catch {
        if (tries + 1 < MAX_TRIES) timers.push(window.setTimeout(() => void capture(tries + 1), RETRY_SECONDS * 1000));
      }
    }

    for (const seconds of MOMENTS_SECONDS) timers.push(window.setTimeout(() => void capture(0), seconds * 1000));
    return () => {
      stopped = true;
      timers.forEach((timer) => window.clearTimeout(timer));
    };
  }, [token]);

  return null;
}