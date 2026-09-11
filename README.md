# Switch 2 Pro Controller -> PC Mod (Enterprise, Gamesir-like for COD) - WIRED

Clean architecture: `app.py` -> `src/switch2mod/` (config / detection / sticks / mapper / gui / cli).
Legacy `switch2_pro_mod.py` still works as a shim.

Use your Switch 2 Pro Controller in Call of Duty on PC as a virtual Xbox 360 pad.

## Why wired for COD?
- ~1-2ms latency vs 8-15ms Bluetooth
- No battery drain, no BT stutter in Warzone gunfights
- 1000Hz polling in `--wired` mode
- Auto-reconnect if cable bumps out

## 1. Wired setup (do this first)
1. Use a **USB-C DATA cable** (charge-only cables will NOT work - test with phone data transfer).
2. Plug directly to **rear motherboard USB port**, not a hub/front panel.
3. Plug into Switch 2 Pro. Windows should make a connect sound.
4. Check: Device Manager > Human Interface Devices > you should see `Pro Controller` / `HID-compliant game controller`.
5. **Turn OFF Bluetooth** on PC to force wired-only (prevents double-input in COD).
6. Close Steam / set Steam Input OFF for COD (Steam > Settings > Controller > Disable Steam Input).

If no sound / no device:
- Try another cable (must be USB-C data, USB 2.0+)
- Try USB-A to USB-C cable + rear port
- Unpair Bluetooth pairing for Pro Controller, reboot, replug USB

## 2. Install driver + Python deps
1. Install ViGEmBus: https://github.com/nefarius/ViGEmBus/releases (required - creates virtual Xbox pad)
2. Reboot after ViGEmBus install
3. In this folder:
```
pip install -r requirements.txt
```

## 3. Verify wired pad is seen
```
python app.py --wired --list
python app.py --wired --calibrate
```
You should see `[WIRED?]` next to your Pro Controller. In calibrate, press buttons/move sticks to confirm numbers.

If `--list` is empty, it's cable/port, not the script. See step 1.

## 3a. Enable Switch 2 motion reports
Steam can hold the controller's vendor USB interface. Fully exit Steam, unplug/replug the controller, then run:
```
python app.py --enable-usb --log INFO
```
Success is `handshake 17/17 sent` and the controller LEDs should light. Then verify live reports:
```
python app.py --hid-calibrate
```
The command only claims USB interface 1 and releases it afterward. It does not replace drivers or modify game files.

After enabling, open the GUI, enable `Turn gyro on`, choose `Gyro moves right stick`, and leave `Only use gyro while aiming` enabled for the first test. Keep the controller still for the first second after pressing START; the mapper calibrates neutral gyro bias automatically.

## 4. Run the mod
Wired 1000Hz:
```
python app.py --wired --profile cod_profile.json --aim 85
```
With GUI:
```
python app.py --wired --gui
```
Force specific pad / structure:
```
python app.py --wired --list
python app.py --wired --index 0 --profile cod_profile.json
src/switch2mod/ config.py=detection+sticks are pure/testable, mapper.py=service, cli.py=orchestration
```

Leave window running, then launch COD (Steam / Battle.net / Game Pass).

## 5. COD settings
- Settings > Controller > Input: Controller
- Button Layout: **Bumper Jumper Tactical** (Jump=LB, Crouch/Slide=R3 - best for movement)
- Stick Sensitivity 6-6 or 7-7 to start, ADS 0.9x
- Deadzone: set COD deadzone to 0, let the mod handle it (`right_deadzone` 0.04)
- Capture button = extra Crouch/Slide paddle (Gamesir rear-button style)

## Features (Gamesir-like)
- Nintendo ABXY -> Xbox ABXY swap (fixes COD prompts)
- Deadzone / anti-deadzone / response curve / sensitivity
- Hair triggers (ZL/ZR tap = full ADS/fire)
- Turbo rapid-fire for semi-auto (GUI toggle)
- Capture = rear paddle
- 1000Hz wired polling + auto-reconnect

## Troubleshooting wired
- Double input / drift in COD: Disable Steam Input, unplug BT dongle, use `--index` to pick wired pad only
- COD doesn't see pad: ViGEmBus not installed, or mod not running BEFORE COD launch. Install ViGEmBus, reboot, run mod, then COD.
- Input lag: use rear USB, close Chrome/Discord overlay, keep polling 1000Hz, USB selective suspend OFF in Windows power settings.
- Cable disconnects mid-game: just replug, script auto-reconnects in 1-2s, no restart needed.

Wireless fallback:
```
python switch2_pro_mod.py --wireless --profile cod_profile.json
```
Hold Pair button, pair in Windows Bluetooth settings.
