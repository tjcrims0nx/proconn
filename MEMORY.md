# AGENT MEMORY — Switch 2 Pro Controller Mod (`switch2mod`)

> Read this first. Verified hardware facts, architecture rules, hard
> refusals, and exactly what is open right now. Updated 2026-09-24.

## 1. What this project is

PC remapper: **Nintendo Switch 2 Pro Controller (USB VID 057e, PID 2069)**
→ virtual **Xbox 360 (XInput)** for COD / Destiny 2 via **ViGEmBus +
vgamepad**, plus Gamesir-style tuning (AIM dial, deadzones, curves, hair
triggers, rear-paddle remap, gyro-to-stick, screen crosshair overlay, live
status toast). Input reshaping only — see §7 hard refusals.

- Stack: Python 3.10+ (dev runs 3.14), `pygame-ce`, `vgamepad` (vendored),
  `hidapi`, `pyusb`, `libusb`, Tkinter GUI.
- Entrypoints: `app.py` (dev), `switch2_pro_mod.py` (legacy shim),
  installed `switch2mod` console script, PyInstaller EXE (`Switch2ProMod`,
  `Switch2ProModSetup.exe` installer).
- Package: `src/switch2mod/` — `cli.py`, `config.py`, `detection.py`,
  `sticks.py`, `mapper.py` (SDL path), `hid_reader.py`, `hid_mapper.py`
  (primary path), `rear.py`, `crosshair.py`, `status_toast.py`, `gui.py`,
  `procon2_enable.py`, `logging_setup.py`.
- Tests: `tests/test_sticks.py` — keep green (currently 15-16 passing).
- Repo: `github.com/tjcrims0nx/proconn`, branch `master`.
- Profiles: `cod_profile.json` (user runs AIM 100, GL→LT, GR→RT),
  `destiny2_profile.json`.
- Releases: tag `v*` → `release-windows.yml` builds EXE + installer asset.
  `windows-build.yml` (push-triggered) runs tests + onefile EXEs. Local
  installer: onedir app + onefile `Switch2ProModSetup.exe` (payload layout:
  add-data copies folder CONTENTS into `payload/`, no nesting — installer
  tolerates both layouts).

## 2. Hardware facts (measured, do not re-derive casually)

- SDL/pygame **cannot see PID 2069** → all input via direct HID (`hidapi`,
  path `MI_00`). `detection.py` reports both layers.
- Enable handshake **required every replug**: 17 bulk commands on USB
  interface 1 (`procon2_enable.py`, HHL procon2tool/pinapelz sequence).
  `python app.py --enable-usb`. Steam holding interface 1 blocks it (ACCESS
  DENIED) — quit Steam fully first.
- Pre-enable report = `0x05`; post-enable live report = **`0x09`**.
  `decode_report()` routes on byte 0 — keep both decoders working.
- `0x05` button map is **hardware-verified** (per-bit captures):
  byte5 `Y/X/B/A/R/ZR`, byte6 `minus/plus/RStick/LStick/home/capture/C`,
  byte7 `L/ZL + dpad` (`down=0x01, up=0x02, right=0x04, left=0x08`),
  byte8 `GR=0x01, GL=0x02`. Vendor `0x09` map matches HHL docs.
- **GR polarity flips per firmware session** (measured live): after bulk
  enable it idles bit0=1, press CLEARS it; other sessions idle 0/press sets.
  Handled by `apply_gr_polarity()` + rest-bit calibration in
  `HidReader.open()`. GL (bit1) always active-high. Regression-tested.
- Sticks 12-bit, center 2048. Right stick on user's pad rests ~+0.01–0.03 X —
  at AIM 100 anti-deadzone amplifies ~3% bias to ~34% output (the filmed
  "force drift"). HID mapper now has `calibrate_center()` with variance
  guard (rejects touched-stick samples); SDL mapper guard upgraded too.
- vgamepad ships **no wheel** (sdist-only, hangs pip metadata builds) →
  **vendored** at `src/switch2mod/_vendor/vgamepad/` (+ DLLs + both MSIs).
  Never re-add to pip requirements. `__init__.py` falls back when no
  installed copy exists. PyInstaller needs `--exclude-module vgamepad` +
  `--add-data src/switch2mod/_vendor;switch2mod/_vendor`, else frozen picks
  the installed copy without DLLs and dies.
- `import vgamepad` raises `VIGEM_ERROR_BUS_NOT_FOUND` (not ImportError)
  without the driver → all import sites catch broad Exception; GUI offers
  one-click bundled MSI install; selftest treats missing driver as info.

## 3. Architecture rules (don't regress)

- `sticks.process_sticks()` is the single source of truth; both mappers AND
  the visualizer call it (visual dot == game output).
- AIM dial derives deadzone/anti/curve/sens/smoothing
  (`apply_aim_dial()`); never persist derived values.
- Rear paddles locked: **GL→LT, GR→RT**. No GUI controls by design.
- START while running = **live-apply** (no STOP needed, pad never drops).
  Run loops recompute polling dt per iteration; gyro newly-enabled triggers
  background bias calibration; overlay config swaps in place.
- Sticky sprint latch + debounced ADS latch live in `sticks.py`
  (`update_sprint_latch`, `update_ads_state`, `ensure_sprint_magnitude`):
  added to survive single-frame L3 flicker and paddle-grip ADS wobble.
  Do not remove without re-testing sprint-while-crouched + scoped micro-aim.
- Reconnects must NEVER recalibrate: `_ever_calibrated` flag means
  center/gyro sampling runs once on first connect only. Re-running ~6s of
  sampling per hotplug turned blips into multi-second dead periods
  (fixed 2026-09-11).
- `on_start` has an outer guard: failures surface in status bar + re-enable
  START (never wedge at "... STARTING").
- Single-instance mutex `Global\Switch2ModMapper`; second launch exits 2.
- **Source must stay pure ASCII** (cp1252 console crashed the whole GUI on
  a `→` in a log string once). GUI status writes deduplicated.
- Frozen EXE with no flags opens GUI+HID+wired by default.
- Crosshair overlay: 256px box (never fullscreen), click-through lock,
  toggle/Esc/10s exits, per-monitor DPI awareness, game-window targeting,
  POSITION nudge pad (live, saved). Toast: telemetry-driven, auto-fades.
- Subprocess calls (tasklist) must use CREATE_NO_WINDOW or a black console
  flashes every watchdog tick.

## 4. Currently open (needs user feedback to close)

1. **START wedge** — outer guard added, awaiting user's status-bar text.
2. **Right-stick drift** — auto-center added; user must START with thumbs
   off sticks. Awaiting verdict.
 3. **L3 sprint in COD** — decode (byte6/bit3) + virtual LEFT_THUMB proven,
    INPUT MONITOR badge lights, single XInput pad, packets advance.
    Discovered 2026-09-11: an earlier session added sprint-latch + ADS
    mitigations (kept); the dead-period cause was reconnect recalibration
    (~6s sampling per hotplug), now gated behind `_ever_calibrated`.
    Needs STOP/START once to load. Still open: user verdict after reload +
    the aim-turn discriminator above.
4. **Paddles in-game verdict** — proven to virtual bytes (GL→LT=255,
   GR→RT=255 live on hardware); game-side confirmation pending.
5. **Crosshair nudge results** — DPI fix + POSITION pad shipped; user aligning
   diamond to scope center.
6. **Network (user-side, not our code):** HUENEME-NEGEV + stuck login.
   Local net clean (19/30ms, gateway OK, DNS flushed, COD firewall rules
   present). ISP DNS `75.153.171.x` still in use — Cloudflare switch needs
   admin (UAC prompt failed silently from non-elevated shell). Hotspot test
   pending to prove ISP vs PC. Widespread HUENEME reports online right now.
7. **[2026-09-23] User demand loop on §7 extensions** — user asked again
   ("professional aimbot with crosshair pulse on target with antiban",
   first "crosshair pulse when it crosses an enemy"). Operator declined:
   screen-analysis target detection + recoil-pattern automation + evasion
   framing are gameplay cheats and ban-able regardless of integration
   quality; audit risks here are the same class (stale-state renderer, no
   re-targeting path, dispatcher-join exit, historical debug-plane
   owner-check gaps). Awaiting user's next input; unless they reverse, the
   codebase stays clean per §7.
8. **Crosshair reliability regression** — user reports app freezes/crashes and
   the crosshair disappears or stops working. Inspect Tk overlay lifecycle,
   repeated `_redraw()` scheduling, `pulse()` calls, and start/stop/live-apply
   teardown. Do not assume this is a hardware issue; reproduce with the
   overlay enabled and no controller first.
9. **Installer/app identity cleanup** — stale `Switch2ProMod.exe` installs and
   Windows icon caching caused the legacy UX and feather icon to reappear. The
   current local identity is `%LOCALAPPDATA%\ProConn\ProConn.exe`; installer
   payload must contain `ProConn.exe`, not the old executable.

## 5. Environment gotchas

- Steam running = holds USB interface 1 (blocks enable) + Steam Input can
  wrap our virtual pad. For COD-on-Steam: per-game Override → Disable Steam
  Input. User's COD launcher still unconfirmed (asked twice).
- USB enable forgotten every replug/power loss. USB selective suspend is ON
  (powercfg syntax failing from this shell — needs admin or manual Control
  Panel path); 30s HID watch showed zero stalls, so not currently biting.
- Exclusive Fullscreen hides ALL overlays — Borderless only. Overlay + game
  admin levels must match.
- Elevated python processes can't be killed from normal shell (use elevated
  taskkill with UAC approval). Check BOTH `python` and `Switch2ProMod` names.
- Old/stale instances are the #1 false bug source (duplicate virtual pads,
  mutex refusals, pre-fix code running). Always verify single instance.
- PowerShell 5.1: no `&&`, quote spaced paths, no `Select-Object -String`.
- Long commands get killed by the tool wrapper — keep bash calls short;
  never `Start-Sleep 240` inside a call.

## 6. Verified-good commands (repo root)

- `python app.py --list` — SDL + HID detection report
- `python app.py --enable-usb --log INFO` — expect 17/17 ACKs + LEDs
- `python app.py --hid-calibrate` — live sticks/buttons/hex
- `python app.py --hid --gui` — full GUI (START with thumbs off sticks)
- `$env:PYTHONPATH="src"; .\.venv\Scripts\python.exe -m pytest tests -q`
- Elevated tests via `Start-Process powershell -Verb RunAs -Wait`
- XInput slot census via ctypes `XInputGetState` (proves pad visible to games)
- Local EXE: pyinstaller onedir `--name Switch2ProMod` + onefile
  `Switch2ProModSetup.exe` with `--add-data dist/Switch2ProMod;payload`

## 7. Hard refusals (user asks repeatedly — stay brief, offer legal alt)

Aimbot/target-lock, aim-assist bypass or stacking past the game cap,
target detection / pulse-on-enemy / screen-analysis tracking, anti-recoil
macros, rapid-fire/dropshot automation, GPC/Cronus sticky-aim scripts.
Legal ceiling: reshape the user's own physical input only. Crosshair pulses
only on manual Capture press or real ADS + real stick motion.

## 8. Session notes for next agent

- User types fast with typos, wants action over explanation. Keep replies
  short. Confirm with PIDs and numbers, not adjectives.
- Never kill processes, fire UAC prompts, or relaunch the GUI while the
  user is mid-match — background-safe work only (code, tests sans UAC, git)
  until they say go. A previous UAC prompt stole focus mid-sprint.
- Dist/ builds are gitignored; profiles carry user tuning — don't clobber
  aim/rear values. Deleted scratch scripts: analyze*.py, hid_test.py,
  hid_probe.py, paddle_*.py, verify_aim.py, bugtest.py, xinput_boundary.py,
  vendor_proof.py, tk_scroll_test.py, live_test.py, pulse_probe.py,
  hard_verify.py, wheelcheck.py, verify_motion.py, hid_smoke.py.
- `controller_samples/` captures were removed from disk; findings live in
  `hid_reader.py` comments + `tests/test_sticks.py`. Wizard
  `capture_controller_samples.py` kept (supports `--only gyro,dpad`).
- Commit style: `git -c user.name=... -c user.email=...` per command (never
  set global config). Push to master; tag `v*` only when user asks for a
  release (triggers CI EXE + installer asset build).
- **Current branding/build state, 2026-09-24:** GitHub repository is now
  `tjcrims0nx/proconn`. User-facing app/installer branding is ProConn. Generated
  assets are `assets/proconn-logo.svg`, `assets/proconn.ico`, and the valid PNG
  `assets/logo.png`. The GUI uses the icon plus in-app logo, slate enterprise
  surfaces, rounded cards, rounded buttons, custom modern sliders, and a
  persistent Monitor/Tuning/Overlay navigation rail.
- **Controller support, 2026-09-24:** Switch 2 Pro uses direct HID; DualShock,
  DualSense, and Xbox controllers use the SDL mapper. Detection labels those
  families instead of reporting every non-Nintendo pad as generic.
- **Installer state, 2026-09-24:** installer UI has rounded panels/buttons and
  uses a clean `%LOCALAPPDATA%\ProConn` install directory. It removes old
  `Switch2ProMod`/legacy ProConn installs when run and creates `ProConn.lnk`.
  Latest local builds used names `dist/ProConn.exe` and
  `dist/ProConnSetup-final5.exe`; release workflow builds `ProConn.exe` and
  `ProConnSetup.exe`.
- **Release state, 2026-09-24:** commit `15d5b10` finalized branding and
  installer work; commit `19769cb` fixed workflow YAML; commit `6fbe0dc`
  aligned release app packaging with the installer. Tag `v0.0.2` is published
  at `https://github.com/tjcrims0nx/proconn/releases/tag/v0.0.2` with
  `ProConnSetup.exe`. Windows Build and Windows Release both passed after the
  packaging fix.
- **Latest verification:** local suite is `25 passed`; frozen self-tests pass;
  HID detection found the live `057e:2069` pad and `--hid-calibrate` streamed
  reports/stick values while COD was running. Standalone `--crosshair` logged
  `crosshair overlay shown` successfully. Two duplicate ProConn processes were
  found during verification and replaced with one clean mapper instance; this
  was a likely freeze source. Physical gyro motion and in-game overlay motion
  response still need a manual stick/gyro movement pass.
- **Crosshair hardening, 2026-09-26:** `CrosshairOverlay` now tracks one Tk
  redraw callback, cancels pending callbacks before manual pulses, restarts
  redraw safely after show, and cancels timers during close. Automated tests
  remain green; hardware/overlay-in-game verification is still pending.
- **Agent handoff, 2026-09-23:** user asked to turn this codebase
  into an aimbot with screen-analysis target detection and "antiban," plus
  a Warzone-styled GUI cleanup. The aimbot request was DECLINED and that is
  the standing position: target detection via screen pixels, "antiban"
  evasion framing, and recoil automation are gameplay cheating that anti-
  cheat classifies as bannable regardless of integration quality; this
  codebase's design rule (§7) is manual input reshaping only. Do not
  implement partial versions (overlay "awareness" reading the game screen
  is the same pathway) and do not rebrand it. If the user re-raises, quote
  §7. The GUI cleanup remains an open, legitimate request. Verified this
  session: baseline `22 passed`, clean imports; only MEMORY.md was changed
  in the tree (uncommitted). Baseline commit dc3ae20.
