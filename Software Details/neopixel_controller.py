# neopixel_controller.py
# Sends NeoPixel lighting commands to ESP32 via WebSocket.
# Each emotion maps to a unique colour + animation effect.

import json
import threading
import time

# emotion tag → (R, G, B, effect, speed, brightness)
# speed: lower = faster (delay in ms per step on ESP32 side)
EMOTION_LIGHT = {
    "HAPPY":    (255, 200,  30, "pulse",    80,    200),
    "EXCITED":  (  0, 230, 255, "strobe",   30,    255),
    "CURIOUS":  (160,  50, 255, "breathe",  60,    180),
    "THINK":    ( 30,  80, 255, "chase",    50,    160),
    "AGREE":    ( 20, 255, 100, "blink",    40,    200),
    "DISAGREE": (255,  80,  10, "flicker",  70,    150),
    "IDLE":     (255, 240, 200, "breathe", 120,    80 ),
}

STATE_LIGHT = {
    "thinking":     ( 50, 100, 255, "chase",   45, 130),
    "hand_tracking":(  0, 255,  80, "rainbow",  25, 200),
    "startup":      (255, 160,  20, "pulse",   90, 220),
    "off":          (  0,   0,   0, "solid",    0,   0),
}


class NeoPixelController:
    def __init__(self, send_fn):
        self._send      = send_fn
        self._lock      = threading.Lock()
        self._current   = None
        print("NeoPixelController ready")

    def set_emotion(self, emotion_tag: str):
        tag = emotion_tag.upper().strip()
        if tag not in EMOTION_LIGHT:
            print(f"   [NEO] Unknown emotion tag: {tag!r} — using IDLE")
            tag = "IDLE"

        if self._current == ("emotion", tag):
            return

        r, g, b, effect, speed, brightness = EMOTION_LIGHT[tag]
        self._apply(r, g, b, effect, speed, brightness)
        self._current = ("emotion", tag)
        print(f"   [NEO] Emotion={tag}  RGB=({r},{g},{b})  fx={effect}  spd={speed}")

    def set_state(self, state: str):
        key = state.lower().strip()
        if key not in STATE_LIGHT:
            print(f"   [NEO] Unknown state: {key!r}")
            return

        if self._current == ("state", key):
            return

        r, g, b, effect, speed, brightness = STATE_LIGHT[key]
        self._apply(r, g, b, effect, speed, brightness)
        self._current = ("state", key)
        print(f"   [NEO] State={key}  RGB=({r},{g},{b})  fx={effect}  spd={speed}")

    def flash_ack(self):
        """Quick white flash to acknowledge hearing a command.
        Clears _current so the next set_emotion/set_state always re-sends,
        since the ESP32's LEDs are now white and need to be explicitly restored."""
        self._current = None
        self._send({
            "command": "neo_flash",
            "r": 255, "g": 255, "b": 255,
            "duration_ms": 120
        })

    def off(self):
        self.set_state("off")

    def _apply(self, r, g, b, effect, speed, brightness):
        cmd = {
            "command":    "neo_set",
            "r":          r,
            "g":          g,
            "b":          b,
            "effect":     effect,
            "speed":      speed,
            "brightness": brightness,
        }
        self._send(cmd)
