import { useEffect, useRef, useState } from "react";
import { Room, RoomEvent, Track } from "livekit-client";

const LIVEKIT_URL = "ws://localhost:7880";

export default function VideoTestPage() {
  const [token, setToken] = useState("");
  const [status, setStatus] = useState("not connected");
  const videosRef = useRef<HTMLDivElement>(null);
  const roomRef = useRef<Room | null>(null);

  async function join() {
    const room = new Room();
    roomRef.current = room;

    room.on(RoomEvent.TrackSubscribed, (track) => {
      videosRef.current?.appendChild(track.attach());
    });

    try {
      setStatus("connecting...");
      await room.connect(LIVEKIT_URL, token.trim());
      await room.localParticipant.enableCameraAndMicrophone();

      const myCamera =
        room.localParticipant.getTrackPublication(Track.Source.Camera)?.track;
      if (myCamera) videosRef.current?.appendChild(myCamera.attach());

      setStatus(`connected as ${room.localParticipant.identity}`);
    } catch (error) {
      setStatus(`failed: ${(error as Error).message}`);
    }
  }

  useEffect(() => () => void roomRef.current?.disconnect(), []);

  return (
    <div className="card">
      <h1>Video test</h1>
      <p className="muted">
        Make a token with{" "}
        <code>docker compose exec api python -m scripts.make_livekit_token tab-1</code>
        , paste it, and press Join. Do the same in a second tab with <code>tab-2</code>.
      </p>

      <div className="field">
        <label htmlFor="token">LiveKit token</label>
        <input
          id="token"
          value={token}
          onChange={(event) => setToken(event.target.value)}
        />
      </div>

      <div className="row">
        <button className="button" onClick={join} disabled={!token.trim()}>
          Join
        </button>
        <span className="muted">{status}</span>
      </div>

      <div className="videos" ref={videosRef} />
    </div>
  );
}