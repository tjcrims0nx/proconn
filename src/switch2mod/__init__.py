"""Switch2Mod enterprise package."""
import os as _os
import sys as _sys


def _vendor_dir() -> str:
    """Directory holding the vendored gamepad stack, frozen or not."""
    candidates = []
    try:
        candidates.append(_os.path.join(
            _os.path.dirname(_os.path.abspath(__file__)), "_vendor"))
    except Exception:
        pass
    meipass = getattr(_sys, "_MEIPASS", None)
    if meipass:
        candidates.append(_os.path.join(meipass, "switch2mod", "_vendor"))
    for c in candidates:
        if _os.path.isdir(c):
            return c
    return candidates[0] if candidates else "_vendor"


# Vendored fallback: if the standalone `vgamepad` package is not installed
# (locked-down machine, index hiccup, or a frozen EXE built without it), fall
# back to the copy shipped at switch2mod/_vendor. An installed vgamepad always
# wins because _vendor is appended, never prepended.
try:
    import vgamepad  # noqa: F401
except ImportError:
    # Package not installed at all: use the vendored copy.
    _vd = _vendor_dir()
    if _os.path.isdir(_vd) and _vd not in _sys.path:
        _sys.path.append(_vd)
except Exception:
    # Installed, but the ViGEmBus driver is missing/not running. Keep the
    # installed package (do NOT fall back) so callers can report the hint.
    pass

from switch2mod.config import AppConfig


def vigem_installer_path() -> str | None:
    """Path to the bundled ViGEmBus driver installer (Windows x64), if shipped."""
    p = _os.path.join(_vendor_dir(), "vgamepad", "win", "vigem", "install",
                      "x64", "ViGEmBusSetup_x64.msi")
    return p if _os.path.exists(p) else None


def selftest() -> int:
    """Verify the frozen/runtime can load its bundled gamepad. Exit non-zero
    only for real packaging problems (missing modules), not for a machine
    that lacks the ViGEmBus kernel driver."""
    ok = True
    print("switch2mod selftest")
    print("  frozen:", bool(getattr(_sys, "frozen", False)))
    vd = _vendor_dir()
    print("  vendor dir:", vd, "exists:", _os.path.isdir(vd))
    driver_missing = False
    try:
        import vgamepad
        print("  vgamepad:", getattr(vgamepad, "__file__", "?"))
        try:
            pad = vgamepad.VX360Gamepad()
            pad.reset()
            pad.update()
            print("  virtual pad: OK")
        except Exception as e:
            driver_missing = True
            print("  virtual pad: driver not installed (%s)" % e)
    except ImportError as e:
        # Module genuinely absent = packaging failure.
        print("  vgamepad: NOT BUNDLED -", e)
        ok = False
    except Exception as e:
        # Module present; it failed while connecting to the bus.
        driver_missing = True
        print("  vgamepad present, driver not installed:", e)
    if driver_missing:
        print("  note: ViGEmBus driver not installed on this machine (normal on CI).")
        print("  driver installer:", vigem_installer_path())
    try:
        import pygame
        print("  pygame:", pygame.version.ver)
    except Exception as e:
        print("  pygame: IMPORT FAILED -", e)
        ok = False
    try:
        import hid  # noqa: F401
        print("  hidapi: OK")
    except Exception as e:
        print("  hidapi: not available -", e)
    print("  result:", "OK" if ok else "PROBLEMS")
    return 0 if ok else 1


__all__ = ["AppConfig", "vigem_installer_path", "selftest"]
__version__ = "0.0.3"

