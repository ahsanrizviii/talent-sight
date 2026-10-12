import { useEffect, useReducer, useRef, useState } from "react";
import { Room, RoomEvent, Track } from "livekit-client";
import type { Participant } from "livekit-client";
import type { JoinInfo } from "../types";

// The video call itself: two tiles and the buttons below them (Task 7.2.1).
// The interviewer's page and the candidate's page both use it; they only differ in how
// they ask the API for a join token (the `join` prop) and in what happens after Leave.

// Any of these events can change what we draw, so each one simply redraws the room.
const REDRAW_EVENTS = [
  RoomEvent.ParticipantConnected,
  RoomEvent.ParticipantDisconnected,
  RoomEvent.TrackPublished,
  RoomEvent.TrackSubscribed,
  RoomEvent.TrackUnsubscribed,
  RoomEvent.TrackMuted,
  RoomEvent.TrackUnmuted,
  RoomEvent.LocalTrackPublished,
  RoomEvent.LocalTrackUnpublished,
];

type Props = {
  join: () => Promise<JoinInfo>; // asks the API for a LiveKit token
  remoteLabel: string; // "Candidate" or "Interviewer": who we are waiting for
  onLeave: () => void; // after the user pressed Leave
  onEnd?: () => void; // interviewer only: the End interview button
};

function Tile({ participant, label, local }: { participant: Participant | null; label: string; local: boolean }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const audioRef = useRef<HTMLAudioElement>(null);
  const cameraTrack = participant?.getTrackPublication(Track.Source.Camera)?.track;
  const micTrack = participant?.getTrackPublication(Track.Source.Microphone)?.track;
  const cameraOn = participant?.isCameraEnabled ?? false;
  const micOn = participant?.isMicrophoneEnabled ?? false;

  useEffect(() => {
    const element = videoRef.current;
    if (!element || !cameraTrack) return;
    cameraTrack.attach(element);
    return () => {
      cameraTrack.detach(element);
    };
  }, [cameraTrack, cameraOn]);

  // Our own voice is never played back to us, only the other person's.
  useEffect(() => {
    const element = audioRef.current;
    if (local || !element || !micTrack) return;
    micTrack.attach(element);
    return () => {
      micTrack.detach(element);
    };
  }, [micTrack, local]);

  const name = participant?.name || label;
  return (
    <div className={`tile ${local ? "local" : "remote"}`}>
      <video ref={videoRef} autoPlay playsInline muted={local} className={cameraOn ? "" : "hidden"} />
      {!local && <audio ref={audioRef} autoPlay />}
      {!cameraOn && (
        <div className="tile-off">
          {participant ? name.charAt(0).toUpperCase() : <span className="small">Waiting for the {label.toLowerCase()} to join...</span>}
        </div>
      )}
      {participant && (
        <span className="tile-name">
          {local ? "You" : name}
          {!micOn && " · muted"}
        </span>
      )}
    </div>
  );
}

export default function VideoRoom({ join, remoteLabel, onLeave, onEnd }: Props) {
  const roomRef = useRef<Room | null>(null);
  const joinRef = useRef(join); // the latest join function, without restarting the call when it changes
  joinRef.current = join;
  const [phase, setPhase] = useState<"connecting" | "live" | "closed">("connecting");
  const [message, setMessage] = useState("");
  const [deviceNote, setDeviceNote] = useState("");
  const [soundBlocked, setSoundBlocked] = useState(false);
  const [, redraw] = useReducer((n: number) => n + 1, 0);

  useEffect(() => {
    let cancelled = false; // true once this page is closed, so late results are ignored
    const room = new Room({ adaptiveStream: true, dynacast: true });
    roomRef.current = room;
    REDRAW_EVENTS.forEach((event) => room.on(event, redraw));
    room.on(RoomEvent.AudioPlaybackStatusChanged, () => setSoundBlocked(!room.canPlaybackAudio));
    room.on(RoomEvent.Disconnected, () => {
      if (cancelled) return;
      setPhase("closed");
      setMessage("You are no longer connected to the interview.");
    });

    (async () => {
      try {
        const info = await joinRef.current();
        if (cancelled) return;
        await room.connect(info.livekit_url, info.token);
        if (cancelled) return;
        setPhase("live");
      } catch (error) {
        if (!cancelled) {
          setPhase("closed");
          setMessage((error as Error).message);
        }
        return;
      }

      // Camera and microphone are asked for one by one, so a missing camera does not cost us the microphone.
      const problems: string[] = [];
      try {
        await room.localParticipant.setMicrophoneEnabled(true);
      } catch {
        problems.push("microphone");
      }
      try {
        await room.localParticipant.setCameraEnabled(true);
      } catch {
        problems.push("camera");
      }
      if (cancelled) return;
      if (problems.length) {
        setDeviceNote(`Your ${problems.join(" and ")} could not be started. Allow access in the browser address bar and use the buttons below.`);
      }
      redraw();
    })();

    return () => {
      cancelled = true;
      room.disconnect();
    };
  }, []);

  const room = roomRef.current;
  const me = phase === "live" && room ? room.localParticipant : null;
  const other = phase === "live" && room ? Array.from(room.remoteParticipants.values())[0] ?? null : null;

  async function toggle(device: "microphone" | "camera") {
    if (!me) return;
    try {
      if (device === "microphone") await me.setMicrophoneEnabled(!me.isMicrophoneEnabled);
      else await me.setCameraEnabled(!me.isCameraEnabled);
      setDeviceNote("");
    } catch {
      setDeviceNote(`The ${device} could not be switched. Check that the browser is allowed to use it.`);
    }
    redraw();
  }

  function leave() {
    room?.disconnect();
    onLeave();
  }

  if (phase === "closed") {
    return (
      <div className="card">
        <p>{message}</p>
        <button className="button" onClick={onLeave}>
          Back
        </button>
      </div>
    );
  }

  return (
    <div className="room">
      <div className="room-stage">
        <Tile participant={other} label={remoteLabel} local={false} />
        {me && <Tile participant={me} label="You" local />}
        {phase === "connecting" && <div className="tile-off">Connecting...</div>}
      </div>

      {deviceNote && <p className="error small">{deviceNote}</p>}
      {soundBlocked && (
        <button className="button secondary" onClick={() => room?.startAudio()}>
          Click to turn on the sound
        </button>
      )}

      <div className="room-bar">
        <button className="button secondary" onClick={() => toggle("microphone")} disabled={!me}>
          {me?.isMicrophoneEnabled ? "Mute" : "Unmute"}
        </button>
        <button className="button secondary" onClick={() => toggle("camera")} disabled={!me}>
          {me?.isCameraEnabled ? "Camera off" : "Camera on"}
        </button>
        <button className="button secondary" onClick={leave}>
          Leave
        </button>
        {onEnd && (
          <button className="button danger" onClick={onEnd}>
            End interview
          </button>
        )}
      </div>
    </div>
  );
}