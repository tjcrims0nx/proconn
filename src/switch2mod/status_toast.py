"""Live status toast - small top-left popup proving the tool is really working.

REAL indicator, not a static badge: every value on it comes from the live
mapper. Green dot pulses while HID reports are flowing; the rate shown is
measured from the mapper's actual report counter; if reports stop the dot
turns orange and says NO PAD DATA; if the mapper dies it turns red, says
STOPPED, and removes itself. Auto-dismisses a few seconds after a healthy
start so it never clutters the HUD.
"""
from __future__ import annotations

import logging
import time

log = logging.getLogger("switch2mod.toast")

BG = "#12b879"
EDGE = "#7affc2"
NEON = "#12f5a0"
NEON_DIM = "#0a6b4e"
WARN = "#ffb454"
ERR = "#ff5c73"
TEXT = "#00100d"
DIM = "#003b2b"


class StatusToast:
    """Small always-on-top, click-through toast pinned top-left.

    Callbacks (required, must be real):
        is_alive()      -> bool  mapper thread alive
        is_receiving()  -> bool  fresh input within last 0.75s
        report_rate()   -> int   measured reports/sec (0 if unknown)
    """

    def __init__(self, root, is_alive, is_receiving, report_rate,
                 show_seconds: float = 4.0):
        import tkinter as tk
        self.root = root
        self.is_alive = is_alive
        self.is_receiving = is_receiving
        self.report_rate = report_rate
        self.show_seconds = show_seconds
        self.win = None
        self.dead = False

        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=BG)
        self.win.geometry("+14+14")

        frame = tk.Frame(self.win, bg=EDGE, bd=0)
        frame.pack(padx=0, pady=0)
        panel = tk.Frame(frame, bg=BG)
        panel.pack(padx=2, pady=2)
        row = tk.Frame(panel, bg=BG)
        row.pack(padx=14, pady=(8, 2))
        self.dot = tk.Canvas(row, width=20, height=20, bg=BG,
                             highlightthickness=0)
        self.dot.pack(side="left")
        self.dot_id = self.dot.create_oval(2, 2, 18, 18, fill=NEON,
                                           outline="")
        self.label = tk.Label(row, text="MOD LIVE", font=("Segoe UI Semibold", 10),
                              fg=TEXT, bg=BG)
        self.label.pack(side="left", padx=(8, 0))
        self.sub = tk.Label(panel, text="", font=("Segoe UI", 8),
                            fg=DIM, bg=BG)
        self.sub.pack(anchor="w", padx=14, pady=(0, 8))

        self._pulse_on = True
        self._t0 = time.monotonic()
        self._last_rate_sample = (time.monotonic(), 0)
        self._measured = 0
        try:
            from switch2mod.crosshair import _set_click_through
            self.win.update_idletasks()
            _set_click_through(self.win.winfo_id(), True)
        except Exception:
            pass
        self._tick()

    def _measure_rate(self) -> None:
        """Real rate: sample the mapper's report counter 1s apart."""
        try:
            now, prev = self._last_rate_sample
            cur = self.report_rate()
            if time.monotonic() - now >= 1.0:
                self._measured = int(cur - prev)
                self._last_rate_sample = (time.monotonic(), cur)
        except Exception:
            self._measured = 0

    def _tick(self) -> None:
        if self.dead or self.win is None:
            return
        try:
            alive = bool(self.is_alive())
            fresh = bool(self.is_receiving())
            self._measure_rate()

            if not alive:
                self.dot.itemconfig(self.dot_id, fill=ERR)
                self.label.config(text="TOOL STOPPED", fg=ERR)
                self.sub.config(text="mapper thread exited")
                self._die_after(1200)
                return
            if not fresh:
                self.dot.itemconfig(self.dot_id, fill=WARN)
                self.label.config(text="NO PAD DATA", fg=WARN)
                self.sub.config(text="mapper alive, no HID reports")
            else:
                self._pulse_on = not self._pulse_on
                self.dot.itemconfig(self.dot_id,
                                    fill=NEON if self._pulse_on else NEON_DIM)
                self.label.config(text="TOOL LIVE", fg=TEXT)
                self.sub.config(text=f"{self._measured} reports/s - "
                                     "virtual pad feeding game")
            if time.monotonic() - self._t0 >= self.show_seconds:
                if alive and fresh:
                    self._fade_out()
                    return
                # unhealthy: keep showing truth up to 10s max
                if time.monotonic() - self._t0 >= 10.0:
                    self._die_after(0)
                    return
            self.win.after(250, self._tick)
        except Exception:
            self.close()

    def _fade_out(self) -> None:
        try:
            alpha = 1.0
            def step():
                nonlocal alpha
                alpha -= 0.12
                if alpha <= 0 or self.win is None:
                    self.close()
                    return
                try:
                    self.win.attributes("-alpha", alpha)
                    self.win.after(30, step)
                except Exception:
                    self.close()
            step()
        except Exception:
            self.close()

    def _die_after(self, ms: int) -> None:
        try:
            self.win.after(ms, self.close)
        except Exception:
            self.close()

    def close(self) -> None:
        self.dead = True
        try:
            if self.win:
                self.win.destroy()
        except Exception:
            pass
        self.win = None
