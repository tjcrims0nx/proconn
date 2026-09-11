"""Small Windows installer wrapper for the onedir Switch2ProMod build."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    if os.name != "nt":
        print("Windows installer only.")
        return 1

    bundle = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "payload"
    source = bundle / "Switch2ProMod"
    install_dir = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Switch2ProMod"
    if not source.exists():
        print(f"Installer payload missing: {source}")
        return 1

    install_dir.parent.mkdir(parents=True, exist_ok=True)
    if install_dir.exists():
        shutil.rmtree(install_dir)
    shutil.copytree(source, install_dir)

    exe = install_dir / "Switch2ProMod.exe"
    shortcut = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Switch 2 Pro Mod.lnk"
    shortcut.parent.mkdir(parents=True, exist_ok=True)
    ps = (
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{shortcut}');"
        "$s.TargetPath='{exe}';$s.WorkingDirectory='{wd}';$s.Save()"
    ).format(shortcut=shortcut, exe=exe, wd=install_dir)
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                   check=False, creationflags=subprocess.CREATE_NO_WINDOW)
    os.startfile(exe)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
