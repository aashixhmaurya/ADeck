"""Dev-only: watch physical key presses / Calculator launch. Not part of the product path."""
import ctypes
import ctypes.wintypes
import json
import subprocess
import time
import urllib.request
from pathlib import Path

LOG = Path.home() / "AppData/Local/ADeck/adeck.log"
OUT = Path(__file__).resolve().parent / "_keypress_monitor_result.txt"
CALC_NAMES = {"calculatorapp", "calculator", "win32calc"}


def calc_pids():
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "(Get-Process CalculatorApp,Calculator,win32calc -ErrorAction SilentlyContinue "
            "| Select-Object -ExpandProperty Id) -join ','",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return {pid for pid in (result.stdout or "").strip().split(",") if pid}


def fg_info():
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    pid = ctypes.wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            f"(Get-Process -Id {pid.value} -ErrorAction SilentlyContinue).ProcessName",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return (result.stdout or "").strip(), pid.value


def backend_status():
    try:
        with urllib.request.urlopen("http://127.0.0.1:8765/api/status", timeout=2) as resp:
            return json.loads(resp.read().decode())
    except Exception as error:
        return {"ok": False, "error": str(error)}


def main():
    lines = []

    def log(message):
        print(message, flush=True)
        lines.append(message)

    subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-Process CalculatorApp,Calculator,win32calc -ErrorAction SilentlyContinue | Stop-Process -Force",
        ],
        check=False,
    )
    time.sleep(1)

    status = backend_status()
    base_pids = calc_pids()
    base_size = LOG.stat().st_size if LOG.is_file() else 0
    fg_name, fg_pid = fg_info()

    log("=== ADeck physical key monitor ACTIVE (retry) ===")
    log("Press physical ADeck key 1 (Calculator) exactly once now.")
    log(
        "Backend connected: "
        f"{status.get('connected')} port={status.get('port')} sync={status.get('last_sync')}"
    )
    log("Active profile: Test | key1 command: calc.exe")
    log(f"Baseline calculator PIDs: {sorted(base_pids) or 'none'} (closed any prior Calculator)")
    log(f"Baseline foreground: {fg_name} ({fg_pid})")
    log("Monitoring for up to 180 seconds...")

    deadline = time.time() + 180
    launch_detected = False
    foreground_hit = False

    while time.time() < deadline:
        now_pids = calc_pids()
        new = now_pids - base_pids
        fg_name_now, fg_pid_now = fg_info()
        if fg_name_now.lower() in CALC_NAMES:
            foreground_hit = True
        if new and not launch_detected:
            launch_detected = True
            log(f"CALCULATOR LAUNCHED new pid(s): {sorted(new)}")
            log(f"Foreground at launch check: {fg_name_now} ({fg_pid_now})")
            log(f"Calculator is foreground: {fg_name_now.lower() in CALC_NAMES}")
            time.sleep(2)
            fg_name_later, fg_pid_later = fg_info()
            log(f"Foreground +2s after launch: {fg_name_later} ({fg_pid_later})")
            log(f"Calculator is foreground +2s: {fg_name_later.lower() in CALC_NAMES}")
            break
        time.sleep(0.5)

    if not launch_detected:
        log("No new calculator process detected during monitoring window.")
        if foreground_hit:
            log("Calculator became foreground at some point without a new PID.")

    new_log = ""
    if LOG.is_file():
        with LOG.open("r", encoding="utf-8", errors="replace") as handle:
            handle.seek(base_size)
            new_log = handle.read().strip()

    log("--- new adeck.log lines during window ---")
    log(new_log or "(none)")

    press_logged = "Physical press received for key" in new_log
    dispatch_logged = "Dispatching command for key" in new_log
    error_logged = "Command for key" in new_log and "failed" in new_log

    log(f"PRESS event logged: {press_logged}")
    log(f"Command dispatch logged: {dispatch_logged}")
    log(f"Command error logged: {error_logged}")

    if press_logged and launch_detected:
        log("RESULT: Backend received press, dispatched calc.exe, Calculator launched.")
    elif press_logged and dispatch_logged and not launch_detected:
        log("RESULT: Backend received press and dispatched command, but Calculator did not start.")
    elif press_logged and not dispatch_logged:
        log("RESULT: Backend received press but no command was dispatched (empty command?).")
    elif not press_logged and launch_detected:
        log("RESULT: Calculator launched without a logged PRESS event (unexpected).")
    else:
        log("RESULT: No evidence that press reached backend.")

    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
