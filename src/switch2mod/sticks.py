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
                   gyro_y: float = 0.0,
                   recenter_active: bool | None = None) -> tuple[float, float, float, float]:
    """Single source of truth for stick output. Mappers AND visualizer use this,
    so the on-screen crosshair always matches what the game receives."""
    power = effective_power(cfg)
    sq = bool(getattr(cfg, "square_mapping", True))
    lx2, ly2 = apply_stick(lx, ly, cfg.left_deadzone, cfg.left_antideadzone, power, 1.0, False)
    if ads_held:
        # ADS booster shaping: keep it SNAPPY (this is an aim-feel tool, not
        # a slowdown). Micro jitter just above the tiny hipfire deadzone used
        # to jump straight to antideadzone (~0.15) then get boosted by
        # aggressive curve + 2x sens = random speed bursts while scoped.
        # Fix = smaller antideadzone step (0.05, not 0) + keep curve/sens
        # near hipfire, then ONE damping multiply. Legal reshape of the
        # user's own thumb only, no automation, no aimbot.
        dz_r = max(float(cfg.right_deadzone), 0.035)
        sens_r = min(float(cfg.right_stick_sensitivity), 1.8)
        power_r = min(power, 2.0)
        rx2, ry2 = apply_stick(rx, ry, dz_r, 0.05, power_r, sens_r, sq)
    else:
        rx2, ry2 = apply_stick(rx, ry, cfg.right_deadzone, cfg.right_antideadzone,
                               power, cfg.right_stick_sensitivity, sq)
    if getattr(cfg, "invert_y", False):
        ry2 = -ry2
    damp = 1.0
    if ads_held:
        # Default 0.85 = booster feel. Your 0.7 + my old 1.25 cap = 0.87x
        # total on top of a flattened curve = mud. Now damping is the ONLY
        # ADS slowdown, curve/sens stay hot, so set 0.85-1.0 in GUI.
        damp = max(0.3, min(1.0, float(getattr(cfg, "ads_damping", 0.85))))
        rx2 *= damp
        ry2 *= damp
        # Legal input shaping only: when the physical right stick is released
        # near center, decay any filtered residual smoothly toward neutral.
        # This never chooses a target or moves aim on its own.
        if ((ads_held if recenter_active is None else recenter_active) and
                getattr(cfg, "ads_recenter_enabled", True) and
                math.hypot(rx, ry) <= max(dz_r + 0.02, 0.12)):
            speed = max(0.0, min(30.0, float(
                getattr(cfg, "ads_recenter_speed", 10.0))))
            recenter = math.exp(-speed * 0.016)
            rx2 *= recenter
            ry2 *= recenter
    if getattr(cfg, "gyro_enabled", False):
        if not getattr(cfg, "gyro_ads_only", True) or ads_held:
            gx = gyro_x - float(getattr(cfg, "gyro_center_x", 0.0))
            gy = gyro_y - float(getattr(cfg, "gyro_center_y", 0.0))
            dz = max(0.0, min(0.5, float(getattr(cfg, "gyro_deadzone", 0.04))))
            if ads_held:
                # Tremor gate: hand shake must clear a wider deadzone scoped.
                dz = max(dz, 0.08)
            gx = 0.0 if abs(gx) < dz else gx
            gy = 0.0 if abs(gy) < dz else gy
            if getattr(cfg, "gyro_invert_x", False):
                gx = -gx
            if getattr(cfg, "gyro_invert_y", False):
                gy = -gy
            if getattr(cfg, "gyro_left_enabled", False):
                sens = float(getattr(cfg, "gyro_left_sensitivity", 0.5))
                lx2, ly2 = lx2 + gx * sens * damp, ly2 + gy * sens * damp
            if getattr(cfg, "gyro_right_enabled", False):
                sens = float(getattr(cfg, "gyro_right_sensitivity", 1.0))
                rx2, ry2 = rx2 + gx * sens * damp, ry2 + gy * sens * damp
    lx2 = max(-1.0, min(1.0, lx2))
    ly2 = max(-1.0, min(1.0, ly2))
    rx2 = max(-1.0, min(1.0, rx2))
    ry2 = max(-1.0, min(1.0, ry2))
    return lx2, ly2, rx2, ry2


def ensure_sprint_magnitude(x: float, y: float, thresh: float = 1.0) -> tuple[float, float]:
    """L3 sprint helper: COD only sprints near full left-stick tilt, and the
    physical click often eases tilt off the gate. When L3 is held, stretch
    the (already tuned) vector to full magnitude, keeping the user's own
    direction. Pure manual-input reshape, no automation."""
    import math as _m
    mag = _m.hypot(x, y)
    if mag < 1e-6 or mag >= thresh:
        return x, y
    s = thresh / mag
    return x * s, y * s


def update_sprint_latch(prev_on: bool, pressed: bool, now: float, last_change: float,
                        release_delay: float = 0.25) -> tuple[bool, float]:
    """Sticky L3 latch. COD drops sprint on a single flicker frame; the click
    switch + HID jitter flicker. Engage instantly, release only after the
    button has been continuously up for release_delay. Pure, unit-tested."""
    if pressed:
        # Track the most recent confirmed pressed frame. Previously this
        # timestamp only recorded the initial press, so after L3 had been
        # held longer than release_delay a single missing HID frame released
        # sprint immediately. It must measure continuous button-up time.
        return True, now
    if prev_on and (now - last_change) >= release_delay:
        return False, now
    return prev_on, last_change


def update_ads_state(prev_on: bool, lt: float, now: float, last_change: float,
                     engage: float = 0.20, release: float = 0.08,
                     min_hold: float = 0.10, min_off: float = 0.03) -> tuple[bool, float]:
    """Debounced ADS latch. Paddle GL fires digital LT=1.0 instantly, so grip
    wobble used to flip hipfire/ADS stick shaping frame-to-frame = speed
    bursts while scoped. Engage fast, release only under a lower threshold
    AND after a minimum hold. Pure function, unit-tested."""
    if prev_on:
        if lt < release and (now - last_change) >= min_hold:
            return False, now
        return True, last_change
    if lt >= engage and (now - last_change) >= min_off:
        return True, now
    return False, last_change


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
