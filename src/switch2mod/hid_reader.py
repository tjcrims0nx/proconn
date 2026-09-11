"""HID reader mode for Switch 2 Pro (057e:2069) - bypasses SDL mapping gap.

Windows exposes the pad as HID MI_00 but SDL 2.32 has no PID 2069 mapping,
so pygame never sees it. This module opens HID directly and decodes the
vendor input report ID 0x09 (~60Hz):

  [0] frame counter, [1] status, [2..4] buttons, [5..7] left stick,
  [8..10] right stick (12-bit packed, center ~2048), [11..] triggers/IMU

Button map (USB, measured on hardware - differs from BLE):
  B2: bit0 B, bit1 A, bit2 Y, bit3 X, bit4 R, bit5 ZR, bit6 +, bit7 RStick
  B3: bit0 DDown, bit1 DRight, bit2 DLeft, bit3 DUp, bit4 L, bit5 ZL, bit6 -, bit7 LStick
  B4: bit0 Home, bit1 Capture, bit2 GR, bit3 GL, bit4 C

Sticks: x = b0 | ((b1 & 0x0F) << 8), y = (b1 >> 4) | (b2 << 4), normalized (v-2048)/2048.

NOTE: Interface 0 HID is silent until enabled. If no reports stream, enable once
via https://handheldlegend.github.io/procon2tool/ (WebUSB enable) then replug
keeping power, or press any pad button. This reader also attempts common
handshakes best-effort.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

log = logging.getLogger("switch2mod.hid")

VID_NINTENDO = 0x057E
PID_PRO2 = 0x2069

BTN_USB = {
    "B": (2, 0x01), "A": (2, 0x02), "Y": (2, 0x04), "X": (2, 0x08),
    "R": (2, 0x10), "ZR": (2, 0x20), "plus": (2, 0x40), "RStick": (2, 0x80),
    "d_down": (3, 0x01), "d_right": (3, 0x02), "d_left": (3, 0x04), "d_up": (3, 0x08),
    "L": (3, 0x10), "ZL": (3, 0x20), "minus": (3, 0x40), "LStick": (3, 0x80),
    "home": (4, 0x01), "capture": (4, 0x02), "GR": (4, 0x04), "GL": (4, 0x08), "C": (4, 0x10),
}

# Unified 0x05 report (offsets INCLUDE report-ID byte):
#   buttons at [5],[6],[7],[8], sticks at [11..13] left / [14..16] right.
# HARDWARE-VERIFIED 2026-09-10 from controller_samples/button_*.txt
# (per-bit set-fraction analysis, each bit unique to its button step).
# Still unknown: byte5 bits 4-5, byte6 bit7.
# Dpad VERIFIED 2026-09-10 (two independent runs, same 4 bits; 0 false
# positives in 53,210 non-dpad samples): byte7 bit0=DOWN, bit1=UP,
# bit2=RIGHT, bit3=LEFT. Holds were partial (~0.7-0.86 of window = slow
# press, not wrong bit), so response may lag a frame, never phantom.
# Gyro PARKED with evidence 2026-09-10: fast-flick captures show NO
# motion-responsive byte in 17..63 (bytes 43-44 = fast counters, 45-46 =
# slow timer, 48-60 = static). The 0x05 unified report on this firmware
# carries no live IMU; motion data likely needs the vendor bulk-interface
# enable handshake (cf. procon2tool). Gyro aim stays disabled until then.
BTN_UNIFIED = {
    "Y": (5, 0x01), "X": (5, 0x02), "B": (5, 0x04), "A": (5, 0x08),
    "R": (5, 0x40), "ZR": (5, 0x80),
    "minus": (6, 0x01), "plus": (6, 0x02),
    "RStick": (6, 0x04), "LStick": (6, 0x08),
    "home": (6, 0x10), "capture": (6, 0x20), "C": (6, 0x40),
    "L": (7, 0x40), "ZL": (7, 0x80),
    "d_down": (7, 0x01), "d_up": (7, 0x02),
    "d_right": (7, 0x04), "d_left": (7, 0x08),
    "GR": (8, 0x01), "GL": (8, 0x02),
}


def decode_stick12(b0: int, b1: int, b2: int) -> tuple[float, float]:
    raw_x = b0 | ((b1 & 0x0F) << 8)
    raw_y = (b1 >> 4) | (b2 << 4)
    x = max(-1.0, min(1.0, (raw_x - 2048) / 2048.0))
    y = max(-1.0, min(1.0, (raw_y - 2048) / 2048.0))
    return x, y


@dataclass
class HidState:
    lx: float = 0.0
    ly: float = 0.0
    rx: float = 0.0
    ry: float = 0.0
    buttons: dict[str, bool] = field(default_factory=dict)
    frame: int = 0
    raw_hex: str = ""
    gyro_x: float = 0.0
    gyro_y: float = 0.0
    gyro_z: float = 0.0


def _s16(data: bytes, offset: int) -> int:
    value = data[offset] | (data[offset + 1] << 8)
    return value - 65536 if value >= 32768 else value


def decode_motion(data: bytes) -> tuple[float, float, float]:
    """Decode Switch 2 USB IMU fields documented by SDL's Switch2 driver.

    The controller emits three sensor frames; frame 0 is at 0x31..0x3c.
    The returned axes are normalized controller rates (-1..1) with SDL's
    controller orientation mapping. Normalizing here keeps the existing GUI
    gyro sensitivity (0..3) predictable.
    """
    if len(data) < 0x3d:
        return 0.0, 0.0, 0.0
    coeff = 1.0 / 32767.0
    gx = _s16(data, 0x37) * coeff
    gy = _s16(data, 0x3B) * coeff
    gz = -_s16(data, 0x39) * coeff
    return gx, gy, gz


def decode_report09(report: bytes) -> HidState | None:
    """Decode vendor report ID 0x09. Accepts with or without leading ID byte."""
    data = bytes(report)
    if not data:
        return None
    if data[0] == 0x09 and len(data) >= 12:
        p = data[1:]
    else:
        p = data
    if len(p) < 11:
        return None
    try:
        frame = p[0]
        b2, b3, b4 = p[2], p[3], p[4]
        lx, ly = decode_stick12(p[5], p[6], p[7])
        rx, ry = decode_stick12(p[8], p[9], p[10])
        btns: dict[str, bool] = {}
        for name, (off, mask) in BTN_USB.items():
            b = {2: b2, 3: b3, 4: b4}.get(off, 0)
            btns[name] = bool(b & mask)
        gx, gy, gz = decode_motion(data)
        return HidState(lx=lx, ly=-ly, rx=rx, ry=-ry, buttons=btns, frame=frame,
                        raw_hex=data.hex(), gyro_x=gx, gyro_y=gy, gyro_z=gz)
    except Exception:
        return None


def decode_report05(report: bytes) -> HidState | None:
    """Decode unified standard report ID 0x05 (what 057e:2069 actually streams).

    Offsets INCLUDE the report-ID byte: buttons at [5],[6],[7],
    left stick [11..13], right stick [14..16], 12-bit packed center 2048.
    """
    data = bytes(report)
    if len(data) < 17 or data[0] != 0x05:
        return None
    try:
        frame = data[1]
        b5, b6, b7, b8 = data[5], data[6], data[7], data[8]
        lx, ly = decode_stick12(data[11], data[12], data[13])
        rx, ry = decode_stick12(data[14], data[15], data[16])
        btns: dict[str, bool] = {}
        for name, (off, mask) in BTN_UNIFIED.items():
            b = {5: b5, 6: b6, 7: b7, 8: b8}.get(off, 0)
            btns[name] = bool(b & mask)
        return HidState(lx=lx, ly=-ly, rx=rx, ry=-ry, buttons=btns, frame=frame,
                        raw_hex=data.hex())
    except Exception:
        return None


def decode_report(report: bytes) -> HidState | None:
    if not report:
        return None
    if report[0] == 0x05:
        return decode_report05(bytes(report))
    if report[0] == 0x09:
        return decode_report09(bytes(report))
    return None


def apply_gr_polarity(buttons: dict, byte8: int, gr_rest: int) -> None:
    """Right paddle polarity is firmware-state dependent (hardware fact,
    measured 2026-09-10): after the USB bulk enable handshake it idles at
    bit0=1 and a press CLEARS it; in other sessions it idles at 0 and a
    press SETS it. A press is therefore 'bit differs from calibrated rest'.
    Left paddle (bit1) is always active-high."""
    bit0 = byte8 & 1
    buttons["GR"] = bool(bit0 ^ gr_rest)


class HidReader:
    """Blocking HID poller for 057e:2069 MI_00. Call open() then poll()."""

    def __init__(self, vid: int = VID_NINTENDO, pid: int = PID_PRO2):
        self.vid = vid
        self.pid = pid
        self.dev = None
        self.path: bytes | None = None
        self.gr_rest = 0

    def _pick_path(self) -> bytes | None:
        import hid as hidapi
        for d in hidapi.enumerate(self.vid, self.pid):
            p = d.get("path")
            s = str(p)
            if "MI_00" in s:
                return p  # type: ignore
        devs = list(hidapi.enumerate(self.vid, self.pid))
        return devs[0].get("path") if devs else None  # type: ignore

    def open(self) -> bool:
        try:
            import hid as hidapi
        except ImportError:
            log.error("hidapi missing: pip install hidapi")
            return False
        try:
            self.path = self._pick_path()
            if not self.path:
                log.error("no HID %04x:%04x found", self.vid, self.pid)
                return False
            self.dev = hidapi.device()
            self.dev.open_path(self.path)
            self.dev.set_nonblocking(True)
            log.info("HID opened %04x:%04x %s", self.vid, self.pid, self.path)
            self._try_enable()
            self._calibrate_gr_rest()
            return True
        except Exception as e:
            log.error("HID open failed: %s", e)
            return False

    def _calibrate_gr_rest(self, samples: int = 40) -> None:
        """Sample the GR bit's resting value. DO NOT touch the right paddle
        during mapper start. Active-low sessions rest at 1, others at 0."""
        self.gr_rest = 0
        try:
            ones = total = 0
            for _ in range(samples):
                d = self.dev.read(64, timeout_ms=20)
                if d and len(d) > 8 and d[0] == 0x05:
                    total += 1
                    ones += (d[8] & 1)
            if total:
                self.gr_rest = 1 if ones * 2 > total else 0
            log.info("GR rest bit calibrated: %d (%d/%d samples)",
                     self.gr_rest, ones, total)
        except Exception as e:
            log.warning("GR calibration failed: %s", e)

    def _try_enable(self) -> None:
        """Best-effort enable handshakes. Harmless if device already streaming."""
        assert self.dev is not None
        candidates: list[tuple[str, bytes]] = [
            ("feature 80 01 (Switch1 MAC req)", bytes([0x80, 0x01])),
            ("feature 80 02 (Switch1 handshake)", bytes([0x80, 0x02])),
        ]
        for name, payload in candidates:
            try:
                self.dev.send_feature_report(payload)
                log.info("HID enable try: %s sent", name)
                time.sleep(0.05)
            except Exception:
                pass
        # Drain any stale reports
        try:
            for _ in range(20):
                if not self.dev.read(64, timeout_ms=5):
                    break
        except Exception:
            pass

    def poll(self, timeout_ms: int = 50) -> HidState | None:
        if self.dev is None:
            return None
        try:
            data = self.dev.read(64, timeout_ms=timeout_ms)
        except Exception as e:
            log.warning("HID read error: %s", e)
            return None
        if not data:
            return None
        raw = bytes(data)
        st = decode_report(raw)
        if st is not None and raw[0] == 0x05 and len(raw) > 8:
            apply_gr_polarity(st.buttons, raw[8], self.gr_rest)
        return st

    def close(self) -> None:
        try:
            if self.dev:
                self.dev.close()
        except Exception:
            pass
        self.dev = None
