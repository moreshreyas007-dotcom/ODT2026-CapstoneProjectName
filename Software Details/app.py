"""
Luxo v2 — Flask voice server.
Whisper STT → Gemini AI → Edge TTS → ESP32 lamp over BLE or serial.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from faster_whisper import WhisperModel

from ai_brain import AIBrain
from emotion_parser import EmotionParser
from hand_tracker import HandTracker
from lamp_link import connect_lamp
from tts import TextToSpeech

try:
    lamp = connect_lamp()
except Exception as e:
    print("\nLuxo v2 requires a connected lamp (BLE or serial).", flush=True)
    print("   %s: %s" % (type(e).__name__, e), flush=True)
    print(
        "   BLE: power ESP32, allow Bluetooth for this app, try LUXO_BLE_ADDRESS + LUXO_BLE_SCAN_DEBUG=1.\n",
        flush=True,
    )
    raise SystemExit(1) from e

if not lamp.is_hardware_connected:
    print("\nLamp not connected after init.\n", flush=True)
    raise SystemExit(1)

# preset name → behavior/neo state. Keys match esp32_main behavior names.
DEMO_PRESETS = {
    "ready": lambda: lamp.send_behavior("attention"),
    "idle": lambda: lamp.send_behavior("idle_look"),
    "happy": lambda: lamp.send_behavior("happy_bounce"),
    "excited": lambda: lamp.send_behavior("wiggle"),
    "curious": lambda: lamp.send_behavior("curious_tilt"),
    "thinking": lambda: lamp.send_behavior("thinking"),
    "confused": lambda: lamp.send_behavior("head_tilt"),
    "agree": lambda: lamp.send_behavior("nod"),
    "disagree": lambda: lamp.send_behavior("head_shake"),
    "rainbow": lambda: (
        lamp.send_behavior("idle_look"),
        lamp.neo.set_state("hand_tracking"),
    ),
    "startup": lambda: (
        lamp.send_behavior("idle_look"),
        lamp.neo.set_state("startup"),
    ),
    "lights_off": lambda: (
        lamp.send_behavior("idle_look"),
        lamp.neo.set_state("off"),
    ),
}

_whisper: WhisperModel | None = None


def get_whisper() -> WhisperModel:
    global _whisper
    if _whisper is None:
        print("Loading Whisper (tiny, int8, CPU)...", flush=True)
        _whisper = WhisperModel("tiny", device="cpu", compute_type="int8")
        print("Whisper ready.", flush=True)
    return _whisper


print("Booting Luxo v2…", flush=True)
ai = AIBrain()
ep = EmotionParser()
tts = TextToSpeech()
tracker = HandTracker(lamp)
tracker.start()

lamp.send_behavior("attention")
print("Say 'follow me' for hand tracking, 'talk to me' to return to chat.\n", flush=True)

app = Flask(__name__)
CORS(app)
_STATIC = os.path.join(_ROOT, "static")


@app.route("/")
def index():
    return send_from_directory(_STATIC, "index.html")


@app.route("/transcribe", methods=["POST"])
def transcribe():
    if "audio" not in request.files:
        return jsonify({"error": "No audio file received."}), 400

    audio_file = request.files["audio"]
    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp:
        tmp_path = tmp.name
        audio_file.save(tmp_path)

    try:
        t0 = time.time()
        lamp.neo.flash_ack()

        whisper_model = get_whisper()
        segments, _ = whisper_model.transcribe(tmp_path, beam_size=1)
        transcript = " ".join(seg.text for seg in segments).strip()
        t_stt = time.time()
        print("You: %r  (STT %.2fs)" % (transcript, t_stt - t0), flush=True)

        if not transcript:
            lamp.neo.set_emotion("IDLE")
            return jsonify({"error": "No speech detected."}), 200

        lower = transcript.lower()

        if any(p in lower for p in ["follow me", "follow my hand", "track my hand"]):
            tracker.enable()
            lamp.neo.set_state("hand_tracking")
            return jsonify(
                {
                    "transcript": transcript,
                    "luxo_response": "Following your hand!",
                    "mode": "hand_tracking",
                }
            )

        if any(p in lower for p in ["talk to me", "stop following", "conversation"]):
            tracker.disable()
            lamp.neo.set_emotion("HAPPY")
            return jsonify(
                {
                    "transcript": transcript,
                    "luxo_response": "Back to conversation mode!",
                    "mode": "conversation",
                }
            )

        if tracker.active:
            return jsonify(
                {
                    "transcript": transcript,
                    "luxo_response": "(hand tracking — say 'talk to me' to chat)",
                    "mode": "hand_tracking",
                }
            )

        lamp.send_behavior("thinking")
        full_response = ""
        first_sentence = ""
        first_spoken = False

        for chunk in ai.stream_response(transcript):
            full_response += chunk
            first_sentence += chunk
            if not first_spoken and any(p in first_sentence for p in [".", "!", "?"]):
                behavior, clean = ep.parse(first_sentence)
                lamp.send_behavior(behavior)
                tts.speak_async(clean)
                first_spoken = True
                first_sentence = ""

        if not first_spoken and full_response.strip():
            behavior, clean = ep.parse(full_response)
            lamp.send_behavior(behavior)
            tts.speak_async(clean)
        elif first_spoken and first_sentence.strip():
            _, clean = ep.parse(first_sentence)
            tts.speak_async(clean)

        _, display_text = ep.parse(full_response)
        print("Luxo: %r  (total %.2fs)\n" % (display_text, time.time() - t0), flush=True)

        return jsonify(
            {
                "transcript": transcript,
                "luxo_response": display_text,
                "mode": "conversation",
            }
        )

    except Exception as exc:
        print("Error: %s" % exc, flush=True)
        lamp.neo.set_emotion("IDLE")
        return jsonify({"error": str(exc)}), 500
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


@app.route("/lamp/preset", methods=["POST"])
def lamp_preset():
    """Apply a hardcoded lamp pose + lights (no STT). Body: {"preset": "ready"}"""
    body = request.get_json(silent=True) or {}
    pid = (body.get("preset") or body.get("id") or "").strip().lower().replace("-", "_")
    fn = DEMO_PRESETS.get(pid)
    if fn is None:
        return jsonify(
            {"ok": False, "error": "unknown preset", "valid": sorted(DEMO_PRESETS)}
        ), 400
    try:
        fn()
        print("Demo preset: %s" % pid, flush=True)
        return jsonify({"ok": True, "preset": pid})
    except Exception as exc:
        print("lamp_preset error: %s" % exc, flush=True)
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/lamp/reconnect", methods=["POST"])
def lamp_reconnect():
    """Retry BLE/serial after the ESP32 powers on or Bluetooth was off at server start."""
    fn = getattr(lamp, "reconnect", None)
    connected = bool(fn()) if callable(fn) else False
    return jsonify(
        {
            "ok": True,
            "lamp_connected": lamp.is_hardware_connected,
            "lamp_transport": getattr(lamp, "lamp_transport", ""),
            "lamp_endpoint": getattr(lamp, "lamp_endpoint", ""),
            "reconnect_attempted": callable(fn),
            "reconnect_returned_connected": connected,
        }
    )


@app.route("/tracking", methods=["POST"])
def tracking_set():
    """Enable/disable hand tracking from the UI toggle. Body: {"enabled": true|false}"""
    body = request.get_json(silent=True) or {}
    if "enabled" not in body and "active" not in body:
        return jsonify({"ok": False, "error": 'Send JSON: {"enabled": true} or {"enabled": false}'}), 400
    want = body.get("enabled", body.get("active"))
    if bool(want):
        tracker.enable()
        lamp.neo.set_state("hand_tracking")
        msg = "Hand tracking ON"
    else:
        tracker.disable()
        lamp.neo.set_emotion("HAPPY")
        msg = "Hand tracking OFF"
    print("%s (tracker.active=%s)" % (msg, tracker.active), flush=True)
    return jsonify(
        {
            "ok": True,
            "hand_tracking": tracker.active,
            "mode": "hand_tracking" if tracker.active else "conversation",
            "message": msg,
        }
    )


@app.route("/health")
def health():
    return jsonify(
        {
            "status": "ok",
            "version": "luxo_v2",
            "mode": "hand_tracking" if tracker.active else "conversation",
            "hand_tracking": tracker.active,
            "lamp_connected": lamp.is_hardware_connected,
            "lamp_transport": getattr(lamp, "lamp_transport", ""),
            "lamp_endpoint": getattr(lamp, "lamp_endpoint", ""),
            "gemini_configured": getattr(ai, "client", None) is not None,
            "lamp_presets": sorted(DEMO_PRESETS),
        }
    )


if __name__ == "__main__":
    port = int(os.environ.get("LUXO_PORT", "5050"))
    print("Luxo v2 → http://0.0.0.0:%s (set LUXO_PORT to change)" % port)
    app.run(host="0.0.0.0", port=port, debug=False)
