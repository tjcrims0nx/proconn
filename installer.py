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
TEXT = "#effff8"
DIM = "#86a79c"
WARN = "#ffc56b"


class Installer:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Switch 2 Pro Mod Setup")
        self.root.geometry("560x430")
        self.root.resizable(False, False)
        self.root.configure(bg=BG)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.running = False
        self.done = False
        self.angle = 0
        self._build()
        self._animate()

    def _build(self) -> None:
        tk.Frame(self.root, bg=NEON, height=3).pack(fill="x")
        tk.Label(self.root, text="SWITCH 2 PRO MOD", font=("Segoe UI", 20, "bold"),
                 fg=NEON, bg=BG).pack(pady=(24, 2))
        tk.Label(self.root, text="Professional controller tuning for Windows",
                 font=("Segoe UI", 10), fg=DIM, bg=BG).pack()

        self.canvas = tk.Canvas(self.root, width=210, height=150, bg=BG,
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

    def _animate(self) -> None:
        self.canvas.delete("all")
        cx, cy = 105, 75
        # Fluid neon ring: moving arcs and a liquid-like inner wave.
        self.canvas.create_oval(38, 8, 172, 142, outline=PANEL2, width=10)
        self.canvas.create_arc(38, 8, 172, 142, start=self.angle,
                              extent=105, outline=NEON, width=8, style="arc")
        self.canvas.create_arc(38, 8, 172, 142, start=self.angle + 180,
                              extent=55, outline="#0a8f68", width=4, style="arc")
        wave = []
        for x in range(65, 146, 4):
            y = cy + 9 * __import__("math").sin((x + self.angle * 2) / 13)
            wave.extend((x, y))
        if wave:
            self.canvas.create_line(*wave, fill=NEON, width=3, smooth=True)
        self.angle = (self.angle + 8) % 360
        if self.root.winfo_exists():
            self.root.after(32, self._animate)

    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self.button.config(state="disabled", text="INSTALLING...")
        threading.Thread(target=self._install, daemon=True).start()

    def _install(self) -> None:
        try:
            bundle = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "payload"
            source = bundle / "Switch2ProMod"
            install_dir = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Switch2ProMod"
            if not source.exists():
                raise RuntimeError(f"Payload missing: {source}")
            self._set("Preparing installation", "Checking bundled runtime...")
            if install_dir.exists():
                shutil.rmtree(install_dir)
            self._set("Installing runtime", "Copying Python, HID, and virtual-pad components...")
            shutil.copytree(source, install_dir)
            exe = install_dir / "Switch2ProMod.exe"
            shortcut = (Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" /
                        "Start Menu" / "Programs" / "Switch 2 Pro Mod.lnk")
            shortcut.parent.mkdir(parents=True, exist_ok=True)
            ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{shortcut}');"
                  "$s.TargetPath='{exe}';$s.WorkingDirectory='{wd}';$s.Save()")
            ps = ps.format(shortcut=shortcut, exe=exe, wd=install_dir)
            subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                            "-Command", ps], check=False,
                           creationflags=subprocess.CREATE_NO_WINDOW)
            self.root.after(0, self._finished)
        except Exception as e:
            self.root.after(0, lambda: self._failed(str(e)))

    def _set(self, title: str, detail: str) -> None:
        self.root.after(0, lambda: (self.status.config(text=title),
                                    self.detail.config(text=detail)))

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
        if not self.running or self.done:
            self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    Installer().run()
