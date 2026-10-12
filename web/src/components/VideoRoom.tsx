import { useEffect, useReducer, useRef, useState } from "react";
import { ConnectionState, DisconnectReason, Room, RoomEvent, Track } from "livekit-client";
import type { Participant } from "livekit-client";
import type { JoinInfo } from "../types";

// The video call itself: two tiles and the buttons below them (Tasks 7.2.1 and 7.3.1).
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

// If the connection is lost, LiveKit first tries by itself for a short while. If that fails we
// ask the API for a fresh token and try again, waiting a little longer each time (Task 7.3.1).
const RETRY_WAIT_SECONDS = [2, 4, 6, 8, 8, 8];
const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
// A 4xx answer (link expired, interview ended) will not get better by trying again.
const refused = (error: unknown) => {
  const status = (error as { status?: number }).status;
  return status !== undefined && status >= 400 && status < 500;
};

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
  const wanted = useRef({ microphone: true, camera: true }); // what the user switched on, kept across reconnects
  const [phase, setPhase] = useState<"connecting" | "live" | "closed">("connecting");
  const [reconnecting, setReconnecting] = useState(false);
  const [message, setMessage] = useState("");
  const [deviceNote, setDeviceNote] = useState("");
  const [soundBlocked, setSoundBlocked] = useState(false);
  const [, redraw] = useReducer((n: number) => n + 1, 0);

  useEffect(() => {
    let cancelled = false; // true once this page is closed, so late results are ignored
    let rejoining = false;
    const room = new Room({ adaptiveStream: true, dynacast: true });
    roomRef.current = room;
    REDRAW_EVENTS.forEach((event) => room.on(event, redraw));
    room.on(RoomEvent.AudioPlaybackStatusChanged, () => setSoundBlocked(!room.canPlaybackAudio));

    function close(text: string) {
      if (cancelled) return;
      setReconnecting(false);
      setPhase("closed");
      setMessage(text);
    }

    // Camera and microphone are asked for one by one, so a missing camera does not cost us the microphone.
    async function startDevices() {
      const problems: string[] = [];
      if (wanted.current.microphone) {
        try {
          await room.localParticipant.setMicrophoneEnabled(true);
        } catch {
          problems.push("microphone");
        }
      }
      if (wanted.current.camera) {
        try {
          await room.localParticipant.setCameraEnabled(true);
        } catch {
          problems.push("camera");
        }
      }
      if (cancelled) return;
      if (problems.length) {
        setDeviceNote(`Your ${problems.join(" and ")} could not be started. Allow access in the browser address bar and use the buttons below.`);
      }
      redraw();
    }

    // Gets a fresh token from the API and enters the room. Used the first time and after a lost connection.
    async function enter() {
      const info = await joinRef.current();
      if (cancelled) return;
      await room.connect(info.livekit_url, info.token);
      if (cancelled) return;
      setReconnecting(false);
      setPhase("live");
      await startDevices();
    }

    async function rejoin() {
      if (rejoining) return;
      rejoining = true;
      setReconnecting(true);
      for (const seconds of RETRY_WAIT_SECONDS) {
        await sleep(seconds * 1000);
        if (cancelled) return;
        try {
          await enter();
          rejoining = false;
          return;
        } catch (error) {
          if (refused(error)) return close((error as Error).message);
        }
      }
      close("We could not reconnect you. Please check your internet connection and join again.");
    }

    // LiveKit's own quick reconnect: we only show or hide the banner.
    room.on(RoomEvent.ConnectionStateChanged, (state: ConnectionState) => {
      if (cancelled) return;
      if (state === ConnectionState.Reconnecting || state === ConnectionState.SignalReconnecting) setReconnecting(true);
      else if (state === ConnectionState.Connected) {
        setReconnecting(false);
        redraw();
      }
    });

    room.on(RoomEvent.Disconnected, (reason?: DisconnectReason) => {
      if (cancelled || reason === DisconnectReason.CLIENT_INITIATED) return; // CLIENT_INITIATED = the Leave button
      if (reason === DisconnectReason.ROOM_DELETED) return close("The interview has ended. Thank you!");
      if (reason === DisconnectReason.DUPLICATE_IDENTITY) return close("You opened the interview in another window, so this one was closed.");
      if (reason === DisconnectReason.PARTICIPANT_REMOVED) return close("You were removed from the interview.");
      void rejoin(); // anything else: the connection was lost
    });

    enter().catch((error) => close((error as Error).message));

    return () => {
      cancelled = true;
      room.disconnect();
    };
  }, []);

  const room = roomRef.current;
  const me = phase === "live" && !reconnecting && room ? room.localParticipant : null;
  const other = phase === "live" && room ? Array.from(room.remoteParticipants.values())[0] ?? null : null;

  async function toggle(device: "microphone" | "camera") {
    if (!me) return;
    try {
      const turnOn = device === "microphone" ? !me.isMicrophoneEnabled : !me.isCameraEnabled;
      if (device === "microphone") await me.setMicrophoneEnabled(turnOn);
      else await me.setCameraEnabled(turnOn);
      wanted.current[device] = turnOn;
      setDeviceNote("");
    } catch {
      setDeviceNote(`The ${device} could not be switched. Check that the browser is allowed to use it.`);
    }
    redraw();
  }

  function leave() {
    room?.disconnect(); // CLIENT_INITIATED: the Disconnected handler knows this is not a lost connection
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
        {phase === "live" && room && <Tile participant={room.localParticipant} label="You" local />}
        {phase === "connecting" && <div className="tile-off">Connecting...</div>}
        {reconnecting && <div className="room-banner">Connection lost. Reconnecting...</div>}
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