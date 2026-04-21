# lamp_link.py — laptop → ESP32 lamp: BLE (default) or USB-serial JSON.
# BLE: pip install bleak
# Serial: pip install pyserial

from __future__ import annotations

import glob
import json
import os
import threading

try:
    import serial
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False

from neopixel_controller import NeoPixelController

SERIAL_BAUD = int(os.environ.get("LUXO_SERIAL_BAUD", "115200"))
_SERIAL_DEBUG = os.environ.get("LUXO_SERIAL_DEBUG", "").strip().lower() in ("1", "true", "yes")

_GLOBS = (
    "/dev/cu.usbserial*",
    "/dev/cu.wchusbserial*",
    "/dev/cu.SLAB_USBtoUART*",
)


def list_serial_candidates() -> list[str]:
    found: list[str] = []
    for pat in _GLOBS:
        found.extend(sorted(glob.glob(pat)))
    seen: set[str] = set()
    uniq: list[str] = []
    for p in found:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


def _env_port_looks_like_placeholder(path: str) -> bool:
    low = path.lower()
    markers = (
        "your_dongle",
        "your-dongle",
        "yourdongle",
        "changeme",
        "paste_",
        "replace_me",
        "ttyusb0",
    )
    return any(m in low for m in markers)


def _print_serial_port_hint() -> None:
    c = list_serial_candidates()
    if c:
        print("   Likely USB-serial devices on this Mac:")
        for p in c:
            print(f"      {p}")
    else:
        print("   No /dev/cu.usbserial* or /dev/cu.wchusbserial* found.")


def resolve_serial_port() -> str | None:
    env = os.environ.get("LUXO_SERIAL_PORT", "").strip()
    if env:
        if _env_port_looks_like_placeholder(env):
            print("LUXO_SERIAL_PORT looks like a placeholder, not a real device name.")
            _print_serial_port_hint()
            env = ""
        elif not os.path.exists(env):
            print(f"LUXO_SERIAL_PORT={env!r} does not exist on this machine.")
            _print_serial_port_hint()
            env = ""
        else:
            return env

    uniq = list_serial_candidates()
    if len(uniq) == 1:
        print(f"Using auto-detected serial port: {uniq[0]}")
        return uniq[0]
    if len(uniq) > 1:
        print(
            "Multiple USB-serial devices found — using the first.\n"
            "   Set LUXO_SERIAL_PORT explicitly to your USB-TTL dongle (GPIO16/17).\n   "
            + repr(uniq)
        )
        return uniq[0]
    return None


class SerialLampController:
    def __init__(self, simulate: bool = False, port: str | None = None):
        self.simulate = bool(simulate)
        self._lock = threading.Lock()
        self.port = port or resolve_serial_port()
        self.ser = None

        if self.simulate:
            print("SerialLampController: offline test mode (no serial)")
        else:
            self._connect()

        self.neo = NeoPixelController(send_fn=self._send)
        self.neo.set_state("startup")

    @property
    def lamp_transport(self) -> str:
        return "serial"

    @property
    def lamp_endpoint(self) -> str:
        if self.port:
            return f"serial:{self.port}@{SERIAL_BAUD}"
        return f"serial:(no port)@{SERIAL_BAUD}"

    @property
    def is_hardware_connected(self) -> bool:
        return not self.simulate and self.ser is not None and getattr(self.ser, "is_open", False)

    def _connect(self) -> None:
        if self.simulate:
            return
        if not SERIAL_AVAILABLE:
            raise RuntimeError(
                "Serial lamp transport requires pyserial. Run: pip install pyserial"
            )
        if not self.port:
            _print_serial_port_hint()
            raise RuntimeError(
                "No serial port for lamp. Set LUXO_SERIAL_PORT to your USB-TTL device (GPIO16/17)."
            )
        try:
            if self.ser is not None:
                try:
                    self.ser.close()
                except Exception:
                    pass
            self.ser = serial.Serial(
                self.port,
                SERIAL_BAUD,
                timeout=0.25,
                write_timeout=2.0,
            )
            print(f"SerialLampController: open {self.port} @ {SERIAL_BAUD}")
        except Exception as e:
            self.ser = None
            raise RuntimeError("Serial open failed (%s): %s" % (self.port, e)) from e

    def send_behavior(self, behavior_name: str):
        cmd = {"command": "behavior", "name": behavior_name}
        self._send(cmd)
        behavior_to_emotion = {
            "thinking": "THINK",
            "attention": "CURIOUS",
            "wiggle": "EXCITED",
            "nod": "AGREE",
            "shake": "DISAGREE",
            "head_shake": "DISAGREE",
            "head_tilt": "THINK",
            "happy": "HAPPY",
            "happy_bounce": "HAPPY",
            "idle": "IDLE",
            "idle_look": "IDLE",
            "excited": "EXCITED",
            "agree": "AGREE",
            "disagree": "DISAGREE",
            "curious": "CURIOUS",
            "curious_tilt": "CURIOUS",
        }
        emotion = behavior_to_emotion.get(behavior_name.lower())
        if emotion:
            self.neo.set_emotion(emotion)

    def send_emotion_light(self, emotion_tag: str):
        self.neo.set_emotion(emotion_tag)

    def send_state_light(self, state: str):
        self.neo.set_state(state)

    def send_move(self, joint: str, angle: int):
        self._send({"command": "move", "joint": joint, "angle": angle})

    def send_music_bounce(self):
        self._send({"command": "music_bounce"})

    def _send(self, cmd: dict):
        line = json.dumps(cmd, separators=(",", ":")) + "\n"
        if self.simulate:
            print(f"[LAMP SERIAL SIM] → {line.strip()}")
            return
        with self._lock:
            try:
                assert self.ser is not None
                self.ser.write(line.encode("utf-8"))
                self.ser.flush()
                if _SERIAL_DEBUG:
                    print(f"   [SERIAL TX] {line.strip()}")
            except Exception as e:
                print(f"[SerialLampController] Send error: {e} — reopening…")
                self._connect()
                try:
                    assert self.ser is not None
                    self.ser.write(line.encode("utf-8"))
                    self.ser.flush()
                except Exception as e2:
                    raise RuntimeError(
                        "Serial lamp send failed after reconnect: %s" % e2
                    ) from e2

    def reconnect(self) -> bool:
        if self.simulate:
            return False
        try:
            self._connect()
            return self.is_hardware_connected
        except Exception as e:
            print(f"Serial reconnect failed: {e}")
            return False

    def close(self):
        if self.ser:
            try:
                self.ser.close()
            except Exception:
                pass
            self.ser = None


import asyncio
import re
import time

try:
    from bleak import BleakClient, BleakScanner
    BLEAK_AVAILABLE = True
except ImportError:
    BLEAK_AVAILABLE = False


NUS_SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
NUS_RX_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
DEFAULT_NAME = os.environ.get("LUXO_BLE_NAME", "Luxo-Lamp").strip()
_SCAN_TIMEOUT = float(os.environ.get("LUXO_BLE_SCAN_TIMEOUT", "20"))
_CONNECT_TIMEOUT = float(os.environ.get("LUXO_BLE_CONNECT_TIMEOUT", "15"))
_SCAN_DEBUG = os.environ.get("LUXO_BLE_SCAN_DEBUG", "").strip().lower() in ("1", "true", "yes")
# initial connect runs several scans sequentially; fut.result must outlast that or you get a blank TimeoutError
_BLE_INIT_FUT_TIMEOUT = _CONNECT_TIMEOUT + 2 * _SCAN_TIMEOUT + 25


def _normalize_ble_address(s: str) -> str:
    # macOS CoreBluetooth uses 8-4-4-4-12 UUID; Linux may use AA:BB:… MAC
    s = s.strip()
    if not s:
        return ""
    if re.fullmatch(
        r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}",
        s,
    ):
        return s.upper()
    return s.upper().replace("-", ":")


class BleLampController:
    def __init__(self, simulate: bool = False, device_name: str | None = None):
        self.simulate = bool(simulate)
        self._name = (device_name or DEFAULT_NAME).strip()
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: threading.Thread | None = None
        self._client: BleakClient | None = None
        self._ready = threading.Event()
        self._ble_address = _normalize_ble_address(os.environ.get("LUXO_BLE_ADDRESS", ""))

        if self.simulate:
            print("BleLampController: offline test mode (no BLE)")
        else:
            if not BLEAK_AVAILABLE:
                raise RuntimeError("BLE lamp transport requires bleak. Run: pip install bleak")
            self._start_loop()
            fut = asyncio.run_coroutine_threadsafe(self._async_connect(), self._loop)
            fut.result(timeout=_BLE_INIT_FUT_TIMEOUT)

        self.neo = NeoPixelController(send_fn=self._send)
        self.neo.set_state("startup")

    def _start_loop(self) -> None:
        self._ready.clear()
        self._loop = asyncio.new_event_loop()

        def _runner():
            asyncio.set_event_loop(self._loop)
            self._ready.set()
            self._loop.run_forever()

        self._loop_thread = threading.Thread(target=_runner, name="bleak-loop", daemon=True)
        self._loop_thread.start()
        self._ready.wait(timeout=5.0)

    def _run_coro(self, coro, timeout: float = 20.0):
        assert self._loop is not None
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result(timeout=timeout)

    async def _async_connect(self) -> None:
        if self._client:
            try:
                await self._client.disconnect()
            except Exception:
                pass
            self._client = None

        if self._ble_address:
            print("BLE: connecting by LUXO_BLE_ADDRESS=%s" % self._ble_address)
            self._client = BleakClient(self._ble_address)
            await self._client.connect()
            print("BleLampController: connected at %s" % (self._ble_address))
            return

        dev = await BleakScanner.find_device_by_name(self._name, timeout=_SCAN_TIMEOUT)
        if dev is None:
            found = list(await BleakScanner.discover(timeout=min(10.0, _SCAN_TIMEOUT)))
            if _SCAN_DEBUG:
                for d in found[:30]:
                    print("   [BLE scan] %r @ %s" % (d.name, d.address))
            want = self._name.lower()
            for d in found:
                n = (d.name or "").strip()
                if not n:
                    continue
                if n == self._name or want in n.lower() or n.lower() in want:
                    dev = d
                    print("BLE: matched peripheral %r @ %s" % (d.name, d.address))
                    break
        if dev is None:
            # macOS often leaves local name as None; ESP32 still advertises Nordic UART service UUID
            try:
                by_svc = list(
                    await BleakScanner.discover(
                        timeout=min(12.0, _SCAN_TIMEOUT),
                        service_uuids=[NUS_SERVICE_UUID],
                    )
                )
            except (TypeError, ValueError, RuntimeError) as e:
                if _SCAN_DEBUG:
                    print("[BLE scan] service_uuids filter not used: %s" % (e,))
                by_svc = []
            if _SCAN_DEBUG and by_svc:
                print("[BLE scan] Nordic UART service filter → %d device(s)" % len(by_svc))
            if len(by_svc) == 1:
                dev = by_svc[0]
                print(
                    "BLE: found one peripheral advertising NUS (name=%r) @ %s"
                    % (dev.name, dev.address)
                )
            elif len(by_svc) > 1:
                for d in by_svc:
                    if _SCAN_DEBUG:
                        print("[BLE NUS] %r @ %s" % (d.name, d.address))
                dev = by_svc[0]
                print(
                    "BLE: multiple NUS advertisers — using first @ %s (set LUXO_BLE_ADDRESS to pick one)"
                    % (dev.address,)
                )
        if dev is None:
            found2 = list(await BleakScanner.discover(timeout=6.0))
            lines = sorted({"%r @ %s" % (x.name, x.address) for x in found2})[:20]
            raise RuntimeError(
                "No BLE Luxo / NUS peripheral. Named scan missed %r; on macOS the ESP32 is often "
                "'None @ <UUID>'. Fix: (1) confirm BLE advertising + esp32_main running. "
                "(2) export LUXO_BLE_ADDRESS=<UUID from scan>. "
                "(3) check Bluetooth permission for this terminal. Nearby sample: %s"
                % (self._name, lines or "(none)")
            )

        self._client = BleakClient(dev)
        await self._client.connect()
        print("BleLampController: connected to %r (%s)" % (self._name, dev.address))

    async def _async_send(self, payload: bytes) -> None:
        if self._client is None or not self._client.is_connected:
            await self._async_connect()
        assert self._client is not None
        await self._client.write_gatt_char(NUS_RX_UUID, payload, response=False)

    @property
    def lamp_transport(self) -> str:
        return "ble"

    @property
    def lamp_endpoint(self) -> str:
        if self._ble_address:
            return "ble:%s @ %s" % (self._name, self._ble_address)
        return "ble:%s (NUS %s)" % (self._name, NUS_RX_UUID)

    @property
    def is_hardware_connected(self) -> bool:
        if self.simulate or not BLEAK_AVAILABLE or self._client is None:
            return False
        return bool(self._client.is_connected)

    def _connect(self) -> None:
        if self.simulate:
            return
        if not BLEAK_AVAILABLE:
            raise RuntimeError("bleak is not installed")
        self._run_coro(self._async_connect(), timeout=_CONNECT_TIMEOUT + _SCAN_TIMEOUT + 5)

    def reconnect(self) -> bool:
        if self.simulate or not BLEAK_AVAILABLE:
            return False
        try:
            self._connect()
            return self.is_hardware_connected
        except Exception as e:
            print(f"BLE reconnect failed: {e}")
            return False

    def send_behavior(self, behavior_name: str):
        cmd = {"command": "behavior", "name": behavior_name}
        self._send(cmd)
        behavior_to_emotion = {
            "thinking": "THINK",
            "attention": "CURIOUS",
            "wiggle": "EXCITED",
            "nod": "AGREE",
            "shake": "DISAGREE",
            "head_shake": "DISAGREE",
            "head_tilt": "THINK",
            "happy": "HAPPY",
            "happy_bounce": "HAPPY",
            "idle": "IDLE",
            "idle_look": "IDLE",
            "excited": "EXCITED",
            "agree": "AGREE",
            "disagree": "DISAGREE",
            "curious": "CURIOUS",
            "curious_tilt": "CURIOUS",
        }
        emotion = behavior_to_emotion.get(behavior_name.lower())
        if emotion:
            self.neo.set_emotion(emotion)

    def send_emotion_light(self, emotion_tag: str):
        self.neo.set_emotion(emotion_tag)

    def send_state_light(self, state: str):
        self.neo.set_state(state)

    def send_move(self, joint: str, angle: int):
        self._send({"command": "move", "joint": joint, "angle": angle})

    def send_music_bounce(self):
        self._send({"command": "music_bounce"})

    def _send(self, cmd: dict):
        line = (json.dumps(cmd, separators=(",", ":")) + "\n").encode("utf-8")
        if self.simulate:
            print(f"   [LAMP BLE SIM] → {line.decode().strip()}")
            return
        with self._lock:
            try:
                self._run_coro(self._async_send(line), timeout=25.0)
            except Exception as e:
                print(f"   [BleLampController] Send error: {e} — reconnecting…")
                try:
                    self._connect()
                except Exception as e2:
                    raise RuntimeError(
                        "Lamp BLE reconnect failed after send error: %s" % e2
                    ) from e2
                try:
                    self._run_coro(self._async_send(line), timeout=25.0)
                except Exception as e3:
                    raise RuntimeError(
                        "Lamp BLE send failed after reconnect: %s" % e3
                    ) from e3

    def close(self):
        if self._loop is not None and self._client is not None:

            async def _disc():
                try:
                    if self._client.is_connected:
                        await self._client.disconnect()
                except Exception:
                    pass

            try:
                fut = asyncio.run_coroutine_threadsafe(_disc(), self._loop)
                fut.result(timeout=5)
            except Exception:
                pass
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._loop_thread is not None:
            self._loop_thread.join(timeout=3.0)


def connect_lamp(simulate: bool = False):
    """Pick BLE or serial from LUXO_LAMP_TRANSPORT (default: ble)."""
    t = os.environ.get("LUXO_LAMP_TRANSPORT", "ble").strip().lower()
    if t in ("serial", "uart", "usb", "usb-serial"):
        return SerialLampController(simulate=simulate)
    return BleLampController(simulate=simulate)
