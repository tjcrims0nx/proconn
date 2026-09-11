"""Pro Controller 2 USB enabler (Switch 2 Pro 057e:2069).

Replicates the HandHeldLegend procon2tool init handshake ( bulk interface 1,
EP OUT 0x02 ) so the pad starts full HID output incl. motion data.
Sequence bytes from HHL procon2tool + pinapelz's pyusb port - credited.

SAFETY: touches ONLY USB interface 1 (vendor bulk). HID interface 0 and the
audio interfaces are never claimed, no drivers are replaced, no reboot.
Interface is released + device disposed before return.
Must re-run each replug/restart (pad forgets on power loss).
"""
from __future__ import annotations

import logging
import os
import time

log = logging.getLogger("switch2mod.enable")

VID = 0x057E
PID_PRO2 = 0x2069
IFACE = 1

CMDS: list[tuple[str, bytes]] = [
    ("Init 0x03", bytes([0x03, 0x91, 0x00, 0x0d, 0x00, 0x08, 0x00, 0x00,
                          0x01, 0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF])),
    ("Unknown 0x07", bytes([0x07, 0x91, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00])),
    ("Unknown 0x16", bytes([0x16, 0x91, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00])),
    ("Req MAC", bytes([0x15, 0x91, 0x00, 0x01, 0x00, 0x0e, 0x00, 0x00,
                        0x00, 0x02, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF,
                        0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF])),
    ("Req LTK", bytes([0x15, 0x91, 0x00, 0x02, 0x00, 0x11, 0x00, 0x00,
                        0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF,
                        0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF])),
    ("Unknown 0x15/03", bytes([0x15, 0x91, 0x00, 0x03, 0x00, 0x01, 0x00, 0x00, 0x00])),
    ("Unknown 0x09", bytes([0x09, 0x91, 0x00, 0x07, 0x00, 0x08, 0x00, 0x00,
                             0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])),
    ("IMU 0x0C/02", bytes([0x0c, 0x91, 0x00, 0x02, 0x00, 0x04, 0x00, 0x00,
                            0x27, 0x00, 0x00, 0x00])),
    ("OUT Unknown 0x11", bytes([0x11, 0x91, 0x00, 0x03, 0x00, 0x00, 0x00, 0x00])),
    ("Unknown 0x0A", bytes([0x0a, 0x91, 0x00, 0x08, 0x00, 0x14, 0x00, 0x00,
                             0x01, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
                             0xff, 0x35, 0x00, 0x46, 0x00, 0x00, 0x00, 0x00,
                             0x00, 0x00, 0x00, 0x00])),
    ("IMU 0x0C/04", bytes([0x0c, 0x91, 0x00, 0x04, 0x00, 0x04, 0x00, 0x00,
                            0x27, 0x00, 0x00, 0x00])),
    ("Enable Haptics", bytes([0x03, 0x91, 0x00, 0x0a, 0x00, 0x04, 0x00, 0x00,
                               0x09, 0x00, 0x00, 0x00])),
    ("OUT Unknown 0x10", bytes([0x10, 0x91, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00])),
    ("OUT Unknown 0x01", bytes([0x01, 0x91, 0x00, 0x0c, 0x00, 0x00, 0x00, 0x00])),
    ("OUT Unknown 0x03", bytes([0x03, 0x91, 0x00, 0x01, 0x00, 0x00, 0x00])),
    ("OUT Unknown 0x0A alt", bytes([0x0a, 0x91, 0x00, 0x02, 0x00, 0x04, 0x00,
                                     0x00, 0x03, 0x00, 0x00])),
    ("LED mask 0x0F", bytes([0x09, 0x91, 0x00, 0x07, 0x00, 0x08, 0x00, 0x00,
                              0x0F, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])),
]


def _backend():
    try:
        import usb.backend.libusb1 as libusb1
    except ImportError:
        return None
    candidates = []
    try:
        import libusb as _lu
        base = os.path.dirname(_lu.__file__)
        candidates.append(os.path.join(base, "_platform", "windows", "x86_64", "libusb-1.0.dll"))
    except Exception:
        pass
    candidates.append(r"C:\Program Files (x86)\Steam\libusb-1.0.dll")
    for dll in candidates:
        if dll and os.path.exists(dll):
            try:
                be = libusb1.get_backend(find_library=lambda x: dll)
                if be is not None:
                    return be
            except Exception:
                continue
    try:
        return libusb1.get_backend()
    except Exception:
        return None


def enable(verbose: bool = False) -> bool:
    """Run the full init handshake. Returns True if all LEDs should be on."""
    try:
        import usb.core
        import usb.util
    except ImportError:
        log.error("pyusb missing: pip install pyusb")
        return False
    be = _backend()
    if be is None:
        log.error("libusb backend missing: pip install libusb")
        return False
    dev = usb.core.find(idVendor=VID, idProduct=PID_PRO2, backend=be)
    if dev is None:
        log.error("057e:2069 not found on USB")
        return False
    log.info("found Pro Controller 2, claiming bulk interface %d", IFACE)
    try:
        if dev.is_kernel_driver_active(IFACE):
            dev.detach_kernel_driver(IFACE)
    except Exception:
        pass  # Windows: no kernel driver concept here
    if os.name != "nt":
        try:
            dev.set_configuration()
        except Exception as e:
            log.warning("set_configuration: %s", e)
    # NOTE: on Windows skip set_configuration (ACCESS when composite is owned);
    # claiming the driverless bulk interface directly is enough.
    try:
        usb.util.claim_interface(dev, IFACE)
    except Exception as e:
        log.error("claim interface %d failed: %s", IFACE, e)
        log.error("Close Steam / BetterJoy (they hold Switch pads), replug USB, retry.")
        return False
    try:
        cfg = dev.get_active_configuration()
        intf = cfg[(IFACE, 0)]
        ep_out = usb.util.find_descriptor(
            intf, custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress)
            == usb.util.ENDPOINT_OUT)
        ep_in = usb.util.find_descriptor(
            intf, custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress)
            == usb.util.ENDPOINT_IN)
        if ep_out is None:
            log.error("no bulk OUT endpoint")
            return False
        ok = 0
        for name, cmd in CMDS:
            try:
                ep_out.write(cmd)
                time.sleep(0.01)
                try:
                    resp = bytes(ep_in.read(32, timeout=100))
                    if verbose:
                        log.info("[%s] ack: %s", name, resp.hex(" "))
                except Exception:
                    pass  # some commands ACK nothing - normal per HHL docs
                ok += 1
            except Exception as e:
                log.error("[%s] write failed: %s", name, e)
                return False
        log.info("handshake %d/%d sent - pad LEDs should light", ok, len(CMDS))
        return ok == len(CMDS)
    finally:
        try:
            usb.util.release_interface(dev, IFACE)
        except Exception:
            pass
        try:
            usb.util.dispose_resources(dev)
        except Exception:
            pass
