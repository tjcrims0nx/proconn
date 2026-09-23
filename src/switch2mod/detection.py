"""Controller detection - robust Nintendo Switch Pro identification."""
from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass

os.environ.setdefault("SDL_JOYSTICK_HIDAPI", "1")
os.environ.setdefault("SDL_JOYSTICK_HIDAPI_SWITCH", "1")
os.environ.setdefault("SDL_HINT_JOYSTICK_HIDAPI_SWITCH", "1")
os.environ.setdefault("SDL_JOYSTICK_THREAD", "1")

import pygame  # noqa: E402

log = logging.getLogger("switch2mod.detection")

NINTENDO_VID = "57e"
SWITCH_PIDS = ("2009", "200e", "2017", "2069", "2093", "2019")
PRO_KEYWORDS = ("pro controller", "switch", "nintendo", "057e", "2093", "2069")
DUALSHOCK_KEYWORDS = ("dualshock", "dual shock", "dualsense", "playstation", "ps4", "ps5")
XBOX_KEYWORDS = ("xbox", "xinput", "x-box")


class NoControllerError(Exception):
    pass


@dataclass
class HidPadInfo:
    vid: int
    pid: int
    product: str
    path: bytes | str
    bus: str  # USB / BT / ?

    def label(self) -> str:
        prod = self.product or "HID device"
        return f"HID vid={self.vid:04x} pid={self.pid:04x} bus={self.bus} prod={prod}"


_HID_WARNED = False


def list_hid_pads(vid_filter: int | None = None) -> list[HidPadInfo]:
    """Direct HID enumeration - sees Switch 2 Pro (057e:2069) even when SDL hides it."""
    global _HID_WARNED
    try:
        import hid as hidapi
    except ImportError:
        if not _HID_WARNED:
            _HID_WARNED = True
            log.warning("hidapi not installed - HID pad detection off "
                        "(run: python -m pip install hidapi, using %s)", sys.executable)
        return []
    try:
        devs = hidapi.enumerate(0x057E) if vid_filter in (None, 0x057E) else hidapi.enumerate()
    except Exception as e:
        log.warning("HID enumerate failed: %s", e)
        return []
    out: list[HidPadInfo] = []
    for d in devs:
        try:
            vid = int(d.get("vendor_id", 0))
            pid = int(d.get("product_id", 0))
        except Exception:
            continue
        if vid_filter is not None and vid != vid_filter:
            continue
        path = str(d.get("path", b""))
        # MI_00 = USB wired interface, BT devices lack MI_ / have different usage page
        bus = "USB" if "MI_00" in path or "MI00" in path else ("BT?" if "BTH" in path.upper() else "?")
        prod = str(d.get("product_string") or d.get("product") or "")
        out.append(HidPadInfo(vid, pid, prod, d.get("path", b""), bus))
    return out


def list_nintendo_hid() -> list[HidPadInfo]:
    # Nintendo exposes Joy-Cons, instruments, and other accessories under the
    # same VID. Keep the HID fallback restricted to known Pro-controller PIDs
    # (or an explicit Pro Controller product string) so we never bind the
    # wrong device in COD.
    pads = [p for p in list_hid_pads(0x057E)
            if f"{p.pid:04x}" in SWITCH_PIDS
            or "pro controller" in p.product.lower()]
    # Prefer Switch 2 Pro PID 2069 first, then other Switch PIDs
    def key(p: HidPadInfo) -> int:
        pid_hex = f"{p.pid:04x}"
        if pid_hex == "2069":
            return 0
        if pid_hex in SWITCH_PIDS:
            return 1
        return 2
    return sorted(pads, key=key)


@dataclass
class ControllerInfo:
    index: int
    name: str
    guid: str
    vid: str
    pid: str
    bus: str
    axes: int
    buttons: int
    hats: int
    is_pro: bool
    likely_wired: bool
    score: int
    family: str = "generic"

    def label(self) -> str:
        tag = self.family.upper()
        return (f"[{self.index}] {self.name} | vid={self.vid} pid={self.pid} "
                f"bus={self.bus} a={self.axes} b={self.buttons} [{tag}]")


def parse_guid(guid: object) -> dict[str, str]:
    s = str(guid).lower().replace("-", "")
    info = {"bus": "?", "vid": "", "pid": "", "raw": str(guid)}
    try:
        if len(s) >= 12:
            bus = s[0:2]
            info["bus"] = {"03": "USB", "05": "BT"}.get(bus, bus)
            info["vid"] = s[4:8]
            info["pid"] = s[8:12]
    except Exception:
        pass
    return info


def controller_family(name: str, vid: str = "") -> str:
    """Classify common SDL pads without changing their raw input path."""
    text = str(name or "").lower()
    if any(word in text for word in DUALSHOCK_KEYWORDS) or vid.lower() == "054c":
        return "dualshock"
    if any(word in text for word in XBOX_KEYWORDS) or vid.lower() == "045e":
        return "xbox"
    if any(word in text for word in PRO_KEYWORDS) or vid.lower() == NINTENDO_VID:
        return "switch-pro"
    return "generic"


class ControllerDetector:
    def list(self) -> list[ControllerInfo]:
        try:
            pygame.joystick.init()
        except Exception as e:
            log.error("joystick init failed: %s", e)
            return []
        out: list[ControllerInfo] = []
        for i in range(pygame.joystick.get_count()):
            try:
                j = pygame.joystick.Joystick(i)
                j.init()
                name = j.get_name()
                try:
                    guid = j.get_guid()
                except Exception:
                    guid = "unknown"
                gi = parse_guid(guid)
                ln = name.lower()
                vid_match = gi["vid"] == NINTENDO_VID
                family = controller_family(name, gi["vid"])
                name_match = family == "switch-pro"
                is_pro = bool(vid_match or name_match)
                bus = gi["bus"]
                if bus == "?":
                    if "usb" in ln or "wired" in ln:
                        bus = "USB?"
                    elif "bluetooth" in ln or "wireless" in ln:
                        bus = "BT?"
                likely_wired = bus in ("USB", "USB?")
                try:
                    na, nb, nh = j.get_numaxes(), j.get_numbuttons(), j.get_numhats()
                except Exception:
                    na = nb = nh = 0
                score = 0
                if is_pro:
                    score += 50
                if vid_match:
                    score += 30
                if gi["pid"] in SWITCH_PIDS:
                    score += 10
                if 4 <= na <= 8 and nb >= 10:
                    score += 5
                out.append(ControllerInfo(i, name, str(guid), gi["vid"], gi["pid"],
                                           bus, na, nb, nh, is_pro, likely_wired, score,
                                           family))
            except Exception as e:
                log.warning("index %d unreadable: %s", i, e)
        out.sort(key=lambda c: c.score, reverse=True)
        return out

    def find(self, prefer_wired: bool = True, index: int | None = None) -> tuple[int | None, list[ControllerInfo]]:
        infos = self.list()
        if index is not None:
            for c in infos:
                if c.index == index:
                    return index, infos
            return None, infos
        if not infos:
            return None, []
        pros = [c for c in infos if c.is_pro]
        pool = pros if pros else infos
        if prefer_wired:
            wired = [c for c in pool if c.likely_wired]
            if wired:
                return wired[0].index, infos
        return pool[0].index, infos

    def full_report(self) -> dict[str, object]:
        """Unified SDL + HID report. HID catches Switch 2 Pro when SDL mapping is missing."""
        sdl = self.list()
        try:
            hid_pads = list_nintendo_hid()
        except Exception:
            hid_pads = []
        sdl_has_nintendo = any(c.is_pro for c in sdl)
        hid_has_nintendo = len(hid_pads) > 0
        if hid_has_nintendo and not sdl_has_nintendo:
            hint = ("FOUND via HID but HIDDEN from SDL - SDL mapping missing PID 2069. "
                    "Use USB-C DATA cable + BetterJoy/Steam Input, or HID reader mode.")
        elif hid_has_nintendo and sdl_has_nintendo:
            hint = "FOUND via HID + SDL - ready."
        elif not hid_has_nintendo and not sdl_has_nintendo:
            hint = "NOT FOUND - plug USB-C DATA cable to rear USB, check Device Manager HID 057E:2069."
        else:
            hint = "FOUND via SDL."
        return {"sdl": sdl, "hid": hid_pads, "hint": hint}
