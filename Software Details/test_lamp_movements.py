#!/usr/bin/env python3
# smoke-test ESP32 lamp movements — no Whisper / Gemini / browser needed

import argparse
import os
import sys
import time

# names must match esp32_main.py run_behavior()
SEQUENCE = [
    "attention",
    "thinking",
    "wiggle",
    "nod",
    "head_shake",
    "idle_look",
    "happy_bounce",
    "curious_tilt",
    "head_tilt",
]


def main():
    p = argparse.ArgumentParser(description="Cycle lamp behaviors to test ESP32 link.")
    p.add_argument(
        "--pause",
        type=float,
        default=4.0,
        help="Seconds between behaviors (default: 4)",
    )
    p.add_argument(
        "--simulate",
        action="store_true",
        help="Offline print-only mode (no BLE/serial; no hardware)",
    )
    p.add_argument(
        "--serial",
        action="store_true",
        help="USB-TTL serial (sets LUXO_LAMP_TRANSPORT=serial)",
    )
    p.add_argument(
        "--ble",
        action="store_true",
        help="Bluetooth bleak (sets LUXO_LAMP_TRANSPORT=ble)",
    )
    p.add_argument(
        "--list-serial",
        action="store_true",
        help="Print likely /dev/cu.* paths and exit",
    )
    args = p.parse_args()

    if args.list_serial:
        from lamp_link import list_serial_candidates

        c = list_serial_candidates()
        print("USB-serial callout devices (macOS):")
        if c:
            for path in c:
                print(f"  {path}")
        else:
            print("  (none — plug in USB-TTL, then: ls /dev/cu.*)")
        return

    if args.serial:
        os.environ["LUXO_LAMP_TRANSPORT"] = "serial"
    elif args.ble:
        os.environ["LUXO_LAMP_TRANSPORT"] = "ble"
    elif "LUXO_LAMP_TRANSPORT" not in os.environ:
        os.environ["LUXO_LAMP_TRANSPORT"] = "ble"

    from lamp_link import connect_lamp

    _t = os.environ.get("LUXO_LAMP_TRANSPORT", "ble").strip().lower()
    endpoint_key = "serial" if _t in ("serial", "uart", "usb", "usb-serial") else "ble"

    print("─" * 50)
    print("Luxo lamp movement test (no AI)")
    if endpoint_key == "ble":
        nm = os.environ.get("LUXO_BLE_NAME", "Luxo-Lamp").strip()
        adr = os.environ.get("LUXO_BLE_ADDRESS", "").strip()
        print(f"Transport:              BLE")
        print(f"Target BLE name:        {nm}")
        if adr:
            print(f"LUXO_BLE_ADDRESS:       {adr}")
    else:
        raw = os.environ.get("LUXO_SERIAL_PORT", "").strip()
        if raw:
            print(f"LUXO_SERIAL_PORT:       {raw}")
    print("─" * 50)

    try:
        lamp = connect_lamp(simulate=args.simulate)
    except Exception as e:
        print(" Could not open lamp link:", type(e).__name__, e, flush=True)
        sys.exit(1)

    if endpoint_key == "serial":
        print(f"Serial port:            {getattr(lamp, 'port', None) or '(none)'}\n")
    else:
        print(f"BLE endpoint:           {getattr(lamp, 'lamp_endpoint', '')}\n")

    if lamp.is_hardware_connected:
        print(f" Hardware ({getattr(lamp, 'lamp_transport', '')}): CONNECTED\n")
    else:
        print(f"  Offline test mode (--simulate); no BLE/serial I/O.\n")

    print("Cycling behaviors (Ctrl+C to stop)…\n")

    try:
        i = 0
        while True:
            name = SEQUENCE[i % len(SEQUENCE)]
            print(f"  → send_behavior({name!r})", flush=True)
            lamp.send_behavior(name)
            time.sleep(args.pause)
            i += 1
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        lamp.close()


if __name__ == "__main__":
    main()
