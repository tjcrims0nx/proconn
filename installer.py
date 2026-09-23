"""Themed one-file installer for Switch2ProMod."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path

BG = "#0b1117"
PANEL = "#121b24"
PANEL2 = "#192633"
NEON = "#6ee7b7"
GLOW = "#38bdf8"
GLOW_DARK = "#263746"
TEXT = "#edf4f8"
DIM = "#8fa3b2"
WARN = "#fbbf75"
LOG_PATH = Path(os.environ.get("TEMP", str(Path.home()))) / "ProConn-install.log"


def log_line(msg: str) -> None:
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


class Installer:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("ProConn Setup")
        self.root.geometry("680x560")
        self.root.resizable(False, False)
        self.root.configure(bg=BG)
        icon = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "assets" / "proconn.ico"
        if icon.exists():
            try:
                self.root.iconbitmap(str(icon))
            except Exception:
                pass
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.running = False
        self.done = False
        self.angle = 0
        self.percent = 0.0
        self.cancel_event = threading.Event()
        self._build()
        self._animate()

    def _build(self) -> None:
        tk.Frame(self.root, bg=NEON, height=2).pack(fill="x")
        hero = tk.Frame(self.root, bg=BG)
        hero.pack(fill="x", padx=30, pady=(22, 8))
        logo_path = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "assets" / "logo.png"
        try:
            image = tk.PhotoImage(file=str(logo_path))
            factor = max(1, image.width() // 92)
            self.logo_image = image.subsample(factor, factor)
            tk.Label(hero, image=self.logo_image, bg=BG).pack(side="left", padx=(0, 16))
        except Exception as e:
            log_line("logo load: " + str(e))
        hero_copy = tk.Frame(hero, bg=BG)
        hero_copy.pack(side="left", anchor="center")
        tk.Label(hero_copy, text="PROCONN", font=("Segoe UI", 22, "bold"),
                 fg=TEXT, bg=BG).pack(anchor="w")
        tk.Label(hero_copy, text="Controller connectivity platform",
                 font=("Segoe UI", 10), fg=DIM, bg=BG).pack(anchor="w")
        tk.Label(hero, text="SETUP", font=("Consolas", 8, "bold"),
                 fg=NEON, bg=PANEL2, padx=9, pady=5).pack(side="right", anchor="n")

        panel = tk.Frame(self.root, bg=PANEL, highlightthickness=1,
                         highlightbackground="#263746")
        panel.pack(fill="both", expand=True, padx=30, pady=(8, 16))
        tk.Label(panel, text="INSTALLATION STATUS", font=("Consolas", 8, "bold"),
                 fg=DIM, bg=PANEL).pack(anchor="w", padx=20, pady=(14, 0))
        self.canvas = tk.Canvas(panel, width=300, height=210, bg=PANEL,
                                highlightthickness=0)
        self.canvas.pack(pady=8)
        self.status = tk.Label(panel, text="Ready to install", font=("Segoe UI", 11),
                               fg=TEXT, bg=PANEL)
        self.status.pack()
        self.detail = tk.Label(panel, text="", font=("Consolas", 8),
                               fg=DIM, bg=PANEL)
        self.detail.pack(pady=5)
        self.button = tk.Button(panel, text="INSTALL", command=self.start,
                                font=("Segoe UI", 11, "bold"), fg=BG, bg=NEON,
                                activebackground="#a7f3d0", relief="flat", bd=0,
                                padx=34, pady=9, cursor="hand2")
        self.button.pack(pady=14)
        self.close_button = tk.Button(panel, text="CLOSE", command=self.close,
                                      font=("Segoe UI", 8), fg=DIM, bg=BG,
                                      activeforeground=TEXT, activebackground=BG,
                                      relief="flat", bd=0, cursor="hand2")
        self.close_button.pack()

    def _animate(self) -> None:
        self.canvas.delete("all")
        cx, cy = 150, 100
        # Slow fluid ring: progress grows clockwise; small highlight rotates.
        self.canvas.create_oval(65, 15, 235, 185, outline=GLOW_DARK, width=18)
        self.canvas.create_oval(65, 15, 235, 185, outline=GLOW, width=11)
        self.canvas.create_oval(65, 15, 235, 185, outline=PANEL2, width=8)
        self.canvas.create_arc(65, 15, 235, 185, start=-90,
                              extent=max(1, self.percent * 360),
                              outline=GLOW, width=12, style="arc")
        self.canvas.create_arc(65, 15, 235, 185, start=-90,
                              extent=max(1, self.percent * 360),
                              outline=NEON, width=6, style="arc")
        self.canvas.create_arc(65, 15, 235, 185, start=self.angle,
                              extent=30, outline="#7affc2", width=4, style="arc")
        self.canvas.create_text(cx, cy, text=f"{int(self.percent * 100)}%",
                                fill=TEXT, font=("Segoe UI", 18, "bold"))
        wave = []
        for x in range(95, 206, 3):
            y = cy + 34 + 4 * __import__("math").sin((x + self.angle * 2) / 18)
            wave.extend((x, y))
        if wave:
            self.canvas.create_line(*wave, fill=NEON, width=2, smooth=True)
        self.angle = (self.angle + 2) % 360
        if self.root.winfo_exists():
            self.root.after(70, self._animate)

    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self.cancel_event.clear()
        self.button.config(state="disabled", text="INSTALLING...")
        # Build the copy queue on the main thread (fast), then copy in
        # small main-thread chunks so progress + animation stay live.
        # Tkinter widgets must only be touched from the main thread.
        try:
            bundle = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "payload"
            # PyInstaller --add-data "dist/Switch2ProMod;payload" copies the
            # FOLDER CONTENTS into payload/ (no nested Switch2ProMod dir),
            # but tolerate both layouts.
            nested = bundle / "Switch2ProMod"
            if (nested / "Switch2ProMod.exe").exists():
                source = nested
            elif (bundle / "Switch2ProMod.exe").exists():
                source = bundle
            else:
                raise RuntimeError(f"Payload missing: {bundle}")
            self._install_dir = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Switch2ProMod"
            self._pending = [(p, self._install_dir / p.relative_to(source))
                             for p in source.rglob("*") if p.is_file()]
            self._pending_total = max(1, len(self._pending))
            self._pending_done = 0
            log_line(f"payload files: {self._pending_total} -> {self._install_dir}")
            if self._install_dir.exists():
                self._set_progress("Removing previous version",
                                   "Closing old app and cleaning...", 0.05)
                try:
                    subprocess.run(["taskkill", "/F", "/IM", "Switch2ProMod.exe"],
                                   capture_output=True, timeout=15,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
                except Exception as e:
                    log_line("taskkill: " + str(e))
                try:
                    shutil.rmtree(self._install_dir)
                except Exception as e:
                    # Locked files (missed process): fall through and
                    # overwrite per-file in the copy loop instead.
                    log_line("rmtree failed, overwriting in place: " + str(e))
            self._set_progress("Installing runtime", "Starting file copy...", 0.08)
            self.root.after(30, self._copy_chunk)
        except Exception as e:
            self._failed(str(e))

    def _copy_chunk(self) -> None:
        # Copy up to 12 files per UI tick: keeps animation + percent smooth.
        try:
            if self.cancel_event.is_set():
                self.running = False
                log_line("cancelled by user")
                self.status.config(text="Installation cancelled", fg=WARN)
                self.button.config(state="normal", text="RETRY", command=self.start)
                return
            for _ in range(12):
                if not self._pending:
                    break
                src, dst = self._pending.pop(0)
                try:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                except Exception as e:
                    # Locked file (app still running): record and continue so
                    # one stuck file can't fail the whole install.
                    log_line(f"skip locked {dst.name}: {e}")
                    self._skipped = getattr(self, "_skipped", [])
                    self._skipped.append(dst.name)
                self._pending_done += 1
            frac = self._pending_done / self._pending_total
            self._set_progress("Installing runtime",
                               f"Copying files ({self._pending_done}/{self._pending_total})",
                               0.10 + 0.78 * frac)
            if self._pending:
                self.root.after(10, self._copy_chunk)
                return
            self._make_shortcut()
        except Exception as e:
            self._failed(str(e))

    def _make_shortcut(self) -> None:
        try:
            exe = self._install_dir / "Switch2ProMod.exe"
            shortcut = (Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" /
                        "Start Menu" / "Programs" / "ProConn.lnk")
            shortcut.parent.mkdir(parents=True, exist_ok=True)
            ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{shortcut}');"
                  "$s.TargetPath='{exe}';$s.WorkingDirectory='{wd}';$s.Save()")
            ps = ps.format(shortcut=shortcut, exe=exe, wd=self._install_dir)
            self._set_progress("Creating shortcuts", "Adding Start Menu shortcut...", 0.94)
            subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                            "-Command", ps], check=False,
                           creationflags=subprocess.CREATE_NO_WINDOW)
            self._set_progress("Finalizing", "Installation complete.", 1.0)
            self.root.after(250, self._finished)
        except Exception as e:
            self._failed(str(e))

    def _install(self) -> None:
        # Legacy entry point kept for compatibility; the chunked main-thread
        # installer above is now used instead.
        self.root.after(0, self.start)

    def _set_progress(self, title: str, detail: str, percent: float) -> None:
        if not self.root.winfo_exists():
            return
        self.percent = max(0.0, min(1.0, percent))
        self.status.config(text=title)
        self.detail.config(text=detail)

    def _finished(self) -> None:
        self.done = True
        skipped = getattr(self, "_skipped", [])
        if skipped:
            self.status.config(text="Installed - close the app and retry for skipped files", fg=WARN)
            self.detail.config(text="Skipped (in use): " + ", ".join(skipped[:4]))
            log_line("skipped: " + ", ".join(skipped))
        else:
            self.status.config(text="Installation complete", fg=NEON)
        self.detail.config(text="ProConn is ready")
        self.button.config(state="normal", text="LAUNCH", command=self.launch)

    def _failed(self, error: str) -> None:
        self.running = False
        log_line("FAILED: " + error)
        self.status.config(text="Installation failed", fg=WARN)
        self.detail.config(text=(error[:70] + "  (log: %TEMP%\\ProConn-install.log)"))
        self.button.config(state="normal", text="RETRY", command=self.start)

    def launch(self) -> None:
        path = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Switch2ProMod" / "Switch2ProMod.exe"
        if path.exists():
            subprocess.Popen([str(path), "--hid", "--gui"], cwd=str(path.parent))
            self.root.destroy()

    def close(self) -> None:
        self.cancel_event.set()
        self.running = False
        try:
            self.root.destroy()
        except Exception:
            pass

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    Installer().run()
