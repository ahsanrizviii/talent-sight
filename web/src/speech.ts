import { Room, RoomEvent, Track } from "livekit-client";
import { socketUrl } from "./api";

// Live speech to text (Module 8): sends THIS browser's microphone to the API, and nothing else.
// The interviewer's browser sends the interviewer, the candidate's browser sends the candidate,
// each over its own WebSocket, so the server always knows who is speaking (Q&A 4).
//
// The microphone is already open for the video call; we only listen to the same track.
// The audio is turned into what the speech service expects: 16 000 samples a second, one channel,
// 16-bit numbers, sent in 100 ms pieces. Each piece is sent and forgotten: nothing is stored (N16).

const TARGET_RATE = 16000;
const PIECE_SAMPLES = 1600; // 100 ms at 16 kHz
const MAX_WAITING_BYTES = 64_000; // about 2 s of audio: if the network is that far behind, skip pieces
const RETRY_WAIT_SECONDS = [1, 2, 4, 8, 10]; // after a lost connection; the last wait repeats (Task 8.1.3)
const PING_SECONDS = 25; // a small message now and then keeps the connection open while muted
// Close codes from the server after which trying again cannot help:
// 4401 not signed in, 4404 no such interview, 4409 this person connected again elsewhere, 4410 interview ended.
const FINAL_CLOSE_CODES = [4401, 4404, 4409, 4410];

// The AudioWorklet runs on the browser's audio thread. It averages the microphone's samples
// (usually 48 000 a second) down to 16 000, converts them to 16-bit numbers and posts a piece every 100 ms.
const WORKLET_CODE = `
class PcmPieces extends AudioWorkletProcessor {
  constructor() {
    super();
    this.step = sampleRate / ${TARGET_RATE}; // input samples per output sample, e.g. 3 for 48 kHz
    this.position = 0;
    this.sum = 0;
    this.count = 0;
    this.piece = new Int16Array(${PIECE_SAMPLES});
    this.filled = 0;
  }
  process(inputs) {
    const samples = inputs[0] && inputs[0][0]; // the first channel is enough for speech
    if (!samples) return true;
    for (let i = 0; i < samples.length; i++) {
      this.sum += samples[i];
      this.count += 1;
      this.position += 1;
      if (this.position >= this.step) {
        this.position -= this.step;
        const value = Math.max(-1, Math.min(1, this.sum / this.count));
        this.piece[this.filled++] = value < 0 ? value * 0x8000 : value * 0x7fff;
        this.sum = 0;
        this.count = 0;
        if (this.filled === this.piece.length) {
          this.port.postMessage(this.piece.buffer, [this.piece.buffer]);
          this.piece = new Int16Array(${PIECE_SAMPLES});
          this.filled = 0;
        }
      }
    }
    return true;
  }
}
registerProcessor("pcm-pieces", PcmPieces);
`;

// Where to send the audio. The interviewer also sends their login token as the first message,
// because a browser cannot put a login header on a WebSocket. The candidate's key is the invite link in the path.
export type SpeechTarget = { path: string; token?: string | null };

// connecting = waiting for the server, on = audio is flowing, unavailable = the speech service
// cannot be used right now (the call goes on), off = stopped or refused
export type SpeechState = "connecting" | "on" | "unavailable" | "off";

export class SpeechSender {
  private socket: WebSocket | null = null;
  private ready = false; // the server accepted us
  private stopped = false;
  private failures = 0; // lost connections in a row
  private retryTimer: number | undefined;
  private pingTimer: number | undefined;
  private context: AudioContext | null = null;
  private worklet: AudioWorkletNode | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private track: MediaStreamTrack | null = null;
  private room: Room;
  private target: SpeechTarget;
  private onState: (state: SpeechState) => void;

  constructor(room: Room, target: SpeechTarget, onState: (state: SpeechState) => void) {
    this.room = room;
    this.target = target;
    this.onState = onState;
  }

  start() {
    // The microphone track changes when it is first switched on and after a reconnect: follow it.
    this.room.on(RoomEvent.LocalTrackPublished, this.followMicrophone);
    this.room.on(RoomEvent.LocalTrackUnpublished, this.followMicrophone);
    document.addEventListener("click", this.wakeAudio);
    this.followMicrophone();
    this.connect();
  }

  stop() {
    this.stopped = true;
    window.clearTimeout(this.retryTimer);
    window.clearInterval(this.pingTimer);
    this.room.off(RoomEvent.LocalTrackPublished, this.followMicrophone);
    this.room.off(RoomEvent.LocalTrackUnpublished, this.followMicrophone);
    document.removeEventListener("click", this.wakeAudio);
    this.socket?.close(1000);
    this.socket = null;
    this.source?.disconnect();
    void this.context?.close().catch(() => {});
    this.context = null;
    this.onState("off");
  }

  private connect() {
    if (this.stopped) return;
    this.onState("connecting");
    const socket = new WebSocket(socketUrl(this.target.path));
    socket.binaryType = "arraybuffer";
    this.socket = socket;
    socket.onopen = () => {
      if (this.target.token) socket.send(JSON.stringify({ token: this.target.token }));
    };
    socket.onmessage = (event) => {
      if (typeof event.data !== "string") return;
      const message = JSON.parse(event.data);
      if (message.type === "ready") {
        this.ready = true;
        this.failures = 0;
        this.onState("on");
      } else if (message.type === "status") {
        // The server opens the speech service when the first audio arrives, and says how it went.
        this.onState(message.state === "listening" ? "on" : "unavailable");
      }
    };
    socket.onclose = (event) => {
      if (this.socket !== socket) return; // an older connection we already replaced
      this.ready = false;
      window.clearInterval(this.pingTimer);
      if (this.stopped) return;
      if (FINAL_CLOSE_CODES.includes(event.code)) {
        this.onState("off");
        return;
      }
      // Lost connection (network, server restart): try again, waiting a little longer each time (Task 8.1.3).
      const wait = RETRY_WAIT_SECONDS[Math.min(this.failures, RETRY_WAIT_SECONDS.length - 1)];
      this.failures += 1;
      this.onState("connecting");
      this.retryTimer = window.setTimeout(() => this.connect(), wait * 1000);
    };
    window.clearInterval(this.pingTimer);
    this.pingTimer = window.setInterval(() => {
      if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "ping" }));
    }, PING_SECONDS * 1000);
  }

  private followMicrophone = () => {
    const publication = this.room.localParticipant.getTrackPublication(Track.Source.Microphone);
    const track = publication?.track?.mediaStreamTrack ?? null;
    if (track !== this.track) void this.listenTo(track);
  };

  private async listenTo(track: MediaStreamTrack | null) {
    this.track = track;
    this.source?.disconnect();
    this.source = null;
    if (!track || this.stopped) return;
    try {
      if (!this.context) {
        this.context = new AudioContext();
        const code = URL.createObjectURL(new Blob([WORKLET_CODE], { type: "application/javascript" }));
        await this.context.audioWorklet.addModule(code);
        URL.revokeObjectURL(code);
        this.worklet = new AudioWorkletNode(this.context, "pcm-pieces");
        this.worklet.port.onmessage = this.sendPiece;
        // The worklet must be connected to the speakers to keep running; a gain of 0 keeps it silent.
        const silent = this.context.createGain();
        silent.gain.value = 0;
        this.worklet.connect(silent).connect(this.context.destination);
      }
      if (this.track !== track || this.stopped || !this.worklet) return; // the track changed while we waited
      this.source = this.context.createMediaStreamSource(new MediaStream([track]));
      this.source.connect(this.worklet);
      void this.context.resume().catch(() => {});
    } catch {
      // Without audio processing the call still works; there is just no transcript from this side.
    }
  }

  // Browsers may start audio processing paused until the user clicks something.
  private wakeAudio = () => {
    if (this.context?.state === "suspended") void this.context.resume().catch(() => {});
  };

  private sendPiece = (event: MessageEvent<ArrayBuffer>) => {
    const socket = this.socket;
    if (!this.ready || !socket || socket.readyState !== WebSocket.OPEN) return;
    if (!this.room.localParticipant.isMicrophoneEnabled) return; // muted: send nothing
    if (socket.bufferedAmount > MAX_WAITING_BYTES) return; // the network is far behind: drop this piece
    socket.send(event.data);
  };
}