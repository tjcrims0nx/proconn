"""Professional screen crosshair overlay with movement detection & screen sync.

Pins a customizable dynamic crosshair on top of any window - no injection, no
game files touched.  Inspired by Crossover (Electron); reimplemented natively
with pro features:

  - **Dynamic bloom** - crosshair spread widens when stick input is detected
    (movement or aim), tightens when idle.  Simulates real weapon behaviour.
  - **Screen sync** - rendering tick adapts to monitor refresh rate for
    butter-smooth interpolation (no fixed 100 ms timer).
  - **Movement-aware colour shift** - optional colour change when moving.
  - **Smooth state transitions** - all changes (gap, opacity, colour) lerp
    over configurable durations so nothing pops.
  - **New pro styles** - t_shape, diamond, chevron, plus originals.
  - **ADS tighten** - gap shrinks and dot tightens while aiming down sights.

Notes:
  - Requires Windowed / Borderless Fullscreen in COD/Destiny 2.
  - Setup mode: overlay is draggable.  Locked mode: click-through.
"""
from __future__ import annotations

import ctypes
import logging
import math
import time
from dataclasses import dataclass, field

log = logging.getLogger("switch2mod.crosshair")

STYLES = ("cross", "dot", "circle", "cross_dot", "t_shape", "diamond", "chevron")
COLORS = ("lime", "red", "cyan", "white", "yellow", "magenta", "orange")


# -- configuration ------------------------------------------------------------

@dataclass
class CrosshairConfig:
    enabled: bool = True
    style: str = "cross_dot"
    size: int = 24          # arm length px
    gap: int = 6            # center gap px (static base)
    thickness: int = 2
    color: str = "lime"
    opacity: float = 0.9    # 0.2-1.0
    center_dot: bool = True
    dot_size: int = 2
    hide_on_ads: bool = True
    offset_x: int = 0
    offset_y: int = 0
    target_window: str = ""  # substring of game window title; "" = screen center

    # -- movement / bloom system --
    movement_detection: bool = True
    bloom_intensity: float = 1.0       # 0-2  multiplier on dynamic gap
    bloom_max_px: int = 20             # max extra gap pixels from bloom
    recovery_speed: float = 6.0        # gap recovery rate (units/sec)
    ads_tighten: float = 0.4           # gap shrinks to this fraction during ADS
    ads_tighten_speed: float = 8.0     # ADS transition lerp speed (units/sec)
    move_color: str = ""               # optional colour while moving ("" = off)
    color_shift_threshold: float = 0.3 # movement magnitude to trigger colour shift
    aim_sweep_pulse: bool = True       # pulse on real ADS + right-stick sweep
    aim_pulse_threshold: float = 0.35
    aim_pulse_cooldown: float = 0.25

    # -- screen sync --
    screen_sync: bool = True           # True = use monitor hz, False = 60fps
    target_fps: int = 0                # 0 = auto-detect from monitor

    def validate(self) -> None:
        if self.style not in STYLES:
            self.style = "cross_dot"
        if self.color not in COLORS:
            self.color = "lime"
        self.size = max(4, min(200, int(self.size)))
        self.gap = max(0, min(100, int(self.gap)))
        self.thickness = max(1, min(10, int(self.thickness)))
        self.opacity = max(0.2, min(1.0, float(self.opacity)))
        self.bloom_intensity = max(0.0, min(2.0, float(self.bloom_intensity)))
        self.bloom_max_px = max(0, min(60, int(self.bloom_max_px)))
        self.recovery_speed = max(1.0, min(20.0, float(self.recovery_speed)))
        self.ads_tighten = max(0.1, min(1.0, float(self.ads_tighten)))
        self.ads_tighten_speed = max(1.0, min(20.0, float(self.ads_tighten_speed)))
        if self.move_color and self.move_color not in COLORS:
            self.move_color = ""
        self.color_shift_threshold = max(0.05, min(1.0, float(self.color_shift_threshold)))
        self.aim_pulse_threshold = max(0.05, min(1.0, float(self.aim_pulse_threshold)))
        self.aim_pulse_cooldown = max(0.05, min(2.0, float(self.aim_pulse_cooldown)))

    @classmethod
    def from_dict(cls, d: dict | None) -> CrosshairConfig:
        c = cls()
        if isinstance(d, dict):
            for k, v in d.items():
                if hasattr(c, k):
                    setattr(c, k, v)
        c.validate()
        return c

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled, "style": self.style, "size": self.size,
            "gap": self.gap, "thickness": self.thickness, "color": self.color,
            "opacity": self.opacity, "center_dot": self.center_dot,
            "dot_size": self.dot_size, "hide_on_ads": self.hide_on_ads,
            "offset_x": self.offset_x, "offset_y": self.offset_y,
            "target_window": self.target_window,
            "movement_detection": self.movement_detection,
            "bloom_intensity": self.bloom_intensity,
            "bloom_max_px": self.bloom_max_px,
            "recovery_speed": self.recovery_speed,
            "ads_tighten": self.ads_tighten,
            "ads_tighten_speed": self.ads_tighten_speed,
            "move_color": self.move_color,
            "color_shift_threshold": self.color_shift_threshold,
            "aim_sweep_pulse": self.aim_sweep_pulse,
            "aim_pulse_threshold": self.aim_pulse_threshold,
            "aim_pulse_cooldown": self.aim_pulse_cooldown,
            "screen_sync": self.screen_sync,
            "target_fps": self.target_fps,
        }


# -- movement state tracker ---------------------------------------------------

@dataclass
class _MovementState:
    """Tracks controller stick velocity to drive dynamic bloom."""
    prev_lx: float = 0.0
    prev_ly: float = 0.0
    prev_rx: float = 0.0
    prev_ry: float = 0.0
    prev_t: float = field(default_factory=time.monotonic)

    # smoothed outputs
    move_mag: float = 0.0       # 0-1 combined stick magnitude
    aim_mag: float = 0.0        # 0-1 right-stick magnitude
    bloom_px: float = 0.0       # current dynamic bloom in pixels
    ads_factor: float = 1.0     # 1.0 = hip, ads_tighten = full ADS

    def update(self, lx: float, ly: float, rx: float, ry: float,
               ads: bool, cfg: CrosshairConfig) -> None:
        now = time.monotonic()
        dt = min(now - self.prev_t, 0.1)  # cap at 100ms to avoid jumps
        self.prev_t = now
        if dt <= 0:
            return

        # stick deltas -> velocity
        dlx = lx - self.prev_lx
        dly = ly - self.prev_ly
        drx = rx - self.prev_rx
        dry = ry - self.prev_ry
        self.prev_lx, self.prev_ly = lx, ly
        self.prev_rx, self.prev_ry = rx, ry

        # magnitude of change (0-1 ish)
        move_v = math.hypot(dlx, dly) / max(dt, 0.001)
        aim_v = math.hypot(drx, dry) / max(dt, 0.001)

        # smooth magnitudes (exponential decay)
        alpha = min(1.0, dt * 10.0)  # fast response
        self.move_mag = self.move_mag * (1 - alpha) + min(1.0, move_v * 0.5) * alpha
        self.aim_mag = self.aim_mag * (1 - alpha) + min(1.0, aim_v * 0.5) * alpha

        # also factor in raw stick position (not just velocity) for sustained holds
        pos_mag = math.hypot(lx, ly)  # 0-1
        aim_pos = math.hypot(rx, ry)
        self.move_mag = max(self.move_mag, min(1.0, pos_mag * 0.3))
        self.aim_mag = max(self.aim_mag, min(1.0, aim_pos * 0.3))

        # bloom target
        combined = max(self.move_mag, self.aim_mag)
        target_bloom = combined * cfg.bloom_max_px * cfg.bloom_intensity

        # bloom approaches target (fast rise, configurable recovery)
        if target_bloom > self.bloom_px:
            # fast snap up
            self.bloom_px = self.bloom_px + (target_bloom - self.bloom_px) * min(1.0, dt * 15.0)
        else:
            # smooth recovery
            self.bloom_px = max(0.0, self.bloom_px - cfg.recovery_speed * dt *
                                cfg.bloom_max_px * 0.3)

        self.bloom_px = max(0.0, min(float(cfg.bloom_max_px), self.bloom_px))

        # ADS factor
        target_ads = cfg.ads_tighten if ads else 1.0
        lerp_rate = cfg.ads_tighten_speed * dt
        self.ads_factor += (target_ads - self.ads_factor) * min(1.0, lerp_rate)


# -- win32 helpers ------------------------------------------------------------

def _set_click_through(hwnd: int, enable: bool) -> bool:
    """Windows WS_EX_TRANSPARENT toggle. Returns False on non-Windows/failure."""
    try:
        user32 = ctypes.windll.user32
        GWL_EXSTYLE = -20
        WS_EX_LAYERED = 0x80000
        WS_EX_TRANSPARENT = 0x20
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if enable:
            style |= WS_EX_LAYERED | WS_EX_TRANSPARENT
        else:
            style &= ~WS_EX_TRANSPARENT
            style |= WS_EX_LAYERED
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        return True
    except Exception as e:
        log.warning("click-through unavailable: %s", e)
        return False


def _get_monitor_hz() -> int:
    """Query primary monitor refresh rate via Win32. Falls back to 60."""
    try:
        user32 = ctypes.windll.user32
        dc = user32.GetDC(0)
        hz = ctypes.windll.gdi32.GetDeviceCaps(dc, 116)  # VREFRESH
        user32.ReleaseDC(0, dc)
        return hz if 30 <= hz <= 500 else 60
    except Exception:
        return 60


# -- overlay ------------------------------------------------------------------

class CrosshairOverlay:
    """Fullscreen transparent overlay with dynamic bloom & screen-sync.

    Callbacks:
        is_ads_held()  -> bool   - whether ADS (left trigger) is active
        get_sticks()   -> tuple  - (lx, ly, rx, ry) floats or None
    """

    def __init__(self, cfg: CrosshairConfig, is_ads_held=None, get_sticks=None):
        self.cfg = cfg
        self.is_ads_held = is_ads_held or (lambda: False)
        self.get_sticks = get_sticks or (lambda: None)
        self.win = None
        self.canvas = None
        self.locked = False
        self._drag = None
        self._mstate = _MovementState()
        self._tick_ms = 16  # will be refined by screen sync
        self._last_frame = time.monotonic()
        self._retarget_n = 0
        self._pulse_until = 0.0

    # -- drawing ----------------------------------------------------------

    def _stipple(self) -> str:
        """Per-shape opacity that leaves the background truly transparent."""
        o = max(0.2, min(1.0, float(self.cfg.opacity)))
        if o >= 0.95:
            return ""
        if o >= 0.7:
            return "gray75"
        if o >= 0.4:
            return "gray50"
        return "gray25"

    def _draw_cross(self, cx, cy, s, g, t, col, st=""):
        """Standard 4-arm cross."""
        c = self.canvas
        c.create_line(cx - g - s, cy, cx - g, cy, fill=col, width=t, stipple=st)
        c.create_line(cx + g, cy, cx + g + s, cy, fill=col, width=t, stipple=st)
        c.create_line(cx, cy - g - s, cx, cy - g, fill=col, width=t, stipple=st)
        c.create_line(cx, cy + g, cx, cy + g + s, fill=col, width=t, stipple=st)

    def _draw_t_shape(self, cx, cy, s, g, t, col, st=""):
        """T-shape: top arm removed for cleaner sight picture."""
        c = self.canvas
        c.create_line(cx - g - s, cy, cx - g, cy, fill=col, width=t, stipple=st)
        c.create_line(cx + g, cy, cx + g + s, cy, fill=col, width=t, stipple=st)
        c.create_line(cx, cy + g, cx, cy + g + s, fill=col, width=t, stipple=st)

    def _draw_diamond(self, cx, cy, s, g, t, col, st=""):
        """Diamond/rhombus outline."""
        c = self.canvas
        pts = [cx, cy - g - s, cx + g + s, cy, cx, cy + g + s, cx - g - s, cy]
        c.create_polygon(pts, outline=col, fill="", width=t, stipple=st)

    def _draw_chevron(self, cx, cy, s, g, t, col, st=""):
        """Downward chevron (V-shape)."""
        c = self.canvas
        half = s // 2
        c.create_line(cx - g - s, cy - half, cx, cy + half, fill=col, width=t, stipple=st)
        c.create_line(cx, cy + half, cx + g + s, cy - half, fill=col, width=t, stipple=st)

    def _draw_circle(self, cx, cy, s, _g, t, col, st=""):
        c = self.canvas
        c.create_oval(cx - s, cy - s, cx + s, cy + s, outline=col, width=t, stipple=st)

    def _draw_dot(self, cx, cy, r, col, st=""):
        self.canvas.create_oval(cx - r, cy - r, cx + r, cy + r, fill=col, outline="", stipple=st)

    # -- main frame -------------------------------------------------------

    def _redraw(self) -> None:
        if not self.canvas:
            return

        now = time.monotonic()
        dt = now - self._last_frame
        self._last_frame = now
        cfg = self.cfg

        # --- movement detection update ---
        ads = False
        if cfg.movement_detection:
            sticks = None
            try:
                sticks = self.get_sticks()
            except Exception:
                pass
            try:
                ads = bool(self.is_ads_held())
            except Exception:
                pass
            if sticks is not None:
                self._mstate.update(sticks[0], sticks[1], sticks[2], sticks[3],
                                    ads, cfg)
            else:
                # no stick data -> decay bloom
                self._mstate.update(0, 0, 0, 0, ads, cfg)
        else:
            try:
                ads = bool(self.is_ads_held())
            except Exception:
                pass
            # no movement detection -> just track ADS factor
            target_ads = cfg.ads_tighten if ads else 1.0
            self._mstate.ads_factor += (target_ads - self._mstate.ads_factor) * min(1.0, dt * cfg.ads_tighten_speed)

        # --- hide on ADS ---
        self.canvas.delete("all")
        if cfg.hide_on_ads and ads:
            self._schedule()
            return

        # --- compute effective gap ---
        base_gap = float(cfg.gap)
        bloom = self._mstate.bloom_px if cfg.movement_detection else 0.0
        ads_f = self._mstate.ads_factor
        effective_gap = (base_gap + bloom) * ads_f
        effective_gap = max(0.0, effective_gap)
        g = int(round(effective_gap))

        # --- determine colour ---
        col = cfg.color
        if (cfg.movement_detection and cfg.move_color and
                self._mstate.move_mag > cfg.color_shift_threshold):
            col = cfg.move_color

        w = self.canvas.winfo_width() or self._box
        h = self.canvas.winfo_height() or self._box
        cx, cy = w // 2, h // 2  # box is pre-centered on screen; offsets move the box
        t = cfg.thickness
        s = cfg.size

        # --- draw style ---
        st = self._stipple()
        style = cfg.style
        if style in ("cross", "cross_dot"):
            self._draw_cross(cx, cy, s, g, t, col, st)
        elif style == "t_shape":
            self._draw_t_shape(cx, cy, s, g, t, col, st)
        elif style == "diamond":
            self._draw_diamond(cx, cy, s, g, t, col, st)
        elif style == "chevron":
            self._draw_chevron(cx, cy, s, g, t, col, st)
        elif style == "circle":
            self._draw_circle(cx, cy, s, g, t, col, st)

        # center dot
        if style == "dot" or (cfg.center_dot and style in
                ("cross", "cross_dot", "circle", "t_shape", "diamond", "chevron")):
            dr = cfg.dot_size + (2 if style == "dot" else 0)
            # ADS: dot shrinks slightly
            if ads and cfg.movement_detection:
                dr = max(1, int(dr * ads_f))
            self._draw_dot(cx, cy, dr, col, st)

        # --- bloom indicator ring (subtle, only when bloom is active) ---
        if cfg.movement_detection and bloom > 2.0:
            bloom_r = int(g + s * 0.3)
            # faint ring showing spread
            self.canvas.create_oval(cx - bloom_r, cy - bloom_r,
                                    cx + bloom_r, cy + bloom_r,
                                     outline=col, width=1, dash=(2, 4))

        # Manual mark pulse: driven by an explicit controller/UI action only.
        if time.monotonic() < self._pulse_until:
            pulse_r = int(s + 14)
            self.canvas.create_oval(cx - pulse_r, cy - pulse_r,
                                    cx + pulse_r, cy + pulse_r,
                                    outline=col, width=max(2, t + 1))

        self._schedule()

    def pulse(self, duration: float = 0.28) -> None:
        """Pulse after an explicit manual mark button. No target detection."""
        self._pulse_until = max(self._pulse_until, time.monotonic() + duration)
        self._redraw()

    def _schedule(self) -> None:
        try:
            if self.win:
                # Re-anchor to the target game window ~1/sec (it can move).
                self._retarget_n += 1
                if self._retarget_n >= max(1, int(1000 / max(1, self._tick_ms))):
                    self._retarget_n = 0
                    self._place_box()
                self.win.after(self._tick_ms, self._redraw)
        except Exception:
            pass

    # -- lifecycle --------------------------------------------------------

    def set_locked(self, locked: bool) -> None:
        self.locked = locked
        if not self.win:
            return
        try:
            hwnd = self.win.winfo_id()
        except Exception:
            return
        _set_click_through(hwnd, locked)

    def show(self) -> bool:
        import tkinter as tk
        if self.win is not None:
            try:
                self.win.deiconify()
                return True
            except Exception:
                self.win = None

        # screen sync: determine tick interval
        if self.cfg.screen_sync:
            hz = self.cfg.target_fps if self.cfg.target_fps > 0 else _get_monitor_hz()
            self._tick_ms = max(4, int(1000 / hz))
            log.info("crosshair screen-sync: %d Hz -> %d ms tick", hz, self._tick_ms)
        else:
            self._tick_ms = 16  # ~60fps fallback

        try:
            # Non-black key colour; the toplevel itself also gets it so no
            # pixel can ever render opaque by accident.
            key_color = "#010101"
            self.win = tk.Toplevel()
            self.win.configure(bg=key_color)
            self.win.overrideredirect(True)
            # Small centered window, NOT fullscreen: worst case of a
            # transparency failure is a small box, never a full blackout.
            self._box = 256
            sw, sh = self.win.winfo_screenwidth(), self.win.winfo_screenheight()
            self._screen_cx, self._screen_cy = sw // 2, sh // 2
            self.canvas = tk.Canvas(self.win, bg=key_color, highlightthickness=0,
                                    bd=0, width=self._box, height=self._box)
            self.canvas.pack()
            self._place_box()
            # Setup-mode drag moves the crosshair center
            self.canvas.bind("<Button-1>", lambda e: setattr(self, "_drag", (e.x, e.y)))
            self.canvas.bind("<B1-Motion>", self._on_drag)
            # Map the window FIRST: -transparentcolor only takes effect on
            # some Windows builds once the window exists on screen.
            self.win.update_idletasks()
            self.win.deiconify()
            self.win.update()
            self.win.attributes("-topmost", True)
            self.win.attributes("-transparentcolor", key_color)
            # NOTE: never use -alpha here: on Windows it dims the ENTIRE
            # screen including transparent regions. Opacity is done per-shape
            # via stipple in _stipple().
            self._force_colorkey(key_color)
            self.win.update()
            self.win.lift()
            self.set_locked(True)
            self._last_frame = time.monotonic()
            self._redraw()
            log.info("crosshair overlay shown (%s, bloom=%s, sync=%s)",
                     self.cfg.style, self.cfg.movement_detection, self.cfg.screen_sync)
            return True
        except Exception as e:
            log.error("overlay failed: %s", e)
            return False

    def _force_colorkey(self, key_color: str) -> None:
        """Explicit LWA_COLORKEY via Win32 so transparency never depends on
        Tk applying -transparentcolor correctly."""
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            gdi32 = ctypes.windll.gdi32
            hwnd = self.win.winfo_id()
            GWL_EXSTYLE = -20
            WS_EX_LAYERED = 0x80000
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED)
            r = int(key_color[1:3], 16)
            g = int(key_color[3:5], 16)
            b = int(key_color[5:7], 16)
            cref = r | (g << 8) | (b << 16)
            LWA_COLORKEY = 0x1
            user32.SetLayeredWindowAttributes(hwnd, cref, 0, LWA_COLORKEY)
            # sanity: read back layered flag
            style2 = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            if not (style2 & WS_EX_LAYERED):
                log.warning("WS_EX_LAYERED did not stick")
        except Exception as e:
            log.warning("colorkey force failed: %s", e)

    def _find_window_center(self, title_sub: str):
        """Center of the first visible window whose title contains title_sub."""
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            match = []

            @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
            def _cb(hwnd, _lp):
                try:
                    if not user32.IsWindowVisible(hwnd):
                        return True
                    n = user32.GetWindowTextLengthW(hwnd)
                    if n <= 0:
                        return True
                    buf = ctypes.create_unicode_buffer(n + 1)
                    user32.GetWindowTextW(hwnd, buf, n + 1)
                    if title_sub.lower() in buf.value.lower():
                        match.append(hwnd)
                        return False
                except Exception:
                    pass
                return True

            user32.EnumWindows(_cb, 0)
            if not match:
                return None
            rect = (wintypes.RECT)()
            if not user32.GetWindowRect(match[0], ctypes.byref(rect)):
                return None
            return ((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2)
        except Exception:
            return None

    def _place_box(self) -> None:
        try:
            cx, cy = self._screen_cx, self._screen_cy
            target = str(getattr(self.cfg, "target_window", "") or "").strip()
            if target:
                found = self._find_window_center(target)
                if found is not None:
                    cx, cy = found
            half = self._box // 2
            x = cx - half + self.cfg.offset_x
            y = cy - half + self.cfg.offset_y
            self.win.geometry(f"{self._box}x{self._box}+{x}+{y}")
        except Exception:
            pass

    def _on_drag(self, event) -> None:
        if self.locked or not self._drag:
            return
        dx, dy = event.x - self._drag[0], event.y - self._drag[1]
        self.cfg.offset_x += dx
        self.cfg.offset_y += dy
        self._drag = (event.x, event.y)
        self._place_box()
        self._redraw()

    def hide(self) -> None:
        try:
            if self.win:
                self.win.withdraw()
        except Exception:
            pass

    def close(self) -> None:
        try:
            if self.win:
                self.win.destroy()
        except Exception:
            pass
        self.win = None
        self.canvas = None
