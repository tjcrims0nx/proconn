"""HID mapper service - Switch 2 Pro via direct HID (057e:2069) to virtual Xbox.

Reuses the same Gamesir-like stick pipeline (center, smoothing, curve,
square mapping, ADS damping, hair triggers) as the SDL mapper, but the
input source is HidReader instead of pygame. Legal tuning only.
"""
from __future__ import annotations

import logging
import time

from switch2mod.config import AppConfig
from switch2mod.hid_reader import HidReader
from switch2mod.sticks import Smoother, process_sticks, to_s16

log = logging.getLogger("switch2mod.hidmapper")

try:
    import vgamepad as vg
    from vgamepad import XUSB_BUTTON as XB
    HAS_VGAMEPAD = True
    _VG_IMPORT_ERROR = None
except Exception as _e:
    # Broad on purpose: importing vgamepad connects to the ViGEmBus driver,
    # which raises VIGEM_ERROR_BUS_NOT_FOUND (not ImportError) when the
    # driver is missing. The app must survive that and show the hint.
    HAS_VGAMEPAD = False
    _VG_IMPORT_ERROR = str(_e)
    vg = None  # type: ignore
    XB = None  # type: ignore


class HidMapperError(Exception):
    pass


class HidProToXInput:
    def __init__(self, cfg: AppConfig):
        self.cfg = cfg.apply_aim_dial()
        self.pad = None
        if HAS_VGAMEPAD:
            try:
                self.pad = vg.VX360Gamepad()
            except Exception as e:
                log.warning("virtual pad create failed: %s", e)
        self.vigem_error = None if self.pad is not None else (
            _VG_IMPORT_ERROR or "ViGEmBus driver not running")
        self.reader = HidReader()
        self.connected = False
        self.running = False
        self.n_reports = 0
        self.last_input_at = 0.0
        self.latest_state = None
        self.last_output = {}
        self.smoother = Smoother(self.cfg.smoothing)
        self.gyro_center_x = 0.0
        self.gyro_center_y = 0.0
        self._connect()

    def _connect(self) -> bool:
        """Try to open the controller. Safe to call repeatedly (hotplug)."""
        if self.connected:
            return True
        try:
            if self.reader is None:
                self.reader = HidReader()
            if self.reader.open():
                self.connected = True
                log.info("controller connected")
                if self.cfg.gyro_enabled:
                    self.calibrate_gyro()
                return True
        except Exception as e:
            log.warning("connect failed: %s", e)
        self.connected = False
        return False

    def calibrate_gyro(self, samples: int = 60) -> None:
        """Capture stationary gyro bias. Keep the controller still during start."""
        values = []
        for _ in range(samples):
            state = self.reader.poll(timeout_ms=50)
            if state is not None:
                values.append((state.gyro_x, state.gyro_y))
        if values:
            self.gyro_center_x = sum(v[0] for v in values) / len(values)
            self.gyro_center_y = sum(v[1] for v in values) / len(values)
            log.info("gyro bias calibrated x=%+.4f y=%+.4f", self.gyro_center_x, self.gyro_center_y)
        self.last_input_at = 0.0
        self.latest_state = None

    def _drop(self) -> None:
        """Disconnect the controller; run() will keep trying to reconnect."""
        self.connected = False
        try:
            if self.reader is not None:
                self.reader.close()
        except Exception:
            pass
        self.reader = None
        try:
            if self.pad is not None:
                self.pad.reset()
                self.pad.update()
        except Exception:
            pass
        log.info("controller disconnected")

    def step(self) -> bool:
        """Poll once. Returns False if no report (silent/disconnected)."""
        if not self.connected or self.reader is None:
            return False
        try:
            st = self.reader.poll(timeout_ms=20)
        except Exception:
            self._drop()
            return False
        if st is None:
            return False
        self.last_input_at = time.monotonic()
        self.latest_state = st
        self.n_reports += 1
        cfg = self.cfg
        b = st.buttons
        # Nintendo -> Xbox swap (same as SDL path)
        n_b, n_a, n_y, n_x = b.get("B", False), b.get("A", False), b.get("Y", False), b.get("X", False)
        if cfg.swap_abxy:
            xa, xb, xx, xy = n_b, n_a, n_y, n_x
        else:
            xa, xb, xx, xy = n_a, n_b, n_x, n_y
        lb, rb = b.get("L", False), b.get("R", False)
        zl, zr = b.get("ZL", False), b.get("ZR", False)
        l3, r3 = b.get("LStick", False), b.get("RStick", False)
        minus, plus = b.get("minus", False), b.get("plus", False)
        home, capture = b.get("home", False), b.get("capture", False)
        gl, gr, c_btn = b.get("GL", False), b.get("GR", False), b.get("C", False)
        du, dd = b.get("d_up", False), b.get("d_down", False)
        dl, dr = b.get("d_left", False), b.get("d_right", False)

        lx = self.smoother.filter("lx", st.lx)
        ly = self.smoother.filter("ly", st.ly)
        rx = self.smoother.filter("rx", st.rx)
        ry = self.smoother.filter("ry", st.ry)

        lt_f = 1.0 if zl else 0.0
        rt_f = 1.0 if zr else 0.0
        gx = st.gyro_x - self.gyro_center_x
        gy = st.gyro_y - self.gyro_center_y
        lx2, ly2, rx2, ry2 = process_sticks(
            cfg, lx, ly, rx, ry, ads_held=lt_f > 0.2,
            gyro_x=gx, gyro_y=gy)

        out = {"A": xa, "B": xb, "X": xx, "Y": xy, "LB": lb, "RB": rb,
               "L3": l3, "R3": r3, "BACK": minus, "START": plus, "GUIDE": home,
               "DUP": du, "DDOWN": dd, "DLEFT": dl, "DRIGHT": dr}
        from switch2mod.rear import apply_rear, normalize_target
        trig = {"LT": lt_f, "RT": rt_f}
        apply_rear(out, cfg.rear_map,
                   {"capture": capture, "gl": gl, "gr": gr, "c": c_btn},
                   triggers=trig)
        lt_f, rt_f = trig["LT"], trig["RT"]
        if normalize_target(getattr(cfg.rear_map, "capture_as", "NONE")) == "NONE":
            layout = cfg.cod_layout
            if layout == "bumper_jumper_tactical" and capture:
                out["R3"] = True
            elif layout == "paddle_crouch" and capture:
                out["B"] = True
            elif layout == "destiny_default" and capture:
                out["B"] = True
            elif layout == "destiny_pvp" and capture:
                out["R3"] = True

        def hair(v: float, en: bool) -> int:
            return 255 if (en and v >= cfg.hair_threshold) else (int(v * 255) if not en else 0)

        if self.pad is None:
            # No ViGEmBus driver: still read/parse input and report telemetry,
            # just cannot emit a virtual pad yet. GUI shows the driver hint.
            self.last_output = {"lx": round(lx2, 3), "ly": round(ly2, 3),
                                "rx": round(rx2, 3), "ry": round(ry2, 3),
                                "lt": round(lt_f, 3), "rt": round(rt_f, 3),
                                "btns": sorted(k for k, v in out.items() if v)}
            return True

        self.pad.reset()
        mapping = {"A": XB.XUSB_GAMEPAD_A, "B": XB.XUSB_GAMEPAD_B,
                   "X": XB.XUSB_GAMEPAD_X, "Y": XB.XUSB_GAMEPAD_Y,
                   "LB": XB.XUSB_GAMEPAD_LEFT_SHOULDER, "RB": XB.XUSB_GAMEPAD_RIGHT_SHOULDER,
                   "L3": XB.XUSB_GAMEPAD_LEFT_THUMB, "R3": XB.XUSB_GAMEPAD_RIGHT_THUMB,
                   "BACK": XB.XUSB_GAMEPAD_BACK, "START": XB.XUSB_GAMEPAD_START,
                   "GUIDE": XB.XUSB_GAMEPAD_GUIDE, "DUP": XB.XUSB_GAMEPAD_DPAD_UP,
                   "DDOWN": XB.XUSB_GAMEPAD_DPAD_DOWN, "DLEFT": XB.XUSB_GAMEPAD_DPAD_LEFT,
                   "DRIGHT": XB.XUSB_GAMEPAD_DPAD_RIGHT}
        for k, v in mapping.items():
            if out.get(k):
                self.pad.press_button(button=v)
        self.pad.left_trigger(value=hair(lt_f, cfg.hair_trigger_left))
        self.pad.right_trigger(value=hair(rt_f, cfg.hair_trigger_right))
        self.pad.left_joystick(x_value=to_s16(lx2), y_value=to_s16(-ly2))
        self.pad.right_joystick(x_value=to_s16(rx2), y_value=to_s16(-ry2))
        self.pad.update()
        self.last_output = {"lx": round(lx2, 3), "ly": round(ly2, 3),
                            "rx": round(rx2, 3), "ry": round(ry2, 3),
                            "lt": round(lt_f, 3), "rt": round(rt_f, 3),
                            "btns": sorted(k for k, v in out.items() if v)}
        return True

    def close(self) -> None:
        """Idempotent teardown: zero the virtual pad, release HID. Safe to
        call from the GUI thread after the run loop exits."""
        try:
            if self.pad is not None:
                self.pad.reset()
                self.pad.update()
        except Exception:
            pass
        try:
            if self.reader is not None:
                self.reader.close()
        except Exception:
            pass
        self.reader = None
        self.connected = False

    def run(self) -> None:
        hz = max(60, min(1000, self.cfg.polling_hz))
        dt = 1.0 / hz
        self.running = True
        game = getattr(self.cfg, "game", "cod").upper()
        log.info("HID running @ %dHz - play %s now (Ctrl+C stop)", hz, game)
        silent_n = 0
        reconnect_at = 0.0
        try:
            while self.running:
                t0 = time.perf_counter()
                if not self.connected:
                    # Hotplug: poll for a controller ~2x/sec until one appears.
                    now = time.monotonic()
                    if now >= reconnect_at:
                        reconnect_at = now + 0.5
                        self._connect()
                    time.sleep(0.05)
                    continue
                got = self.step()
                if not got:
                    silent_n += 1
                    if silent_n == 100:
                        # Long silence: treat as unplugged and re-arm hotplug.
                        log.warning("HID silent 100 polls - treating as disconnected")
                        self._drop()
                        silent_n = 0
                    time.sleep(0.005)
                else:
                    silent_n = 0
                time.sleep(max(0, dt - (time.perf_counter() - t0)))
        except KeyboardInterrupt:
            log.info("stopped")
        finally:
            self.close()
