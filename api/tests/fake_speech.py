from app.speech import Heard, SpeechError

MS_PER_TURN = 1000


class FakeSpeechStream:
    script: list[str] = []  # sentences handed out in order, shared by all streams
    made: list["FakeSpeechStream"] = []  # every stream created, oldest first
    failures_left = 0  # how many starts fail before one works
    drop_after_ms = 0  # 0 = never close by itself

    def __init__(self, on_heard, on_closed):
        self.on_heard = on_heard
        self.on_closed = on_closed
        self.started = False
        self.stopped = False
        self.audio_ms = 0
        self.turn = 0
        self.turn_start = 0
        FakeSpeechStream.made.append(self)

    @classmethod
    def reset(cls, script: list[str] | None = None) -> None:
        cls.script = list(script or [])
        cls.made = []
        cls.failures_left = 0
        cls.drop_after_ms = 0

    async def start(self) -> None:
        if FakeSpeechStream.failures_left > 0:
            FakeSpeechStream.failures_left -= 1
            raise SpeechError("The speech service is not reachable.")
        self.started = True

    async def send(self, chunk: bytes) -> None:
        self.audio_ms += len(chunk) // 32
        if self.audio_ms - self.turn_start >= MS_PER_TURN:
            text = FakeSpeechStream.script.pop(0) if FakeSpeechStream.script else f"words {self.turn}"
            await self.on_heard(Heard(self.turn, text[: len(text) // 2], self.turn_start, self.audio_ms, final=False))
            await self.on_heard(Heard(self.turn, text, self.turn_start, self.audio_ms, final=True))
            self.turn += 1
            self.turn_start = self.audio_ms
        if FakeSpeechStream.drop_after_ms and self.audio_ms >= FakeSpeechStream.drop_after_ms and not self.stopped:
            self.stopped = True
            await self.on_closed("Session expired (code 3008)")

    async def stop(self) -> None:
        self.stopped = True