"""Application configuration - single source of truth, validated dataclass."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from switch2mod.crosshair import CrosshairConfig


@dataclass
class RearMap:
    # Permanently locked: GL fires LT (aim), GR fires RT (fire).
    capture_as: str = "R3"
    gl_as: str = "LT"
    gr_as: str = "RT"
    c_as: str = "X"
    plus_as: str = "START"
    minus_as: str = "BACK"
    home_as: str = "GUIDE"


@dataclass
class AppConfig:
    # identity
    name: str = "COD - Switch 2 Pro to Xbox (Gamesir-like)"
    description: str = "Optimized for Call of Duty on PC."
    game: str = "cod"  # cod | destiny2
    # connection
    wired_mode: bool = True
    polling_hz: int = 1000
    # mapping
    swap_abxy: bool = True
    cod_layout: str = "bumper_jumper_tactical"
    rear_map: RearMap = field(default_factory=RearMap)
    crosshair: CrosshairConfig = field(default_factory=CrosshairConfig)
    # aim / sticks (Gamesir-like dial, legal tuning only)
    aim_assist: float = 85.0          # 0-100 dial
    ads_damping: float = 0.85         # 0.3-1.0, sole ADS slowdown (booster feel)
    ads_recenter_enabled: bool = True
    ads_recenter_speed: float = 10.0  # residual-stick decay per second
    smoothing: float = 0.15           # 0-0.6, lower = snappier
    square_mapping: bool = True
    auto_center: bool = True
    left_deadzone: float = 0.06
    right_deadzone: float = 0.02
    left_antideadzone: float = 0.0
    right_antideadzone: float = 0.12
    response_curve: str = "aggressive"
    curve_power: float = 2.2
    invert_y: bool = False
    right_stick_sensitivity: float = 1.85
    # gyro routing (decoder remains inactive until hardware offsets are verified)
    gyro_enabled: bool = False
    gyro_left_enabled: bool = False
    gyro_right_enabled: bool = False
    gyro_ads_only: bool = True
    gyro_left_sensitivity: float = 0.50
    gyro_right_sensitivity: float = 1.00
    gyro_deadzone: float = 0.04
    gyro_invert_x: bool = False
    gyro_invert_y: bool = False
    gyro_center_x: float = 0.0
    gyro_center_y: float = 0.0
    # triggers
    hair_trigger_left: bool = True
    hair_trigger_right: bool = True
    hair_threshold: float = 0.15
    turbo_enabled: bool = False
    turbo_button: str = "RT"
    turbo_cps: int = 12
    rumble_scale: float = 0.8

    def validate(self) -> None:
        if not 0 <= self.aim_assist <= 100:
            raise ValueError("aim_assist must be 0-100")
        if not 60 <= self.polling_hz <= 1000:
            raise ValueError("polling_hz must be 60-1000")
        if self.response_curve not in ("linear", "aggressive", "precise", "raw"):
            raise ValueError(f"bad response_curve: {self.response_curve}")

    def apply_aim_dial(self) -> AppConfig:
        """Derive effective stick params from 0-100 dial. Pure, testable."""
        import copy
        c: AppConfig = copy.deepcopy(self)
        a = max(0.0, min(100.0, float(self.aim_assist))) / 100.0
        c.right_deadzone = 0.12 - 0.10 * a
        c.right_antideadzone = 0.0 + 0.15 * a
        c.curve_power = 1.2 + 1.2 * a
        c.right_stick_sensitivity = 1.0 + 1.0 * a
        c.smoothing = 0.45 - 0.35 * a
        return c

    def apply_legit_max_preset(self) -> AppConfig:
        """Return a responsive manual-input preset; never moves the stick itself."""
        import copy
        c = copy.deepcopy(self)
        c.aim_assist = 100.0
        c.ads_damping = 0.70
        c.right_deadzone = 0.02
        c.right_antideadzone = 0.15
        c.right_stick_sensitivity = 2.0
        c.smoothing = 0.10
        c.response_curve = "aggressive"
        c.curve_power = 2.4
        return c

    @classmethod
    def load(cls, path: str | Path) -> AppConfig:
        cfg = cls()
        p = Path(path)
        if not p.exists():
            return cfg
        try:
            data: dict[str, Any] = json.loads(p.read_text())
        except Exception:
            return cfg
        rear = data.pop("rear_map", None)
        xh = data.pop("crosshair", None)
        for k, v in data.items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)
        if isinstance(rear, dict):
            for k, v in rear.items():
                if hasattr(cfg.rear_map, k):
                    setattr(cfg.rear_map, k, v)
        cfg.crosshair = CrosshairConfig.from_dict(xh)
        try:
            cfg.validate()
        except ValueError:
            pass
        return cfg

    def save(self, path: str | Path) -> None:
        d = asdict(self)
        Path(path).write_text(json.dumps(d, indent=2))
