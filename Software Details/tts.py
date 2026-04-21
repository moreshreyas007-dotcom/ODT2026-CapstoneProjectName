# tts.py
# Text to speech using Edge TTS — plays on laptop speaker only

import asyncio
import edge_tts
import io
import threading

VOICE = "en-US-GuyNeural"


class TextToSpeech:
    def __init__(self):
        # lazy import pygame so OpenCV (hand_tracker) loads first — reduces duplicate libSDL2
        # warnings on macOS when cv2 and pygame both ship SDL
        import pygame

        self._pygame = pygame
        pygame.mixer.init(frequency=22050, size=-16, channels=1, buffer=512)
        print(f"TTS ready (Edge TTS → laptop speaker — {VOICE})")

    def speak(self, text: str):
        if not text.strip():
            return
        try:
            audio_bytes = asyncio.run(self._synthesize(text))
            self._play_local(audio_bytes)
        except Exception as e:
            print(f"   [TTS] Error: {e}")

    def speak_async(self, text: str):
        t = threading.Thread(target=self.speak, args=(text,), daemon=True)
        t.start()
        return t

    async def _synthesize(self, text: str) -> bytes:
        communicate  = edge_tts.Communicate(text, VOICE)
        audio_chunks = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_chunks.append(chunk["data"])
        return b"".join(audio_chunks)

    def _play_local(self, audio_bytes: bytes):
        pg = self._pygame
        buf = io.BytesIO(audio_bytes)
        pg.mixer.music.load(buf)
        pg.mixer.music.play()
        while pg.mixer.music.get_busy():
            pg.time.wait(50)

    def stop(self):
        self._pygame.mixer.music.stop()
