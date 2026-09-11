"""Input->XInput mapping service. Single responsibility: poll SDL pad, drive virtual Xbox pad."""
from __future__ import annotations

import logging
import time

import pygame

from switch2mod.config import AppConfig
from switch2mod.sticks import Smoother, process_sticks, to_s16

log = logging.getLogger("switch2mod.mapper")

try:
    import vgamepad as vg
    from vgamepad import XUSB_BUTTON as XB
    HAS_VGAMEPAD = True
except ImportError:
    HAS_VGAMEPAD = False
    vg = None  # type: ignore
    XB = None  # type: ignore

BTN = {
    "B_bottom": 0, "A_right": 1, "Y_left": 2, "X_top": 3,
    "minus": 4, "home": 5, "plus": 6, "L3": 7, "R3": 8,
    "LB": 9, "RB": 10, "ZL_btn": 11, "ZR_btn": 12,
    "dpad_up": 13, "dpad_down": 14, "dpad_left": 15,
    "dpad_right": 16, "capture": 17,
    # Rear paddles: SDL index varies by driver/SDL version - verify with --calibrate.
    # Switch 2 Pro GL/GR/C typically follow Capture when exposed via Steam/BetterJoy.
    "gl": 18, "gr": 19, "c_btn": 20,
}


class MapperError(Exception):
    pass


class ProToXInput:
    def __init__(self, cfg: AppConfig, joy_index: int):
        if not HAS_VGAMEPAD:
            raise MapperError("vgamepad + ViGEmBus required. See README.")
        self.cfg = cfg.apply_aim_dial()
        self.joy = pygame.joystick.Joystick(joy_index)
        self.joy.init()
        log.info("input: %s axes=%d btns=%d", self.joy.get_name(),
                 self.joy.get_numaxes(), self.joy.get_numbuttons())
        self.pad = vg.VX360Gamepad()
        self.running = False
        self.n_reports = 0
        self.smoother = Smoother(self.cfg.smoothing)
        self.cx_l = self.cy_l = self.cx_r = self.cy_r = 0.0
        self.turbo_state = False
        self.turbo_last = 0.0
        self.last_input_at = 0.0
        if cfg.auto_center:
            self.calibrate_center()

    def calibrate_center(self, samples: int = 80) -> None:
        sx = [0.0, 0.0, 0.0, 0.0]
        n = 0
        for _ in range(samples):
            pygame.event.pump()
            try:
                for k in range(4):
                    sx[k] += self.joy.get_axis(k)
                n += 1
            except Exception:
                break
            time.sleep(0.002)
        if n:
            vals = [max(-0.2, min(0.2, v / n)) for v in sx]
            self.cx_l, self.cy_l, self.cx_r, self.cy_r = vals
            log.info("center L(%+.3f,%+.3f) R(%+.3f,%+.3f)", *vals)

    def _btn(self, key: str) -> bool:
        i = BTN[key]
        try:
            return self.joy.get_numbuttons() > i and bool(self.joy.get_button(i))
        except pygame.error:
            raise
        except Exception:
            return False

    def read_triggers(self) -> tuple[float, float]:
        lt = rt = 0.0
        try:
            na = self.joy.get_numaxes()
            nb = self.joy.get_numbuttons()
            if na >= 6:
                lt = (self.joy.get_axis(4) + 1.0) / 2.0
                rt = (self.joy.get_axis(5) + 1.0) / 2.0
            if nb > max(BTN["ZL_btn"], BTN["ZR_btn"]):
                if self.joy.get_button(BTN["ZL_btn"]):
                    lt = 1.0
                if self.joy.get_button(BTN["ZR_btn"]):
                    rt = 1.0
            return max(0.0, min(1.0, lt)), max(0.0, min(1.0, rt))
        except pygame.error:
            raise
        except Exception:
            return 0.0, 0.0

    def _hair(self, v: float, enabled: bool) -> int:
        if not enabled:
            return int(v * 255)
        return 255 if v >= self.cfg.hair_threshold else 0

    def step(self) -> None:
        pygame.event.pump()
        self.last_input_at = time.monotonic()
        self.n_reports += 1
        self.last_output = getattr(self, "last_output", {})
        cfg = self.cfg
        n_b, n_a = self._btn("B_bottom"), self._btn("A_right")
        n_y, n_x = self._btn("Y_left"), self._btn("X_top")
        if cfg.swap_abxy:
            xa, xb, xx, xy = n_b, n_a, n_y, n_x
        else:
            xa, xb, xx, xy = n_a, n_b, n_x, n_y

        lb, rb = self._btn("LB"), self._btn("RB")
        l3, r3 = self._btn("L3"), self._btn("R3")
        minus, plus, home = self._btn("minus"), self._btn("plus"), self._btn("home")
        du, dd = self._btn("dpad_up"), self._btn("dpad_down")
        dl, dr = self._btn("dpad_left"), self._btn("dpad_right")
        def raw_btn(idx: int) -> bool:
            try:
                nb = self.joy.get_numbuttons()
                return bool(self.joy.get_button(idx)) if nb > idx else False
            except pygame.error:
                raise
            except Exception:
                return False

        capture = raw_btn(BTN["capture"])
        gl = raw_btn(BTN["gl"])
        gr = raw_btn(BTN["gr"])
        c_btn = raw_btn(BTN["c_btn"])

        if self.joy.get_numhats() > 0:
            try:
                hx, hy = self.joy.get_hat(0)
                dl = dl or hx == -1
                dr = dr or hx == 1
                du = du or hy == 1
                dd = dd or hy == -1
            except pygame.error:
                raise
            except Exception:
                pass

        try:
            lx = self.smoother.filter("lx", self.joy.get_axis(0) - self.cx_l)
            ly = self.smoother.filter("ly", self.joy.get_axis(1) - self.cy_l)
            rx = self.smoother.filter("rx", self.joy.get_axis(2) - self.cx_r)
            ry = self.smoother.filter("ry", self.joy.get_axis(3) - self.cy_r)
        except pygame.error:
            raise
        except Exception:
            lx = ly = rx = ry = 0.0

        lt_f, rt_f = self.read_triggers()
        lx2, ly2, rx2, ry2 = process_sticks(cfg, lx, ly, rx, ry, ads_held=lt_f > 0.2)

        out = {"A": xa, "B": xb, "X": xx, "Y": xy, "LB": lb, "RB": rb,
               "L3": l3, "R3": r3, "BACK": minus, "START": plus, "GUIDE": home,
               "DUP": du, "DDOWN": dd, "DLEFT": dl, "DRIGHT": dr}
        from switch2mod.rear import apply_rear
        trig = {"LT": lt_f, "RT": rt_f}
        apply_rear(out, cfg.rear_map,
                   {"capture": capture, "gl": gl, "gr": gr, "c": c_btn},
                   triggers=trig)
        lt_f, rt_f = trig["LT"], trig["RT"]
        # Legacy layout fallback only when Capture paddle is disabled (NONE)
        from switch2mod.rear import normalize_target
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
        self.pad.left_trigger(value=self._hair(lt_f, cfg.hair_trigger_left))
        self.pad.right_trigger(value=self._hair(rt_f, cfg.hair_trigger_right))
        self.pad.left_joystick(x_value=to_s16(lx2), y_value=to_s16(-ly2))
        self.pad.right_joystick(x_value=to_s16(rx2), y_value=to_s16(-ry2))
        self.pad.update()
        self.last_output = {"lx": round(lx2, 3), "ly": round(ly2, 3),
                            "rx": round(rx2, 3), "ry": round(ry2, 3),
                            "lt": round(lt_f, 3), "rt": round(rt_f, 3),
                            "btns": sorted(k for k, v in out.items() if v)}

    def reinit(self) -> bool:
        try:
            pygame.joystick.quit()
            pygame.joystick.init()
            self.joy = pygame.joystick.Joystick(self.joy.get_id())
            self.joy.init()
            log.info("reconnected: %s", self.joy.get_name())
            return True
        except Exception as e:
            log.warning("reconnect failed: %s", e)
            return False

    def run(self) -> None:
        hz = max(60, min(1000, self.cfg.polling_hz))
        dt = 1.0 / hz
        self.running = True
        conn = "WIRED (USB)" if self.cfg.wired_mode else "wireless/BT"
        game = getattr(self.cfg, "game", "cod")
        log.info("running @ %dHz over %s - play %s now", hz, conn, game.upper())
        try:
            while self.running:
                t0 = time.perf_counter()
                try:
                    self.step()
                except pygame.error:
                    log.warning("disconnected, waiting for replug...")
                    try:
                        self.pad.reset()
                        self.pad.update()
                    except Exception:
                        pass
                    for _ in range(60):
                        if not self.running:
                            break
                        time.sleep(1.0)
                        if self.reinit():
                            break
                    else:
                        self.running = False
                time.sleep(max(0, dt - (time.perf_counter() - t0)))
        except KeyboardInterrupt:
            log.info("stopped")
        finally:
            self.close()

    def close(self) -> None:
        """Idempotent teardown for GUI stop/start cycles."""
        try:
            self.pad.reset()
            self.pad.update()
        except Exception:
                pass
