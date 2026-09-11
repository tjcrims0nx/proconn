"""Switch2Mod enterprise package."""
import os as _os
import sys as _sys

# Vendored fallback: if the standalone `vgamepad` package is not installed
# (e.g. locked-down machine / index hiccup), fall back to the copy shipped
# inside this wheel at switch2mod/_vendor. An installed vgamepad always wins
# because _vendor is appended, not prepended.
try:
    import vgamepad  # noqa: F401
except ImportError:
    _vendor = _os.path.join(_os.path.dirname(__file__), "_vendor")
    if _os.path.isdir(_vendor) and _vendor not in _sys.path:
        _sys.path.append(_vendor)

from switch2mod.config import AppConfig


def vigem_installer_path() -> str | None:
    """Path to the bundled ViGEmBus driver installer (Windows x64), if shipped."""
    p = _os.path.join(
        _os.path.dirname(__file__), "_vendor", "vgamepad", "win",
        "vigem", "install", "x64", "ViGEmBusSetup_x64.msi")
    return p if _os.path.exists(p) else None


__all__ = ["AppConfig", "vigem_installer_path"]
__version__ = "0.0.2"
