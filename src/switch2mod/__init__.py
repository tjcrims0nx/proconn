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
    _vd = _vendor_dir()
    if _os.path.isdir(_vd) and _vd not in _sys.path:
        _sys.path.append(_vd)

from switch2mod.config import AppConfig


def vigem_installer_path() -> str | None:
    """Path to the bundled ViGEmBus driver installer (Windows x64), if shipped."""
    p = _os.path.join(_vendor_dir(), "vgamepad", "win", "vigem", "install",
                      "x64", "ViGEmBusSetup_x64.msi")
    return p if _os.path.exists(p) else None


def selftest() -> int:
    """Verify the runtime can actually drive a virtual pad. Used by CI."""
    ok = True
    print("switch2mod selftest")
    print("  frozen:", bool(getattr(_sys, "frozen", False)))
    try:
        import vgamepad
        print("  vgamepad:", vgamepad.__file__)
    except Exception as e:
        print("  vgamepad: IMPORT FAILED -", e)
        return 1
    try:
        pad = vgamepad.VX360Gamepad()
        pad.reset()
        pad.update()
        print("  virtual pad: OK")
    except Exception as e:
        print("  virtual pad: FAILED -", e)
        print("  hint: install the driver at", vigem_installer_path())
        ok = False
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
    return 0 if ok else 1


__all__ = ["AppConfig", "vigem_installer_path", "selftest"]
__version__ = "0.0.3"

