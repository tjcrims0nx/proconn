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
except ImportError:
    HAS_VGAMEPAD = False
    vg = None  # type: ignore
    XB = None  # type: ignore


class HidMapperError(Exception):
    pass


class HidProToXInput:
    def __init__(self, cfg: AppConfig):
        if not HAS_VGAMEPAD:
            raise HidMapperError("vgamepad + ViGEmBus required. See README.")
        self.cfg = cfg.apply_aim_dial()
        self.reader = HidReader()
        if not self.reader.open():
            raise HidMapperError(
                "HID 057e:2069 not opened. Plug USB-C DATA cable to rear USB. "
                "If silent (no reports), enable once via procon2tool WebUSB then retry.")
        self.pad = vg.VX360Gamepad()
        self.running = False
        self.n_reports = 0
        self.smoother = Smoother(self.cfg.smoothing)
        self.gyro_center_x = 0.0
        self.gyro_center_y = 0.0
        if self.cfg.gyro_enabled:
            self.calibrate_gyro()

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

    def step(self) -> bool:
        """Poll once. Returns False if no report (silent/disconnected)."""
        st = self.reader.poll(timeout_ms=20)
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
            self.pad.reset()
            self.pad.update()
        except Exception:
            pass
        try:
            self.reader.close()
        except Exception:
            pass

    def run(self) -> None:
        hz = max(60, min(1000, self.cfg.polling_hz))
        dt = 1.0 / hz
        self.running = True
        game = getattr(self.cfg, "game", "cod").upper()
        log.info("HID running @ %dHz - play %s now (Ctrl+C stop)", hz, game)
        silent_n = 0
        try:
            while self.running:
                t0 = time.perf_counter()
                got = self.step()
                if not got:
                    silent_n += 1
                    if silent_n == 100:
                        log.warning("HID silent 100 polls - press pad buttons; if still silent, "
                                    "enable via procon2tool WebUSB then replug.")
                    # keep virtual pad alive with last state; brief sleep
                    time.sleep(0.005)
                else:
                    silent_n = 0
                time.sleep(max(0, dt - (time.perf_counter() - t0)))
        except KeyboardInterrupt:
            log.info("stopped")
        finally:
            self.close()
