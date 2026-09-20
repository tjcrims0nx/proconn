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
from switch2mod.sticks import Smoother, ensure_sprint_magnitude, process_sticks, to_s16, update_ads_state, update_sprint_latch

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
        self._prev_l3 = False
        self._prev_r3 = False
        # Game -> pad rumble, scaled by cfg.rumble_scale. Receipt only:
        # Switch 2 Pro HD-haptic output encoding is unverified, so motors
        # are NOT driven (no blind bytes to hardware). GUI shows activity.
        self.last_rumble = (0, 0, 0.0)
        if self.pad is not None:
            try:
                self.pad.register_notification(self._on_rumble)
            except Exception as e:
                log.warning("rumble notify unavailable: %s", e)
        self.smoother = Smoother(self.cfg.smoothing)
        self.cx_l = self.cy_l = self.cx_r = self.cy_r = 0.0
        self.gyro_center_x = 0.0
        self.gyro_center_y = 0.0
        # Debounced ADS latch so paddle GL chatter can't flip hipfire/ADS
        # stick shaping frame-to-frame (paddle speed bursts while scoped).
        self.ads_on = False
        self.ads_changed_at = 0.0
        # Sticky sprint: COD drops sprint on one flicker frame. Latch L3 so
        # click-switch/HID jitter can't kill a run mid-stride.
        self.sprint_on = False
        self.sprint_changed_at = 0.0
        # Calibrations run once on first connect. Reconnects must resume
        # instantly - re-running ~6s of sampling on every hotplug is what
        # used to turn a blink into a dead period.
        self._ever_calibrated = False
        self._connect()

    def _on_rumble(self, _client, _target, large_motor, small_motor, _led, _user=None) -> None:
        """ViGEm thread callback: record scaled game rumble. Never touch Tk here."""
        try:
            s = max(0.0, min(2.0, float(self.cfg.rumble_scale)))
            import time
            self.last_rumble = (int(large_motor * s), int(small_motor * s), time.monotonic())
        except Exception:
            pass

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
                if not self._ever_calibrated:
                    self.calibrate_center()
                    if self.cfg.gyro_enabled:
                        self.calibrate_gyro()
                    self._ever_calibrated = True
                return True
        except Exception as e:
            log.warning("connect failed: %s", e)
        self.connected = False
        return False

    def calibrate_center(self, samples: int = 60) -> None:
        """Measure stick rest offsets so small hardware bias doesn't get
        amplified by anti-deadzone into visible drift. Hands off sticks.
        High-variance sample = stick was touched -> keep zeros, warn."""
        xs: list[float] = []
        ys: list[float] = []
        rxs: list[float] = []
        rys: list[float] = []
        for _ in range(samples):
            try:
                st = self.reader.poll(timeout_ms=50)
            except Exception:
                break
            if st is None:
                continue
            xs.append(st.lx)
            ys.append(st.ly)
            rxs.append(st.rx)
            rys.append(st.ry)
        if len(xs) < 10:
            return
        import statistics
        spread = max(statistics.pstdev(xs), statistics.pstdev(ys),
                     statistics.pstdev(rxs), statistics.pstdev(rys))
        if spread > 0.15:
            log.warning("center cal rejected (spread %.3f) - sticks were touched; "
                        "keeping zero offsets", spread)
            return
        def avg(v: list[float]) -> float:
            m = sum(v) / len(v)
            return max(-0.2, min(0.2, m))
        self.cx_l, self.cy_l, self.cx_r, self.cy_r = (
            avg(xs), avg(ys), avg(rxs), avg(rys))
        log.info("center cal L(%+.3f,%+.3f) R(%+.3f,%+.3f)",
                 self.cx_l, self.cy_l, self.cx_r, self.cy_r)

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
        # Sprint-slide-crouch triage: L3 is the ONLY legal thumb source for
        # R3/L3 outputs. Rear C/Capture must never inject the thumb click,
        # or crouch bleeds into sprint and COD slide-cancels feel random.
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

        lx = self.smoother.filter("lx", st.lx - self.cx_l)
        ly = self.smoother.filter("ly", st.ly - self.cy_l)
        rx = self.smoother.filter("rx", st.rx - self.cx_r)
        ry = self.smoother.filter("ry", st.ry - self.cy_r)

        lt_f = 1.0 if zl else 0.0
        rt_f = 1.0 if zr else 0.0
        gx = st.gyro_x - self.gyro_center_x
        gy = st.gyro_y - self.gyro_center_y
        self.ads_on, self.ads_changed_at = update_ads_state(
            self.ads_on, lt_f, time.monotonic(), self.ads_changed_at)
        self.sprint_on, self.sprint_changed_at = update_sprint_latch(
            self.sprint_on, l3, time.monotonic(), self.sprint_changed_at)
        lx2, ly2, rx2, ry2 = process_sticks(
            cfg, lx, ly, rx, ry, ads_held=self.ads_on,
            gyro_x=gx, gyro_y=gy, recenter_active=(lt_f > 0.2))
        if self.sprint_on:
            # Hold-to-sprint repair: the click eases tilt just under COD's
            # sprint gate, so hold + full tilt must always send full tilt.
            # Latched, not raw: one flicker frame must not drop the run.
            lx2, ly2 = ensure_sprint_magnitude(lx2, ly2)

        out = {"A": xa, "B": xb, "X": xx, "Y": xy, "LB": lb, "RB": rb,
               # Preserve raw L3 for steady-aim/hold-breath. In hipfire only,
               # keep the sprint click alive through the debounce window so
               # COD registers sprint even when the mechanical click is brief.
               "L3": bool(l3 or (self.sprint_on and not self.ads_on)),
               "R3": r3, "BACK": minus, "START": plus, "GUIDE": home,
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
                # Recomputed per loop so a live-apply polling change takes
                # effect without restarting (virtual pad never drops).
                hz = max(60, min(1000, getattr(self.cfg, "polling_hz", 500)))
                dt = 1.0 / hz
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
