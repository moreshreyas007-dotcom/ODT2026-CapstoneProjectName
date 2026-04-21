# hand_tracker.py
# Reads ESP32-CAM stream → MediaPipe hand detection →
# sends pan/tilt/lean servo commands to LampController

import cv2
import threading
import time
import numpy as np

try:
    import mediapipe as _mediapipe
    _mp_hands   = _mediapipe.solutions.hands
    _mp_drawing = _mediapipe.solutions.drawing_utils
    MP_AVAILABLE = True
except Exception as _e:
    _mp_hands   = None
    _mp_drawing = None
    MP_AVAILABLE = False
    print(f"  mediapipe not available: {_e}")

ESP32_CAM_URL = None
# "http://10.91.2.59/stream"  ← set to your ESP32-CAM's IP

# servo angle ranges (match esp32_main.py)
PAN_MIN   = 40;  PAN_MAX   = 140;  PAN_CENTER   = 90
TILT_MIN  = 50;  TILT_MAX  = 130;  TILT_CENTER  = 90
LEAN_MIN  = 60;  LEAN_MAX  = 120;  LEAN_CENTER  = 90

# hand bounding box height as fraction of frame height — tune after testing
HAND_CLOSE = 0.6   # hand fills 60% of frame = very close → lean forward
HAND_FAR   = 0.15  # hand fills 15% of frame = far away  → lean back

# higher = slower/smoother, lower = faster/jittery
SMOOTH = 0.15


class HandTracker:
    def __init__(self, lamp):
        self.lamp = lamp
        self.running = False
        self.active  = False   # True = hand tracking mode, False = paused
        self.thread  = None

        self._pan  = float(PAN_CENTER)
        self._tilt = float(TILT_CENTER)
        self._lean = float(LEAN_CENTER)

        self._last_pan  = PAN_CENTER
        self._last_tilt = TILT_CENTER
        self._last_lean = LEAN_CENTER

        if not MP_AVAILABLE:
            print(" HandTracker: mediapipe not available")
            return

        self.mp_hands   = _mp_hands
        self.mp_drawing = _mp_drawing
        self.hands      = self.mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=1,
            min_detection_confidence=0.6,
            min_tracking_confidence=0.5,
        )
        print("️  HandTracker ready")

    def start(self):
        if not MP_AVAILABLE:
            return
        if self.running:
            return
        self.running = True
        self.thread  = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        print("  Hand tracking thread started")

    def stop(self):
        self.running = False

    def enable(self):
        self.active = True
        print("  Hand tracking ENABLED — lamp following hand")

    def disable(self):
        self.active = False
        self.lamp.send_move("pan",  PAN_CENTER)
        self.lamp.send_move("tilt", TILT_CENTER)
        self.lamp.send_move("lower", LEAN_CENTER)
        print(" Hand tracking DISABLED — back to conversation mode")

    def _loop(self):
        cap = None
        consecutive_failures = 0

        while self.running:
            if not self.active:
                time.sleep(0.1)
                continue

            if cap is None or not cap.isOpened():
                source = ESP32_CAM_URL if ESP32_CAM_URL else 0
                cap = cv2.VideoCapture(source)
                if not cap.isOpened():
                    time.sleep(3)
                    consecutive_failures += 1
                    if consecutive_failures > 5:
                        print(" Too many failures — disabling hand tracking")
                        self.active = False
                        consecutive_failures = 0
                    continue
                else:
                    consecutive_failures = 0

            ret, frame = cap.read()
            if not ret:
                cap.release()
                cap = None
                time.sleep(1)
                continue

            self._process_frame(frame)
            time.sleep(0.05)  # ~20fps is enough for smooth tracking

        if cap:
            cap.release()

    def _process_frame(self, frame):
        h, w = frame.shape[:2]

        # flip horizontally so movement feels natural (mirror mode)
        frame = cv2.flip(frame, 1)

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self.hands.process(rgb)

        if not results.multi_hand_landmarks:
            self._smooth_move_to(PAN_CENTER, TILT_CENTER, LEAN_CENTER, factor=0.03)
            return

        landmarks = results.multi_hand_landmarks[0]

        xs = [lm.x for lm in landmarks.landmark]
        ys = [lm.y for lm in landmarks.landmark]

        hand_cx = sum(xs) / len(xs)  # 0.0 (left) to 1.0 (right)
        hand_cy = sum(ys) / len(ys)  # 0.0 (top)  to 1.0 (bottom)

        # bounding box height as proxy for distance
        hand_h = (max(ys) - min(ys))

        target_pan  = self._map(hand_cx, 0.0, 1.0, PAN_MAX, PAN_MIN)
        target_tilt = self._map(hand_cy, 0.0, 1.0, TILT_MIN, TILT_MAX)
        target_lean = self._map(hand_h, HAND_FAR, HAND_CLOSE, LEAN_MIN, LEAN_MAX)

        self._smooth_move_to(target_pan, target_tilt, target_lean)

        if int(time.time() * 20) % 30 == 0:
            print(f"  hand=({hand_cx:.2f}, {hand_cy:.2f}) size={hand_h:.2f} "
                  f" pan={int(self._pan)} tilt={int(self._tilt)} lean={int(self._lean)}")

    def _smooth_move_to(self, target_pan, target_tilt, target_lean, factor=None):
        f = factor or SMOOTH

        self._pan  += (target_pan  - self._pan)  * f
        self._tilt += (target_tilt - self._tilt) * f
        self._lean += (target_lean - self._lean) * f

        pan  = int(self._pan)
        tilt = int(self._tilt)
        lean = int(self._lean)

        # only send command if angle changed by more than 1 degree
        if abs(pan  - self._last_pan)  >= 1:
            self.lamp.send_move("pan",   pan)
            self._last_pan  = pan

        if abs(tilt - self._last_tilt) >= 1:
            self.lamp.send_move("tilt",  tilt)
            self._last_tilt = tilt

        if abs(lean - self._last_lean) >= 1:
            self.lamp.send_move("lower", lean)
            self._last_lean = lean

    @staticmethod
    def _map(value, in_min, in_max, out_min, out_max):
        if in_max == in_min:
            return out_min
        ratio  = (value - in_min) / (in_max - in_min)
        ratio  = max(0.0, min(1.0, ratio))
        return out_min + ratio * (out_max - out_min)
