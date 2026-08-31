# ADeck

A little Stream Deck for your desk — but it's an Arduino UNO R4 WiFi with a 2.4" touchscreen. You edit six buttons in a local web app (labels, colors, Windows commands). Commands run on your PC; the board just stores what to show on the TFT.

## Features

- Six customizable buttons with labels and colors
- Multiple profiles, saved locally
- Touch the screen → runs the mapped command on Windows
- Installs as a desktop app (own window, desktop + Start Menu icon) — no URL typing
- System page in the app: status, restart, reconnect, repair, firmware, logs
- Web UI at `http://127.0.0.1:8765` — no internet needed
- Auto-detects the UNO R4 WiFi COM port (no hardcoded COM3 nonsense)
- Save in the browser syncs config to the board over USB
- Survives unplug/replug and board resets (EEPROM on the Arduino side)

## Hardware

You need:

- Windows 10 or 11
- Arduino **UNO R4 WiFi** (other UNO models won't work)
- 2.4" ILI9341 display + resistive touch, wired per `firmware/ADeck/ADeck.ino`
- A **data** USB cable (charge-only cables are useless here)

Board FQBN: `arduino:renesas_uno:unor4wifi`

## How it works

```
Browser (index.html)  →  deck.py (:8765)  →  USB serial  →  UNO R4 WiFi  →  TFT
```

1. `deck.py` is the local backend. It serves the web UI, holds your profiles, and talks to the board.
2. The firmware on the UNO draws buttons and listens for touch.
3. When you hit Save, config goes serial → board → screen updates.
4. When you touch a button, the board sends `PRESS` over serial and `deck.py` runs your Windows command.

Protocol handshake: `ADECK_PING` / `ADECK_PONG` (version 2).

## Project structure

```text
ADeck-Control.bat      control menu (start, check, repair, logs…)
Setup ADeck.bat        first-time installer
Start ADeck.bat        daily launcher
adeck.bat              alias for ADeck-Control.bat

deck.py                backend + serial bridge
adeck_control.py       CLI for the control menu
install_firmware.py    flash / verify UNO firmware
install.ps1            setup script (called by Setup ADeck.bat)

index.html             web UI
script.js
style.css
manifest.webmanifest   desktop-app manifest (installable window)
sw.js                  service worker (app shell cache, never caches /api)
icon-192.png           app icons
icon-512.png
icon-maskable-512.png
adeck.ico              Windows shortcut / favicon icon

firmware/ADeck/ADeck.ino   Arduino sketch

requirements.txt
test_reliability.py
```

Generated at runtime (gitignored): `.venv/`, `.tools/`, `.build/`

User data lives outside the repo:

```text
%APPDATA%\ADeck\config.json       profiles
%LOCALAPPDATA%\ADeck\             logs, runtime lock, board identity
```

## Install

1. Plug in the UNO R4 WiFi with a data cable.
2. Close Arduino Serial Monitor and anything else using the COM port.
3. Double-click **Setup ADeck.bat**.
4. Wait for "ADeck is ready" with Web and Hardware status.
5. ADeck opens in its own app window, and you get an **ADeck** icon on the desktop and in the Start Menu.

That's it. You don't need to know Python.

Setup also registers the `adeck://` handler so the app can start the service on demand.
To add ADeck as a browser-installed app too, use **INSTALL APP** on the System page (or your
browser's "Install ADeck" menu item).

Manual install if you prefer:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

Setup creates `.venv`, installs deps, bundles Arduino CLI if needed, flashes firmware only when `ADECK_PONG` isn't already working, starts the backend, and adds a Windows Startup shortcut — but only if everything actually passes.

## Daily use

Open the **ADeck** icon (desktop or Start Menu). It starts the service if needed and opens the
app window. After a good install, ADeck also starts with Windows.

Everything normal lives in the app's **System** page:

| Section | What you can do |
| --- | --- |
| Status | service, hardware, COM port, firmware, sync, config, setup state |
| Device | reconnect the board, pin a COM port, resync to device |
| Service control | restart, stop, view log, open log folder |
| Desktop app | install app window, create desktop icon, start with Windows |
| Advanced | Check System, Show Errors, Install / Repair, Reinstall Firmware |

Output from Check System / Repair / Firmware / Restart streams into the app, and keeps streaming
while the service restarts.

Fallbacks (still supported, no longer the normal path):

- **Start ADeck.bat** — starts the backend if needed, opens the browser when ready
- **ADeck-Control.bat** — the same maintenance from a terminal menu

Control menu:

```text
[1] Start ADeck
[2] Check System
[3] Install / Repair
[4] Reinstall Firmware
[5] View Logs
[6] Stop ADeck
[7] Show Latest Errors
[8] Status Summary
[9] Exit
```

Save in the web UI updates local config and pushes the active profile to the TFT. If USB is unplugged, the UI still works — it'll resync when the board comes back.

## Troubleshooting

First move: open ADeck → **System** page. The banner at the top names the problem and offers the
matching action. **Check System** there prints the same report as the control menu.

If the app window says "ADeck service is not running", use **START SERVICE** (uses `adeck://`), or
open the ADeck desktop icon. The window itself loads from cache, so it can explain the state even
while the service is down.

Terminal fallback: **ADeck-Control.bat → Check System**.

Quick checks:

```powershell
.\.venv\Scripts\python.exe .\adeck_control.py check
.\.venv\Scripts\python.exe .\adeck_control.py status
curl http://127.0.0.1:8765/api/status
```

## Firmware update

Normal installs skip reflash if firmware already responds to `ADECK_PONG`.

To force a reflash: **ADeck-Control.bat → Reinstall Firmware**

Or from a terminal:

```powershell
.\.venv\Scripts\python.exe .\install_firmware.py
.\.venv\Scripts\python.exe .\install_firmware.py --if-needed
.\.venv\Scripts\python.exe .\install_firmware.py --cli-only
```

## Common problems

**"Python was not found"** — run Setup ADeck.bat first.

**Board not detected** — data cable, only one UNO connected, close Serial Monitor.

**Backend up but hardware offline** — unplug/replug USB, then Check System or Install / Repair.

**Port already in use / stale runtime** — Control → Stop, then Start. If that fails, Install / Repair.

**Opening index.html directly** — won't work. You need `deck.py` running on :8765. Use Start ADeck.bat.

## Recovery

If automatic 1200-bps bootloader recovery fails during firmware install:

1. Double-press the UNO R4 WiFi **RESET** button.
2. Press Enter at the installer prompt right away.
3. Keep USB plugged in (~20 seconds while it scans).

Still stuck? Control → Reinstall Firmware. Don't swap in a different Arduino model or guess a COM port.

Nuclear option:

```powershell
# stop backend
.\.venv\Scripts\python.exe .\adeck_control.py stop
# remove generated stuff, then rerun Setup
Remove-Item -Recurse -Force .venv, .tools, .build -ErrorAction SilentlyContinue
.\Setup ADeck.bat
```

## Logs

Logs live in `%LOCALAPPDATA%\ADeck\`:

- `adeck.log` — main app log
- `runtime.stdout.log` / `runtime.stderr.log` — backend process output

Control menu → **View Logs** opens that folder. **Show Latest Errors** prints recent error lines without dumping full tracebacks at you.

## COM auto-detect

No hardcoded COM ports. Detection uses Arduino CLI board list (VID/PID, serial number) and falls back through available ports. The backend re-discovers the board after USB reconnect. Board identity is cached in `%LOCALAPPDATA%\ADeck\board.json`.

## Git clone

```powershell
git clone <your-repo-url> ADeck
cd ADeck
.\Setup ADeck.bat
```

Don't commit `.venv`, `.tools`, or `.build` — they're in `.gitignore`.

## Developer section

Debug logging:

```powershell
$env:ADECK_DEBUG = "1"
.\.venv\Scripts\python.exe .\adeck_control.py check --debug
.\.venv\Scripts\python.exe .\deck.py --debug
```

Backend control:

```powershell
.\.venv\Scripts\python.exe .\adeck_control.py start
.\.venv\Scripts\python.exe .\adeck_control.py stop
.\.venv\Scripts\python.exe .\adeck_control.py restart
.\.venv\Scripts\python.exe .\adeck_control.py repair
```

Desktop app integration:

```powershell
.\.venv\Scripts\python.exe .\adeck_control.py app          # start service + app window
.\.venv\Scripts\python.exe .\adeck_control.py shortcuts    # desktop + Start Menu icons
.\.venv\Scripts\python.exe .\adeck_control.py autostart     # --disable to turn off
.\.venv\Scripts\python.exe .\adeck_control.py protocol      # register adeck://
.\.venv\Scripts\python.exe .\adeck_control.py integrate     # all of the above
```

API used by the System page (localhost, same-origin only):

```text
GET  /api/status          service + device state
GET  /api/system          service, device, ports, config, environment, integration
GET  /api/logs?source=app|stdout|stderr&lines=N
GET  /api/tasks           recent maintenance tasks
GET  /api/tasks/<id>      one task with live output
POST /api/control         {"action": "reconnect|resync|open-logs|restart|stop|check|
                            errors|repair|reinstall-firmware|autostart-on|autostart-off|
                            create-shortcuts|remove-shortcuts|register-protocol"}
```

Run tests:

```powershell
.\.venv\Scripts\python.exe -m py_compile deck.py adeck_control.py install_firmware.py
.\.venv\Scripts\python.exe -m unittest test_reliability.py
```

JS syntax check:

```powershell
node --check script.js
```

## From-scratch verification

Handy checklist if you're changing something big:

- Delete `.venv`, `.tools`, `.build`, and the ADeck Startup shortcut
- Run Setup ADeck.bat with hardware connected — every stage should pass
- Confirm the ADeck desktop/Start Menu icon opens the app window (no browser tab)
- Stop the service, reopen the app window — it must load and explain the state, not error out
- Confirm `ADECK_PONG 2` after a required flash
- Confirm `/api/status` is healthy with `connected: true`
- Save a six-button profile, confirm TFT ACK
- Reset the board — EEPROM labels/colors should survive
- Press each touch target — commands should fire
- Disconnect/reconnect USB — rediscovery + resync
- Re-run install — healthy firmware should NOT get reflashed
- Run Start ADeck.bat twice — only one backend instance
- Break something on purpose — installer should NOT claim success, open browser, or create Startup shortcut
