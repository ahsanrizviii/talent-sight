import sys
import time
import wave

from assemblyai.streaming.v3 import (
    Encoding,
    RealTimeError,
    RealTimeEvents,
    RealTimeParameters,
    RealTimeTranscriber,
    RealTimeTranscriberOptions,
    TurnEvent,
)

from app.settings import settings

CHUNK_MS = 100  
START = time.monotonic()


def on_turn(client: RealTimeTranscriber, event: TurnEvent) -> None:
    if event.transcript:
        label = "FINAL  " if event.end_of_turn else "partial"
        print(f"{time.monotonic() - START:5.1f}s  {label}  {event.transcript}")


def on_error(client: RealTimeTranscriber, error: RealTimeError) -> None:
    print(f"ERROR: {error}")


def main(path: str) -> None:
    if not settings.assemblyai_api_key:
        sys.exit("ASSEMBLYAI_API_KEY is missing in .env")
    with wave.open(path, "rb") as recording:
        if recording.getnchannels() != 1 or recording.getsampwidth() != 2:
            sys.exit("Please use a mono (1 channel), 16-bit WAV file.")
        sample_rate = recording.getframerate()
        frames_per_chunk = sample_rate * CHUNK_MS // 1000

        client = RealTimeTranscriber(
            RealTimeTranscriberOptions(terminate_timeout=30.0),
            api_key=settings.assemblyai_api_key,
        )
        client.on(RealTimeEvents.Turn, on_turn)
        client.on(RealTimeEvents.Error, on_error)
        client.connect(
            RealTimeParameters(
                speech_model=settings.stt_model,
                encoding=Encoding.pcm_s16le,
                sample_rate=sample_rate,
            )
        )
        try:
            while data := recording.readframes(frames_per_chunk):
                client.stream(data)
                time.sleep(CHUNK_MS / 1000)  
        finally:
            client.disconnect(terminate=True)  


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: python -m scripts.stt_check /tmp/my-voice.wav")
    main(sys.argv[1])