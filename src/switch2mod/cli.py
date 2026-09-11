"""CLI - thin orchestration layer. Commands: list / calibrate / run / gui."""
from __future__ import annotations

import argparse
import logging
import sys
import time
import subprocess
from pathlib import Path

import pygame

from switch2mod.config import AppConfig
from switch2mod.detection import ControllerDetector, NoControllerError
from switch2mod.logging_setup import setup_logging
from switch2mod.mapper import ProToXInput

log = logging.getLogger("switch2mod.cli")


def cmd_list() -> int:
    det = ControllerDetector()
    rep = det.full_report()
    infos = rep["sdl"]  # type: ignore
    hid_pads = rep["hid"]  # type: ignore
    print("=== SDL PADS ===" if infos else "No SDL pads.")
    for c in infos:
        print(" ", c.label())
    print("=== HID PADS (direct, catches Switch 2 Pro 057e:2069) ===" if hid_pads else "No Nintendo HID pads.")
    for h in hid_pads:
        print(" ", h.label())  # type: ignore
    print(f"Hint: {rep['hint']}")
    print(f"SDL: {pygame.get_sdl_version()}")
    return 0


def cmd_calibrate(index: int | None) -> int:
    pygame.init()
    det = ControllerDetector()
    rep = det.full_report()
    for c in rep["sdl"]:  # type: ignore
        print(" ", c.label())  # type: ignore
    sdl_pro = any(c.is_pro for c in rep["sdl"])  # type: ignore
    # Switch 2 Pro 2069 is hidden from SDL - route straight to live HID mode
    if not sdl_pro and rep["hid"]:
        print("SDL has no Switch Pro, but HID found 057e:2069 - switching to live HID calibration.")
        return cmd_hid_calibrate()
    idx, _ = det.find(prefer_wired=True, index=index)
    if idx is None:
        print("No SDL controller. WIRED: DATA cable + rear USB. WIRELESS: hold Pair.")
        print("TIP: SDL hides Switch 2 Pro 2069 - use --hid-calibrate for direct HID mode.")
        return 1
    j = pygame.joystick.Joystick(idx)
    j.init()
    print(f"Using [{idx}]: {j.get_name()} axes={j.get_numaxes()} btns={j.get_numbuttons()}")
    print("Drift check 3s (don't touch)...")
    samples = []
    for _ in range(60):
        pygame.event.pump()
        samples.append([j.get_axis(a) for a in range(min(4, j.get_numaxes()))])
        time.sleep(0.05)
    avg = [sum(c[i] for c in samples) / len(samples) for i in range(len(samples[0]))]
    print(f"Center L({avg[0]:+.3f},{avg[1]:+.3f}) R({avg[2]:+.3f},{avg[3]:+.3f})")
    print("Live map Ctrl+C to exit.")
    try:
        while True:
            pygame.event.pump()
            axes = [round(j.get_axis(a), 3) for a in range(j.get_numaxes())]
            btns = [i for i in range(j.get_numbuttons()) if j.get_button(i)]
            print(f"axes={axes} pressed={btns}   ", end="\r")
            time.sleep(0.05)
    except KeyboardInterrupt:
        print("\nDone.")
    return 0


def cmd_hid_calibrate() -> int:
    from switch2mod.hid_reader import HidReader
    r = HidReader()
    if not r.open():
        print("HID open failed. Plug USB-C DATA cable to rear USB.")
        print("If silent: enable once via https://handheldlegend.github.io/procon2tool/ then retry.")
        return 1
    print("HID 057e:2069 open. Move sticks + press buttons. Ctrl+C to exit.")
    print("If silent (no lines): press pad buttons; if still silent enable via procon2tool WebUSB.")
    try:
        n = 0
        while True:
            st = r.poll(timeout_ms=50)
            if st is None:
                print("waiting for HID reports... (press buttons/sticks)      ", end="\r")
                continue
            n += 1
            pressed = sorted([k for k, v in st.buttons.items() if v])
            print(f"#{st.frame:03d} L({st.lx:+.2f},{st.ly:+.2f}) R({st.rx:+.2f},{st.ry:+.2f}) "
                  f"btns={pressed} raw={st.raw_hex}   ", end="\r")
            if n % 20 == 0:
                print()
    except KeyboardInterrupt:
        print("\nDone.")
    finally:
        r.close()
    return 0


GAME_PROFILES = {"cod": "cod_profile.json", "destiny2": "destiny2_profile.json", "d2": "destiny2_profile.json"}

COD_PROCESS_NAMES = {"cod.exe", "modernwarfare.exe", "modernwarfarelauncher.exe",
                     "blackops6.exe", "blackops7.exe", "warzone.exe"}


def _game_running() -> bool:
    try:
        raw = subprocess.check_output(["tasklist", "/fo", "csv", "/nh"],
                                      text=True, stderr=subprocess.DEVNULL)
        names = {line.split(",", 1)[0].strip('"').lower()
                 for line in raw.splitlines() if line}
        return bool(names & COD_PROCESS_NAMES)
    except Exception:
        return False


def cmd_watch_game(args) -> int:
    """Keep no overlay open until COD is actually running."""
    print("Waiting for Call of Duty... (Ctrl+C to stop)")
    while not _game_running():
        time.sleep(1.0)
    print("Call of Duty detected. Launching controller GUI.")
    profile = args.profile or GAME_PROFILES.get(args.game, "cod_profile.json")
    cfg = AppConfig.load(profile)
    from switch2mod.gui import ModGui
    ModGui(cfg, Path(profile), wired=args.wired, index=args.index,
           hid_mode=args.hid).run()
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Switch 2 Pro -> XInput (enterprise)")
    ap.add_argument("--profile", default=None, help="JSON profile (default from --game)")
    ap.add_argument("--game", default="cod", choices=["cod", "destiny2", "d2"],
                    help="Game preset: cod or destiny2")
    ap.add_argument("--gui", action="store_true")
    ap.add_argument("--calibrate", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--wired", action="store_true")
    ap.add_argument("--wireless", action="store_true")
    ap.add_argument("--index", type=int, default=None)
    ap.add_argument("--aim", type=float, default=None, help="0-100 dial override")
    ap.add_argument("--no-center", action="store_true")
    ap.add_argument("--hid", action="store_true", help="Use direct HID reader (057e:2069) instead of SDL")
    ap.add_argument("--hid-calibrate", action="store_true", help="Live HID report dump for Switch 2 Pro")
    ap.add_argument("--enable-usb", action="store_true",
                    help="Initialize Switch 2 Pro USB bulk interface and enable motion reports")
    ap.add_argument("--crosshair", action="store_true", help="Overlay-only mode: screen crosshair, no mapper")
    ap.add_argument("--watch-game", action="store_true",
                    help="Wait for COD, then launch the GUI; close it when COD exits")
    ap.add_argument("--log", default="INFO")
    return ap


def check_deps() -> list[str]:
    """Return missing optional packages for the running interpreter."""
    missing = []
    try:
        import hid  # noqa: F401
    except ImportError:
        missing.append("hidapi")
    try:
        import vgamepad  # noqa: F401
    except ImportError:
        missing.append("vgamepad")
    return missing


_MUTEX_HANDLE = None


def ensure_single_mapper() -> bool:
    """Windows named mutex: only one mapper/GUI at a time. Auto-releases on exit/crash."""
    global _MUTEX_HANDLE
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.CreateMutexW(None, False, "Global\\Switch2ModMapper")
        already = kernel32.GetLastError() == 183  # ERROR_ALREADY_EXISTS
        if already:
            if handle:
                kernel32.CloseHandle(handle)
            return False
        _MUTEX_HANDLE = handle
        return True
    except Exception:
        return True  # non-Windows or ctypes unavailable: don't block


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    setup_logging(args.log)
    try:
        return _run(args)
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0


def _run(args) -> int:
    missing = check_deps()
    if missing:
        print(f"WARNING: missing {missing} for {sys.executable}")
        print(f"  fix: python -m pip install {' '.join(missing)}  (use the same python that runs app.py)")
    pygame.init()

    if args.watch_game:
        return cmd_watch_game(args)

    if args.list:
        return cmd_list()
    if args.hid_calibrate:
        return cmd_hid_calibrate()
    if args.enable_usb:
        from switch2mod.procon2_enable import enable
        return 0 if enable(verbose=True) else 1
    if args.calibrate:
        return cmd_calibrate(args.index)

    profile = args.profile or GAME_PROFILES.get(args.game, "cod_profile.json")
    cfg = AppConfig.load(profile)
    if args.crosshair:
        import tkinter as tk
        from switch2mod.crosshair import CrosshairOverlay
        cfg.crosshair.enabled = True
        root = tk.Tk()
        root.withdraw()
        ov = CrosshairOverlay(cfg.crosshair)
        if not ov.show():
            return 1
        ov.set_locked(True)
        print("Crosshair overlay on (Windowed/Borderless required). Close this window to quit.")
        try:
            root.mainloop()
        except KeyboardInterrupt:
            pass
        finally:
            ov.close()
        return 0
    # stamp game so mapper/GUI log correctly
    cfg.game = "destiny2" if args.game in ("destiny2", "d2") else "cod"
    if args.wired:
        cfg.wired_mode = True
        cfg.polling_hz = 1000
    if args.wireless:
        cfg.wired_mode = False
    if args.aim is not None:
        cfg.aim_assist = max(0, min(100, args.aim))
    if args.no_center:
        cfg.auto_center = False
    # Raw cfg stays canonical; mappers derive effective stick params internally.
    eff = cfg.apply_aim_dial()
    log.info("[%s] AIM %.0f -> dz=%.3f sens=%.2f curve=%.2f smooth=%.2f (%s)",
             cfg.game.upper(), cfg.aim_assist, eff.right_deadzone,
             eff.right_stick_sensitivity, eff.curve_power, eff.smoothing, profile)

    # Mapper paths (GUI / HID / SDL) are exclusive: one instance only.
    # Standalone --crosshair is exempt (lightweight, pairs with a mapper).
    if args.gui or args.hid or not (args.list or args.calibrate or args.hid_calibrate or args.crosshair):
        if not ensure_single_mapper():
            print("Another mod instance is already running - refusing to stack a second mapper.")
            print("Close the old window first, or kill leftovers: Get-Process python | Stop-Process")
            return 2
    if args.gui:
        from switch2mod.gui import ModGui
        ModGui(cfg, Path(profile), wired=args.wired, index=args.index, hid_mode=args.hid).run()
        return 0

    if args.hid:
        from switch2mod.hid_mapper import HidProToXInput
        try:
            HidProToXInput(cfg).run()
        except Exception as e:
            print(f"HID mode failed: {e}")
            return 1
        return 0

    det = ControllerDetector()
    idx, infos = det.find(prefer_wired=not args.wireless, index=args.index)
    for c in infos:
        print(" ", c.label())
    if idx is None:
        print("No SDL controller. Try HID mode: python app.py --hid --game cod")
        print("Or diagnose: python app.py --list  +  python app.py --hid-calibrate")
        return 1
    ProToXInput(cfg, idx).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
