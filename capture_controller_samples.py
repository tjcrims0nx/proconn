"""Guided Switch 2 Pro HID capture for button and gyro reverse engineering."""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from switch2mod.hid_reader import HidReader


STEPS = [
    ("neutral", "Put the controller down. Do not touch it."),
    ("left_stick_left", "Move only the LEFT stick left and hold it."),
    ("left_stick_right", "Move only the LEFT stick right and hold it."),
    ("left_stick_up", "Move only the LEFT stick up and hold it."),
    ("left_stick_down", "Move only the LEFT stick down and hold it."),
    ("left_stick_circle", "Move only the LEFT stick slowly around its full edge."),
    ("right_stick_left", "Move only the RIGHT stick left and hold it."),
    ("right_stick_right", "Move only the RIGHT stick right and hold it."),
    ("right_stick_up", "Move only the RIGHT stick up and hold it."),
    ("right_stick_down", "Move only the RIGHT stick down and hold it."),
    ("right_stick_circle", "Move only the RIGHT stick slowly around its full edge."),
    *[(f"button_{name.lower()}", f"Hold {name} only.")
      for name in ("A", "B", "X", "Y", "L", "R", "ZL", "ZR", "L3", "R3",
                   "PLUS", "MINUS", "HOME", "CAPTURE", "GL", "GR", "C")],
    ("dpad_up", "Hold D-Pad UP only."),
    ("dpad_down", "Hold D-Pad DOWN only."),
    ("dpad_left", "Hold D-Pad LEFT only."),
    ("dpad_right", "Hold D-Pad RIGHT only."),
    ("gyro_yaw_left", "Turn it slowly left."),
    ("gyro_yaw_right", "Turn it slowly right."),
    ("gyro_pitch_up", "Tilt the front up slowly."),
    ("gyro_pitch_down", "Tilt the front down slowly."),
    ("gyro_roll_left", "Tilt the left side down slowly."),
    ("gyro_roll_right", "Tilt the right side down slowly."),
]


def capture_full(reader: HidReader, seconds: float) -> list[bytes]:
    """Capture FULL 64B reports (not the truncated display slice) so IMU bytes
    at offset 22+ are preserved for gyro reverse engineering."""
    try:
        import hid as hidapi  # noqa: F401
    except ImportError:
        print("hidapi required.")
        return []
    dev = reader.dev
    if dev is None:
        return []
    end = time.monotonic() + seconds
    reports: list[bytes] = []
    while time.monotonic() < end:
        try:
            data = dev.read(64, timeout_ms=25)
        except Exception:
            break
        if data and len(bytes(data)) >= 32:
            reports.append(bytes(data))
    return reports


def capture(reader: HidReader, seconds: float) -> list[bytes]:
    return capture_full(reader, seconds)


def byte_summary(neutral: list[bytes], reports: list[bytes]) -> list[dict]:
    if not neutral or not reports:
        return []
    width = min(min(map(len, neutral)), min(map(len, reports)))
    base = [Counter(r[i] for r in neutral).most_common(1)[0][0] for i in range(width)]
    result = []
    for i in range(width):
        values = Counter(r[i] for r in reports)
        changed = sum(n for value, n in values.items() if value != base[i])
        if changed:
            result.append({
                "offset": i,
                "neutral": base[i],
                "values": dict(values.most_common(8)),
                "changed_percent": round(changed * 100 / len(reports), 1),
            })
    return result


def gyro_recommendation(summary: dict[str, list[dict]]) -> dict:
    """Create conservative starting values for both stick gyro routes."""
    motion = [row for name, rows in summary.items() if name.startswith("gyro_")
              for row in rows]
    changed = sum(float(row.get("changed_percent", 0)) for row in motion)
    signal = min(1.0, changed / max(1.0, len(motion) * 100.0))
    deadzone = round(max(0.03, min(0.12, 0.08 - signal * 0.03)), 3)
    return {
        "gyro_enabled": False,
        "gyro_ads_only": True,
        "gyro_deadzone": deadzone,
        "left_stick": {"enabled": False, "sensitivity": 0.50},
        "right_stick": {"enabled": False, "sensitivity": 1.00},
        "note": "Review samples before enabling. Both routes are manual-input tuning only.",
    }


def stick_capture_status(captures: dict[str, list[bytes]]) -> dict:
    required = [
        "left_stick_left", "left_stick_right", "left_stick_up",
        "left_stick_down", "left_stick_circle", "right_stick_left",
        "right_stick_right", "right_stick_up", "right_stick_down",
        "right_stick_circle",
    ]
    return {
        "left_stick_complete": all(captures.get(name) for name in required[:5]),
        "right_stick_complete": all(captures.get(name) for name in required[5:]),
        "samples": {name: len(captures.get(name, [])) for name in required},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=3.0)
    parser.add_argument("--output", default="controller_samples")
    parser.add_argument("--only", default="",
                        help="comma list of step prefixes to run (e.g. gyro,dpad). "
                             "Redo just gyro motions with full 64B reports.")
    args = parser.parse_args()
    only = [p.strip() for p in args.only.split(",") if p.strip()]
    run_steps = [(n, i) for n, i in STEPS
                 if not only or n == "neutral" or any(n.startswith(p) for p in only)]
    print("Switch 2 Pro controller test")
    print("You will do one simple action at a time.")
    print(f"Each step records for {args.seconds:.0f} seconds.\n")
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)

    reader = HidReader()
    if not reader.open():
        print("Could not open Switch 2 Pro HID 057e:2069.")
        return 1

    captures: dict[str, list[bytes]] = {}
    try:
        for name, instruction in run_steps:
            print(f"\nStep: {name.replace('_', ' ').upper()}")
            print(instruction)
            input("Press Enter, then do it for the next few seconds. ")
            print("Recording...")
            reports = capture(reader, args.seconds)
            captures[name] = reports
            path = output / f"{name}.txt"
            path.write_text("\n".join(r.hex() for r in reports), encoding="ascii")
            print(f"Done ({len(reports)} samples). Release the button/motion.")
    finally:
        reader.close()

    neutral = captures.get("neutral", [])
    summary = {name: byte_summary(neutral, reports)
               for name, reports in captures.items() if name != "neutral"}
    summary_path = output / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="ascii")
    recommendation_path = output / "gyro_recommendation.json"
    recommendation_path.write_text(
        json.dumps(gyro_recommendation(summary), indent=2), encoding="ascii")
    stick_path = output / "stick_capture_status.json"
    stick_path.write_text(json.dumps(stick_capture_status(captures), indent=2),
                          encoding="ascii")
    print(f"\nAnalysis written to {summary_path}")
    print(f"Gyro settings for both sticks written to {recommendation_path}")
    print(f"Left/right stick capture status written to {stick_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
