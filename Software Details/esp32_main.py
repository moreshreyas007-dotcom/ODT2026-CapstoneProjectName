
import machine, time, random, json, _thread, math, neopixel
from machine import Pin, PWM, UART

USE_UART_JSON_BRIDGE = False
UART_JSON_BAUD = 115200
UART_JSON_RX_PIN = 16
UART_JSON_TX_PIN = 17

USE_BLE_JSON_BRIDGE = True
BLE_GAP_NAME = "Luxo-Lamp"

LAMP_DIAG_INTERVAL_MS = 2000

IDLE_BOOT_GRACE_MS = 5000
# Time between idle animations (ms) — lower = more “alive” (was 8000–20000).
IDLE_WAIT_MIN_MS = 2500
IDLE_WAIT_MAX_MS = 7000

NEO_PIN = 15
NEO_COUNT = 12
# Neo updates faster than 8 ms/step can look glitchy; 0 from host means “fast”.
NEO_SPEED_MIN_MS = 8

np = neopixel.NeoPixel(Pin(NEO_PIN), NEO_COUNT)

neo_state = {
    "r": 255, "g": 240, "b": 200,
    "brightness": 80, "speed": 120,
    "effect": "breathe", "dirty": True,
}
neo_step = 0
neo_last_tick = 0
flash_until = 0
flash_color = (255, 255, 255)
neo_lock = _thread.allocate_lock()

def _pixels_off():
    for i in range(NEO_COUNT):
        np[i] = (0, 0, 0)

def _apply_brightness(r, g, b, brightness):
    s = brightness / 255.0
    return int(r * s), int(g * s), int(b * s)

def _fill_all(r, g, b, brightness=None):
    bri = brightness if brightness is not None else neo_state["brightness"]
    r, g, b = _apply_brightness(r, g, b, bri)
    for i in range(NEO_COUNT):
        np[i] = (r, g, b)

def _hsv_to_rgb(h, s, v):
    h = h % 360
    i = int(h / 60)
    f = (h / 60) - i
    p = v * (1 - s)
    q = v * (1 - f * s)
    t = v * (1 - (1 - f) * s)
    r, g, b = [(v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q)][i]
    return int(r * 255), int(g * 255), int(b * 255)

def neo_tick():
    global neo_step, neo_last_tick, flash_until
    now = time.ticks_ms()

    with neo_lock:
        fu = flash_until
    if fu > 0:
        if time.ticks_diff(fu, now) > 0:
            return
        else:
            with neo_lock:
                flash_until = 0
                neo_state["dirty"] = True

    with neo_lock:
        dirty = neo_state["dirty"]
        effect = neo_state["effect"]
        r = neo_state["r"]
        g = neo_state["g"]
        b = neo_state["b"]
        bri = neo_state["brightness"]
        speed = max(NEO_SPEED_MIN_MS, int(neo_state["speed"]))
        if dirty:
            neo_state["dirty"] = False

    if dirty:
        neo_step = 0
        neo_last_tick = now
        _pixels_off()
        np.write()

    if time.ticks_diff(now, neo_last_tick) < speed:
        return
    neo_last_tick = now

    if effect == "solid":
        if neo_step == 0:
            _fill_all(r, g, b)

    elif effect == "pulse":
        s = neo_step % 256
        t = s / 127.0 if s < 128 else (255 - s) / 127.0
        t = t * t * (3 - 2 * t)
        _fill_all(r, g, b, int(40 + t * (bri - 40)))

    elif effect == "breathe":
        angle = (neo_step % 200) / 200.0 * 2 * math.pi
        t = (math.sin(angle - math.pi / 2) + 1) / 2
        _fill_all(r, g, b, int(15 + t * (bri - 15)))

    elif effect == "blink":
        phase = neo_step % 32
        if phase < 3 or (6 <= phase < 9):
            _fill_all(r, g, b)
        else:
            _pixels_off()

    elif effect == "strobe":
        if neo_step % 2 == 0:
            _fill_all(r, g, b)
        else:
            _pixels_off()

    elif effect == "chase":
        _pixels_off()
        head = neo_step % NEO_COUNT
        for t in range(4):
            idx = (head - t) % NEO_COUNT
            fade = 1.0 - t * 0.22
            np[idx] = (int(r * fade * bri / 255), int(g * fade * bri / 255), int(b * fade * bri / 255))

    elif effect == "rainbow":
        offset = (neo_step * 3) % 360
        for i in range(NEO_COUNT):
            hue = (offset + i * (360 // max(NEO_COUNT, 1))) % 360
            rr, gg, bb = _hsv_to_rgb(hue, 1.0, bri / 255.0)
            np[i] = (rr, gg, bb)

    elif effect == "flicker":
        b2 = int(bri * (0.5 + 0.5 * random.random()))
        _fill_all(r, g, b, b2)

    elif effect == "sweep":
        _pixels_off()
        pos = neo_step % (NEO_COUNT * 2)
        if pos >= NEO_COUNT:
            pos = (NEO_COUNT * 2 - 1) - pos
        np[pos] = _apply_brightness(r, g, b, bri)
        if pos > 0:
            np[pos - 1] = _apply_brightness(r, g, b, bri // 4)
        if pos < NEO_COUNT - 1:
            np[pos + 1] = _apply_brightness(r, g, b, bri // 4)

    else:
        _fill_all(r, g, b)

    np.write()
    neo_step += 1

def neo_set(r, g, b, effect, speed, brightness):
    with neo_lock:
        neo_state.update({
            "r": r, "g": g, "b": b, "effect": effect,
            "speed": max(NEO_SPEED_MIN_MS, int(speed)),
            "brightness": int(brightness), "dirty": True,
        })
    print("   [NEO] %s rgb=(%d,%d,%d) bri=%d spd=%d" % (effect, r, g, b, brightness, max(NEO_SPEED_MIN_MS, int(speed))))

def neo_flash(r, g, b, duration_ms):
    global flash_until, flash_color
    flash_color = (r, g, b)
    with neo_lock:
        flash_until = time.ticks_ms() + duration_ms
    _fill_all(r, g, b, 255)
    np.write()

EMOTION_LIGHT = {
    "HAPPY": (255, 200, 30, "pulse", 80, 200),
    "EXCITED": (0, 230, 255, "strobe", 30, 255),
    "CURIOUS": (160, 50, 255, "breathe", 60, 180),
    "THINK": (30, 80, 255, "chase", 50, 160),
    "AGREE": (20, 255, 100, "blink", 40, 200),
    "DISAGREE": (255, 80, 10, "flicker", 70, 150),
    "IDLE": (255, 240, 200, "breathe", 120, 80),
}
STATE_LIGHT = {
    "thinking": (50, 100, 255, "chase", 45, 130),
    # speed 0 confused timing; use small step delay for smooth rainbow
    "hand_tracking": (0, 255, 80, "rainbow", 25, 200),
    "startup": (255, 160, 20, "pulse", 90, 220),
    "off": (0, 0, 0, "solid", 0, 0),
}

def apply_neo_command(cmd):
    command = cmd.get("command", "")
    if command == "neo_set":
        sp = int(cmd.get("speed", 60))
        neo_set(
            int(cmd.get("r", 255)), int(cmd.get("g", 255)), int(cmd.get("b", 255)),
            cmd.get("effect", "solid"),
            sp,
            int(cmd.get("brightness", 128)),
        )
    elif command == "neo_flash":
        neo_flash(
            int(cmd.get("r", 255)), int(cmd.get("g", 255)), int(cmd.get("b", 255)),
            int(cmd.get("duration_ms", 150)),
        )
    elif command == "neo_emotion":
        tag = cmd.get("tag", "IDLE").upper()
        if tag in EMOTION_LIGHT:
            neo_set(*EMOTION_LIGHT[tag])
    elif command == "neo_state":
        s = cmd.get("state", "startup").lower()
        if s in STATE_LIGHT:
            neo_set(*STATE_LIGHT[s])

SERVO_MIN_US = 950
SERVO_MAX_US = 2050
_SERVO_DUTY_MAX = 1023

class Servo:
    def __init__(self, pin, min_us=None, max_us=None, freq=50):
        min_us = SERVO_MIN_US if min_us is None else min_us
        max_us = SERVO_MAX_US if max_us is None else max_us
        if min_us >= max_us:
            min_us, max_us = 950, 2050
        self.pwm = PWM(Pin(pin), freq=freq)
        self.min_us = min_us
        self.max_us = max_us
        self._angle = 90
        self.write(90)

    def write(self, angle):
        angle = max(0, min(180, angle))
        self._angle = angle
        us = self.min_us + (self.max_us - self.min_us) * angle // 180
        duty = us * 1024 * 50 // 1_000_000
        if duty > _SERVO_DUTY_MAX:
            duty = _SERVO_DUTY_MAX
        if duty < 0:
            duty = 0
        self.pwm.duty(duty)

    def read(self):
        return self._angle

STEPPER_MAX_STEPS_PER_MOVE = 600

class Stepper:
    def __init__(self, step_pin, dir_pin):
        self.step = Pin(step_pin, Pin.OUT)
        self.dir = Pin(dir_pin, Pin.OUT)
        self.pos = 0

    def move_to(self, target, step_delay_us=None):
        if step_delay_us is None:
            step_delay_us = STEPPER_STEP_DELAY_US
        target = max(-STEPPER_MAX_IDLE, min(STEPPER_MAX_IDLE, target))
        direction = 1 if target > self.pos else -1
        self.dir.value(1 if direction > 0 else 0)
        steps_left = abs(target - self.pos) + 40
        guard = min(steps_left, STEPPER_MAX_STEPS_PER_MOVE)
        n = 0
        while self.pos != target and n < guard:
            if _idle_animating:
                with _cmd_lock:
                    if _cmd_queue:
                        return
            self.step.value(1)
            time.sleep_us(step_delay_us)
            self.step.value(0)
            time.sleep_us(step_delay_us)
            self.pos += direction
            n += 1
        if n >= guard and self.pos != target:
            print("Stepper: stop at guard steps (target=%d pos=%d)" % (target, self.pos))

    def home(self):
        self.move_to(0)

PIN_LOWER = 13
PIN_MID = 12
PIN_HTILT = 14
PIN_HPAN = 27
STEP_PIN = 32
DIR_PIN = 4

lower_joint = Servo(PIN_LOWER)
mid_joint = Servo(PIN_MID)
head_tilt = Servo(PIN_HTILT)
head_pan = Servo(PIN_HPAN)
stepper = Stepper(STEP_PIN, DIR_PIN)

LOWER_CENTER = 90
LOWER_FWD = 112
LOWER_BACK = 68
LOWER_MIN = 65
LOWER_MAX = 115
MID_CENTER = 90
MID_UP = 68
MID_DOWN = 112
MID_MIN = 58
MID_MAX = 118
HTILT_CENTER = 90
HTILT_UP = 68
HTILT_DOWN = 112
HTILT_MIN = 55
HTILT_MAX = 125
HPAN_CENTER = 90
HPAN_LEFT = 58
HPAN_RIGHT = 122
HPAN_MIN = 50
HPAN_MAX = 130

STEPPER_MAX_IDLE = 200
STEPPER_STEP_DELAY_US = 1400

_cmd_queue = []
_cmd_lock = _thread.allocate_lock()
_busy = False
_servo_lock = _thread.allocate_lock()
_idle_animating = False
_idle_grace_deadline = 0

def clamp(val, lo, hi):
    return max(lo, min(hi, val))

def smoothstep(t):
    return t * t * (3 - 2 * t)

def idle_sleep_ms(ms):
    if ms <= 0:
        return
    elapsed = 0
    chunk = 50
    while elapsed < ms:
        with _cmd_lock:
            if _cmd_queue:
                return
        step = ms - elapsed if (ms - elapsed) < chunk else chunk
        time.sleep_ms(step)
        elapsed += step

def move_servo(servo, target, duration_ms):
    start = servo.read()
    target = clamp(target, 0, 180)
    steps = 40
    for i in range(steps + 1):
        if _idle_animating:
            with _cmd_lock:
                if _cmd_queue:
                    return
        t = i / steps
        servo.write(int(start + (target - start) * smoothstep(t)))
        time.sleep_ms(max(1, duration_ms // steps))

def drift_to_neutral():
    move_servo(head_pan, HPAN_CENTER + random.randint(-4, 4), 500)
    move_servo(head_tilt, HTILT_CENTER + random.randint(-3, 3), 500)
    move_servo(lower_joint, LOWER_CENTER, 600)
    move_servo(mid_joint, MID_CENTER, 600)

def run_behavior(name):
    global _busy
    print("   [BEHAVIOR] %s" % name)
    try:
        if name == "attention":
            move_servo(head_pan, HPAN_CENTER, 400)
            move_servo(head_tilt, HTILT_CENTER, 400)
            move_servo(mid_joint, MID_CENTER, 400)
            move_servo(lower_joint, LOWER_CENTER, 400)
        elif name == "nod":
            move_servo(head_tilt, HTILT_DOWN, 250)
            time.sleep_ms(200)
            move_servo(head_tilt, HTILT_UP, 250)
            time.sleep_ms(200)
            move_servo(head_tilt, HTILT_CENTER, 300)
        elif name == "head_shake":
            move_servo(head_pan, HPAN_LEFT, 250)
            time.sleep_ms(150)
            move_servo(head_pan, HPAN_RIGHT, 250)
            time.sleep_ms(150)
            move_servo(head_pan, HPAN_CENTER, 300)
        elif name == "wiggle":
            for _ in range(3):
                move_servo(head_pan, HPAN_LEFT, 120)
                move_servo(head_pan, HPAN_RIGHT, 120)
            move_servo(head_pan, HPAN_CENTER, 250)
        elif name == "head_tilt":
            move_servo(head_tilt, HTILT_UP, 400)
            move_servo(head_pan, HPAN_RIGHT, 400)
            time.sleep_ms(500)
        elif name == "idle_look":
            move_servo(head_pan, HPAN_CENTER, 400)
            move_servo(head_tilt, HTILT_CENTER + 5, 400)
        elif name == "happy_bounce":
            for _ in range(2):
                move_servo(mid_joint, MID_UP, 300)
                time.sleep_ms(150)
                move_servo(mid_joint, MID_DOWN, 300)
                time.sleep_ms(150)
            move_servo(mid_joint, MID_CENTER, 400)
        elif name == "curious_tilt":
            move_servo(head_tilt, HTILT_UP, 400)
            move_servo(head_pan, HPAN_RIGHT, 400)
            move_servo(lower_joint, LOWER_FWD, 600)
            time.sleep_ms(600)
        elif name == "thinking":
            move_servo(head_tilt, HTILT_UP, 400)
            move_servo(head_pan, HPAN_RIGHT, 400)
            move_servo(mid_joint, MID_UP, 500)
        else:
            print("   [BEHAVIOR] Unknown: %r" % name)
            drift_to_neutral()
    except Exception as e:
        print("   [BEHAVIOR] error:", e)
    finally:
        with _servo_lock:
            _busy = False

def run_move(joint, angle):
    servo_map = {"pan": head_pan, "tilt": head_tilt, "lower": lower_joint, "mid": mid_joint}
    if joint in servo_map:
        servo_map[joint].write(int(angle))
    else:
        print("   [MOVE] Unknown joint: %r" % joint)

def do_head_glance():
    direction = 1 if random.randint(0, 1) else -1
    target = clamp(HPAN_CENTER + direction * random.randint(15, 35), HPAN_MIN, HPAN_MAX)
    move_servo(head_pan, target, random.randint(180, 320))
    idle_sleep_ms(random.randint(300, 900))
    move_servo(head_pan, HPAN_CENTER, random.randint(250, 450))

def do_slow_scan():
    direction = 1 if random.randint(0, 1) else -1
    move_servo(head_pan, clamp(HPAN_CENTER + direction * random.randint(5, 15), HPAN_MIN, HPAN_MAX), 300)
    idle_sleep_ms(100)
    stepper.move_to(stepper.pos + direction * random.randint(80, 180))
    idle_sleep_ms(random.randint(500, 1200))
    move_servo(head_pan, HPAN_CENTER, 400)
    stepper.home()

def do_desk_look():
    move_servo(mid_joint, MID_DOWN, random.randint(500, 800))
    move_servo(head_tilt, HTILT_DOWN, random.randint(300, 500))
    idle_sleep_ms(random.randint(700, 2000))
    move_servo(head_tilt, HTILT_CENTER, 400)
    move_servo(mid_joint, MID_CENTER, random.randint(500, 750))

def do_micro_twitch():
    cur = head_pan.read()
    nudge = random.randint(2, 6) * (1 if random.randint(0, 1) else -1)
    move_servo(head_pan, clamp(cur + nudge, HPAN_MIN, HPAN_MAX), 70)
    idle_sleep_ms(50)
    move_servo(head_pan, cur, 100)

def do_curious_lean():
    lean = random.randint(15, 25)
    move_servo(lower_joint, clamp(LOWER_CENTER + lean, LOWER_MIN, LOWER_MAX), random.randint(600, 1000))
    idle_sleep_ms(80)
    move_servo(head_tilt, clamp(HTILT_CENTER + 8, HTILT_MIN, HTILT_MAX), 300)
    idle_sleep_ms(random.randint(900, 2200))
    move_servo(head_tilt, HTILT_CENTER, 400)
    move_servo(lower_joint, LOWER_CENTER, random.randint(700, 1100))

def do_body_bob():
    bob = random.randint(12, 22)
    move_servo(mid_joint, clamp(MID_CENTER - bob, MID_MIN, MID_MAX), random.randint(450, 700))
    move_servo(head_tilt, clamp(HTILT_CENTER + 6, HTILT_MIN, HTILT_MAX), 280)
    idle_sleep_ms(random.randint(150, 400))
    move_servo(mid_joint, clamp(MID_CENTER + bob, MID_MIN, MID_MAX), random.randint(350, 600))
    move_servo(head_tilt, clamp(HTILT_CENTER - 6, HTILT_MIN, HTILT_MAX), 280)
    idle_sleep_ms(random.randint(150, 350))
    move_servo(mid_joint, MID_CENTER, random.randint(450, 700))
    move_servo(head_tilt, HTILT_CENTER, 350)

def do_stretch_up():
    rise = random.randint(20, 30)
    move_servo(mid_joint, clamp(MID_CENTER - rise, MID_MIN, MID_MAX), random.randint(900, 1400))
    move_servo(head_tilt, HTILT_UP, 500)
    idle_sleep_ms(random.randint(600, 1300))
    move_servo(mid_joint, clamp(MID_CENTER + 8, MID_MIN, MID_MAX), random.randint(600, 900))
    idle_sleep_ms(120)
    move_servo(mid_joint, MID_CENTER, 300)
    move_servo(head_tilt, HTILT_CENTER, 500)

def do_startle_recoil():
    recoil = random.randint(18, 28)
    move_servo(lower_joint, clamp(LOWER_CENTER - recoil, LOWER_MIN, LOWER_MAX), random.randint(80, 130))
    move_servo(head_tilt, HTILT_UP, 100)
    idle_sleep_ms(random.randint(300, 700))
    move_servo(lower_joint, LOWER_CENTER, random.randint(800, 1200))
    move_servo(head_tilt, HTILT_CENTER, 600)

MOVE_POOL = [
    do_head_glance, do_head_glance, do_head_glance,
    do_slow_scan, do_slow_scan,
    do_desk_look, do_desk_look,
    do_micro_twitch, do_micro_twitch,
    do_curious_lean, do_curious_lean,
    do_body_bob, do_stretch_up, do_startle_recoil,
]

def servo_dispatcher():
    global _busy
    print(" Servo dispatcher started")
    while True:
        behavior_cmd = None
        move_cmds = {}
        with _cmd_lock:
            if _cmd_queue:
                for c in _cmd_queue:
                    if c.get("command") == "move":
                        move_cmds[c.get("joint")] = c
                    elif c.get("command") == "behavior":
                        behavior_cmd = c
                _cmd_queue.clear()

        if behavior_cmd:
            while True:
                with _servo_lock:
                    if not _busy:
                        _busy = True
                        break
                time.sleep_ms(20)
            nm = behavior_cmd.get("name", "attention")
            print("  dispatcher: running behavior %r" % nm)
            run_behavior(nm)
        elif move_cmds:
            while True:
                with _servo_lock:
                    if not _busy:
                        _busy = True
                        break
                time.sleep_ms(20)
            for mc in move_cmds.values():
                run_move(mc.get("joint"), mc.get("angle", 90))
            with _servo_lock:
                _busy = False
        else:
            time.sleep_ms(20)

def idle_loop():
    global _busy, _idle_animating
    print(" Idle loop started (grace %d ms before random moves)" % IDLE_BOOT_GRACE_MS)
    while True:
        while time.ticks_diff(_idle_grace_deadline, time.ticks_ms()) > 0:
            time.sleep_ms(200)
        wait_ms = random.randint(IDLE_WAIT_MIN_MS, IDLE_WAIT_MAX_MS)
        start = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), start) < wait_ms:
            if _busy:
                time.sleep_ms(100)
                start = time.ticks_ms()
            time.sleep_ms(50)
        claimed = False
        with _servo_lock:
            if not _busy:
                _busy = True
                claimed = True
        if claimed:
            _idle_animating = True
            try:
                random.choice(MOVE_POOL)()
            except Exception as e:
                print(" idle anim error:", e)
            finally:
                _idle_animating = False
                idle_sleep_ms(random.randint(400, 1500))
                with _cmd_lock:
                    pending = len(_cmd_queue) > 0
                if not pending:
                    drift_to_neutral()
                with _servo_lock:
                    _busy = False

def dispatch_lamp_cmd(cmd, src=""):
    tag = ("[%s] " % src) if src else ""
    try:
        if not isinstance(cmd, dict):
            print(tag + "  Not a dict:", cmd)
            return
        command = cmd.get("command", "")
        print(tag + "%s" % (cmd,))
        if command.startswith("neo_"):
            apply_neo_command(cmd)
        elif command == "music_bounce":
            with _cmd_lock:
                _cmd_queue.append({"command": "behavior", "name": "wiggle"})
                qn = len(_cmd_queue)
            print(tag + " Queued music_bounce→wiggle (queue=%d)" % qn)
        elif command in ("behavior", "move"):
            with _cmd_lock:
                _cmd_queue.append(cmd)
                qn = len(_cmd_queue)
            print(tag + " Queued (queue=%d): %s" % (qn, cmd))
        else:
            print(tag + "Unknown: %s" % command)
    except Exception as e:
        print(tag + " dispatch: %s" % e)

def run_uart_json_bridge():
    if not USE_UART_JSON_BRIDGE:
        return
    u = UART(
        2,
        baudrate=UART_JSON_BAUD,
        tx=UART_JSON_TX_PIN,
        rx=UART_JSON_RX_PIN,
        timeout=200,
        timeout_char=50,
    )
    print("UART JSON bridge UART2 rx=%d tx=%d @ %d baud" % (UART_JSON_RX_PIN, UART_JSON_TX_PIN, UART_JSON_BAUD))
    buf = b""
    while True:
        try:
            if u.any():
                buf += u.read(u.any())
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    if len(line) > 600:
                        print("  UART line too long, skip")
                        continue
                    try:
                        cmd = json.loads(line.decode())
                        dispatch_lamp_cmd(cmd, "UART")
                    except ValueError as e:
                        print("UART JSON: %s | line=%r" % (e, line[:80]))
            else:
                time.sleep_ms(4)
        except Exception as e:
            print("UART bridge: %s" % e)
            time.sleep_ms(200)

_ble_inst = None
_ble_char_handle = None
_ble_central_connected = False
_diag_ble_gatt_chunks = 0
_diag_ble_json_ok = 0
_diag_ble_json_err = 0
_diag_ble_gatt_write_irq = 0
_diag_ble_gatt_wr_mismatch = 0
_diag_ble_gatt_wr_empty = 0
_last_lamp_diag_ms = 0
_ble_irq_chunks = []
_ble_line_acc = b""
# Nordic UART JSON lines are >20 bytes; default GATT max is 20 (writes truncated, no '\n' → no parse).
BLE_NUS_RX_BUF = 512

BLE_SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
BLE_CHAR_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"

_BLE_IRQ_CENTRAL_CONNECT = 1
_BLE_IRQ_CENTRAL_DISCONNECT = 2
_BLE_IRQ_GATTS_WRITE = 3

def lamp_diag_maybe_print():
    """Periodic USB log: confirms main loop alive; gatt/json counters show if BLE data arrives."""
    global _last_lamp_diag_ms
    if LAMP_DIAG_INTERVAL_MS <= 0:
        return
    now = time.ticks_ms()
    if _last_lamp_diag_ms == 0:
        _last_lamp_diag_ms = now
        return
    if time.ticks_diff(now, _last_lamp_diag_ms) < LAMP_DIAG_INTERVAL_MS:
        return
    _last_lamp_diag_ms = now
    qlen = 0
    with _cmd_lock:
        qlen = len(_cmd_queue)
    ns = neo_state
    neo_s = "%s rgb=(%d,%d,%d)" % (ns["effect"], ns["r"], ns["g"], ns["b"])
    acc = len(_ble_line_acc) if USE_BLE_JSON_BRIDGE else 0
    if USE_BLE_JSON_BRIDGE:
        print(
            "📡 diag  ble=%s  wr_irq=%d  bad_hdl=%d  empty=%d  queued=%d  json_ok=%d  json_err=%d  acc=%dB  busy=%s  idle_anim=%s  q=%d  %s"
            % (
                "linked" if _ble_central_connected else "adv",
                _diag_ble_gatt_write_irq,
                _diag_ble_gatt_wr_mismatch,
                _diag_ble_gatt_wr_empty,
                _diag_ble_gatt_chunks,
                _diag_ble_json_ok,
                _diag_ble_json_err,
                acc,
                _busy,
                _idle_animating,
                qlen,
                neo_s,
            )
        )
    else:
        print(
            "📡 diag  busy=%s  idle_anim=%s  q=%d  %s"
            % (_busy, _idle_animating, qlen, neo_s)
        )

def _ble_gap_advertise():
    name_bytes = BLE_GAP_NAME.encode()
    flags = bytearray([0x02, 0x01, 0x06])
    nus_le = bytes([
        0x9E, 0xCA, 0xDC, 0x24, 0x0E, 0xE5, 0xA9, 0xE0,
        0x93, 0xF3, 0xA3, 0xB5, 0x01, 0x00, 0x40, 0x6E,
    ])
    adv_svc = bytearray([17, 0x07]) + bytearray(nus_le)
    complete_name = bytearray([len(name_bytes) + 1, 0x09]) + name_bytes
    adv_primary = flags + adv_svc
    try:
        _ble_inst.gap_advertise(250_000, adv_data=adv_primary, resp_data=complete_name)
    except TypeError:
        adv_data = flags + adv_svc + complete_name
        if len(adv_data) > 31:
            short = bytearray([min(len(name_bytes), 7) + 1, 0x08]) + name_bytes[:7]
            adv_data = flags + adv_svc + short
        _ble_inst.gap_advertise(250_000, adv_data=adv_data)
    print("BLE: advertising as", BLE_GAP_NAME, "(NUS service UUID in ADV)")

def _ble_irq_handler(event, data):
    global _ble_central_connected, _diag_ble_gatt_chunks
    global _diag_ble_gatt_write_irq, _diag_ble_gatt_wr_mismatch, _diag_ble_gatt_wr_empty
    if event == _BLE_IRQ_CENTRAL_CONNECT:
        _ble_central_connected = True
        print("BLE: central connected")
    elif event == _BLE_IRQ_CENTRAL_DISCONNECT:
        _ble_central_connected = False
        print("BLE: central disconnected")
        _ble_gap_advertise()
    elif event == _BLE_IRQ_GATTS_WRITE:
        _diag_ble_gatt_write_irq += 1
        if len(data) < 2:
            return
        _conn, attr_handle = data[0], data[1]
        if attr_handle != _ble_char_handle:
            _diag_ble_gatt_wr_mismatch += 1
            return
        # Nimble passes the written bytes as data[2]; gatts_read() in the IRQ is often empty.
        raw = b""
        if len(data) > 2 and data[2] is not None:
            try:
                raw = bytes(data[2])
            except (TypeError, ValueError):
                raw = b""
        if not raw:
            raw = _ble_inst.gatts_read(_ble_char_handle) or b""
        raw = raw.rstrip(b"\x00")
        if not raw:
            _diag_ble_gatt_wr_empty += 1
            return
        _diag_ble_gatt_chunks += 1
        _ble_irq_chunks.append(raw)

def ble_lamp_init():
    global _ble_inst, _ble_char_handle
    if not USE_BLE_JSON_BRIDGE:
        return
    try:
        import bluetooth
    except ImportError:
        print("BLE: `import bluetooth` failed — use a BLE-capable MicroPython build")
        return
    _ble_inst = bluetooth.BLE()
    _ble_inst.active(False)
    time.sleep_ms(400)
    _ble_inst.active(True)
    _ble_inst.config(gap_name=BLE_GAP_NAME)
    service_uuid = bluetooth.UUID(BLE_SERVICE_UUID)
    char_uuid = bluetooth.UUID(BLE_CHAR_UUID)
    char = (char_uuid, bluetooth.FLAG_WRITE)
    service = (service_uuid, (char,))
    ((_ble_char_handle,),) = _ble_inst.gatts_register_services((service,))
    # See bluetooth docs: default client-write max is 20 bytes; extend + buffer like Nordic UART.
    try:
        _ble_inst.gatts_write(_ble_char_handle, bytes(BLE_NUS_RX_BUF))
    except MemoryError:
        _ble_inst.gatts_write(_ble_char_handle, bytes(128))
    try:
        _ble_inst.gatts_set_buffer(_ble_char_handle, BLE_NUS_RX_BUF, True)
    except (AttributeError, OSError, ValueError):
        pass
    _ble_inst.irq(_ble_irq_handler)
    _ble_gap_advertise()
    print("BLE: NUS JSON bridge ready (service %s)" % BLE_SERVICE_UUID)

def ble_process_rx():
    global _ble_line_acc, _ble_irq_chunks, _diag_ble_json_ok, _diag_ble_json_err
    if not USE_BLE_JSON_BRIDGE or _ble_inst is None:
        return
    ist = machine.disable_irq()
    try:
        drained = _ble_irq_chunks
        _ble_irq_chunks = []
    finally:
        machine.enable_irq(ist)
    if not drained:
        return
    for part in drained:
        _ble_line_acc += part
    if len(_ble_line_acc) > 1200:
        print(" BLE rx buffer overflow, clearing")
        _ble_line_acc = b""
        return
    while b"\n" in _ble_line_acc:
        line, _ble_line_acc = _ble_line_acc.split(b"\n", 1)
        line = line.strip()
        if not line:
            continue
        if len(line) > 600:
            print("BLE line too long, skip")
            continue
        try:
            cmd = json.loads(line.decode())
            _diag_ble_json_ok += 1
            dispatch_lamp_cmd(cmd, "BLE")
        except ValueError as e:
            _diag_ble_json_err += 1
            print("BLE JSON: %s | line=%r" % (e, line[:80]))

def boot_sequence():
    lower_joint.write(LOWER_CENTER)
    mid_joint.write(MID_CENTER)
    head_tilt.write(HTILT_CENTER)
    head_pan.write(HPAN_CENTER)
    time.sleep_ms(800)
    print("Servos at neutral")
    neo_set(*list(STATE_LIGHT["startup"]))
    time.sleep_ms(500)

print(" Luxo ESP32 booting…")

boot_sequence()

_idle_grace_deadline = time.ticks_add(time.ticks_ms(), IDLE_BOOT_GRACE_MS)

_thread.start_new_thread(servo_dispatcher, ())
_thread.start_new_thread(idle_loop, ())

if USE_UART_JSON_BRIDGE:
    _thread.start_new_thread(run_uart_json_bridge, ())

if USE_BLE_JSON_BRIDGE:
    ble_lamp_init()

if USE_BLE_JSON_BRIDGE:
    neo_set(0, 200, 255, "pulse", 80, 150)
elif USE_UART_JSON_BRIDGE:
    neo_set(100, 50, 255, "pulse", 80, 150)
else:
    neo_set(255, 0, 0, "pulse", 80, 150)

print(" Main NeoPixel — UART=%s BLE=%s" % (USE_UART_JSON_BRIDGE, USE_BLE_JSON_BRIDGE))
print(" USB serial: [BLE]/[UART] lines; then [BEHAVIOR] = servos.")
if LAMP_DIAG_INTERVAL_MS > 0:
    print(" Heartbeat every %d ms (set LAMP_DIAG_INTERVAL_MS=0 to disable)" % LAMP_DIAG_INTERVAL_MS)

while True:
    neo_tick()
    ble_process_rx()
    lamp_diag_maybe_print()
    time.sleep_ms(10)
