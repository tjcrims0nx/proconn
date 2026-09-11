"""Rear paddle mapping - GL/GR/C/Capture to Xbox outputs. Single source of truth.

Switch 2 Pro has rear grip paddles GL/GR plus front C and Capture buttons.
Targets use Xbox naming; RS=R3 and LS=L3 aliases accepted (Gamesir-style).
NONE disables a paddle (falls back to layout default for Capture).
"""
from __future__ import annotations

TARGETS = ("NONE", "A", "B", "X", "Y", "LB", "RB", "LT", "RT", "L3", "R3", "RS", "LS",
           "START", "BACK", "GUIDE", "DUP", "DDOWN", "DLEFT", "DRIGHT")

_ALIAS = {"RS": "R3", "LS": "L3"}


def normalize_target(s: object) -> str:
    t = str(s or "NONE").strip().upper()
    t = _ALIAS.get(t, t)
    return t if t in TARGETS or t in ("R3", "L3") else "NONE"


def apply_rear(out: dict[str, bool], rear, pressed: dict[str, bool],
               triggers: dict[str, float] | None = None) -> dict[str, bool]:
    """out: button output dict. pressed: capture/gl/gr/c bools.
    triggers: optional {'LT': float, 'RT': float} - LT/RT targets set full 1.0 press."""
    mapping = {
        "capture": getattr(rear, "capture_as", "NONE"),
        "gl": getattr(rear, "gl_as", "NONE"),
        "gr": getattr(rear, "gr_as", "NONE"),
        "c": getattr(rear, "c_as", "NONE"),
    }
    for key, target in mapping.items():
        if not pressed.get(key):
            continue
        t = normalize_target(target)
        if t in ("NONE", ""):
            continue
        if t in ("LT", "RT") and triggers is not None:
            triggers[t] = 1.0
        else:
            out[t] = True
    return out
