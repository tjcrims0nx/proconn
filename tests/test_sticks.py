from switch2mod.config import AppConfig
from switch2mod.sticks import apply_stick, circular_to_square


def test_aim_dial_high_is_snappier():
    low = AppConfig(aim_assist=20).apply_aim_dial()
    high = AppConfig(aim_assist=90).apply_aim_dial()
    assert high.right_stick_sensitivity > low.right_stick_sensitivity
    assert high.right_deadzone < low.right_deadzone


def test_aim_dial_changes_live_right_stick_output():
    """The GUI dial must affect the values sent to the virtual pad."""
    low = AppConfig(aim_assist=0).apply_aim_dial()
    high = AppConfig(aim_assist=100).apply_aim_dial()
    low_out = apply_stick(0.25, 0.0, low.right_deadzone,
                           low.right_antideadzone, low.curve_power,
                           low.right_stick_sensitivity, low.square_mapping)[0]
    high_out = apply_stick(0.25, 0.0, high.right_deadzone,
                            high.right_antideadzone, high.curve_power,
                            high.right_stick_sensitivity, high.square_mapping)[0]
    assert high_out > low_out


def test_deadzone_blocks_noise():
    assert apply_stick(0.01, 0.0, 0.05, 0.0, 1.0) == (0.0, 0.0)


def test_square_preserves_center():
    assert circular_to_square(0.0, 0.0) == (0.0, 0.0)


def test_gr_polarity_handles_both_firmware_states():
    """GR idles at different bits per session; a press = change from rest."""
    from switch2mod.hid_reader import apply_gr_polarity
    b = {}
    apply_gr_polarity(b, 0x00, gr_rest=1)  # active-low session, pressed
    assert b["GR"] is True
    apply_gr_polarity(b, 0x01, gr_rest=1)  # active-low session, released
    assert b["GR"] is False
    apply_gr_polarity(b, 0x01, gr_rest=0)  # active-high session, pressed
    assert b["GR"] is True
    apply_gr_polarity(b, 0x00, gr_rest=0)  # active-high session, released
    assert b["GR"] is False
    apply_gr_polarity(b, 0x02, gr_rest=0)  # GL bit must not leak into GR
    assert b["GR"] is False


def test_crosshair_roundtrip():
    from switch2mod.config import AppConfig
    c = AppConfig.load("cod_profile.json")
    c.crosshair.style = "dot"
    c.crosshair.size = 40
    c.save("tests/tmp_profile.json")
    try:
        r = AppConfig.load("tests/tmp_profile.json")
        assert r.crosshair.style == "dot" and r.crosshair.size == 40
    finally:
        import os
        os.remove("tests/tmp_profile.json")


def test_crosshair_pulse_settings_roundtrip():
    from switch2mod.crosshair import CrosshairConfig
    c = CrosshairConfig.from_dict({
        "aim_sweep_pulse": True,
        "aim_pulse_threshold": 0.4,
        "aim_pulse_cooldown": 0.3,
    })
    assert c.aim_sweep_pulse is True
    assert c.aim_pulse_threshold == 0.4
    assert c.aim_pulse_cooldown == 0.3


def test_crosshair_movement_bloom_and_ads_tighten():
    from switch2mod.crosshair import CrosshairConfig, _MovementState

    cfg = CrosshairConfig(bloom_max_px=20, ads_tighten=0.4)
    state = _MovementState(prev_t=0.0)
    # Make the update deterministic without sleeping.
    import time
    now = time.monotonic()
    state.prev_t = now - 0.05
    state.update(0.0, 0.0, 0.8, 0.0, False, cfg)
    assert state.bloom_px > 0
    state.prev_t = time.monotonic() - 0.05
    state.update(0.0, 0.0, 0.0, 0.0, True, cfg)
    assert state.ads_factor < 1.0


def test_hid05_button_bits_hardware_verified():
    """Pin the 2026-09-10 capture results: each button = one bit, byte5/6/7/8."""
    from switch2mod.hid_reader import decode_report05
    base = bytearray.fromhex("053cab1400000000000000ff27821e9882")
    cases = {"A": (5, 0x08), "B": (5, 0x04), "X": (5, 0x02), "Y": (5, 0x01),
             "R": (5, 0x40), "ZR": (5, 0x80), "L": (7, 0x40), "ZL": (7, 0x80),
             "minus": (6, 0x01), "plus": (6, 0x02), "RStick": (6, 0x04),
             "LStick": (6, 0x08), "home": (6, 0x10), "capture": (6, 0x20),
             "C": (6, 0x40), "GR": (8, 0x01), "GL": (8, 0x02),
             "d_down": (7, 0x01), "d_up": (7, 0x02),
             "d_right": (7, 0x04), "d_left": (7, 0x08)}
    for name, (off, mask) in cases.items():
        rep = bytearray(base)
        rep[off] |= mask
        st = decode_report05(bytes(rep))
        assert st is not None and st.buttons.get(name) is True, name
        # no other named button may fire
        others = [k for k, v in st.buttons.items() if v and k != name]
        assert not others, (name, others)


def test_hid05_rest_decodes_center():
    from switch2mod.hid_reader import decode_report05
    raw = bytes.fromhex("053cab1400000000000000ff27821e9882")
    st = decode_report05(raw)
    assert st is not None
    assert abs(st.lx) < 0.05 and abs(st.ly) < 0.05
    assert abs(st.rx) < 0.05 and abs(st.ry) < 0.05
    assert st.buttons and all(v is False for v in st.buttons.values())


def test_hid05_left_stick_click_decodes_to_lstick():
    from switch2mod.hid_reader import decode_report05
    raw = bytearray.fromhex("053cab1400000000000000ff27821e9882")
    raw[6] |= 0x08  # verified unified 0x05 LStick bit
    st = decode_report05(bytes(raw))
    assert st is not None and st.buttons["LStick"] is True


def test_motion_decode_uses_confirmed_offsets():
    from switch2mod.hid_reader import decode_motion
    raw = bytearray(64)
    raw[0x37:0x39] = (16384).to_bytes(2, "little", signed=True)
    raw[0x39:0x3B] = (8192).to_bytes(2, "little", signed=True)
    raw[0x3B:0x3D] = (-8192).to_bytes(2, "little", signed=True)
    gx, gy, gz = decode_motion(bytes(raw))
    assert 0.49 < gx < 0.51
    assert -0.26 < gy < -0.24
    assert -0.26 < gz < -0.24


def test_sprint_latch_rides_through_flicker():
    from switch2mod.sticks import update_sprint_latch
    on, t = update_sprint_latch(False, True, 1.0, 0.0)
    assert on is True
    on2, _ = update_sprint_latch(on, False, 1.10, t)
    assert on2 is True  # 100ms dropout must not drop the run
    on3, _ = update_sprint_latch(on, False, 1.50, t)
    assert on3 is False


def test_sprint_latch_ignores_flicker_after_long_hold():
    """A missed report must not cut sprint after L3 has been held awhile."""
    from switch2mod.sticks import update_sprint_latch
    on, seen = update_sprint_latch(False, True, 1.0, 0.0)
    on, seen = update_sprint_latch(on, True, 2.0, seen)
    on, seen = update_sprint_latch(on, True, 3.0, seen)
    on, _ = update_sprint_latch(on, False, 3.01, seen)
    assert on is True


def test_ads_latch_debounces_paddle_chatter():
    from switch2mod.sticks import update_ads_state
    on, t = update_ads_state(False, 1.0, 1.0, 0.0)
    assert on is True
    on2, _ = update_ads_state(on, 0.0, 1.05, t)
    assert on2 is True  # 50ms dropout must not flip to hipfire shaping
    on3, _ = update_ads_state(on, 0.0, 1.50, t)
    assert on3 is False


def test_ads_shaping_kills_antideadzone_jump():
    from switch2mod.config import AppConfig
    from switch2mod.sticks import process_sticks
    cfg = AppConfig(aim_assist=100, right_deadzone=0.02,
                    right_antideadzone=0.15, right_stick_sensitivity=2.0,
                    curve_power=2.4, response_curve="aggressive",
                    ads_damping=1.0, gyro_enabled=False)
    _, _, hip, _ = process_sticks(cfg, 0.0, 0.0, 0.08, 0.0, ads_held=False)
    _, _, scoped, _ = process_sticks(cfg, 0.0, 0.0, 0.08, 0.0, ads_held=True)
    assert abs(scoped) < abs(hip)
    # Booster check: big deliberate flicks must stay HOT scoped, not muddy.
    # Old caps (sens 1.25 + flat curve + 0.7 damp) made ADS crawl.
    _, _, hip_big, _ = process_sticks(cfg, 0.0, 0.0, 0.6, 0.0, ads_held=False)
    _, _, scoped_big, _ = process_sticks(cfg, 0.0, 0.0, 0.6, 0.0, ads_held=True)
    assert abs(scoped_big) >= 0.8 * abs(hip_big)


def test_ads_recenter_reduces_residual_near_stick_center():
    from switch2mod.config import AppConfig
    from switch2mod.sticks import process_sticks
    cfg = AppConfig(aim_assist=100, ads_recenter_enabled=True,
                    ads_recenter_speed=10.0, ads_damping=1.0,
                    right_deadzone=0.02, right_antideadzone=0.0,
                    right_stick_sensitivity=1.0, gyro_enabled=False)
    _, _, recentered, _ = process_sticks(cfg, 0.0, 0.0, 0.10, 0.0, ads_held=True)
    cfg.ads_recenter_enabled = False
    _, _, baseline, _ = process_sticks(cfg, 0.0, 0.0, 0.10, 0.0, ads_held=True)
    assert abs(recentered) < abs(baseline)


def test_l3_hold_boosts_partial_tilt_to_sprint_gate():
    from switch2mod.sticks import ensure_sprint_magnitude
    import math
    x, y = ensure_sprint_magnitude(0.0, -0.80)
    assert math.hypot(x, y) >= 0.999
    x0, y0 = ensure_sprint_magnitude(0.0, 0.0)
    assert (x0, y0) == (0.0, 0.0)


def test_rear_paddle_mapping_sets_requested_outputs():
    from switch2mod.rear import apply_rear
    from switch2mod.config import RearMap
    out = {"A": False, "LB": False, "RT": False}
    trig = {"LT": 0.0, "RT": 0.0}
    apply_rear(out, RearMap(gl_as="LB", gr_as="RT"),
               {"gl": True, "gr": True}, triggers=trig)
    assert out["LB"] is True and trig["RT"] == 1.0


def test_gyro_can_tune_both_sticks_independently():
    cfg = AppConfig(gyro_enabled=True, gyro_left_enabled=True,
                    gyro_right_enabled=True, gyro_ads_only=False,
                    gyro_left_sensitivity=0.5, gyro_right_sensitivity=1.0,
                    right_deadzone=0.0, left_deadzone=0.0)
    lx, ly, rx, ry = __import__("switch2mod.sticks", fromlist=["process_sticks"]).process_sticks(
        cfg, 0.0, 0.0, 0.0, 0.0, gyro_x=0.2, gyro_y=-0.1)
    assert round(lx, 3) == 0.1 and round(rx, 3) == 0.2
    assert round(ly, 3) == -0.05 and round(ry, 3) == -0.1


def test_capture_recommends_both_gyro_routes():
    from capture_controller_samples import gyro_recommendation
    rec = gyro_recommendation({"gyro_yaw_left": [{"changed_percent": 50}]})
    assert "left_stick" in rec and "right_stick" in rec
    assert rec["left_stick"]["sensitivity"] != rec["right_stick"]["sensitivity"]


def test_capture_requires_both_physical_sticks():
    from capture_controller_samples import stick_capture_status
    captures = {name: [b"sample"] for name in (
        "left_stick_left", "left_stick_right", "left_stick_up",
        "left_stick_down", "left_stick_circle")}
    status = stick_capture_status(captures)
    assert status["left_stick_complete"] is True
    assert status["right_stick_complete"] is False
