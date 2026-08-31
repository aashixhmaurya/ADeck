"""ADeck diagnostics, repair, start/stop, and control-menu helpers."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

BASE_DIR = Path(__file__).resolve().parent
VENV_PYTHON = BASE_DIR / ".venv" / "Scripts" / "python.exe"
VENV_PYTHONW = BASE_DIR / ".venv" / "Scripts" / "pythonw.exe"
DECK = BASE_DIR / "deck.py"
CONTROL_SCRIPT = Path(__file__).resolve()
REQUIREMENTS = BASE_DIR / "requirements.txt"
INSTALL_FIRMWARE = BASE_DIR / "install_firmware.py"
WEB_DIR = BASE_DIR / "ADeck Web app"
APP_ICON = WEB_DIR / "adeck.ico"
HEALTH_URL = "http://127.0.0.1:8765/api/status"
WEB_URL = "http://127.0.0.1:8765/"
SERVICE_NAME = "ADeck"
PROTOCOL_REPLY = "ADECK_PONG\t2"
LOCAL_DATA = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ADeck"
APP_DATA = Path(os.environ.get("APPDATA", Path.home())) / "ADeck"
CONFIG_PATH = APP_DATA / "config.json"
LOG_PATH = LOCAL_DATA / "adeck.log"
STDOUT_LOG = LOCAL_DATA / "runtime.stdout.log"
STDERR_LOG = LOCAL_DATA / "runtime.stderr.log"
LOCK_PATH = LOCAL_DATA / "runtime.lock"
RUNTIME_PATH = LOCAL_DATA / "runtime.json"
TASKS_DIR = LOCAL_DATA / "tasks"
INTEGRATION_PATH = LOCAL_DATA / "integration.json"
BUNDLED_CLI = BASE_DIR / ".tools" / "arduino-cli" / "arduino-cli.exe"
REPAIR_ACTION = "ADeck-Control.bat -> Install / Repair (or Stop, then Start)"
SHORTCUT_NAME = "ADeck.lnk"
URL_SCHEME = "adeck"
TASK_ID_PATTERN = re.compile(r"[0-9]{8}-[0-9]{6}-[0-9a-f]{4}")
TASK_OUTPUT_LIMIT = 400
TASK_HISTORY = 20
TASK_STALE_SECONDS = 180
APP_BROWSERS = ("brave.exe", "chrome.exe", "msedge.exe", "vivaldi.exe", "chromium.exe")


@dataclass
class CheckItem:
    name: str
    ok: bool
    detail: str = ""
    action: str = ""


def debug_enabled(flag: bool = False) -> bool:
    if flag:
        return True
    value = os.environ.get("ADECK_DEBUG", "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def debug_print(enabled: bool, message: str) -> None:
    if enabled:
        print(f"[debug] {message}", flush=True)


def python_exe() -> Path:
    if VENV_PYTHON.is_file():
        return VENV_PYTHON
    return Path(sys.executable)


def run(
    command: list[object],
    *,
    timeout: float | None = None,
    check: bool = False,
    capture: bool = True,
) -> subprocess.CompletedProcess[str]:
    display = [str(part) for part in command]
    return subprocess.run(
        display,
        cwd=str(BASE_DIR),
        capture_output=capture,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=check,
    )


def fetch_status(timeout: float = 1.0) -> dict | None:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if isinstance(payload, dict):
            return payload
    except (OSError, urllib.error.URLError, ValueError, TypeError):
        return None
    return None


def backend_healthy(status: dict | None = None) -> bool:
    status = status if status is not None else fetch_status()
    return bool(
        status
        and status.get("ok") is True
        and status.get("service") == SERVICE_NAME
        and status.get("bridge_version")
    )


def port_listening(port: int = 8765) -> bool:
    import socket

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.4)
    try:
        return sock.connect_ex(("127.0.0.1", port)) == 0
    except OSError:
        return False
    finally:
        sock.close()


def runtime_lock_held() -> bool:
    """True when another process currently holds runtime.lock."""
    if not LOCK_PATH.exists():
        return False
    handle = None
    try:
        handle = LOCK_PATH.open("a+b")
        handle.seek(0)
        if handle.read(1) == b"":
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return False
    except OSError:
        return True
    finally:
        if handle is not None:
            try:
                handle.close()
            except OSError:
                pass


def runtime_pid_alive() -> int | None:
    """Return runtime.json pid if that process still exists."""
    try:
        payload = json.loads(RUNTIME_PATH.read_text(encoding="utf-8"))
        pid = int(payload.get("pid"))
    except (OSError, ValueError, TypeError):
        return None
    if pid <= 0 or pid == os.getpid():
        return None
    if os.name == "nt":
        result = run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], timeout=10)
        text = result.stdout or ""
        if str(pid) in text and "No tasks" not in text:
            return pid
        return None
    try:
        os.kill(pid, 0)
        return pid
    except OSError:
        return None


def backend_inconsistent() -> bool:
    """Lock/process/port present without a healthy ADeck /api/status."""
    if backend_healthy():
        return False
    return bool(
        runtime_lock_held()
        or runtime_pid_alive() is not None
        or deck_processes()
        or port_listening(8765)
    )


def log_mentions_already_running(since_sizes: dict[Path, int] | None = None) -> bool:
    needle = "ADeck service is already running"
    for path in (STDOUT_LOG, STDERR_LOG):
        try:
            if not path.is_file():
                continue
            data = path.read_bytes()
            if since_sizes is not None:
                start = max(0, int(since_sizes.get(path, 0)))
                data = data[start:]
            else:
                data = data[-4096:]
            if needle.encode("utf-8") in data:
                return True
        except OSError:
            continue
    return False


def mark(ok: bool) -> str:
    return "[OK]" if ok else "[FAIL]"


def print_check(item: CheckItem) -> None:
    suffix = f" - {item.detail}" if item.detail else ""
    print(f"{mark(item.ok)} {item.name}{suffix}")
    if not item.ok and item.action:
        print(f"     -> {item.action}")


def check_python() -> CheckItem:
    try:
        version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        ok = sys.version_info.major == 3 and sys.version_info.minor >= 9
        return CheckItem(
            "Python",
            ok,
            f"{version} ({sys.executable})",
            "Install Python 3 from python.org and rerun Setup ADeck.bat",
        )
    except Exception as error:
        return CheckItem("Python", False, str(error), "Install Python 3 from python.org")


def check_venv() -> CheckItem:
    ok = VENV_PYTHON.is_file() and VENV_PYTHONW.is_file()
    return CheckItem(
        "venv",
        ok,
        str(BASE_DIR / ".venv") if ok else "missing",
        "Run Install / Repair from ADeck-Control.bat",
    )


def check_pyserial(debug: bool) -> CheckItem:
    if not VENV_PYTHON.is_file():
        return CheckItem(
            "PySerial",
            False,
            "venv missing",
            "Run Install / Repair from ADeck-Control.bat",
        )
    result = run(
        [VENV_PYTHON, "-c", "import serial; print(getattr(serial, '__version__', 'ok'))"],
        timeout=15,
    )
    if result.returncode == 0:
        version = (result.stdout or "").strip() or "installed"
        return CheckItem("PySerial", True, version)
    detail = (result.stderr or result.stdout or "import failed").strip()
    if not debug and len(detail) > 160:
        detail = detail[:160] + "..."
    return CheckItem(
        "PySerial",
        False,
        detail,
        "Run Install / Repair to reinstall requirements.txt",
    )


def check_arduino_cli(debug: bool) -> CheckItem:
    candidates = []
    if BUNDLED_CLI.is_file():
        candidates.append(BUNDLED_CLI)
    which = run(["where", "arduino-cli"], timeout=10)
    if which.returncode == 0:
        for line in (which.stdout or "").splitlines():
            path = Path(line.strip())
            if path.is_file():
                candidates.append(path)
    for path in candidates:
        result = run([path, "version", "--format", "json"], timeout=15)
        if result.returncode != 0:
            debug_print(debug, f"arduino-cli version failed for {path}: {result.stderr}")
            continue
        try:
            payload = json.loads(result.stdout or "{}")
        except json.JSONDecodeError:
            continue
        version = None
        if isinstance(payload, dict):
            version = payload.get("VersionString") or payload.get("version")
        return CheckItem("Arduino CLI", True, f"{version or 'ok'} ({path})")
    return CheckItem(
        "Arduino CLI",
        False,
        "not found",
        "Run Install / Repair, or .\\.venv\\Scripts\\python.exe .\\install_firmware.py --cli-only",
    )


def _import_firmware():
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    import install_firmware as firmware

    return firmware


def check_board_and_pong(debug: bool) -> tuple[CheckItem, CheckItem, CheckItem]:
    status = fetch_status()
    if backend_healthy(status) and status and status.get("connected"):
        port = status.get("port") or "unknown"
        board = CheckItem("UNO R4 WiFi", True, f"connected via backend on {port}")
        com = CheckItem("COM port", True, str(port))
        pong = CheckItem("ADECK_PONG", True, f"protocol via backend on {port}")
        return board, com, pong

    previous_quiet = os.environ.get("ADECK_QUIET")
    if not debug:
        os.environ["ADECK_QUIET"] = "1"
    try:
        firmware = _import_firmware()
        cli_path = None
        if firmware.BUNDLED_CLI.is_file():
            try:
                firmware.validate_cli(firmware.BUNDLED_CLI)
                cli_path = firmware.BUNDLED_CLI
            except Exception:
                cli_path = None
        if cli_path is None:
            which = run(["where", "arduino-cli"], timeout=10)
            if which.returncode == 0:
                for line in (which.stdout or "").splitlines():
                    path = Path(line.strip())
                    if path.is_file():
                        try:
                            firmware.validate_cli(path)
                            cli_path = path
                            break
                        except Exception:
                            continue
        if cli_path is None:
            raise RuntimeError("Arduino CLI is not available")

        board_info = firmware.detect_target_board(cli_path)
        board = CheckItem(
            "UNO R4 WiFi",
            True,
            f"{board_info.board_name or 'UNO R4 WiFi'} on {board_info.port}",
        )
        com = CheckItem("COM port", True, board_info.port)
        if backend_healthy(status):
            pong = CheckItem(
                "ADECK_PONG",
                False,
                "backend is up but not connected",
                "Unplug/replug USB, close Serial Monitor, then use Repair or Reinstall Firmware",
            )
            return board, com, pong
        ok = firmware.ping_firmware(board_info.port)
        pong = CheckItem(
            "ADECK_PONG",
            ok,
            PROTOCOL_REPLY.replace("\t", " ") if ok else "no reply",
            ""
            if ok
            else "Use Reinstall Firmware from ADeck-Control.bat",
        )
        return board, com, pong
    except Exception as error:
        detail = str(error)
        if not debug:
            detail = detail.splitlines()[0][:200]
        else:
            traceback.print_exc()
        board = CheckItem(
            "UNO R4 WiFi",
            False,
            detail,
            "Connect the UNO R4 WiFi by USB and close Arduino Serial Monitor",
        )
        com = CheckItem(
            "COM port",
            False,
            "not detected",
            "Use a data-capable USB cable and leave only one UNO R4 WiFi connected",
        )
        pong = CheckItem(
            "ADECK_PONG",
            False,
            "skipped",
            "Fix board detection first, then Check System again",
        )
        return board, com, pong
    finally:
        if previous_quiet is None:
            os.environ.pop("ADECK_QUIET", None)
        else:
            os.environ["ADECK_QUIET"] = previous_quiet


def check_backend(status: dict | None) -> CheckItem:
    if backend_healthy(status):
        version = status.get("bridge_version") if status else "?"
        return CheckItem("backend", True, f"ADeck {version} (healthy)")
    if backend_inconsistent():
        bits: list[str] = []
        if runtime_lock_held():
            bits.append("runtime.lock held")
        pid = runtime_pid_alive()
        if pid is not None:
            bits.append(f"runtime pid {pid}")
        procs = deck_processes()
        if procs:
            bits.append(f"deck.py pid(s) {', '.join(str(p) for p in procs)}")
        if port_listening(8765):
            bits.append(":8765 listening")
        detail = "; ".join(bits) if bits else "stale runtime state"
        return CheckItem(
            "backend",
            False,
            f"inconsistent ({detail}; /api/status unhealthy)",
            REPAIR_ACTION,
        )
    return CheckItem(
        "backend",
        False,
        "unavailable (no healthy service on :8765)",
        "Choose Start ADeck, or Install / Repair if startup keeps failing",
    )


def check_port_8765() -> CheckItem:
    ok = port_listening(8765)
    if ok and not backend_healthy():
        return CheckItem(
            ":8765",
            False,
            "listening but /api/status unhealthy",
            REPAIR_ACTION,
        )
    return CheckItem(
        ":8765",
        ok,
        "listening" if ok else "not listening",
        "Start ADeck from ADeck-Control.bat",
    )


def check_connected(status: dict | None) -> CheckItem:
    if not backend_healthy(status):
        if backend_inconsistent():
            return CheckItem(
                "hardware",
                False,
                "unknown (backend inconsistent)",
                REPAIR_ACTION,
            )
        return CheckItem(
            "hardware",
            False,
            "unknown (backend unavailable)",
            "Start ADeck first",
        )
    connected = bool(status and status.get("connected"))
    if connected:
        return CheckItem(
            "hardware",
            True,
            f"connected on {status.get('port')}",
        )
    detail = (status or {}).get("error") or "disconnected"
    return CheckItem(
        "hardware",
        False,
        f"disconnected ({detail})",
        "Backend is healthy; reconnect USB or use Repair if the board stays offline",
    )


def check_config() -> CheckItem:
    if not CONFIG_PATH.is_file():
        return CheckItem(
            "config",
            True,
            "no saved config yet (OK until first Save)",
        )
    try:
        if str(BASE_DIR) not in sys.path:
            sys.path.insert(0, str(BASE_DIR))
        import deck

        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        deck.normalize_config(raw)
        return CheckItem("config", True, str(CONFIG_PATH))
    except Exception as error:
        return CheckItem(
            "config",
            False,
            str(error).splitlines()[0][:200],
            f"Inspect or restore {CONFIG_PATH} / config.backup.json",
        )


def cmd_check(debug: bool = False) -> int:
    print("ADeck Check System")
    print("=" * 40)
    items: list[CheckItem] = []
    items.append(check_python())
    items.append(check_venv())
    items.append(check_pyserial(debug))
    items.append(check_arduino_cli(debug))
    board, com, pong = check_board_and_pong(debug)
    items.extend([board, com, pong])
    status = fetch_status()
    items.append(check_backend(status))
    items.append(check_port_8765())
    items.append(check_connected(status))
    items.append(check_config())
    for item in items:
        print_check(item)
    failed = [item for item in items if not item.ok]
    print()
    if failed:
        print(f"{len(failed)} check(s) failed.")
        return 1
    print("All checks passed.")
    return 0


def cmd_status() -> int:
    status = fetch_status()
    config_ok = check_config().ok
    board = "unknown"
    port = "-"
    firmware = "-"
    backend = "stopped"
    web = "down"
    hardware = "offline"

    if backend_healthy(status) and status:
        backend = f"running (v{status.get('bridge_version', '?')})"
        web = "http://127.0.0.1:8765/"
        if status.get("connected"):
            hardware = "connected"
            port = str(status.get("port") or "-")
            firmware = str(status.get("firmware") or PROTOCOL_REPLY.split("\t")[1])
            board = "UNO R4 WiFi"
        else:
            hardware = status.get("error") or "not connected"
    elif backend_inconsistent():
        backend = "inconsistent (lock/process without healthy /api/status)"
        web = "ambiguous"
        hardware = "unknown"
    elif port_listening(8765):
        backend = "port open, status unhealthy"
        web = "ambiguous"

    if board == "unknown":
        previous_quiet = os.environ.get("ADECK_QUIET")
        os.environ["ADECK_QUIET"] = "1"
        try:
            firmware_mod = _import_firmware()
            cli = None
            if firmware_mod.BUNDLED_CLI.is_file():
                try:
                    firmware_mod.validate_cli(firmware_mod.BUNDLED_CLI)
                    cli = firmware_mod.BUNDLED_CLI
                except Exception:
                    cli = None
            if cli is not None:
                info = firmware_mod.detect_target_board(cli)
                board = info.board_name or "UNO R4 WiFi"
                if port == "-":
                    port = info.port
        except Exception:
            board = "not detected"
        finally:
            if previous_quiet is None:
                os.environ.pop("ADECK_QUIET", None)
            else:
                os.environ["ADECK_QUIET"] = previous_quiet

    print("ADeck Status Summary")
    print("=" * 40)
    print(f"Backend:   {backend}")
    print(f"Web:       {web}")
    print(f"Hardware:  {hardware}")
    print(f"Board:     {board}")
    print(f"Port:      {port}")
    print(f"Firmware:  {firmware}")
    print(f"Config:    {'OK' if config_ok else 'INVALID'} ({CONFIG_PATH})")
    return 0


_ERROR_LINE = re.compile(r"(error|exception|traceback|failed|fail\b)", re.IGNORECASE)
_LOG_TIMESTAMP = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
_BENIGN_HISTORICAL = (
    re.compile(r"ADeck service is already running", re.IGNORECASE),
    re.compile(r"ClearCommError failed", re.IGNORECASE),
)
_RECENT_ERROR_SECONDS = 6 * 3600


def _recent_error_lines(path: Path, limit: int = 40) -> list[str]:
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    matched = [line for line in lines if _ERROR_LINE.search(line)]
    return matched[-limit:]


def _line_epoch(line: str) -> float | None:
    match = _LOG_TIMESTAMP.match(line)
    if not match:
        return None
    try:
        return time.mktime(time.strptime(match.group(1), "%Y-%m-%d %H:%M:%S"))
    except (ValueError, OverflowError):
        return None


def _is_benign_historical(line: str) -> bool:
    return any(pattern.search(line) for pattern in _BENIGN_HISTORICAL)


def _classify_error_lines(
    lines: list[str],
    *,
    now: float,
    backend_ok: bool,
) -> tuple[list[str], list[str]]:
    """Split matched log lines into current/recent vs older historical entries."""
    current: list[str] = []
    historical: list[str] = []
    cutoff = now - _RECENT_ERROR_SECONDS
    for line in lines:
        ts = _line_epoch(line)
        is_recent = ts is None or ts >= cutoff
        if is_recent and not (_is_benign_historical(line) and backend_ok):
            current.append(line)
        else:
            historical.append(line)
    return current, historical


def _print_error_section(title: str, grouped: list[tuple[str, list[str]]]) -> bool:
    printed = False
    for label, lines in grouped:
        if not lines:
            continue
        if not printed:
            print(title)
            printed = True
        print(f"\n[{label}]")
        for line in lines[-15:]:
            print(line)
    return printed


def cmd_errors() -> int:
    print("ADeck Latest Errors")
    print("=" * 40)
    sources = [
        ("adeck.log", LOG_PATH),
        ("runtime.stderr.log", STDERR_LOG),
        ("runtime.stdout.log", STDOUT_LOG),
    ]
    backend_ok = backend_healthy()
    now = time.time()
    current_groups: list[tuple[str, list[str]]] = []
    historical_groups: list[tuple[str, list[str]]] = []
    for label, path in sources:
        lines = _recent_error_lines(path)
        if not lines:
            continue
        current, historical = _classify_error_lines(lines, now=now, backend_ok=backend_ok)
        if current:
            current_groups.append((label, current))
        if historical:
            historical_groups.append((label, historical))

    found_current = _print_error_section("\nCurrent / recent issues:", current_groups)
    found_historical = _print_error_section(
        "\nHistorical entries (may already be resolved):",
        historical_groups,
    )
    if not found_current and not found_historical:
        print("No recent error lines found.")
        print(f"Logs: {LOCAL_DATA}")
        return 0
    if not found_current and found_historical:
        print("\nNo current errors. Older log entries are shown above.")
    print(f"\nFull logs: {LOCAL_DATA}")
    return 0


def cmd_logs() -> int:
    LOCAL_DATA.mkdir(parents=True, exist_ok=True)
    os.startfile(str(LOCAL_DATA))
    print(f"Opened {LOCAL_DATA}")
    return 0


def deck_process_entries() -> list[tuple[int, int]]:
    """Return (pid, parent_pid) pairs for this install's deck.py processes."""
    if os.name != "nt":
        return []
    marker = str(DECK.resolve()).casefold().replace("'", "''")
    script = (
        "$marker = '%s';"
        "Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |"
        " Where-Object {"
        "  $_.Name -match 'python' -and $_.CommandLine -and"
        "  ($_.CommandLine.ToLower() -like ('*' + $marker + '*'))"
        "} | ForEach-Object { '{0}|{1}' -f $_.ProcessId, $_.ParentProcessId }"
    ) % marker
    result = run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        timeout=20,
    )
    entries: list[tuple[int, int]] = []
    for line in (result.stdout or "").splitlines():
        text = line.strip()
        if "|" not in text:
            continue
        left, right = text.split("|", 1)
        if left.isdigit() and right.isdigit():
            pid = int(left)
            if pid != os.getpid():
                entries.append((pid, int(right)))
    return entries


def deck_processes() -> list[int]:
    """Root deck.py processes only (venv pythonw launcher + child counts as one)."""
    entries = deck_process_entries()
    pids = {pid for pid, _ in entries}
    return sorted(pid for pid, parent in entries if parent not in pids)


def terminate_deck_processes(debug: bool = False) -> None:
    # Kill every matching pid so launcher stubs and workers both exit.
    for pid in sorted({pid for pid, _ in deck_process_entries()}, reverse=True):
        debug_print(debug, f"terminating leftover deck process {pid}")
        run(["taskkill", "/PID", str(pid), "/F"], timeout=10)


def cmd_stop(debug: bool = False) -> int:
    exe = python_exe()
    if not DECK.is_file():
        print("deck.py is missing.")
        return 1
    result = run([exe, str(DECK), "--stop"], timeout=20)
    text = ((result.stdout or "") + (result.stderr or "")).strip()
    if text:
        print(text)
    elif result.returncode == 0:
        print("ADeck service stopped")
    if debug and result.returncode:
        print(f"[debug] stop exit={result.returncode}")
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if not backend_healthy() and not port_listening(8765):
            break
        time.sleep(0.3)
    leftovers = deck_processes()
    if leftovers:
        terminate_deck_processes(debug)
        time.sleep(0.5)
    if backend_healthy() or port_listening(8765):
        print("Backend still appears to be listening on :8765.")
        return 1
    return 0


def wait_until_ready(timeout: float = 30.0) -> dict | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = fetch_status()
        if backend_healthy(status):
            return status
        time.sleep(0.5)
    return None


def cmd_start(open_browser: bool = True, debug: bool = False) -> int:
    if not VENV_PYTHONW.is_file():
        print("ADeck is not installed yet.")
        print("Run Setup ADeck.bat or choose Install / Repair.")
        return 1

    status = fetch_status()
    if backend_healthy(status):
        print("ADeck is already running.")
        if open_browser:
            webbrowser.open(WEB_URL)
        if status and not status.get("connected"):
            print("Hardware is offline. The web UI is available; reconnect USB to sync.")
        return 0

    existing = deck_processes()
    if existing or port_listening(8765) or runtime_lock_held():
        debug_print(
            debug,
            f"waiting on existing process(es): {existing}; "
            f"port={port_listening(8765)}; lock={runtime_lock_held()}",
        )
        # Lock held with no listener/process is unlikely to become healthy — fail faster.
        wait_s = 12.0
        if runtime_lock_held() and not port_listening(8765) and not existing:
            wait_s = 2.0
        status = wait_until_ready(wait_s)
        if backend_healthy(status):
            print("ADeck is already running.")
            if open_browser:
                webbrowser.open(WEB_URL)
            if status and not status.get("connected"):
                print("Hardware is offline. The web UI is available; reconnect USB to sync.")
            return 0
        # Stale process / port / lock without a healthy API — clear and continue.
        print("Runtime looks inconsistent (lock/process without healthy /api/status). Clearing...")
        terminate_deck_processes(debug)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and (
            port_listening(8765) or runtime_lock_held() or deck_processes()
        ):
            time.sleep(0.3)
        if backend_inconsistent():
            print("ADeck runtime lock/process is inconsistent and could not be cleared.")
            print(f"Repair action: {REPAIR_ACTION}")
            return 1

    LOCAL_DATA.mkdir(parents=True, exist_ok=True)
    debug_print(debug, f"starting {VENV_PYTHONW} {DECK}")
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
    launched_pid: int | None = None
    log_sizes = {
        path: path.stat().st_size if path.is_file() else 0
        for path in (STDOUT_LOG, STDERR_LOG)
    }
    try:
        with STDOUT_LOG.open("a", encoding="utf-8") as out, STDERR_LOG.open(
            "a", encoding="utf-8"
        ) as err:
            proc = subprocess.Popen(
                [str(VENV_PYTHONW), str(DECK)],
                cwd=str(BASE_DIR),
                stdout=out,
                stderr=err,
                creationflags=creationflags,
                close_fds=True,
            )
            launched_pid = proc.pid
    except OSError as error:
        print(f"Could not start ADeck: {error}")
        return 1

    if launched_pid is not None:
        debug_print(debug, f"launched PID {launched_pid}")

    status = wait_until_ready(30)
    if backend_healthy(status):
        print("ADeck is ready.")
        if status and not status.get("connected"):
            print("Hardware is offline. The web UI is available; reconnect USB to sync.")
        if open_browser:
            webbrowser.open(WEB_URL)
        return 0

    # Launcher may have lost the single-instance race — recheck before failing.
    if log_mentions_already_running(log_sizes):
        status = fetch_status()
        if backend_healthy(status):
            print("ADeck is already running.")
            if open_browser:
                webbrowser.open(WEB_URL)
            if status and not status.get("connected"):
                print("Hardware is offline. The web UI is available; reconnect USB to sync.")
            return 0
        print(
            "ADeck reported 'service is already running', but /api/status is not healthy."
        )
        print(f"Repair action: {REPAIR_ACTION}")
        return 1

    if backend_inconsistent():
        print("ADeck did not become ready; runtime lock/process looks inconsistent.")
        print(f"Repair action: {REPAIR_ACTION}")
        print(f"Check logs in: {LOCAL_DATA}")
        return 1

    pid_note = f" (PID {launched_pid})" if launched_pid is not None else ""
    print(f"ADeck did not become ready within 30 seconds{pid_note}.")
    print(f"Check logs in: {LOCAL_DATA}")
    return 1


def ensure_venv(debug: bool) -> None:
    if VENV_PYTHON.is_file() and VENV_PYTHONW.is_file():
        probe = run(
            [VENV_PYTHON, "-c", "import sys; raise SystemExit(0 if sys.version_info.major == 3 else 1)"],
            timeout=15,
        )
        if probe.returncode == 0:
            return
    print("Creating Python environment...")
    launcher = run(["py", "-3", "-m", "venv", str(BASE_DIR / ".venv")], timeout=120)
    if launcher.returncode != 0:
        result = run([sys.executable, "-m", "venv", str(BASE_DIR / ".venv")], timeout=120)
        if result.returncode != 0:
            raise RuntimeError(
                (result.stderr or launcher.stderr or "venv creation failed").strip()
            )
    if not (VENV_PYTHON.is_file() and VENV_PYTHONW.is_file()):
        raise RuntimeError("The Python environment is incomplete after setup.")
    debug_print(debug, "venv ready")


def ensure_deps(debug: bool) -> None:
    result = run(
        [VENV_PYTHON, "-c", "import serial"],
        timeout=15,
    )
    if result.returncode == 0:
        return
    print("Installing Python dependencies...")
    install = run(
        [
            VENV_PYTHON,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "-r",
            str(REQUIREMENTS),
        ],
        timeout=180,
    )
    if install.returncode != 0:
        detail = (install.stderr or install.stdout or "pip failed").strip()
        if not debug and len(detail) > 400:
            detail = detail[-400:]
        raise RuntimeError(detail)
    debug_print(debug, "dependencies ready")


def ensure_cli(debug: bool) -> None:
    result = run([VENV_PYTHON, str(INSTALL_FIRMWARE), "--cli-only"], timeout=300)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "Arduino CLI repair failed").strip()
        if not debug and len(detail) > 400:
            detail = detail[-400:]
        raise RuntimeError(detail)
    debug_print(debug, "Arduino CLI ready")


def noninteractive() -> bool:
    """True when nobody can answer a prompt (background task, no console).

    Windows reports the NUL device as a TTY, so an explicit flag is needed for
    detached task processes.
    """
    if os.environ.get("ADECK_NONINTERACTIVE", "").strip().lower() in {"1", "true", "yes", "on"}:
        return True
    try:
        return not sys.stdin.isatty()
    except (AttributeError, ValueError, OSError):
        return True


def ask_yes_no(prompt: str, default: bool = False) -> bool:
    if noninteractive():
        return default
    suffix = " [Y/n] " if default else " [y/N] "
    try:
        answer = input(prompt + suffix).strip().lower()
    except (EOFError, OSError):
        return default
    if not answer:
        return default
    return answer in {"y", "yes"}


def cmd_repair(debug: bool = False, force_firmware: bool = False) -> int:
    print("ADeck Install / Repair")
    print("=" * 40)
    try:
        ensure_venv(debug)
        ensure_deps(debug)
        ensure_cli(debug)

        status = fetch_status()
        need_firmware = force_firmware
        if not need_firmware:
            if backend_healthy(status) and status and status.get("connected"):
                print("Firmware already verified through the running backend.")
            else:
                if backend_healthy(status):
                    cmd_stop(debug)
                try:
                    firmware = _import_firmware()
                    cli = firmware.resolve_cli()
                    board = firmware.detect_target_board(cli)
                    if firmware.ping_firmware(board.port):
                        firmware.save_identity(board)
                        print(f"Firmware already replies on {board.port}.")
                    else:
                        need_firmware = True
                        print("Board found, but ADECK_PONG failed.")
                except Exception as error:
                    need_firmware = True
                    detail = str(error).splitlines()[0]
                    print(f"Firmware check failed: {detail}")

        if need_firmware:
            if force_firmware or ask_yes_no(
                "Reinstall firmware on the UNO R4 WiFi now?", default=True
            ):
                print("Installing firmware...")
                args = [VENV_PYTHON, str(INSTALL_FIRMWARE)]
                if not force_firmware:
                    args.append("--if-needed")
                result = run(args, timeout=900, capture=False)
                if result.returncode != 0:
                    print("Firmware installation failed.")
                    return result.returncode
            else:
                print("Skipped firmware reinstall.")

        print("Starting backend for verification...")
        started = cmd_start(open_browser=False, debug=debug)
        if started != 0:
            return started
        status = wait_until_ready(45) or fetch_status()
        if not backend_healthy(status):
            print("Backend did not become healthy after repair.")
            return 1
        if status and status.get("connected"):
            print(f"Repair complete. Connected on {status.get('port')}.")
            return 0
        print("Backend is healthy, but hardware is not connected.")
        print("Connect the board by USB, then run Check System.")
        return 1
    except Exception as error:
        if debug:
            traceback.print_exc()
        print(f"Repair failed: {error}")
        return 1


def cmd_reinstall_firmware(debug: bool = False) -> int:
    print("ADeck Reinstall Firmware")
    print("=" * 40)
    if not VENV_PYTHON.is_file():
        print("venv missing. Run Install / Repair first.")
        return 1
    if backend_healthy():
        cmd_stop(debug)
    result = run([VENV_PYTHON, str(INSTALL_FIRMWARE)], timeout=900, capture=False)
    if result.returncode != 0:
        return result.returncode
    return cmd_start(open_browser=False, debug=debug)


def cmd_restart(debug: bool = False) -> int:
    print("ADeck Restart")
    print("=" * 40)
    cmd_stop(debug)
    return cmd_start(open_browser=False, debug=debug)


# --- background tasks ----------------------------------------------------
# The web UI triggers maintenance work through detached task processes so a
# task keeps running (and keeps logging) even while the backend restarts.

TASK_ACTIONS: dict[str, Callable[[bool], int]] = {
    "check": lambda debug: cmd_check(debug),
    "status": lambda debug: cmd_status(),
    "errors": lambda debug: cmd_errors(),
    "start": lambda debug: cmd_start(open_browser=False, debug=debug),
    "stop": lambda debug: cmd_stop(debug),
    "restart": lambda debug: cmd_restart(debug),
    "repair": lambda debug: cmd_repair(debug=debug, force_firmware=False),
    "reinstall-firmware": lambda debug: cmd_reinstall_firmware(debug),
}

# "stop" is deliberate, everything else here should end with a live service.
TASK_RESTORE_SERVICE = frozenset({"restart", "repair", "reinstall-firmware", "start"})


def _task_paths(task_id: str) -> tuple[Path, Path]:
    return TASKS_DIR / f"{task_id}.json", TASKS_DIR / f"{task_id}.log"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _read_json(path: Path) -> dict | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def tail_lines(path: Path, limit: int = TASK_OUTPUT_LIMIT, max_bytes: int = 256 * 1024) -> list[str]:
    """Last `limit` lines of a log file, reading only the tail of the file."""
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size > max_bytes:
                handle.seek(size - max_bytes)
                handle.readline()
            data = handle.read()
    except OSError:
        return []
    text = data.decode("utf-8", errors="replace")
    return [line.rstrip() for line in text.splitlines()][-max(1, limit) :]


def _prune_tasks(keep: int = TASK_HISTORY) -> None:
    try:
        files = sorted(TASKS_DIR.glob("*.json"), key=lambda item: item.name, reverse=True)
    except OSError:
        return
    for path in files[keep:]:
        for victim in (path, path.with_suffix(".log")):
            try:
                victim.unlink(missing_ok=True)
            except OSError:
                pass


def start_task(action: str, *, debug: bool = False) -> dict:
    """Launch a detached task process and return its initial record."""
    if action not in TASK_ACTIONS:
        raise ValueError(f"Unknown task action: {action}")
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    _prune_tasks()
    task_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(2)}"
    json_path, log_path = _task_paths(task_id)
    record = {
        "id": task_id,
        "action": action,
        "state": "starting",
        "started_at": time.time(),
        "finished_at": None,
        "exit_code": None,
        "pid": None,
    }
    _write_json(json_path, record)
    log_path.write_text("", encoding="utf-8")

    executable = VENV_PYTHON if VENV_PYTHON.is_file() else Path(sys.executable)
    command = [
        str(executable),
        str(CONTROL_SCRIPT),
        "task",
        "--task-id",
        task_id,
        "--task-action",
        action,
    ]
    if debug:
        command.append("--debug")
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
    # Tasks are unattended: no prompt may block them, and Windows reports NUL
    # as a TTY, so the flag has to be explicit for the task and its children.
    environment = dict(os.environ, ADECK_NONINTERACTIVE="1")
    try:
        with log_path.open("a", encoding="utf-8") as log:
            process = subprocess.Popen(
                command,
                cwd=str(BASE_DIR),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=creationflags,
                close_fds=True,
                env=environment,
            )
    except OSError as error:
        record.update({"state": "done", "exit_code": 1, "finished_at": time.time()})
        _write_json(json_path, record)
        with log_path.open("a", encoding="utf-8") as log:
            log.write(f"Could not start task: {error}\n")
        return record
    record.update({"state": "running", "pid": process.pid})
    _write_json(json_path, record)
    return record


def read_task(task_id: str, *, lines: int = TASK_OUTPUT_LIMIT) -> dict | None:
    if not TASK_ID_PATTERN.fullmatch(task_id or ""):
        return None
    json_path, log_path = _task_paths(task_id)
    record = _read_json(json_path)
    if record is None:
        return None
    if record.get("state") == "running":
        try:
            idle = time.time() - max(json_path.stat().st_mtime, log_path.stat().st_mtime)
        except OSError:
            idle = 0
        if idle > TASK_STALE_SECONDS:
            record["state"] = "unknown"
    record["output"] = tail_lines(log_path, lines)
    return record


def list_tasks(limit: int = 10) -> list[dict]:
    try:
        files = sorted(TASKS_DIR.glob("*.json"), key=lambda item: item.name, reverse=True)
    except OSError:
        return []
    records = []
    for path in files[: max(1, limit)]:
        record = _read_json(path)
        if record:
            records.append(record)
    return records


def cmd_task(task_id: str, action: str, debug: bool = False) -> int:
    """Task body: runs inside the detached process, logging to the task log."""
    if action not in TASK_ACTIONS:
        print(f"Unknown task action: {action}")
        return 2
    if not TASK_ID_PATTERN.fullmatch(task_id or ""):
        print(f"Invalid task id: {task_id}")
        return 2
    try:
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)
    except (AttributeError, ValueError, OSError):
        pass
    json_path, _ = _task_paths(task_id)
    record = _read_json(json_path) or {
        "id": task_id,
        "action": action,
        "started_at": time.time(),
    }
    record.update({"state": "running", "pid": os.getpid(), "exit_code": None})
    _write_json(json_path, record)
    print(f"[{time.strftime('%H:%M:%S')}] {action} started")
    code = 1
    try:
        code = TASK_ACTIONS[action](debug)
        # Maintenance that failed midway can leave the service down. The UI is
        # served by that service, so bring it back instead of stranding the app.
        if action in TASK_RESTORE_SERVICE and not backend_healthy():
            print()
            print("Service is not running after this task; starting it again...")
            if cmd_start(open_browser=False, debug=debug) == 0 and code != 0:
                print("Service restored. The reported problem above still needs attention.")
    except KeyboardInterrupt:
        print("Cancelled.")
        code = 130
    except Exception as error:
        print(f"Task failed: {error}")
        if debug:
            traceback.print_exc()
        code = 1
    finally:
        print(f"[{time.strftime('%H:%M:%S')}] {action} finished (exit code {code})")
        record.update(
            {"state": "done", "exit_code": code, "finished_at": time.time()}
        )
        _write_json(json_path, record)
    return code


# --- Windows desktop integration ----------------------------------------


def _powershell(script: str, *, env: dict[str, str] | None = None, timeout: float = 60):
    environment = dict(os.environ)
    if env:
        environment.update(env)
    return subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        cwd=str(BASE_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env=environment,
    )


_SHORTCUT_SCRIPT = """
$ErrorActionPreference = 'Stop'
$shell = New-Object -ComObject WScript.Shell
$results = @{}
foreach ($slot in $env:ADECK_SLOTS.Split(',')) {
  if (-not $slot) { continue }
  $folderName = [Environment]::GetEnvironmentVariable("ADECK_FOLDER_$slot")
  $folder = [Environment]::GetFolderPath($folderName)
  if (-not $folder) { continue }
  if (-not (Test-Path -LiteralPath $folder)) {
    New-Item -ItemType Directory -Path $folder -Force | Out-Null
  }
  $path = Join-Path $folder $env:ADECK_LINK_NAME
  $link = $shell.CreateShortcut($path)
  $link.TargetPath = [Environment]::GetEnvironmentVariable("ADECK_TARGET_$slot")
  $link.Arguments = [Environment]::GetEnvironmentVariable("ADECK_ARGS_$slot")
  $link.WorkingDirectory = $env:ADECK_WORKDIR
  $link.Description = 'ADeck'
  if ($env:ADECK_ICON) { $link.IconLocation = $env:ADECK_ICON }
  $link.Save()
  $results[$slot] = $path
}
$results | ConvertTo-Json -Compress
"""


def _create_shortcut(slots: dict[str, tuple[str, str, str]]) -> dict[str, str]:
    """Create .lnk files. slots maps a name to (shell folder, target, arguments)."""
    if os.name != "nt":
        raise RuntimeError("Shortcuts are only supported on Windows")
    if not slots:
        return {}
    env = {
        "ADECK_SLOTS": ",".join(slots),
        "ADECK_LINK_NAME": SHORTCUT_NAME,
        "ADECK_WORKDIR": str(BASE_DIR),
        "ADECK_ICON": str(APP_ICON) if APP_ICON.is_file() else "",
    }
    for slot, (folder, target, arguments) in slots.items():
        env[f"ADECK_FOLDER_{slot}"] = folder
        env[f"ADECK_TARGET_{slot}"] = target
        env[f"ADECK_ARGS_{slot}"] = arguments
    result = _powershell(_SHORTCUT_SCRIPT, env=env)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "shortcut creation failed").strip()
        raise RuntimeError(detail.splitlines()[0][:300])
    payload = _read_powershell_json(result.stdout)
    return {str(key): str(value) for key, value in payload.items()}


def _read_powershell_json(text: str) -> dict:
    for line in reversed((text or "").strip().splitlines()):
        candidate = line.strip()
        if candidate.startswith("{"):
            try:
                payload = json.loads(candidate)
            except ValueError:
                continue
            if isinstance(payload, dict):
                return payload
    return {}


def _launcher_target() -> tuple[str, str]:
    """Target/arguments used by the ADeck app shortcut."""
    return str(VENV_PYTHONW), f'"{CONTROL_SCRIPT}" app'


def _autostart_target() -> tuple[str, str]:
    return str(VENV_PYTHONW), f'"{DECK}"'


def _shortcut_candidates() -> dict[str, list[Path]]:
    """Best-effort shortcut locations, used for state reporting without PowerShell."""
    appdata = Path(os.environ.get("APPDATA", Path.home()))
    home = Path(os.environ.get("USERPROFILE", Path.home()))
    onedrive = os.environ.get("OneDrive") or os.environ.get("OneDriveConsumer")
    desktops = [home / "Desktop" / SHORTCUT_NAME]
    if onedrive:
        desktops.append(Path(onedrive) / "Desktop" / SHORTCUT_NAME)
    programs = appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    return {
        "desktop": desktops,
        "start_menu": [programs / SHORTCUT_NAME],
        "startup": [programs / "Startup" / SHORTCUT_NAME],
    }


def _record_integration(updates: dict) -> None:
    payload = _read_json(INTEGRATION_PATH) or {}
    payload.update(updates)
    payload["updated_at"] = time.time()
    try:
        _write_json(INTEGRATION_PATH, payload)
    except OSError:
        pass


def _existing_shortcut(slot: str) -> Path | None:
    recorded = _read_json(INTEGRATION_PATH) or {}
    candidates: list[Path] = []
    value = recorded.get(f"{slot}_path")
    if isinstance(value, str) and value:
        candidates.append(Path(value))
    candidates.extend(_shortcut_candidates().get(slot, []))
    for path in candidates:
        try:
            if path.is_file():
                return path
        except OSError:
            continue
    return None


def create_app_shortcuts(desktop: bool = True, start_menu: bool = True) -> dict[str, str]:
    target, arguments = _launcher_target()
    slots: dict[str, tuple[str, str, str]] = {}
    if desktop:
        slots["desktop"] = ("Desktop", target, arguments)
    if start_menu:
        slots["start_menu"] = ("Programs", target, arguments)
    created = _create_shortcut(slots)
    _record_integration({f"{slot}_path": path for slot, path in created.items()})
    return created


def remove_app_shortcuts() -> list[str]:
    removed = []
    for slot in ("desktop", "start_menu"):
        path = _existing_shortcut(slot)
        if path is not None:
            try:
                path.unlink()
                removed.append(str(path))
            except OSError:
                continue
    return removed


def set_autostart(enabled: bool) -> str | None:
    """Create or remove the Windows Startup shortcut for the backend."""
    if enabled:
        target, arguments = _autostart_target()
        created = _create_shortcut({"startup": ("Startup", target, arguments)})
        path = created.get("startup")
        if path:
            _record_integration({"startup_path": path})
        return path
    path = _existing_shortcut("startup")
    if path is None:
        return None
    try:
        path.unlink()
    except OSError as error:
        raise RuntimeError(f"Could not remove autostart shortcut: {error}") from error
    return str(path)


def _protocol_command() -> str:
    return f'"{VENV_PYTHONW}" "{CONTROL_SCRIPT}" app --uri "%1"'


def register_protocol() -> str:
    """Register adeck:// so the app window can be started from a link."""
    if os.name != "nt":
        raise RuntimeError("The adeck:// handler is only supported on Windows")
    import winreg

    command = _protocol_command()
    root = winreg.HKEY_CURRENT_USER
    with winreg.CreateKey(root, rf"Software\Classes\{URL_SCHEME}") as key:
        winreg.SetValueEx(key, None, 0, winreg.REG_SZ, "URL:ADeck")
        winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
    if APP_ICON.is_file():
        with winreg.CreateKey(root, rf"Software\Classes\{URL_SCHEME}\DefaultIcon") as key:
            winreg.SetValueEx(key, None, 0, winreg.REG_SZ, f"{APP_ICON},0")
    with winreg.CreateKey(root, rf"Software\Classes\{URL_SCHEME}\shell\open\command") as key:
        winreg.SetValueEx(key, None, 0, winreg.REG_SZ, command)
    _record_integration({"protocol_command": command})
    return command


def protocol_registered() -> bool:
    if os.name != "nt":
        return False
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, rf"Software\Classes\{URL_SCHEME}\shell\open\command"
        ) as key:
            value = winreg.QueryValueEx(key, None)[0]
    except OSError:
        return False
    return str(CONTROL_SCRIPT).casefold() in str(value).casefold()


def integration_state() -> dict:
    desktop = _existing_shortcut("desktop")
    start_menu = _existing_shortcut("start_menu")
    startup = _existing_shortcut("startup")
    return {
        "desktop_shortcut": desktop is not None,
        "desktop_path": str(desktop) if desktop else None,
        "start_menu_shortcut": start_menu is not None,
        "start_menu_path": str(start_menu) if start_menu else None,
        "autostart": startup is not None,
        "autostart_path": str(startup) if startup else None,
        "protocol_handler": protocol_registered(),
        "url_scheme": f"{URL_SCHEME}://start",
        "shortcuts_supported": os.name == "nt",
    }


def _registry_string(root, path: str, name: str | None = None) -> str:
    try:
        import winreg

        with winreg.OpenKey(root, path) as key:
            return str(winreg.QueryValueEx(key, name)[0])
    except OSError:
        return ""


def _executable_from_command(command: str) -> Path | None:
    text = (command or "").strip()
    if not text:
        return None
    if text.startswith('"'):
        end = text.find('"', 1)
        candidate = Path(os.path.expandvars(text[1:end] if end != -1 else text[1:]))
        return candidate if candidate.is_file() else None
    expanded = os.path.expandvars(text)
    if Path(expanded).is_file():
        return Path(expanded)
    # Unquoted registry commands may still contain spaces in the program path.
    parts = expanded.split(" ")
    for count in range(1, len(parts)):
        candidate = Path(" ".join(parts[:count]))
        if candidate.is_file():
            return candidate
    return None


def find_app_browser() -> Path | None:
    """A Chromium-family browser that supports --app windows."""
    if os.name != "nt":
        return None
    import winreg

    progid = _registry_string(
        winreg.HKEY_CURRENT_USER,
        r"SOFTWARE\Microsoft\Windows\Shell\Associations\UrlAssociations\http\UserChoice",
        "ProgId",
    )
    if progid:
        for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            command = _registry_string(root, rf"SOFTWARE\Classes\{progid}\shell\open\command")
            executable = _executable_from_command(command)
            if executable and executable.name.casefold() in APP_BROWSERS:
                return executable
    for name in APP_BROWSERS:
        for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            command = _registry_string(
                root, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{name}"
            )
            executable = _executable_from_command(command)
            if executable:
                return executable
    return None


def open_app_window(url: str = WEB_URL) -> bool:
    """Open ADeck in a standalone app window; fall back to the default browser."""
    browser = find_app_browser()
    if browser is not None:
        try:
            subprocess.Popen(
                [str(browser), f"--app={url}"],
                cwd=str(BASE_DIR),
                close_fds=True,
            )
            return True
        except OSError:
            pass
    webbrowser.open(url)
    return False


def cmd_app(debug: bool = False) -> int:
    """Desktop entry point: make sure the backend is up, then show the app window."""
    started = cmd_start(open_browser=False, debug=debug)
    # Open the window either way: when startup failed the UI explains the state.
    open_app_window()
    return started


def cmd_shortcuts(debug: bool = False, remove: bool = False) -> int:
    print("ADeck Desktop Shortcuts")
    print("=" * 40)
    try:
        if remove:
            removed = remove_app_shortcuts()
            for path in removed:
                print(f"Removed {path}")
            if not removed:
                print("No ADeck shortcuts were present.")
            return 0
        created = create_app_shortcuts()
        for slot, path in created.items():
            print(f"Created {slot.replace('_', ' ')} shortcut: {path}")
        if not created:
            print("No shortcuts were created.")
            return 1
        return 0
    except Exception as error:
        if debug:
            traceback.print_exc()
        print(f"Shortcut update failed: {error}")
        return 1


def cmd_autostart(enable: bool, debug: bool = False) -> int:
    print("ADeck Autostart")
    print("=" * 40)
    try:
        path = set_autostart(enable)
        if enable:
            print(f"ADeck will start with Windows: {path}")
        elif path:
            print(f"Autostart removed: {path}")
        else:
            print("Autostart was not enabled.")
        return 0
    except Exception as error:
        if debug:
            traceback.print_exc()
        print(f"Autostart update failed: {error}")
        return 1


def cmd_protocol(debug: bool = False) -> int:
    print("ADeck URL Handler")
    print("=" * 40)
    try:
        command = register_protocol()
        print(f"Registered {URL_SCHEME}://  ->  {command}")
        return 0
    except Exception as error:
        if debug:
            traceback.print_exc()
        print(f"Could not register {URL_SCHEME}://: {error}")
        return 1


def cmd_integrate(debug: bool = False) -> int:
    """Everything needed to launch ADeck like an installed desktop app."""
    print("ADeck Desktop Integration")
    print("=" * 40)
    failures = 0
    failures += cmd_shortcuts(debug)
    failures += cmd_protocol(debug)
    failures += cmd_autostart(True, debug)
    state = integration_state()
    print()
    print(f"Desktop shortcut:  {'yes' if state['desktop_shortcut'] else 'no'}")
    print(f"Start Menu:        {'yes' if state['start_menu_shortcut'] else 'no'}")
    print(f"Autostart:         {'yes' if state['autostart'] else 'no'}")
    print(f"adeck:// handler:  {'yes' if state['protocol_handler'] else 'no'}")
    return 1 if failures else 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ADeck control helper")
    parser.add_argument(
        "command",
        choices=[
            "check",
            "status",
            "errors",
            "logs",
            "start",
            "stop",
            "restart",
            "repair",
            "reinstall-firmware",
            "app",
            "shortcuts",
            "autostart",
            "protocol",
            "integrate",
            "task",
        ],
    )
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--task-id", default="")
    parser.add_argument("--task-action", default="")
    parser.add_argument("--remove", action="store_true", help="shortcuts: delete instead of create")
    parser.add_argument("--disable", action="store_true", help="autostart: turn off")
    parser.add_argument("--uri", default="", help="ignored; accepts the adeck:// argument")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    debug = debug_enabled(args.debug)
    if debug:
        os.environ["ADECK_DEBUG"] = "1"
    handlers: dict[str, Callable[[], int]] = {
        "check": lambda: cmd_check(debug),
        "status": cmd_status,
        "errors": cmd_errors,
        "logs": cmd_logs,
        "start": lambda: cmd_start(open_browser=not args.no_browser, debug=debug),
        "stop": lambda: cmd_stop(debug),
        "restart": lambda: cmd_restart(debug),
        "repair": lambda: cmd_repair(debug=debug, force_firmware=False),
        "reinstall-firmware": lambda: cmd_reinstall_firmware(debug),
        "app": lambda: cmd_app(debug),
        "shortcuts": lambda: cmd_shortcuts(debug, remove=args.remove),
        "autostart": lambda: cmd_autostart(not args.disable, debug),
        "protocol": lambda: cmd_protocol(debug),
        "integrate": lambda: cmd_integrate(debug),
        "task": lambda: cmd_task(args.task_id, args.task_action, debug),
    }
    try:
        return handlers[args.command]()
    except KeyboardInterrupt:
        print("\nCancelled.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
