import sys
import time
import wave

from google.cloud import speech

CHUNK_MS = 100  


def read_chunks(path: str, frames_per_chunk: int):
    with wave.open(path, "rb") as recording:
        while True:
            data = recording.readframes(frames_per_chunk)
            if not data:
                break
            yield speech.StreamingRecognizeRequest(audio_content=data)
            time.sleep(CHUNK_MS / 1000)  


def main(path: str) -> None:
    with wave.open(path, "rb") as recording:
        if recording.getnchannels() != 1 or recording.getsampwidth() != 2:
            sys.exit("Please use a mono (1 channel), 16-bit WAV file.")
        sample_rate = recording.getframerate()

    config = speech.StreamingRecognitionConfig(
        config=speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=sample_rate,
            language_code="en-US",
            enable_automatic_punctuation=True,
        ),
        interim_results=True, 
    )

    client = speech.SpeechClient()
    requests = read_chunks(path, sample_rate * CHUNK_MS // 1000)
    start = time.monotonic()

    for response in client.streaming_recognize(config, requests):
        for result in response.results:
            label = "FINAL " if result.is_final else "partial"
            print(
                f"{time.monotonic() - start:5.1f}s {label} "
                f"{result.alternatives[0].transcript}"
            )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: python -m scripts.stt_check /tmp/my-voice.wav")
    main(sys.argv[1])