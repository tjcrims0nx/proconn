"""Themed one-file installer for Switch2ProMod."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path

BG = "#00100f"
PANEL = "#06221d"
PANEL2 = "#0a3028"
NEON = "#12f5a0"
GLOW = "#087b59"
GLOW_DARK = "#064a39"
TEXT = "#effff8"
DIM = "#86a79c"
WARN = "#ffc56b"
LOG_PATH = Path(os.environ.get("TEMP", str(Path.home()))) / "Switch2ProMod-install.log"


def log_line(msg: str) -> None:
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


class Installer:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Switch 2 Pro Mod Setup")
        self.root.geometry("600x470")
        self.root.resizable(False, False)
        self.root.configure(bg=BG)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.running = False
        self.done = False
        self.angle = 0
        self.percent = 0.0
        self.cancel_event = threading.Event()
        self._build()
        self._animate()

    def _build(self) -> None:
        tk.Frame(self.root, bg=NEON, height=3).pack(fill="x")
        tk.Label(self.root, text="SWITCH 2 PRO MOD", font=("Segoe UI", 20, "bold"),
                 fg=NEON, bg=BG).pack(pady=(24, 2))
        tk.Label(self.root, text="Professional controller tuning for Windows",
                 font=("Segoe UI", 10), fg=DIM, bg=BG).pack()

        self.canvas = tk.Canvas(self.root, width=300, height=210, bg=BG,
                                highlightthickness=0)
        self.canvas.pack(pady=18)
        self.status = tk.Label(self.root, text="Ready to install", font=("Segoe UI", 11),
                               fg=TEXT, bg=BG)
        self.status.pack()
        self.detail = tk.Label(self.root, text="", font=("Consolas", 8),
                               fg=DIM, bg=BG)
        self.detail.pack(pady=5)
        self.button = tk.Button(self.root, text="INSTALL", command=self.start,
                                font=("Segoe UI", 11, "bold"), fg=BG, bg=NEON,
                                activebackground="#7affc2", relief="flat", bd=0,
                                padx=34, pady=9, cursor="hand2")
        self.button.pack(pady=14)
        self.close_button = tk.Button(self.root, text="CLOSE", command=self.close,
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
            source = bundle / "Switch2ProMod"
            self._install_dir = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Switch2ProMod"
            if not source.exists():
                raise RuntimeError(f"Payload missing: {source}")
            self._pending = [(p, self._install_dir / p.relative_to(source))
                             for p in source.rglob("*") if p.is_file()]
            self._pending_total = max(1, len(self._pending))
            self._pending_done = 0
            log_line(f"payload files: {self._pending_total} -> {self._install_dir}")
            if self._install_dir.exists():
                self._set_progress("Removing previous version",
                                   "Cleaning the old installation...", 0.05)
                shutil.rmtree(self._install_dir)
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
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
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
                        "Start Menu" / "Programs" / "Switch 2 Pro Mod.lnk")
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
        self.status.config(text="Installation complete", fg=NEON)
        self.detail.config(text="Switch 2 Pro Mod is ready")
        self.button.config(state="normal", text="LAUNCH", command=self.launch)

    def _failed(self, error: str) -> None:
        self.running = False
        log_line("FAILED: " + error)
        self.status.config(text="Installation failed", fg=WARN)
        self.detail.config(text=(error[:70] + "  (log: %TEMP%\\Switch2ProMod-install.log)"))
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
