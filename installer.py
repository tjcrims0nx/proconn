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
        threading.Thread(target=self._install, daemon=True).start()

    def _install(self) -> None:
        try:
            bundle = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "payload"
            source = bundle / "Switch2ProMod"
            install_dir = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Switch2ProMod"
            if not source.exists():
                raise RuntimeError(f"Payload missing: {source}")
            self._set_progress("Preparing installation", "Checking bundled runtime...", 0.02)
            if install_dir.exists():
                self._set_progress("Removing previous version", "Cleaning the old installation...", 0.08)
                shutil.rmtree(install_dir)
            files = [p for p in source.rglob("*") if p.is_file()]
            total = max(1, len(files))
            for n, src in enumerate(files, 1):
                if self.cancel_event.is_set():
                    return
                dst = install_dir / src.relative_to(source)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                self._set_progress("Installing runtime",
                                   f"Copying {src.name} ({n}/{total})",
                                   0.10 + 0.78 * n / total)
            exe = install_dir / "Switch2ProMod.exe"
            shortcut = (Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" /
                        "Start Menu" / "Programs" / "Switch 2 Pro Mod.lnk")
            shortcut.parent.mkdir(parents=True, exist_ok=True)
            ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{shortcut}');"
                  "$s.TargetPath='{exe}';$s.WorkingDirectory='{wd}';$s.Save()")
            ps = ps.format(shortcut=shortcut, exe=exe, wd=install_dir)
            self._set_progress("Creating shortcuts", "Adding Start Menu shortcut...", 0.94)
            subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                            "-Command", ps], check=False,
                           creationflags=subprocess.CREATE_NO_WINDOW)
            self._set_progress("Finalizing", "Installation complete.", 1.0)
            self.root.after(0, self._finished)
        except Exception as e:
            self.root.after(0, lambda: self._failed(str(e)))

    def _set_progress(self, title: str, detail: str, percent: float) -> None:
        def update():
            if not self.root.winfo_exists():
                return
            self.percent = max(0.0, min(1.0, percent))
            self.status.config(text=title)
            self.detail.config(text=detail)
        self.root.after(0, update)

    def _finished(self) -> None:
        self.done = True
        self.status.config(text="Installation complete", fg=NEON)
        self.detail.config(text="Switch 2 Pro Mod is ready")
        self.button.config(state="normal", text="LAUNCH", command=self.launch)

    def _failed(self, error: str) -> None:
        self.running = False
        self.status.config(text="Installation failed", fg=WARN)
        self.detail.config(text=error[:90])
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
