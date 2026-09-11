"""Tk GUI - compact dark tuning console over AppConfig + MapperService."""
from __future__ import annotations

import logging
import math
import os
import threading
import time
from pathlib import Path

from switch2mod.config import AppConfig
from switch2mod.detection import ControllerDetector
from switch2mod.mapper import ProToXInput

log = logging.getLogger("switch2mod.gui")

# -- Colour palette ----------------------------------------------------------
BG          = "#00100f"
SURFACE     = "#031715"
SURFACE2    = "#08231f"
BORDER      = "#0a2924"
NEON        = "#12f5a0"
NEON_DIM    = "#0fc77f"
NEON_GLOW   = "#12f5a01c"
ACCENT2     = "#7affc2"
ACCENT_WARN = "#ffc56b"
ACCENT_ERR  = "#ff6c80"
TEXT        = "#f1faf7"
TEXT_DIM    = "#7f9d95"
VIZ_BG      = "#021311"
VIZ_GRID    = "#0d332c"
VIZ_DZ      = "#1b5145"


class ModGui:
    def __init__(self, cfg: AppConfig, profile_path: Path | None, wired: bool = False,
                 index: int | None = None, hid_mode: bool = False):
        self.cfg = cfg
        self.profile_path = profile_path
        self.wired = wired
        self.index = index
        self.hid_mode = hid_mode
        self.runner = None
        self.runner_thread = None
        self.watchdog_enabled = True
        self.overlay = None

    # -- helpers ----------------------------------------------------------
    @staticmethod
    def _card(parent, title: str | None = None, pad: int = 10):
        """Create a dark card frame with optional header label."""
        import tkinter as tk
        outer = tk.Frame(parent, bg=BG)
        outer.pack(fill="x", padx=20, pady=(10, 0))
        # Soft dashboard cards: no hard 1px outlines or nested boxed borders.
        card = tk.Frame(outer, bg=SURFACE, bd=0,
                        highlightthickness=0)
        card.pack(fill="x", ipadx=pad + 2, ipady=max(7, pad - 1))
        if title:
            tk.Label(card, text=title, font=("Segoe UI", 9),
                     fg=TEXT, bg=SURFACE).pack(anchor="w", padx=16, pady=(10, 6))
        return card

    @staticmethod
    def _sep(parent):
        import tkinter as tk
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", padx=10, pady=6)

    # -- main -------------------------------------------------------------
    def run(self) -> None:
        import tkinter as tk
        from tkinter import ttk

        root = tk.Tk()
        root.title("Switch 2 Pro Tweaks")
        root.geometry("1280x810")
        root.minsize(980, 640)
        root.configure(bg=BG)

        # -- ttk theme / style -------------------------------------------
        style = ttk.Style(root)
        style.theme_use("clam")

        style.configure(".", background=SURFACE, foreground=TEXT,
                        fieldbackground=SURFACE2, borderwidth=0,
                        font=("Segoe UI", 9))
        style.configure("TFrame", background=SURFACE)
        style.configure("TLabel", background=SURFACE, foreground=TEXT,
                        font=("Segoe UI", 9))
        style.configure("Dim.TLabel", foreground=TEXT_DIM, font=("Segoe UI", 8))
        style.configure("Neon.TLabel", foreground=NEON, font=("Segoe UI", 9))
        style.configure("Title.TLabel", foreground=NEON,
                        font=("Segoe UI", 15), background=BG)
        style.configure("Sub.TLabel", foreground=TEXT_DIM,
                        font=("Segoe UI", 9), background=BG)
        style.configure("TCheckbutton", background=SURFACE, foreground=TEXT,
                        font=("Segoe UI", 9), indicatorsize=14)
        style.map("TCheckbutton",
                  background=[("active", SURFACE2)],
                  foreground=[("active", NEON)])
        style.configure("TCombobox", fieldbackground=SURFACE2,
                        background=SURFACE2, foreground=TEXT,
                        arrowcolor=NEON, selectbackground=NEON_DIM,
                        selectforeground=BG)
        style.map("TCombobox",
                  fieldbackground=[("readonly", SURFACE2)],
                  foreground=[("readonly", TEXT)])
        # Scale (slider) - neon trough
        style.configure("Green.Horizontal.TScale",
                        troughcolor=SURFACE2, background=NEON,
                        sliderlength=18, sliderthickness=18)
        style.map("Green.Horizontal.TScale",
                  background=[("active", ACCENT2)])
        # Scrollbar
        style.configure("Vertical.TScrollbar",
                        troughcolor=BG, background=SURFACE2,
                        arrowcolor=NEON)
        style.map("Vertical.TScrollbar",
                  background=[("active", NEON_DIM)])

        # -- scrollable body ---------------------------------------------
        outer = tk.Frame(root, bg=BG)
        outer.pack(fill="both", expand=True)

        workspace = tk.Frame(outer, bg=BG)
        workspace.pack(fill="both", expand=True)
        topbar = tk.Frame(workspace, bg="#021210", height=58,
                          highlightthickness=0)
        topbar.pack(fill="x")
        topbar.pack_propagate(False)
        tk.Label(topbar, text="Switch 2 Pro Controller",
                 font=("Segoe UI", 10), fg=TEXT_DIM,
                 bg="#021210").pack(pady=19)

        content = tk.Frame(workspace, bg=BG)
        content.pack(fill="both", expand=True)
        canvas = tk.Canvas(content, bg=BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(content, orient="vertical",
                                  command=canvas.yview,
                                  style="Vertical.TScrollbar")
        body = tk.Frame(canvas, bg=BG)
        body_id = canvas.create_window((0, 0), window=body, anchor="nw")

        def _sync(_=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            try:
                canvas.itemconfig(body_id, width=canvas.winfo_width())
            except Exception:
                pass

        body.bind("<Configure>", _sync)
        canvas.bind("<Configure>", _sync)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        def _wheel(event):
            try:
                if getattr(event, "delta", 0):
                    canvas.yview_scroll(-1 * (event.delta // 120), "units")
                elif getattr(event, "num", 0) == 4:
                    canvas.yview_scroll(-3, "units")
                elif getattr(event, "num", 0) == 5:
                    canvas.yview_scroll(3, "units")
            except Exception:
                pass

        canvas.bind_all("<MouseWheel>", _wheel)
        canvas.bind_all("<Button-4>", _wheel)
        canvas.bind_all("<Button-5>", _wheel)
        root.bind_all("<Up>", lambda _event: canvas.yview_scroll(-3, "units"))
        root.bind_all("<Down>", lambda _event: canvas.yview_scroll(3, "units"))
        root.bind_all("<Prior>", lambda _event: canvas.yview_scroll(-1, "pages"))
        root.bind_all("<Next>", lambda _event: canvas.yview_scroll(1, "pages"))
        root.bind_all("<Home>", lambda _event: canvas.yview_moveto(0.0))
        root.bind_all("<End>", lambda _event: canvas.yview_moveto(1.0))

        # -- accent strip at top -----------------------------------------
        tk.Frame(body, bg=NEON, height=3).pack(fill="x")

        # -- header ------------------------------------------------------
        hdr = tk.Frame(body, bg=BG)
        hdr.pack(fill="x", padx=16, pady=(12, 0))
        ttk.Label(hdr, text="SWITCH 2 PRO MOD", style="Title.TLabel").pack(
            anchor="w")
        mode = "WIRED 1000 Hz" if (self.wired or self.cfg.wired_mode) else "WIRELESS"
        game = getattr(self.cfg, "game", "cod").upper()
        layout = getattr(self.cfg, "cod_layout", "")
        # pill badges
        badge_row = tk.Frame(hdr, bg=BG)
        badge_row.pack(anchor="w", pady=(2, 0))
        for txt, color in ((game, NEON), (layout.replace("_", " ").upper(), TEXT_DIM),
                           (mode, NEON_DIM)):
            if not txt:
                continue
            pill = tk.Label(badge_row, text=f" {txt} ", font=("Segoe UI Semibold", 8),
                            fg=BG, bg=color, bd=0, padx=6, pady=1)
            pill.pack(side="left", padx=(0, 6))

        state: dict[str, tk.DoubleVar] = {}
        viz_cache: dict[str, object] = {"joy": None, "idx": None}

        # ================================================================
        #CONNECTION CARD
        # ================================================================
        conn_card = self._card(body, "CONNECTION")
        conn_inner = tk.Frame(conn_card, bg=SURFACE)
        conn_inner.pack(fill="x", padx=10, pady=4)
        dot = tk.Canvas(conn_inner, width=16, height=16, bg=SURFACE,
                        highlightthickness=0)
        dot.pack(side="left")
        dot_id = dot.create_oval(3, 3, 13, 13, fill=ACCENT_ERR, outline="")
        glow_id = dot.create_oval(1, 1, 15, 15, outline=ACCENT_ERR, width=1)
        conn_label = tk.Label(conn_inner, text="Detecting...",
                              font=("Segoe UI", 9), fg=TEXT_DIM, bg=SURFACE)
        conn_label.pack(side="left", padx=10)
        hid_badge = tk.Label(conn_inner, text="", font=("Segoe UI Semibold", 7),
                             fg=BG, bg=SURFACE, padx=4, pady=1)
        hid_badge.pack(side="right")

        # ================================================================
        #STICK VISUALIZER CARD
        # ================================================================
        viz_card = self._card(body, "STICK VISUALIZER")
        viz_row = tk.Frame(viz_card, bg=SURFACE)
        viz_row.pack(pady=4)

        def _viz_canvas(parent, label_text):
            f = tk.Frame(parent, bg=SURFACE)
            f.pack(side="left", padx=12)
            tk.Label(f, text=label_text, font=("Segoe UI Semibold", 8),
                     fg=NEON, bg=SURFACE).pack()
            c = tk.Canvas(f, width=130, height=130, bg=VIZ_BG,
                          highlightthickness=1, highlightbackground=BORDER)
            c.pack()
            coord = tk.Label(f, text="0.00, 0.00", font=("Consolas", 8),
                             fg=TEXT_DIM, bg=SURFACE)
            coord.pack()
            return c, coord

        left_canvas, left_coord = _viz_canvas(viz_row, "LEFT")
        right_canvas, right_coord = _viz_canvas(viz_row, "RIGHT (AIM)")

        def draw_stick(cv: tk.Canvas, rx: float, ry: float, ex: float, ey: float,
                       deadzone: float, ads: bool = False):
            cv.delete("all")
            cx = cy = 65
            r = 60
            # grid
            for i in range(-2, 3):
                cv.create_line(cx + i * r // 2, cy - r, cx + i * r // 2, cy + r,
                               fill=VIZ_GRID, width=1)
                cv.create_line(cx - r, cy + i * r // 2, cx + r, cy + i * r // 2,
                               fill=VIZ_GRID, width=1)
            # outer ring
            cv.create_oval(cx - r, cy - r, cx + r, cy + r, outline="#1e3a1e", width=1)
            # deadzone ring
            dzr = max(2.0, float(deadzone) * r)
            cv.create_oval(cx - dzr, cy - dzr, cx + dzr, cy + dzr,
                           outline=VIZ_DZ, width=1, dash=(3, 3))
            # raw ghost dot
            gx = cx + max(-1.0, min(1.0, rx)) * r
            gy = cy + max(-1.0, min(1.0, ry)) * r
            cv.create_oval(gx - 3, gy - 3, gx + 3, gy + 3,
                           fill="#333333", outline="#444444")
            # effective dot with glow
            px = cx + max(-1.0, min(1.0, ex)) * r
            py = cy + max(-1.0, min(1.0, ey)) * r
            color = ACCENT_WARN if ads else NEON
            dim = NEON_DIM if not ads else "#cc7700"
            cv.create_oval(px - 10, py - 10, px + 10, py + 10,
                           outline=dim, width=1)
            cv.create_oval(px - 5, py - 5, px + 5, py + 5,
                           fill=color, outline="")
            # ADS badge
            if ads:
                cv.create_text(cx, cy + r + 8, text="ADS", fill=ACCENT_WARN,
                               font=("Segoe UI Semibold", 7))

        # ================================================================
        #INPUT MONITOR CARD - live button states incl. GL/GR paddles
        # ================================================================
        BTN_DISPLAY = (
            ("A", "A"), ("B", "B"), ("X", "X"), ("Y", "Y"),
            ("LB", "L"), ("RB", "R"), ("LT", "ZL"), ("RT", "ZR"),
            ("L3", "LStick"), ("R3", "RStick"),
            ("START", "plus"), ("BACK", "minus"), ("GUIDE", "home"),
            ("DUP", "d_up"), ("DDOWN", "d_down"),
            ("DLEFT", "d_left"), ("DRIGHT", "d_right"),
            ("GL", "GL"), ("GR", "GR"), ("C", "C"), ("CAP", "capture"),
        )
        mon_card = self._card(body, "INPUT MONITOR - press anything")
        mon_grid = tk.Frame(mon_card, bg=SURFACE)
        mon_grid.pack(fill="x", padx=10, pady=6)
        btn_widgets: dict[str, object] = {}
        for pos, (label, _key) in enumerate(BTN_DISPLAY):
            r, c = divmod(pos, 7)
            w = tk.Label(mon_grid, text=label, font=("Consolas", 8, "bold"),
                         fg=TEXT_DIM, bg=SURFACE2, width=6, pady=3)
            w.grid(row=r, column=c, padx=3, pady=3)
            btn_widgets[label] = w

        def refresh_buttons(btns: dict) -> None:
            for label, key in BTN_DISPLAY:
                try:
                    on = bool(btns.get(key, False))
                    btn_widgets[label].config(
                        bg=NEON if on else SURFACE2,
                        fg=BG if on else TEXT_DIM)
                except Exception:
                    pass

        # ================================================================
        #PROOF CARD - what the GAME actually receives + overlay self-test
        # ================================================================
        proof_card = self._card(body, "PROOF IT WORKS IN-GAME")
        proof_lbl = tk.Label(proof_card, text="Start the mod, then move sticks / press buttons.",
                             font=("Consolas", 8), fg=TEXT_DIM, bg=SURFACE,
                             justify="left")
        proof_lbl.pack(anchor="w", padx=10, pady=4)

        def refresh_proof() -> None:
            try:
                r = self.runner
                if r is None or not getattr(r, "running", False):
                    return
                o = getattr(r, "last_output", None) or {}
                if not o:
                    return
                proof_lbl.config(
                    text=f"VIRTUAL XBOX -> game: L({o.get('lx',0):+.2f},{o.get('ly',0):+.2f}) "
                         f"R({o.get('rx',0):+.2f},{o.get('ry',0):+.2f}) "
                         f"LT {o.get('lt',0):.2f} RT {o.get('rt',0):.2f}\n"
                         f"held: {','.join(o.get('btns', [])) or '-'}",
                    fg=NEON)
            except Exception:
                pass

        proof_btns = tk.Frame(proof_card, bg=SURFACE)
        proof_btns.pack(fill="x", padx=10, pady=4)

        def _current_crosshair():
            """Fresh config from the live panel widgets (style/color/size/
            target/etc.) so TEST and START always use what you see."""
            import copy
            ch = copy.deepcopy(self.cfg.crosshair)
            try:
                ch.style = str(xh_style.get())
                ch.color = str(xh_color.get())
                ch.size = int(float(xh_size.get()))
                ch.hide_on_ads = bool(xh_hide_ads.get())
                ch.target_window = str(xh_target.get()).strip()
                ch.movement_detection = bool(xh_movement.get())
                ch.screen_sync = bool(xh_screen_sync.get())
                ch.aim_sweep_pulse = bool(xh_aim_pulse.get())
                ch.bloom_intensity = float(xh_bloom.get())
                ch.bloom_max_px = int(xh_bloom_max.get())
                ch.recovery_speed = float(xh_recovery.get())
                ch.ads_tighten = float(xh_ads_tighten.get())
                ch.move_color = str(xh_move_color.get())
                ch.color_shift_threshold = float(xh_cs_thresh.get())
            except Exception:
                pass
            ch.enabled = True
            ch.validate()
            return ch

        def test_crosshair_now() -> None:
            # Toggle: second press (or Esc, or 10s timeout) removes it.
            # Always locked click-through so it can NEVER trap input.
            try:
                old = getattr(self, "_test_ov", None)
                if old is not None:
                    try:
                        old.close()
                    except Exception:
                        pass
                    self._test_ov = None
                    set_status("Crosshair test hidden", TEXT_DIM)
                    return
                from switch2mod.crosshair import CrosshairOverlay
                ch = _current_crosshair()
                ov = CrosshairOverlay(ch, is_ads_held=lambda: False)
                if ov.show():
                    ov.set_locked(True)
                    self._test_ov = ov
                    where = f"on '{ch.target_window}'" if ch.target_window else "screen center"
                    set_status(f"TEST diamond {where} ({ch.style}) - press TEST again or Esc, auto-hides 10s", NEON)
                    def _hide_test():
                        try:
                            if getattr(self, "_test_ov", None) is ov:
                                ov.close()
                                self._test_ov = None
                                set_status("Crosshair test hidden", TEXT_DIM)
                        except Exception:
                            pass
                    try:
                        root.after(10000, _hide_test)
                        root.bind_all("<Escape>", lambda _e: _hide_test(), add="+")
                    except Exception:
                        pass
                else:
                    set_status("Overlay failed - try Borderless/Windowed desktop", ACCENT_ERR)
            except Exception as e:
                set_status(f"Overlay failed: {e}", ACCENT_ERR)

        def open_joycpl() -> None:
            import subprocess
            try:
                subprocess.Popen(["joy.cpl"] if os.name == "nt" else ["echo"])
                set_status("joy.cpl open -> Properties on Xbox 360 Controller -> move pad", NEON)
            except Exception as e:
                set_status(f"joy.cpl failed: {e}", ACCENT_ERR)

        tk.Button(proof_btns, text="TEST CROSSHAIR",
                  command=test_crosshair_now, font=("Segoe UI", 8, "bold"),
                  fg=BG, bg=NEON, activebackground=ACCENT2,
                  relief="flat", bd=0, padx=10, pady=5,
                  cursor="hand2").pack(side="left", padx=(0, 6))
        tk.Button(proof_btns, text="OPEN joy.cpl (verify virtual pad)",
                  command=open_joycpl, font=("Segoe UI", 8),
                  fg=TEXT, bg=SURFACE2, activeforeground=NEON,
                  activebackground=BORDER, relief="flat", bd=0,
                  padx=10, pady=5, cursor="hand2").pack(side="left")
        def is_admin() -> bool:
            try:
                import ctypes
                return bool(ctypes.windll.shell32.IsUserAnAdmin())
            except Exception:
                return False

        # --- ViGEmBus driver status + one-click install from bundled MSI ---
        driver_lbl = tk.Label(proof_card, text="", font=("Segoe UI", 8),
                              bg=SURFACE)
        driver_lbl.pack(anchor="w", padx=10, pady=(2, 0))

        def driver_present() -> bool:
            # Importing vgamepad connects to the ViGEmBus driver, so a
            # successful import means the virtual pad stack is usable.
            try:
                import vgamepad  # noqa: F401
                return True
            except Exception:
                return False

        def refresh_driver_label():
            try:
                ok = driver_present()
                driver_lbl.config(
                    text="Virtual gamepad: ready (ViGEmBus present)" if ok
                    else "Virtual gamepad: ViGEmBus missing",
                    fg=NEON if ok else ACCENT_ERR)
                try:
                    install_btn.config(state="disabled" if ok else "normal",
                                       fg=TEXT_DIM if ok else TEXT)
                except Exception:
                    pass
            except Exception:
                pass

        def install_driver() -> None:
            import subprocess
            try:
                from switch2mod import vigem_installer_path
                msi = vigem_installer_path()
                if not msi:
                    set_status("Bundled driver installer not found", ACCENT_ERR)
                    return
                subprocess.Popen(["msiexec", "/i", msi], shell=False)
                set_status("Driver installer launched - approve UAC, then reconnect", NEON)
                root.after(3000, refresh_driver_label)
            except Exception as e:
                set_status(f"Driver install failed: {e}", ACCENT_ERR)

        install_btn = tk.Button(proof_btns, text="INSTALL DRIVER (only if missing)",
                                command=install_driver, font=("Segoe UI", 8),
                                fg=TEXT, bg=SURFACE2, activeforeground=NEON,
                                activebackground=BORDER, relief="flat", bd=0,
                                padx=10, pady=5, cursor="hand2")
        install_btn.pack(side="left", padx=(6, 0))
        try:
            refresh_driver_label()
        except Exception:
            pass

        admin_lbl = tk.Label(proof_card, text="", font=("Segoe UI", 8),
                             bg=SURFACE)
        admin_lbl.pack(anchor="w", padx=10)
        try:
            admin_lbl.config(text="Running as ADMIN" if is_admin()
                             else "Not admin - if COD runs elevated, overlay can't draw over it",
                             fg=NEON if is_admin() else ACCENT_WARN)
        except Exception:
            pass

        def restart_admin() -> None:
            import subprocess
            import sys
            try:
                params = " ".join([sys.executable, "app.py", "--hid", "--gui"])
                subprocess.Popen(
                    ["powershell", "-Command",
                     f'Start-Process -FilePath "{sys.executable}" '
                     f'-ArgumentList "app.py","--hid","--gui" '
                     f'-WorkingDirectory "{os.getcwd()}" -Verb RunAs'])
                set_status("Relaunching as admin - approve the UAC prompt", NEON)
            except Exception as e:
                set_status(f"Admin relaunch failed: {e}", ACCENT_ERR)

        tk.Button(proof_btns, text="RESTART AS ADMIN",
                  command=restart_admin, font=("Segoe UI", 8),
                  fg=TEXT, bg=SURFACE2, activeforeground=NEON,
                  activebackground=BORDER, relief="flat", bd=0,
                  padx=10, pady=5, cursor="hand2").pack(side="left", padx=(6, 0))
        tk.Label(proof_card,
                 text="COD: Settings -> Graphics -> Display Mode -> Fullscreen Borderless.\n"
                      "Exclusive Fullscreen hides ALL overlays. Match admin level with the game.",
                 font=("Segoe UI", 8), fg=TEXT_DIM, bg=SURFACE).pack(
            anchor="w", padx=10, pady=(0, 4))

        # ================================================================
        #AIM TUNING CARD
        # ================================================================
        aim_card = self._card(body, "AIM TUNING")

        def slider(parent, label: str, key: str, lo: float, hi: float,
                   fmt: str = ".0f"):
            row = tk.Frame(parent, bg=SURFACE)
            row.pack(fill="x", padx=10, pady=3)
            val = float(getattr(self.cfg, key))
            v = tk.DoubleVar(value=val)
            lbl = tk.Label(row, text=label, font=("Segoe UI", 9),
                           fg=TEXT, bg=SURFACE)
            lbl.pack(side="left")
            val_lbl = tk.Label(row, text=f"{val:{fmt}}",
                               font=("Consolas", 9, "bold"),
                               fg=NEON, bg=SURFACE, width=6, anchor="e")
            val_lbl.pack(side="right")
            s = ttk.Scale(parent, from_=lo, to=hi, variable=v,
                          orient="horizontal",
                          style="Green.Horizontal.TScale")
            s.pack(fill="x", padx=10, pady=(0, 2))
            state[key] = v

            def _upd(*_):
                try:
                    val_lbl.config(text=f"{v.get():{fmt}}")
                except Exception:
                    pass
            v.trace_add("write", _upd)
            return v

        tk.Label(aim_card, text="Legal tuning only - adjust the dial for aim feel.",
                 font=("Segoe UI", 8), fg=TEXT_DIM, bg=SURFACE).pack(
            anchor="w", padx=10, pady=(2, 4))

        slider(aim_card, "AIM-ASSIST", "aim_assist", 0, 100)
        slider(aim_card, "ADS Damping", "ads_damping", 0.3, 1.0, fmt=".2f")
        slider(aim_card, "Hair Trigger Threshold", "hair_threshold", 0.02, 0.6,
               fmt=".2f")

        def apply_legit_max():
            preset = self.cfg.apply_legit_max_preset()
            state["aim_assist"].set(preset.aim_assist)
            state["ads_damping"].set(preset.ads_damping)
            state["hair_threshold"].set(preset.hair_threshold)
            set_status("Legit Max preset loaded - manual input only", NEON)

        tk.Button(aim_card, text="Load Legit Max preset",
                  command=apply_legit_max, font=("Segoe UI", 8),
                  fg=TEXT, bg=SURFACE2, activeforeground=NEON,
                  activebackground=BORDER, relief="flat", bd=0,
                  padx=10, pady=5, cursor="hand2").pack(anchor="w", padx=10,
                                                         pady=(3, 6))

        self._sep(aim_card)
        derived = tk.Label(aim_card, text="", font=("Consolas", 8),
                           fg=TEXT_DIM, bg=SURFACE)
        derived.pack(anchor="w", padx=10, pady=(0, 4))

        def refresh_derived(*_):
            try:
                a = max(0.0, min(100.0, float(state["aim_assist"].get()))) / 100.0
                derived.config(
                    text=f"dz={0.12 - 0.10 * a:.3f}  sens={1.0 + 1.0 * a:.2f}  "
                         f"curve={1.2 + 1.2 * a:.2f}  smooth={0.45 - 0.35 * a:.2f}")
            except Exception:
                pass

        try:
            state["aim_assist"].trace_add("write", refresh_derived)
        except Exception:
            pass
        refresh_derived()

        # Rear paddles are permanently locked (GL->LT, GR->RT) and have no
        # GUI controls by design. Mapping lives in the profile + mapper.

        # ================================================================
        #CROSSHAIR OVERLAY CARD
        # ================================================================
        from switch2mod.crosshair import STYLES, COLORS, CrosshairOverlay

        xh_card = self._card(body, "CROSSHAIR OVERLAY")
        tk.Label(xh_card, text="Windowed / Borderless required in-game",
                 font=("Segoe UI", 8), fg=TEXT_DIM, bg=SURFACE).pack(
            anchor="w", padx=10)

        xh_on = tk.BooleanVar(value=bool(getattr(self.cfg.crosshair, "enabled", False)))
        ttk.Checkbutton(xh_card, text="Enable crosshair overlay",
                        variable=xh_on).pack(anchor="w", padx=10, pady=2)

        xh_grid = tk.Frame(xh_card, bg=SURFACE)
        xh_grid.pack(fill="x", padx=10, pady=4)
        xh_grid.columnconfigure(0, weight=1)
        xh_grid.columnconfigure(1, weight=1)

        # Style
        tk.Label(xh_grid, text="Style", font=("Segoe UI", 8),
                 fg=TEXT_DIM, bg=SURFACE).grid(row=0, column=0, sticky="w")
        xh_style = tk.StringVar(value=str(getattr(self.cfg.crosshair, "style", "cross_dot")))
        ttk.Combobox(xh_grid, textvariable=xh_style, values=list(STYLES),
                     state="readonly", width=10).grid(row=1, column=0, sticky="w", pady=2)
        # Color
        tk.Label(xh_grid, text="Color", font=("Segoe UI", 8),
                 fg=TEXT_DIM, bg=SURFACE).grid(row=0, column=1, sticky="w", padx=(10, 0))
        xh_color = tk.StringVar(value=str(getattr(self.cfg.crosshair, "color", "lime")))
        ttk.Combobox(xh_grid, textvariable=xh_color, values=list(COLORS),
                     state="readonly", width=10).grid(row=1, column=1, sticky="w",
                                                       padx=(10, 0), pady=2)

        xh_size = tk.DoubleVar(value=float(getattr(self.cfg.crosshair, "size", 24)))
        size_row = tk.Frame(xh_card, bg=SURFACE)
        size_row.pack(fill="x", padx=10, pady=2)
        tk.Label(size_row, text="Size", font=("Segoe UI", 8),
                 fg=TEXT_DIM, bg=SURFACE).pack(side="left")
        xh_size_lbl = tk.Label(size_row, text=str(int(xh_size.get())),
                               font=("Consolas", 9, "bold"), fg=NEON, bg=SURFACE,
                               width=4, anchor="e")
        xh_size_lbl.pack(side="right")
        ttk.Scale(xh_card, from_=8, to=80, variable=xh_size,
                  orient="horizontal",
                  style="Green.Horizontal.TScale").pack(fill="x", padx=10)

        def _xh_upd(*_):
            try:
                xh_size_lbl.config(text=str(int(xh_size.get())))
            except Exception:
                pass
        xh_size.trace_add("write", _xh_upd)

        xh_hide_ads = tk.BooleanVar(value=bool(getattr(self.cfg.crosshair, "hide_on_ads", True)))
        ttk.Checkbutton(xh_card, text="Hide while ADS (scope)",
                        variable=xh_hide_ads).pack(anchor="w", padx=10)
        tk.Label(xh_card, text="Game window title (blank = screen center)",
                 font=("Segoe UI", 8), fg=TEXT_DIM, bg=SURFACE).pack(anchor="w", padx=10)
        xh_target = tk.StringVar(value=str(getattr(self.cfg.crosshair, "target_window", "")))
        tk.Entry(xh_card, textvariable=xh_target, font=("Segoe UI", 9),
                 fg=TEXT, bg=SURFACE2, insertbackground=NEON,
                 relief="flat", width=28).pack(anchor="w", padx=10, pady=2)
        xh_lock = tk.BooleanVar(value=True)
        ttk.Checkbutton(xh_card, text="Lock overlay (click-through)",
                        variable=xh_lock).pack(anchor="w", padx=10, pady=(0, 4))

        # -- live crosshair shape preview ---------------------------------
        self._sep(xh_card)
        tk.Label(xh_card, text="PREVIEW", font=("Segoe UI Semibold", 8),
                 fg=NEON, bg=SURFACE).pack(anchor="w", padx=10)
        xh_preview = tk.Canvas(xh_card, width=200, height=200, bg="#060810",
                               highlightthickness=1, highlightbackground=BORDER)
        xh_preview.pack(padx=10, pady=(2, 8))

        # Neon colour map for canvas rendering
        _COLOR_MAP = {
            "lime": "#00ff41", "red": "#ff1744", "cyan": "#00e5ff",
            "white": "#f0f0f0", "yellow": "#ffea00", "magenta": "#e040fb",
            "orange": "#ff9100",
        }

        def _draw_preview(*_):
            """Redraw crosshair preview from current GUI vars."""
            pv = xh_preview
            pv.delete("all")
            pw, ph = 200, 200
            pcx, pcy = pw // 2, ph // 2

            # subtle grid
            for i in range(0, pw, 20):
                pv.create_line(i, 0, i, ph, fill="#0e1418", width=1)
                pv.create_line(0, i, pw, i, fill="#0e1418", width=1)
            # center cross hair guides (very faint)
            pv.create_line(pcx, 0, pcx, ph, fill="#162217", width=1, dash=(2, 4))
            pv.create_line(0, pcy, pw, pcy, fill="#162217", width=1, dash=(2, 4))

            sty = xh_style.get()
            col = _COLOR_MAP.get(xh_color.get(), "#00ff41")
            dim_col = col + "88"  # faded version (canvas won't use alpha, so use it as outline)
            sz = max(4, min(80, int(xh_size.get())))
            gap = self.cfg.crosshair.gap if hasattr(self.cfg.crosshair, "gap") else 6
            t = max(1, self.cfg.crosshair.thickness if hasattr(self.cfg.crosshair, "thickness") else 2)
            s = sz
            g = gap

            # draw neon glow ring (outer aura)
            glow_r = s + g + 4
            pv.create_oval(pcx - glow_r, pcy - glow_r,
                           pcx + glow_r, pcy + glow_r,
                           outline="#0a2a0a", width=1)

            if sty in ("cross", "cross_dot"):
                # 4-arm cross
                pv.create_line(pcx - g - s, pcy, pcx - g, pcy, fill=col, width=t)
                pv.create_line(pcx + g, pcy, pcx + g + s, pcy, fill=col, width=t)
                pv.create_line(pcx, pcy - g - s, pcx, pcy - g, fill=col, width=t)
                pv.create_line(pcx, pcy + g, pcx, pcy + g + s, fill=col, width=t)
            elif sty == "t_shape":
                # T-shape (no top arm)
                pv.create_line(pcx - g - s, pcy, pcx - g, pcy, fill=col, width=t)
                pv.create_line(pcx + g, pcy, pcx + g + s, pcy, fill=col, width=t)
                pv.create_line(pcx, pcy + g, pcx, pcy + g + s, fill=col, width=t)
            elif sty == "diamond":
                pts = [pcx, pcy - g - s, pcx + g + s, pcy,
                       pcx, pcy + g + s, pcx - g - s, pcy]
                pv.create_polygon(pts, outline=col, fill="", width=t)
            elif sty == "chevron":
                half = s // 2
                pv.create_line(pcx - g - s, pcy - half, pcx, pcy + half,
                               fill=col, width=t)
                pv.create_line(pcx, pcy + half, pcx + g + s, pcy - half,
                               fill=col, width=t)
            elif sty == "circle":
                pv.create_oval(pcx - s, pcy - s, pcx + s, pcy + s,
                               outline=col, width=t)

            # center dot
            ds = self.cfg.crosshair.dot_size if hasattr(self.cfg.crosshair, "dot_size") else 2
            if sty == "dot":
                dr = ds + 2
                pv.create_oval(pcx - dr, pcy - dr, pcx + dr, pcy + dr,
                               fill=col, outline="")
            elif sty in ("cross", "cross_dot", "circle", "t_shape",
                         "diamond", "chevron"):
                pv.create_oval(pcx - ds, pcy - ds, pcx + ds, pcy + ds,
                               fill=col, outline="")

            # style name label
            pv.create_text(pcx, ph - 10, text=sty.upper().replace("_", " "),
                           fill=NEON_DIM, font=("Consolas", 8))

        # bind preview updates to all crosshair controls
        xh_style.trace_add("write", _draw_preview)
        xh_color.trace_add("write", _draw_preview)
        xh_size.trace_add("write", _draw_preview)
        # initial draw
        root.after(100, _draw_preview)


        # ================================================================
        #DYNAMIC CROSSHAIR CARD (movement detection + screen sync)
        # ================================================================
        dyn_card = self._card(body, "DYNAMIC CROSSHAIR")
        tk.Label(dyn_card, text="Movement-reactive bloom & screen-synced rendering",
                 font=("Segoe UI", 8), fg=TEXT_DIM, bg=SURFACE).pack(
            anchor="w", padx=10, pady=(0, 4))

        xh_movement = tk.BooleanVar(
            value=bool(getattr(self.cfg.crosshair, "movement_detection", True)))
        ttk.Checkbutton(dyn_card, text="Movement detection (dynamic bloom)",
                        variable=xh_movement).pack(anchor="w", padx=10, pady=1)

        xh_screen_sync = tk.BooleanVar(
            value=bool(getattr(self.cfg.crosshair, "screen_sync", True)))
        ttk.Checkbutton(dyn_card, text="Screen sync (match monitor refresh rate)",
                        variable=xh_screen_sync).pack(anchor="w", padx=10, pady=1)

        xh_aim_pulse = tk.BooleanVar(
            value=bool(getattr(self.cfg.crosshair, "aim_sweep_pulse", True)))
        ttk.Checkbutton(dyn_card, text="Pulse on ADS aim sweep (manual input only)",
                        variable=xh_aim_pulse).pack(anchor="w", padx=10, pady=1)

        self._sep(dyn_card)

        # Bloom intensity
        xh_bloom = tk.DoubleVar(
            value=float(getattr(self.cfg.crosshair, "bloom_intensity", 1.0)))
        bloom_row = tk.Frame(dyn_card, bg=SURFACE)
        bloom_row.pack(fill="x", padx=10, pady=2)
        tk.Label(bloom_row, text="Bloom Intensity", font=("Segoe UI", 9),
                 fg=TEXT, bg=SURFACE).pack(side="left")
        bloom_val = tk.Label(bloom_row, text=f"{xh_bloom.get():.1f}",
                             font=("Consolas", 9, "bold"), fg=NEON, bg=SURFACE,
                             width=4, anchor="e")
        bloom_val.pack(side="right")
        ttk.Scale(dyn_card, from_=0.0, to=2.0, variable=xh_bloom,
                  orient="horizontal",
                  style="Green.Horizontal.TScale").pack(fill="x", padx=10)
        xh_bloom.trace_add("write", lambda *_: bloom_val.config(
            text=f"{xh_bloom.get():.1f}"))

        # Bloom max px
        xh_bloom_max = tk.DoubleVar(
            value=float(getattr(self.cfg.crosshair, "bloom_max_px", 20)))
        bmax_row = tk.Frame(dyn_card, bg=SURFACE)
        bmax_row.pack(fill="x", padx=10, pady=2)
        tk.Label(bmax_row, text="Max Bloom (px)", font=("Segoe UI", 9),
                 fg=TEXT, bg=SURFACE).pack(side="left")
        bmax_val = tk.Label(bmax_row, text=str(int(xh_bloom_max.get())),
                            font=("Consolas", 9, "bold"), fg=NEON, bg=SURFACE,
                            width=4, anchor="e")
        bmax_val.pack(side="right")
        ttk.Scale(dyn_card, from_=0, to=60, variable=xh_bloom_max,
                  orient="horizontal",
                  style="Green.Horizontal.TScale").pack(fill="x", padx=10)
        xh_bloom_max.trace_add("write", lambda *_: bmax_val.config(
            text=str(int(xh_bloom_max.get()))))

        # Recovery speed
        xh_recovery = tk.DoubleVar(
            value=float(getattr(self.cfg.crosshair, "recovery_speed", 6.0)))
        rec_row = tk.Frame(dyn_card, bg=SURFACE)
        rec_row.pack(fill="x", padx=10, pady=2)
        tk.Label(rec_row, text="Recovery Speed", font=("Segoe UI", 9),
                 fg=TEXT, bg=SURFACE).pack(side="left")
        rec_val = tk.Label(rec_row, text=f"{xh_recovery.get():.1f}",
                           font=("Consolas", 9, "bold"), fg=NEON, bg=SURFACE,
                           width=4, anchor="e")
        rec_val.pack(side="right")
        ttk.Scale(dyn_card, from_=1.0, to=20.0, variable=xh_recovery,
                  orient="horizontal",
                  style="Green.Horizontal.TScale").pack(fill="x", padx=10)
        xh_recovery.trace_add("write", lambda *_: rec_val.config(
            text=f"{xh_recovery.get():.1f}"))

        # ADS tighten
        xh_ads_tighten = tk.DoubleVar(
            value=float(getattr(self.cfg.crosshair, "ads_tighten", 0.4)))
        ads_row = tk.Frame(dyn_card, bg=SURFACE)
        ads_row.pack(fill="x", padx=10, pady=2)
        tk.Label(ads_row, text="ADS Tighten", font=("Segoe UI", 9),
                 fg=TEXT, bg=SURFACE).pack(side="left")
        ads_val = tk.Label(ads_row, text=f"{xh_ads_tighten.get():.2f}",
                           font=("Consolas", 9, "bold"), fg=NEON, bg=SURFACE,
                           width=4, anchor="e")
        ads_val.pack(side="right")
        ttk.Scale(dyn_card, from_=0.1, to=1.0, variable=xh_ads_tighten,
                  orient="horizontal",
                  style="Green.Horizontal.TScale").pack(fill="x", padx=10)
        xh_ads_tighten.trace_add("write", lambda *_: ads_val.config(
            text=f"{xh_ads_tighten.get():.2f}"))

        self._sep(dyn_card)

        # Move colour
        dyn_grid = tk.Frame(dyn_card, bg=SURFACE)
        dyn_grid.pack(fill="x", padx=10, pady=4)
        dyn_grid.columnconfigure(0, weight=1)
        dyn_grid.columnconfigure(1, weight=1)
        tk.Label(dyn_grid, text="Move Color (blank=off)", font=("Segoe UI", 8),
                 fg=TEXT_DIM, bg=SURFACE).grid(row=0, column=0, sticky="w")
        xh_move_color = tk.StringVar(
            value=str(getattr(self.cfg.crosshair, "move_color", "")))
        ttk.Combobox(dyn_grid, textvariable=xh_move_color,
                     values=[""] + list(COLORS), state="readonly",
                     width=10).grid(row=1, column=0, sticky="w", pady=2)
        tk.Label(dyn_grid, text="Color Shift Threshold", font=("Segoe UI", 8),
                 fg=TEXT_DIM, bg=SURFACE).grid(row=0, column=1, sticky="w", padx=(10, 0))
        xh_cs_thresh = tk.DoubleVar(
            value=float(getattr(self.cfg.crosshair, "color_shift_threshold", 0.3)))
        ttk.Scale(dyn_grid, from_=0.05, to=1.0, variable=xh_cs_thresh,
                  orient="horizontal",
                  style="Green.Horizontal.TScale").grid(
            row=1, column=1, sticky="ew", padx=(10, 0), pady=2)

        # ================================================================
        #OPTIONS CARD
        # ================================================================
        opt_card = self._card(body, "OPTIONS")
        swap_v = tk.BooleanVar(value=self.cfg.swap_abxy)
        hl_v = tk.BooleanVar(value=self.cfg.hair_trigger_left)
        hr_v = tk.BooleanVar(value=self.cfg.hair_trigger_right)
        hid_v = tk.BooleanVar(value=self.hid_mode)
        auto_game_v = tk.BooleanVar(value=False)

        ttk.Checkbutton(opt_card, text="Swap ABXY (Nintendo -> Xbox, REQUIRED)",
                        variable=swap_v).pack(anchor="w", padx=10, pady=1)
        ttk.Checkbutton(opt_card, text="Hair trigger LT",
                        variable=hl_v).pack(anchor="w", padx=10, pady=1)
        ttk.Checkbutton(opt_card, text="Hair trigger RT",
                        variable=hr_v).pack(anchor="w", padx=10, pady=1)
        self._sep(opt_card)
        ttk.Checkbutton(opt_card, text="HID mode (direct 057e:2069, bypass SDL)",
                        variable=hid_v).pack(anchor="w", padx=10, pady=(1, 6))
        ttk.Checkbutton(opt_card, text="Auto-start when COD is detected",
                        variable=auto_game_v).pack(anchor="w", padx=10, pady=(1, 6))

        self._sep(opt_card)
        tk.Label(opt_card, text="GYRO FOR BOTH STICKS", font=("Segoe UI", 9),
                 fg=TEXT, bg=SURFACE).pack(anchor="w", padx=10, pady=(2, 4))
        gyro_on_v = tk.BooleanVar(value=self.cfg.gyro_enabled)
        gyro_left_v = tk.BooleanVar(value=self.cfg.gyro_left_enabled)
        gyro_right_v = tk.BooleanVar(value=self.cfg.gyro_right_enabled)
        gyro_ads_v = tk.BooleanVar(value=self.cfg.gyro_ads_only)
        ttk.Checkbutton(opt_card, text="Turn gyro on", variable=gyro_on_v).pack(anchor="w", padx=10)
        ttk.Checkbutton(opt_card, text="Gyro moves left stick", variable=gyro_left_v).pack(anchor="w", padx=10)
        ttk.Checkbutton(opt_card, text="Gyro moves right stick", variable=gyro_right_v).pack(anchor="w", padx=10)
        ttk.Checkbutton(opt_card, text="Only use gyro while aiming", variable=gyro_ads_v).pack(anchor="w", padx=10)
        slider(opt_card, "Left-stick gyro strength", "gyro_left_sensitivity", 0.0, 2.0, fmt=".2f")
        slider(opt_card, "Right-stick gyro strength", "gyro_right_sensitivity", 0.0, 3.0, fmt=".2f")
        slider(opt_card, "Gyro deadzone", "gyro_deadzone", 0.0, 0.3, fmt=".2f")

        # ================================================================
        #  ACTION BUTTONS + STATUS
        # ================================================================
        act_frame = tk.Frame(body, bg=BG)
        act_frame.pack(fill="x", padx=14, pady=(10, 4))

        # START button - large neon
        start_btn = tk.Button(
            act_frame, text=">  Start controller", font=("Segoe UI", 10),
            fg=BG, bg=NEON, activeforeground=BG, activebackground=ACCENT2,
            bd=0, padx=18, pady=7, cursor="hand2", relief="flat")
        start_btn.pack(fill="x", pady=(0, 6))

        # STOP button - outlined
        stop_btn = tk.Button(
            act_frame, text="*  Stop", font=("Segoe UI", 9),
            fg=TEXT_DIM, bg=SURFACE, activeforeground=TEXT,
            activebackground=SURFACE2, bd=0, padx=16, pady=6,
            cursor="hand2", relief="flat",
            highlightbackground=BORDER, highlightthickness=1)
        stop_btn.pack(fill="x")

        # Hover effects
        def _hover_start(e):
            start_btn.config(bg=ACCENT2)

        def _leave_start(e):
            start_btn.config(bg=NEON)

        start_btn.bind("<Enter>", _hover_start)
        start_btn.bind("<Leave>", _leave_start)

        def _hover_stop(e):
            stop_btn.config(fg=ACCENT_ERR, highlightbackground=ACCENT_ERR)

        def _leave_stop(e):
            stop_btn.config(fg=TEXT_DIM, highlightbackground=BORDER)

        stop_btn.bind("<Enter>", _hover_stop)
        stop_btn.bind("<Leave>", _leave_stop)

        # -- status bar --------------------------------------------------
        status_bar = tk.Frame(body, bg=SURFACE2, height=32)
        status_bar.pack(fill="x", padx=14, pady=(8, 14))
        status_bar.pack_propagate(False)
        status_dot = tk.Canvas(status_bar, width=10, height=10, bg=SURFACE2,
                               highlightthickness=0)
        status_dot.pack(side="left", padx=(10, 6), pady=10)
        st_dot_id = status_dot.create_oval(1, 1, 9, 9, fill=TEXT_DIM, outline="")
        status = tk.Label(status_bar, text="Ready - press START to begin",
                          font=("Segoe UI", 8), fg=TEXT_DIM, bg=SURFACE2,
                          anchor="w")
        status.pack(side="left", fill="x", expand=True)
        _status_state = ["Ready - press START to begin", TEXT_DIM]

        def set_status(text: str, color: str = TEXT_DIM):
            if _status_state[0] == text and _status_state[1] == color:
                return
            _status_state[0] = text
            _status_state[1] = color
            status.config(text=text, fg=color)
            status_dot.itemconfig(st_dot_id, fill=color)

        game_was_detected = False

        def detected_game() -> str | None:
            """Return a supported running game name; no screen/gameplay inspection."""
            try:
                import subprocess
                raw = subprocess.check_output(
                    ["tasklist", "/fo", "csv", "/nh"],
                    text=True, stderr=subprocess.DEVNULL)
                names = {line.split(",", 1)[0].strip('"').lower()
                         for line in raw.splitlines() if line}
                cod_names = {
                    "cod.exe": "Call of Duty", "modernwarfare.exe": "Modern Warfare",
                    "modernwarfarelauncher.exe": "Modern Warfare",
                    "blackops6.exe": "Black Ops 6", "blackops7.exe": "Black Ops",
                    "warzone.exe": "Warzone",
                }
                for exe, title in cod_names.items():
                    if exe in names:
                        return title
            except Exception:
                return None
            return None

        # -- tick functions (same logic, styled) -------------------------
        def read_viz_axes():
            import pygame
            try:
                if self.runner is not None and getattr(self.runner, "running", False):
                    if hasattr(self.runner, "reader"):
                        st = getattr(self.runner, "latest_state", None)
                        if st is not None:
                            return (st.lx, st.ly, st.rx, st.ry,
                                    bool(st.buttons.get("ZL")))
                    else:
                        j = self.runner.joy
                        try:
                            lt, _ = self.runner.read_triggers()
                        except Exception:
                            lt = 0.0
                        return (j.get_axis(0) - self.runner.cx_l,
                                j.get_axis(1) - self.runner.cy_l,
                                j.get_axis(2) - self.runner.cx_r,
                                j.get_axis(3) - self.runner.cy_r,
                                lt > 0.2)
            except Exception:
                pass
            try:
                if viz_cache.get("hid") is None:
                    from switch2mod.hid_reader import HidReader
                    hr = HidReader()
                    viz_cache["hid"] = hr if hr.open() else False
                hr = viz_cache.get("hid")
                if hr:
                    st = hr.poll(timeout_ms=10)
                    if st is not None:
                        viz_cache["hid_ok"] = True
                        return (st.lx, st.ly, st.rx, st.ry,
                                bool(st.buttons.get("ZL")))
            except Exception:
                pass
            try:
                import pygame as pg
                try:
                    pg.joystick.init()
                except Exception:
                    pass
                idx, _ = ControllerDetector().find(prefer_wired=True,
                                                   index=self.index)
                if idx is None:
                    return None
                if viz_cache.get("idx") != idx or viz_cache.get("joy") is None:
                    try:
                        viz_cache["joy"] = pg.joystick.Joystick(idx)
                        viz_cache["joy"].init()
                        viz_cache["idx"] = idx
                    except Exception:
                        return None
                j = viz_cache["joy"]
                return (j.get_axis(0), j.get_axis(1),
                        j.get_axis(2), j.get_axis(3), False)
            except Exception:
                viz_cache["joy"] = None
                viz_cache["idx"] = None
                return None

        _glow_on = [True]

        def tick_connection():
            try:
                rep = ControllerDetector().full_report()
                infos = rep["sdl"]
                hid_pads = rep["hid"]
                r = self.runner
                mapped = bool(r is not None and getattr(r, "running", False)
                              and getattr(r, "connected", False))
                if hid_pads:
                    h = hid_pads[0]
                    if mapped:
                        color = NEON if _glow_on[0] else NEON_DIM
                        _glow_on[0] = not _glow_on[0]
                    else:
                        color = ACCENT_WARN
                    dot.itemconfig(dot_id, fill=color)
                    dot.itemconfig(glow_id, outline=color)
                    suffix = "  [LIVE]" if mapped else "  [press START]"
                    conn_label.config(
                        text=f"Controller connected: 057e:{h.pid:04x}  {h.bus}{suffix}",
                        fg=TEXT)
                    hid_badge.config(text=" HID ", bg=NEON, fg=BG)
                elif infos:
                    top = infos[0]
                    color = NEON if top.is_pro else ACCENT_WARN
                    dot.itemconfig(dot_id, fill=color)
                    dot.itemconfig(glow_id, outline=color)
                    conn_label.config(
                        text=f"{top.name[:32]}  |  {top.bus}  vid={top.vid}  pid={top.pid}",
                        fg=TEXT)
                    hid_badge.config(text=" SDL ", bg=NEON_DIM, fg=BG)
                else:
                    dot.itemconfig(dot_id, fill=ACCENT_ERR)
                    dot.itemconfig(glow_id, outline=ACCENT_ERR)
                    conn_label.config(
                        text="Controller disconnected - plug in via USB-C DATA cable",
                        fg=TEXT_DIM)
                    hid_badge.config(text="", bg=SURFACE)
            except Exception as e:
                dot.itemconfig(dot_id, fill=ACCENT_ERR)
                dot.itemconfig(glow_id, outline=ACCENT_ERR)
                conn_label.config(text=f"Detect error: {e}", fg=ACCENT_ERR)
            root.after(1000, tick_connection)

        # Sticks read from a background thread at controller-rate so the
        # Tk render loop never blocks waiting on HID.
        _viz_holder = {"lx": 0.0, "ly": 0.0, "rx": 0.0, "ry": 0.0,
                        "ads": False, "dead": False, "btns": {}}
        _capture_was_down = [False]
        _last_aim_pulse = [0.0]

        def _viz_reader():
            import pygame as pg
            from switch2mod.hid_reader import HidReader
            # Direct HID is authoritative for Switch 2: SDL exposes a generic
            # If_Hid pad that omits the real paddle/button layout.
            try:
                hr = HidReader()
                if hr.open():
                    _viz_holder["dead"] = None
                    while True:
                        state = hr.poll(timeout_ms=50)
                        if state is None:
                            time.sleep(0.002)
                            continue
                        _viz_holder.update(
                            lx=state.lx, ly=state.ly, rx=state.rx, ry=state.ry,
                            ads=bool(state.buttons.get("ZL")),
                            btns=dict(state.buttons), dead=False)
            except Exception:
                pass
            # SDL fallback for non-Switch controllers.
            try:
                pg.joystick.init()
                idx, _ = ControllerDetector().find(prefer_wired=True, index=self.index)
                if idx is None:
                    _viz_holder["dead"] = True
                    return
                pj = pg.joystick.Joystick(idx)
                pj.init()
                _viz_holder["dead"] = None
                while True:
                    pg.event.pump()
                    _viz_holder.update(
                        lx=pj.get_axis(0), ly=pj.get_axis(1),
                        rx=pj.get_axis(2) if pj.get_numaxes() > 2 else 0.0,
                        ry=pj.get_axis(3) if pj.get_numaxes() > 3 else 0.0,
                        ads=pj.get_button(11) if pj.get_numbuttons() > 11 else False,
                        dead=False)
                    time.sleep(0.002)
            except Exception:
                _viz_holder["dead"] = True

        _viz_t = threading.Thread(target=_viz_reader, daemon=True)
        _viz_t.start()

        def tick_sticks():
            try:
                import copy
                from switch2mod.sticks import process_sticks
                live = copy.deepcopy(self.cfg)
                for k, v in state.items():
                    try:
                        setattr(live, k, float(v.get()))
                    except Exception:
                        pass
                eff = live.apply_aim_dial()
                v = _viz_holder
                capture_down = bool(v.get("btns", {}).get("capture", False))
                if capture_down and not _capture_was_down[0] and self.overlay is not None:
                    # Manual Capture press is the mark/pulse action. This
                    # never identifies or tracks targets automatically.
                    self.overlay.pulse()
                _capture_was_down[0] = capture_down
                # Safe visual feedback: only actual ADS + right-stick motion,
                # never screen/target detection or automated aiming.
                if (getattr(self.cfg.crosshair, "aim_sweep_pulse", True)
                        and v.get("ads", False)
                        and math.hypot(v.get("rx", 0.0), v.get("ry", 0.0))
                        >= getattr(self.cfg.crosshair, "aim_pulse_threshold", 0.35)
                        and time.monotonic() - _last_aim_pulse[0]
                        >= getattr(self.cfg.crosshair, "aim_pulse_cooldown", 0.25)
                        and self.overlay is not None):
                    self.overlay.pulse(0.12)
                    _last_aim_pulse[0] = time.monotonic()
                if v["dead"]:
                    draw_stick(left_canvas, 0, 0, 0, 0, eff.left_deadzone)
                    draw_stick(right_canvas, 0, 0, 0, 0, eff.right_deadzone)
                    left_coord.config(text="0.00, 0.00")
                    right_coord.config(text="0.00, 0.00")
                    refresh_buttons({})
                else:
                    lx, ly, rx, ry = v.get("lx", 0.0), v.get("ly", 0.0), v.get("rx", 0.0), v.get("ry", 0.0)
                    ads = v.get("ads", False)
                    lx2, ly2, rx2, ry2 = process_sticks(eff, lx, ly, rx, ry,
                                                         ads_held=ads)
                    draw_stick(left_canvas, lx, ly, lx2, ly2, eff.left_deadzone)
                    # Display the processed stick coordinates directly. The
                    # profile's invert_y setting is already applied once by
                    # process_sticks; do not invert the GUI a second time.
                    draw_stick(right_canvas, rx, ry, rx2, ry2,
                               eff.right_deadzone, ads=ads)
                    left_coord.config(text=f"{lx2:+.2f}, {ly2:+.2f}")
                    right_coord.config(text=f"{rx2:+.2f}, {ry2:+.2f}")
                    refresh_buttons(v.get("btns", {}))
            except Exception:
                pass
            root.after(33, tick_sticks)

        def is_ads_held() -> bool:
            try:
                r = self.runner
                if r is not None and getattr(r, "running", False):
                    if hasattr(r, "reader"):
                        st = getattr(r, "latest_state", None)
                        return bool(st and st.buttons.get("ZL"))
                    if hasattr(r, "read_triggers"):
                        lt, _ = r.read_triggers()
                        return lt > 0.2
            except Exception:
                pass
            return False

        # -- actions -----------------------------------------------------
        def get_sticks():
            """Returns (lx, ly, rx, ry) from controller for crosshair bloom."""
            data = read_viz_axes()
            if data is not None:
                return (data[0], data[1], data[2], data[3])
            return None

        def _close_test_overlay() -> None:
            try:
                old = getattr(self, "_test_ov", None)
                if old is not None:
                    old.close()
                    self._test_ov = None
            except Exception:
                pass

        def _read_panel_into_cfg() -> None:
            """Push every widget into cfg + profile. Paddles are locked."""
            for k, v in state.items():
                try:
                    setattr(self.cfg, k, float(v.get()))
                except Exception:
                    pass

        def _rear_summary() -> str:
            rm = self.cfg.rear_map
            return (f"GL->{rm.gl_as} GR->{rm.gr_as} "
                    f"C->{rm.c_as} CAP->{rm.capture_as}")

        def on_start():
            _read_panel_into_cfg()
            if self.profile_path:
                try:
                    self.cfg.save(self.profile_path)
                except Exception:
                    pass
            if self.runner is not None and getattr(self.runner, "running", False):
                set_status(f"Already running ({_rear_summary()})", ACCENT_WARN)
                return
            # Never start over a zombie: a leftover thread still holding the
            # HID device is exactly why a second START used to do nothing.
            if self.runner_thread and self.runner_thread.is_alive():
                self.runner_thread.join(timeout=2.0)
            self.runner_thread = None
            self.runner = None
            start_btn.config(state="disabled", text="...  STARTING")
            stop_btn.config(state="normal")
            self.cfg.swap_abxy = bool(swap_v.get())
            self.cfg.hair_trigger_left = bool(hl_v.get())
            self.cfg.hair_trigger_right = bool(hr_v.get())
            self.cfg.gyro_enabled = bool(gyro_on_v.get())
            self.cfg.gyro_left_enabled = bool(gyro_left_v.get())
            self.cfg.gyro_right_enabled = bool(gyro_right_v.get())
            self.cfg.gyro_ads_only = bool(gyro_ads_v.get())
            for key in ("gyro_left_sensitivity", "gyro_right_sensitivity", "gyro_deadzone"):
                setattr(self.cfg, key, float(state[key].get()))
            if self.wired:
                self.cfg.wired_mode = True
                self.cfg.polling_hz = 1000
            ch = _current_crosshair()
            ch.enabled = bool(xh_on.get())
            if ch.aim_sweep_pulse and not ch.enabled:
                # Pulse needs a surface: auto-enable the overlay so the
                # toggle visibly does something instead of silently nothing.
                ch.enabled = True
                try:
                    xh_on.set(True)
                except Exception:
                    pass
                set_status("Crosshair auto-enabled (required for ADS pulse)", NEON)
            self.cfg.crosshair = ch
            if self.profile_path:
                self.cfg.save(self.profile_path)
            try:
                if self.overlay:
                    self.overlay.close()
                    self.overlay = None
            except Exception:
                pass
            _close_test_overlay()
            if ch.enabled:
                self.overlay = CrosshairOverlay(ch, is_ads_held=is_ads_held,
                                                get_sticks=get_sticks)
                if self.overlay.show():
                    self.overlay.set_locked(bool(xh_lock.get()))
                else:
                    self.overlay = None
                    set_status("Crosshair failed to create; use borderless/windowed mode",
                               ACCENT_ERR)
            use_hid = bool(hid_v.get())
            try:
                if use_hid:
                    from switch2mod.hid_mapper import HidProToXInput
                    self.runner = HidProToXInput(self.cfg)
                    if getattr(self.runner, "pad", None) is None:
                        set_status("Started - waiting: ViGEmBus driver missing "
                                   "(click INSTALL DRIVER). Controller input is live.",
                                   ACCENT_WARN)
                    elif not getattr(self.runner, "connected", False):
                        set_status("Started - waiting for controller (plug in USB-C)",
                                   ACCENT_WARN)
                else:
                    idx, _ = ControllerDetector().find(prefer_wired=True,
                                                       index=self.index)
                    if idx is None:
                        set_status("No SDL pad - tick HID mode or use --hid-calibrate",
                                   ACCENT_ERR)
                        start_btn.config(state="normal", text=">  Start controller")
                        stop_btn.config(state="disabled")
                        return
                    self.runner = ProToXInput(self.cfg, idx)
            except Exception as e:
                set_status(f"Start failed: {e}", ACCENT_ERR)
                self.runner = None
                start_btn.config(state="normal", text=">  Start controller")
                stop_btn.config(state="disabled")
                return
            g = getattr(self.cfg, "game", "cod").upper()
            bloom_s = "ON" if ch.movement_detection else "OFF"
            sync_s = "ON" if ch.screen_sync else "OFF"
            set_status(f"Running  [{g}]AIM {self.cfg.aim_assist:.0f}  "
                       f"HID={'ON' if use_hid else 'OFF'}  "
                       f"BLOOM={bloom_s}  SYNC={sync_s}  {_rear_summary()}", NEON)
            self.runner_thread = threading.Thread(target=self.runner.run,
                                                  name="switch2mod-runner",
                                                  daemon=True)
            self.runner_thread.start()
            # Real indicator: toast driven by live mapper telemetry
            try:
                if getattr(self, "toast", None):
                    self.toast.close()
                from switch2mod.status_toast import StatusToast
                self.toast = StatusToast(
                    root,
                    is_alive=lambda: (self.runner_thread is not None
                                      and self.runner_thread.is_alive()),
                    is_receiving=lambda: (
                        self.runner is not None
                        and time.monotonic() - getattr(
                            self.runner, "last_input_at", 0.0) < 0.75),
                    report_rate=lambda: getattr(
                        self.runner, "n_reports", 0))
            except Exception as e:
                log.warning("toast failed: %s", e)
            start_btn.config(text="*  Controller active", state="disabled")
            if ch.enabled and self.overlay is not None and self.overlay.win is not None:
                set_status("Healthy - aim tuning + controller + crosshair active", NEON)

        def on_stop():
            r = self.runner
            if r:
                r.running = False
            try:
                if getattr(self, "toast", None):
                    self.toast.close()
                    self.toast = None
            except Exception:
                pass
            if self.runner_thread and self.runner_thread.is_alive():
                self.runner_thread.join(timeout=2.0)
            # Force teardown even if the thread lagged: frees HID + virtual pad
            # so the next START gets a clean device, not a zombie fight.
            try:
                if r:
                    r.close()
            except Exception:
                pass
            self.runner_thread = None
            self.runner = None
            try:
                if self.overlay:
                    self.overlay.hide()
            except Exception:
                pass
            set_status("Stopped - press START to run again", ACCENT_WARN)
            start_btn.config(state="normal", text=">  Start controller")
            stop_btn.config(state="disabled")

        def tick_watchdog():
            """Monitor the local controller pipeline without inspecting gameplay."""
            nonlocal game_was_detected
            game = detected_game()
            if game and not game_was_detected:
                game_was_detected = True
                if auto_game_v.get() and self.runner is None:
                    set_status(f"{game} detected - starting controller", NEON)
                    root.after(50, on_start)
                elif self.runner is None:
                    set_status(f"{game} detected - press Start controller", NEON)
            elif not game and game_was_detected:
                game_was_detected = False
                if self.runner is not None:
                    on_stop()
                else:
                    set_status("Game closed - controller ready", TEXT_DIM)
            if self.watchdog_enabled and self.runner is not None:
                import time
                alive = bool(self.runner_thread and self.runner_thread.is_alive())
                receiving = time.monotonic() - getattr(
                    self.runner, "last_input_at", 0.0) < 1.5
                overlay_ok = not self.cfg.crosshair.enabled or bool(
                    self.overlay and self.overlay.win)
                if not alive:
                    set_status("Watchdog: mapper stopped unexpectedly", ACCENT_ERR)
                    self.runner = None
                    self.runner_thread = None
                    start_btn.config(state="normal", text=">  Start controller")
                    stop_btn.config(state="disabled")
                elif not receiving:
                    set_status("Watchdog: waiting for controller input", ACCENT_WARN)
                elif not overlay_ok:
                    set_status("Watchdog: crosshair overlay unavailable", ACCENT_WARN)
                else:
                    set_status("Healthy - controller input - virtual pad - crosshair", NEON)
            refresh_proof()
            root.after(500, tick_watchdog)

        start_btn.config(command=on_start)
        stop_btn.config(command=on_stop)
        stop_btn.config(state="disabled")

        # -- go ----------------------------------------------------------
        tick_connection()
        tick_sticks()
        tick_watchdog()
        root.mainloop()
