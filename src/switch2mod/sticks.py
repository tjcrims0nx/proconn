"""Pure stick math - no I/O, fully unit-testable."""
from __future__ import annotations

import math


def circular_to_square(x: float, y: float) -> tuple[float, float]:
    if x == 0 and y == 0:
        return 0.0, 0.0
    mag = math.hypot(x, y)
    if mag > 1.0:
        x, y = x / mag, y / mag
        mag = 1.0
    ax, ay = abs(x), abs(y)
    if ax > 0 and ay > 0 and max(ax, ay) > 0:
        scale = mag / max(ax, ay)
        target = min(1.0, mag * (0.4 + 0.6 * scale))
        x, y = x / mag * target, y / mag * target
    return x, y


def apply_stick(
    x: float, y: float,
    deadzone: float, antideadzone: float,
    power: float, sens: float = 1.0,
    square: bool = False,
) -> tuple[float, float]:
    if abs(x) < 0.003:
        x = 0.0
    if abs(y) < 0.003:
        y = 0.0
    mag = math.hypot(x, y)
    if mag < deadzone:
        return 0.0, 0.0
    norm = min(1.0, (mag - deadzone) / max(1e-6, 1.0 - deadzone))
    if power != 1.0:
        norm = 1.0 - pow(1.0 - norm, power)
    norm = antideadzone + norm * (1.0 - antideadzone)
    norm = min(1.0, norm * sens)
    if mag <= 0:
        return 0.0, 0.0
    ox, oy = x / mag * norm, y / mag * norm
    if square:
        ox, oy = circular_to_square(ox, oy)
    return ox, oy


def to_s16(f: float) -> int:
    return int(max(-1.0, min(1.0, f)) * 32767)


def effective_power(cfg) -> float:
    curve = getattr(cfg, "response_curve", "aggressive")
    if curve == "linear":
        return 1.0
    if curve == "precise":
        return 0.7
    if curve == "raw":
        return 1.0
    return float(getattr(cfg, "curve_power", 2.0))


def process_sticks(cfg, lx: float, ly: float, rx: float, ry: float,
                   ads_held: bool = False, gyro_x: float = 0.0,
                   gyro_y: float = 0.0) -> tuple[float, float, float, float]:
    """Single source of truth for stick output. Mappers AND visualizer use this,
    so the on-screen crosshair always matches what the game receives."""
    power = effective_power(cfg)
    sq = bool(getattr(cfg, "square_mapping", True))
    lx2, ly2 = apply_stick(lx, ly, cfg.left_deadzone, cfg.left_antideadzone, power, 1.0, False)
    rx2, ry2 = apply_stick(rx, ry, cfg.right_deadzone, cfg.right_antideadzone,
                           power, cfg.right_stick_sensitivity, sq)
    if getattr(cfg, "invert_y", False):
        ry2 = -ry2
    if ads_held:
        damp = max(0.3, min(1.0, float(getattr(cfg, "ads_damping", 0.65))))
        rx2 *= damp
        ry2 *= damp
    if getattr(cfg, "gyro_enabled", False):
        if not getattr(cfg, "gyro_ads_only", True) or ads_held:
            gx = gyro_x - float(getattr(cfg, "gyro_center_x", 0.0))
            gy = gyro_y - float(getattr(cfg, "gyro_center_y", 0.0))
            dz = max(0.0, min(0.5, float(getattr(cfg, "gyro_deadzone", 0.04))))
            gx = 0.0 if abs(gx) < dz else gx
            gy = 0.0 if abs(gy) < dz else gy
            if getattr(cfg, "gyro_invert_x", False):
                gx = -gx
            if getattr(cfg, "gyro_invert_y", False):
                gy = -gy
            if getattr(cfg, "gyro_left_enabled", False):
                sens = float(getattr(cfg, "gyro_left_sensitivity", 0.5))
                lx2, ly2 = lx2 + gx * sens, ly2 + gy * sens
            if getattr(cfg, "gyro_right_enabled", False):
                sens = float(getattr(cfg, "gyro_right_sensitivity", 1.0))
                rx2, ry2 = rx2 + gx * sens, ry2 + gy * sens
    lx2 = max(-1.0, min(1.0, lx2))
    ly2 = max(-1.0, min(1.0, ly2))
    rx2 = max(-1.0, min(1.0, rx2))
    ry2 = max(-1.0, min(1.0, ry2))
    return lx2, ly2, rx2, ry2


class Smoother:
    """EMA filter per axis. a=0 snappy, 0.6 heavy."""

    def __init__(self, amount: float = 0.15):
        self.amount = max(0.0, min(0.6, amount))
        self.state = {"lx": 0.0, "ly": 0.0, "rx": 0.0, "ry": 0.0}

    def set_amount(self, amount: float) -> None:
        self.amount = max(0.0, min(0.6, float(amount)))

    def filter(self, key: str, target: float) -> float:
        self.state[key] = self.state[key] * self.amount + target * (1 - self.amount)
        return self.state[key]
