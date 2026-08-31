"""Local HTTP/config/serial runtime for ADeck."""

import argparse
import ctypes
import ctypes.wintypes
import hashlib
import json
import logging
import mimetypes
import os
import queue
import re
import secrets
import shutil
import signal
import struct
import subprocess
import sys
import threading
import time
import zlib
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    serial = None
    list_ports = None


APP_VERSION = "2.1.0"
SERVICE_NAME = "ADeck"
PROTOCOL_VERSION = "2"
BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "ADeck Web app"
DATA_DIR = Path(os.environ.get("APPDATA", Path.home())) / "ADeck"
LOCAL_DATA_DIR = (
    Path(os.environ["LOCALAPPDATA"]) / "ADeck"
    if os.environ.get("LOCALAPPDATA")
    else DATA_DIR
)
CONFIG_PATH = DATA_DIR / "config.json"
BACKUP_PATH = DATA_DIR / "config.backup.json"
IDENTITY_PATH = DATA_DIR / "device.json"
TOKEN_PATH = LOCAL_DATA_DIR / "control.token"
RUNTIME_PATH = LOCAL_DATA_DIR / "runtime.json"
LOCK_PATH = LOCAL_DATA_DIR / "runtime.lock"
LOG_PATH = LOCAL_DATA_DIR / "adeck.log"
STDOUT_LOG = LOCAL_DATA_DIR / "runtime.stdout.log"
STDERR_LOG = LOCAL_DATA_DIR / "runtime.stderr.log"
ICON_CACHE_DIR = LOCAL_DATA_DIR / "app-icons"
LOG_SOURCES = {"app": LOG_PATH, "stdout": STDOUT_LOG, "stderr": STDERR_LOG}
VENV_PYTHON = BASE_DIR / ".venv" / "Scripts" / "python.exe"
BUNDLED_CLI = BASE_DIR / ".tools" / "arduino-cli" / "arduino-cli.exe"
SERIAL_PORT_PATTERN = re.compile(r"[A-Za-z0-9_.:/\\-]{1,64}")
MAX_CONTROL_BYTES = 8 * 1024
BAUD = 115200
SLOT_COUNT = 6
LABEL_MAX = 10
COMMAND_MAX = 256
PROFILE_NAME_MAX = 32
MAX_CONFIG_BYTES = 1024 * 1024
ARDUINO_VIDS = {0x2341, 0x2A03}
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
COLOR_PATTERN = re.compile(r"#[0-9a-fA-F]{6}")
LOGGER = logging.getLogger("adeck")

mimetypes.add_type("application/manifest+json", ".webmanifest")
mimetypes.add_type("text/javascript", ".js")


def control_module():
    """Lazily import the control helper; process/OS actions are implemented there."""
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    import adeck_control

    return adeck_control


def debug_enabled():
    value = os.environ.get("ADECK_DEBUG", "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def setup_logging(debug=None):
    LOCAL_DATA_DIR.mkdir(parents=True, exist_ok=True)
    enabled = debug_enabled() if debug is None else bool(debug)
    LOGGER.setLevel(logging.DEBUG if enabled else logging.INFO)
    if not LOGGER.handlers:
        handler = RotatingFileHandler(
            LOG_PATH, maxBytes=512 * 1024, backupCount=3, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        LOGGER.addHandler(handler)
        if enabled:
            stream = logging.StreamHandler()
            stream.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
            LOGGER.addHandler(stream)


def _clone(value):
    return json.loads(json.dumps(value))


def _atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def _clean_text(value, field_name, maximum, ascii_only=False, allow_empty=True):
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be text")
    if not allow_empty and not value.strip():
        raise ValueError(f"{field_name} is required")
    if len(value) > maximum:
        raise ValueError(f"{field_name} can use up to {maximum} characters")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError(f"{field_name} contains control characters")
    if ascii_only and any(ord(char) > 126 for char in value):
        raise ValueError(f"{field_name} must use printable ASCII")
    return value


def normalize_config(raw):
    """Validate and convert supported exports/local-cache shapes to one schema."""
    if not isinstance(raw, dict):
        raise ValueError("Config must be an object")
    raw_profiles = raw.get("profiles")
    if not isinstance(raw_profiles, list) or not raw_profiles:
        raise ValueError("At least one profile is required")
    if len(raw_profiles) > 100:
        raise ValueError("Too many profiles")

    profiles = []
    names = set()
    ids = set()
    for profile_number, raw_profile in enumerate(raw_profiles, 1):
        if not isinstance(raw_profile, dict):
            raise ValueError(f"Profile {profile_number} must be an object")
        name = _clean_text(
            raw_profile.get("name", ""),
            f"Profile {profile_number} name",
            PROFILE_NAME_MAX,
            allow_empty=False,
        ).strip()
        folded = name.casefold()
        if folded in names:
            raise ValueError("Profile names must be unique")
        names.add(folded)

        profile_id = raw_profile.get("id")
        if profile_id is not None:
            profile_id = _clean_text(
                profile_id, f"Profile {profile_number} id", 64, ascii_only=True
            )
            if not re.fullmatch(r"[A-Za-z0-9_.-]+", profile_id) or profile_id in ids:
                raise ValueError("Profile ids must be unique safe identifiers")
            ids.add(profile_id)

        raw_slots = raw_profile.get("buttons")
        key_field = "key"
        base = 1
        if raw_slots is None:
            raw_slots = raw_profile.get("slots")
            key_field = "index"
            base = 0
        if not isinstance(raw_slots, list) or len(raw_slots) != SLOT_COUNT:
            raise ValueError(f'Profile "{name}" must contain exactly six slots')

        slots = {}
        for position, raw_slot in enumerate(raw_slots):
            if not isinstance(raw_slot, dict):
                raise ValueError(f'Profile "{name}" slot {position + 1} must be an object')
            if key_field not in raw_slot:
                raise ValueError(f'Profile "{name}" slot {position + 1} is missing its index')
            raw_index = raw_slot[key_field]
            if isinstance(raw_index, bool):
                raise ValueError(f'Profile "{name}" has an invalid slot index')
            try:
                index = int(raw_index) - base
            except (TypeError, ValueError):
                raise ValueError(f'Profile "{name}" has an invalid slot index') from None
            if index < 0 or index >= SLOT_COUNT or index in slots:
                raise ValueError(f'Profile "{name}" slot indices must be unique 0..5')

            label = _clean_text(
                raw_slot.get("label", ""),
                f'Profile "{name}" slot {index} label',
                LABEL_MAX,
                ascii_only=True,
            )
            command = _clean_text(
                raw_slot.get("command", ""),
                f'Profile "{name}" slot {index} command',
                COMMAND_MAX,
            )
            color = raw_slot.get("color", "#c5c5c3")
            if not isinstance(color, str) or not COLOR_PATTERN.fullmatch(color):
                raise ValueError(f'Profile "{name}" slot {index} color must be #RRGGBB')
            kind = raw_slot.get("kind", "")
            if kind is None:
                kind = ""
            if not isinstance(kind, str):
                raise ValueError(f'Profile "{name}" slot {index} kind must be a string')
            kind = kind.strip().lower()
            if kind not in {"", "app", "command"}:
                raise ValueError(f'Profile "{name}" slot {index} kind must be app or command')
            slot = {
                "key": index + 1,
                "label": label,
                "command": command,
                "color": color.lower(),
            }
            if kind:
                slot["kind"] = kind
            slots[index] = slot

        profile = {"name": name, "buttons": [slots[index] for index in range(SLOT_COUNT)]}
        if profile_id is not None:
            profile["id"] = profile_id
        profiles.append(profile)

    active_name = raw.get("active_profile")
    if active_name is None and raw.get("activeProfileId") is not None:
        active_id = str(raw["activeProfileId"])
        active_name = next(
            (profile["name"] for profile in profiles if profile.get("id") == active_id),
            None,
        )
    if active_name is None:
        active_name = profiles[0]["name"]
    if not isinstance(active_name, str) or active_name.casefold() not in names:
        raise ValueError("Active profile must name an existing profile")
    active_name = next(
        profile["name"]
        for profile in profiles
        if profile["name"].casefold() == active_name.casefold()
    )

    settings = raw.get("settings", {})
    if settings is None:
        settings = {}
    if not isinstance(settings, dict):
        raise ValueError("Settings must be an object")

    return {
        "device": "ADECK",
        "version": 2,
        "app_version": str(raw.get("app_version", ""))[:32],
        "active_profile": active_name,
        "settings": _clone(settings),
        "profiles": profiles,
    }


def validate_config(config):
    normalize_config(config)


def active_buttons(config):
    if not config:
        return []
    active = config["active_profile"]
    profile = next(item for item in config["profiles"] if item["name"] == active)
    return profile["buttons"]


def crc16_ccitt_false(buttons):
    crc = 0xFFFF
    for index, button in enumerate(buttons):
        color = button["color"]
        label = button["label"].encode("ascii")
        payload = bytes(
            [
                index,
                int(color[1:3], 16),
                int(color[3:5], 16),
                int(color[5:7], 16),
                len(label),
            ]
        ) + label
        for value in payload:
            crc ^= value << 8
            for _ in range(8):
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def config_frame(config, txid):
    buttons = active_buttons(config)
    lines = [f"CFG_BEGIN\t{txid}\t{SLOT_COUNT}"]
    for index, button in enumerate(buttons):
        lines.append(
            f"CFG_SLOT\t{txid}\t{index}\t{button['color'].upper()}\t{button['label']}"
        )
    lines.append(f"CFG_END\t{txid}\t{crc16_ccitt_false(buttons):04X}")
    return ("\n".join(lines) + "\n").encode("ascii")


_WIN_SHELL_META = re.compile(r"[&|><^]")
_WIN_EXECUTABLE_SUFFIXES = {".exe", ".com", ".bat", ".cmd", ".msi", ".lnk"}
_WIN_PE_SUFFIXES = {".exe", ".com"}
_WIN_SCRIPT_SUFFIXES = {".bat", ".cmd"}
_CLI_COMMAND_NAMES = {
    "adb",
    "bash",
    "cargo",
    "choco",
    "clang",
    "cmake",
    "cmd",
    "conda",
    "curl",
    "docker",
    "dotnet",
    "echo",
    "gcc",
    "git",
    "go",
    "gradle",
    "kubectl",
    "make",
    "mvn",
    "node",
    "npm",
    "npx",
    "perl",
    "php",
    "pip",
    "pip3",
    "pipenv",
    "poetry",
    "powershell",
    "pwsh",
    "py",
    "python",
    "python3",
    "ruby",
    "rustc",
    "scoop",
    "scp",
    "ssh",
    "uv",
    "wget",
    "winget",
    "wsl",
    "yarn",
}
_TOGGLE_SKIP_NAMES = {
    "applicationframehost.exe",
    "cmd.exe",
    "conhost.exe",
    "dllhost.exe",
    "dwm.exe",
    "powershell.exe",
    "pwsh.exe",
    "runtimebroker.exe",
    "sihost.exe",
    "svchost.exe",
}
_EXPLORER_FOLDER_CLASSES = {"cabinetwclass", "explorewclass"}
_GUI_PROCESS_ALIASES = {
    "calc.exe": ("calc.exe", "calculator.exe", "calculatorapp.exe", "win32calc.exe"),
    "calculator.exe": ("calc.exe", "calculator.exe", "calculatorapp.exe", "win32calc.exe"),
    "calculatorapp.exe": ("calc.exe", "calculator.exe", "calculatorapp.exe", "win32calc.exe"),
    "mspaint.exe": ("mspaint.exe", "paintapp.exe", "paint.exe"),
    "paint.exe": ("mspaint.exe", "paintapp.exe", "paint.exe"),
    "paintapp.exe": ("mspaint.exe", "paintapp.exe", "paint.exe"),
}
_SW_SHOW = 5
_SW_MINIMIZE = 6
_SW_RESTORE = 9
_WM_CLOSE = 0x0010
_GW_OWNER = 4
_GWL_EXSTYLE = -20
_WS_EX_TOOLWINDOW = 0x00000080
_HWND_TOPMOST = -1
_HWND_NOTOPMOST = -2
_SWP_NOSIZE = 0x0001
_SWP_NOMOVE = 0x0002
_SWP_SHOWWINDOW = 0x0040
_VK_CONTROL = 0x11
_KEYEVENTF_KEYUP = 0x0002
_LSFW_UNLOCK = 2
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_IMAGE_SUBSYSTEM_WINDOWS_GUI = 2
_FOREGROUND_NEW_WINDOW_WAIT = 2.0
_FOREGROUND_LATE_WINDOW_WAIT = 0.45
_FOREGROUND_POLL = 0.06


def _allow_foreground_grant():
    if os.name != "nt":
        return
    try:
        ctypes.windll.user32.AllowSetForegroundWindow(0xFFFFFFFF)
    except Exception:
        pass


def _needs_cmd_shell(command):
    return bool(_WIN_SHELL_META.search(command))


def _parse_win_command(command):
    text = command.strip()
    if not text:
        return "", ""
    expanded_full = os.path.expandvars(text)
    if Path(expanded_full).exists():
        return expanded_full, ""
    if text[0] == '"':
        end = text.find('"', 1)
        if end != -1:
            return text[1:end], text[end + 1 :].strip()
    split_at = text.find(" ")
    if split_at == -1:
        return text, ""
    return text[:split_at], text[split_at + 1 :].strip()


def _resolve_win_executable(executable):
    expanded = os.path.expandvars(executable.strip().strip('"'))
    path = Path(expanded)
    if path.exists():
        return str(path.resolve())
    resolved = shutil.which(expanded)
    if not resolved:
        return None
    resolved_path = Path(resolved)
    if resolved_path.suffix.lower() in _WIN_EXECUTABLE_SUFFIXES:
        return str(resolved_path.resolve())
    return None


def _is_win_executable_file(path):
    return path.suffix.lower() in _WIN_EXECUTABLE_SUFFIXES


def _uses_explorer_host_launch(path, params=""):
    return (
        not params
        and _is_win_executable_file(path)
        and path.name.lower() != "explorer.exe"
    )


def _shell_execute_win(file_path, params=""):
    _allow_foreground_grant()
    result = ctypes.windll.shell32.ShellExecuteW(
        None, "open", file_path, params or None, None, 1
    )
    if result <= 32:
        raise OSError(f"ShellExecute failed ({result})")


def _normalize_relaunch_mode(value):
    text = str(value or "new").strip().lower()
    if text in {"minimize", "minimise", "toggle"}:
        return "minimize"
    if text in {"close", "quit"}:
        return "close"
    return "new"


def _command_base_name(executable):
    name = Path(os.path.expandvars(executable.strip().strip('"'))).name.lower()
    if name.endswith(".exe"):
        return name[:-4]
    if name.endswith(".cmd") or name.endswith(".bat") or name.endswith(".com"):
        return Path(name).stem
    return name


def _pe_is_gui(path):
    try:
        with Path(path).open("rb") as handle:
            if handle.read(2) != b"MZ":
                return False
            handle.seek(0x3C)
            pe_offset = int.from_bytes(handle.read(4), "little")
            handle.seek(pe_offset)
            if handle.read(4) != b"PE\0\0":
                return False
            handle.seek(pe_offset + 24 + 68)
            subsystem = int.from_bytes(handle.read(2), "little")
            return subsystem == _IMAGE_SUBSYSTEM_WINDOWS_GUI
    except OSError:
        return False


def _companion_gui_exe(script_path):
    stem = script_path.stem.lower()
    for folder in (script_path.parent, script_path.parent.parent):
        if not folder.is_dir():
            continue
        direct = folder / f"{script_path.stem}.exe"
        if direct.is_file() and _pe_is_gui(direct):
            return direct
        for candidate in folder.glob("*.exe"):
            if candidate.stem.lower() == stem and _pe_is_gui(candidate):
                return candidate
    return None


def _is_app_execution_alias(path):
    path = Path(path)
    parts = {part.lower() for part in path.parts}
    if "windowsapps" not in parts or path.suffix.lower() not in _WIN_PE_SUFFIXES:
        return False
    try:
        if path.stat().st_size == 0:
            return True
    except OSError:
        return False
    return not _pe_is_gui(path)


def _gui_exe_for_resolved(path):
    suffix = path.suffix.lower()
    name = path.name.lower()
    if name in _TOGGLE_SKIP_NAMES:
        return None
    if suffix in _WIN_PE_SUFFIXES:
        if _pe_is_gui(path) or _is_app_execution_alias(path):
            return path
        return None
    if suffix in _WIN_SCRIPT_SUFFIXES:
        return _companion_gui_exe(path)
    return None


def _win_gui_app_identity(command):
    if os.name != "nt":
        return None
    text = command.strip()
    if not text or _needs_cmd_shell(text):
        return None
    if re.fullmatch(r"https?://\S+", text, re.IGNORECASE):
        return None
    executable, _params = _parse_win_command(os.path.expandvars(text))
    if not executable or _command_base_name(executable) in _CLI_COMMAND_NAMES:
        return None
    resolved = _resolve_win_executable(executable)
    if not resolved:
        return None
    path = Path(resolved)
    gui_exe = _gui_exe_for_resolved(path)
    if gui_exe is None:
        return None
    resolved_gui = str(gui_exe.resolve())
    name = Path(resolved_gui).name.lower()
    names = {name, *(_GUI_PROCESS_ALIASES.get(name, ()))}
    return {"path": resolved_gui, "names": names}


def _window_class_name(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    ctypes.windll.user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _is_explorer_folder_window(hwnd):
    return _window_class_name(hwnd).lower() in _EXPLORER_FOLDER_CLASSES


def _window_pid(hwnd):
    pid = ctypes.wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _process_image_path(pid):
    handle = ctypes.windll.kernel32.OpenProcess(
        _PROCESS_QUERY_LIMITED_INFORMATION, False, pid
    )
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(32768)
        size = ctypes.c_ulong(len(buf))
        ok = ctypes.windll.kernel32.QueryFullProcessImageNameW(
            handle, 0, buf, ctypes.byref(size)
        )
        return buf.value if ok else ""
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def _enum_child_windows(hwnd):
    hwnds = []

    @ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    def callback(child, _lparam):
        hwnds.append(child)
        return True

    ctypes.windll.user32.EnumChildWindows(hwnd, callback, 0)
    return hwnds


def _window_app_image(hwnd):
    pid = _window_pid(hwnd)
    image = _process_image_path(pid)
    name = Path(image).name.lower() if image else ""
    if name != "applicationframehost.exe":
        return image
    for child in _enum_child_windows(hwnd):
        child_pid = _window_pid(child)
        if not child_pid or child_pid == pid:
            continue
        hosted = _process_image_path(child_pid)
        hosted_name = Path(hosted).name.lower() if hosted else ""
        if hosted and hosted_name not in _TOGGLE_SKIP_NAMES:
            return hosted
    return image


def _is_top_level_app_window(hwnd):
    if ctypes.windll.user32.GetWindow(hwnd, _GW_OWNER):
        return False
    getter = getattr(
        ctypes.windll.user32, "GetWindowLongPtrW", ctypes.windll.user32.GetWindowLongW
    )
    ex_style = getter(hwnd, _GWL_EXSTYLE)
    if ex_style & _WS_EX_TOOLWINDOW:
        return False
    if ctypes.windll.user32.IsIconic(hwnd):
        return True
    return bool(ctypes.windll.user32.IsWindowVisible(hwnd))


def _find_windows_for_app(identity):
    if not identity:
        return []
    wanted_names = {name.lower() for name in identity["names"]}
    wanted_path = os.path.normcase(identity["path"])
    hwnds = []

    @ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    def callback(hwnd, _lparam):
        if not _is_top_level_app_window(hwnd):
            return True
        image = _window_app_image(hwnd)
        if not image:
            return True
        image_path = Path(image)
        is_explorer = "explorer.exe" in wanted_names
        if is_explorer:
            if image_path.name.lower() == "explorer.exe" and _is_explorer_folder_window(hwnd):
                hwnds.append(hwnd)
            return True
        if image_path.name.lower() in _TOGGLE_SKIP_NAMES:
            return True
        if os.path.normcase(str(image_path)) == wanted_path or image_path.name.lower() in wanted_names:
            hwnds.append(hwnd)
        return True

    ctypes.windll.user32.EnumWindows(callback, 0)
    return hwnds


def _unlock_foreground():
    _allow_foreground_grant()
    try:
        ctypes.windll.user32.LockSetForegroundWindow(_LSFW_UNLOCK)
    except Exception:
        pass
    try:
        ctypes.windll.user32.keybd_event(_VK_CONTROL, 0, 0, 0)
        ctypes.windll.user32.keybd_event(_VK_CONTROL, 0, _KEYEVENTF_KEYUP, 0)
    except Exception:
        pass


def _window_tid(hwnd):
    pid = ctypes.wintypes.DWORD()
    return ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))


def _force_window_foreground(hwnd):
    if os.name != "nt" or not hwnd:
        return False
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    try:
        hwnd = int(hwnd)
    except (TypeError, ValueError):
        return False
    if not user32.IsWindow(hwnd):
        return False
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, _SW_RESTORE)
    else:
        user32.ShowWindow(hwnd, _SW_SHOW)
    if int(user32.GetForegroundWindow() or 0) == hwnd:
        return True
    _allow_foreground_grant()
    try:
        user32.LockSetForegroundWindow(_LSFW_UNLOCK)
    except Exception:
        pass
    if user32.SetForegroundWindow(hwnd) and int(user32.GetForegroundWindow() or 0) == hwnd:
        return True
    _unlock_foreground()
    fg = user32.GetForegroundWindow()
    current_tid = kernel32.GetCurrentThreadId()
    fg_tid = _window_tid(fg) if fg else 0
    target_tid = _window_tid(hwnd)
    attached_fg = False
    attached_target = False
    try:
        if fg_tid and fg_tid != current_tid:
            attached_fg = bool(user32.AttachThreadInput(current_tid, fg_tid, True))
        if target_tid and target_tid != current_tid and target_tid != fg_tid:
            attached_target = bool(user32.AttachThreadInput(current_tid, target_tid, True))
        user32.BringWindowToTop(hwnd)
        user32.SetWindowPos(
            hwnd,
            _HWND_TOPMOST,
            0,
            0,
            0,
            0,
            _SWP_NOMOVE | _SWP_NOSIZE,
        )
        user32.SetWindowPos(
            hwnd,
            _HWND_NOTOPMOST,
            0,
            0,
            0,
            0,
            _SWP_NOMOVE | _SWP_NOSIZE | _SWP_SHOWWINDOW,
        )
        user32.SetForegroundWindow(hwnd)
        try:
            user32.SwitchToThisWindow(hwnd, True)
        except Exception:
            pass
    finally:
        if attached_target:
            user32.AttachThreadInput(current_tid, target_tid, False)
        if attached_fg:
            user32.AttachThreadInput(current_tid, fg_tid, False)
    return True


def _bring_app_windows_forward(identity, before_hwnds, timeout=7.0):
    if not identity:
        return False
    before = {int(hwnd) for hwnd in before_hwnds}
    started = time.monotonic()
    deadline = started + max(0.2, float(timeout))
    last_target = 0
    last_force_at = 0.0
    saw_created = False
    try:
        while time.monotonic() < deadline:
            hwnds = [int(hwnd) for hwnd in _find_windows_for_app(identity)]
            created = [hwnd for hwnd in hwnds if hwnd not in before]
            elapsed = time.monotonic() - started
            if created:
                saw_created = True
                target = created[-1]
            elif hwnds:
                target = hwnds[0]
            else:
                target = 0
            if target:
                now = time.monotonic()
                fg = int(ctypes.windll.user32.GetForegroundWindow() or 0)
                if (target != last_target or fg != target) and now - last_force_at >= 0.2:
                    _force_window_foreground(target)
                    last_target = target
                    last_force_at = now
            if saw_created and last_target and last_target == target:
                extra_until = time.monotonic() + _FOREGROUND_LATE_WINDOW_WAIT
                while time.monotonic() < extra_until:
                    later = [
                        int(hwnd)
                        for hwnd in _find_windows_for_app(identity)
                        if int(hwnd) not in before
                    ]
                    if later and later[-1] != last_target:
                        _force_window_foreground(later[-1])
                        break
                    time.sleep(_FOREGROUND_POLL)
                return True
            if not created and hwnds and last_target and elapsed >= _FOREGROUND_NEW_WINDOW_WAIT:
                return True
            time.sleep(_FOREGROUND_POLL)
        if last_target:
            return _force_window_foreground(last_target)
        hwnds = [int(hwnd) for hwnd in _find_windows_for_app(identity)]
        return _force_window_foreground(hwnds[0]) if hwnds else False
    except Exception as error:
        LOGGER.debug("Foreground bring-up failed: %s", error)
        return False


def _schedule_bring_app_forward(identity, before_hwnds):
    if os.name != "nt" or not identity:
        return
    threading.Thread(
        target=_bring_app_windows_forward,
        args=(identity, list(before_hwnds)),
        daemon=True,
        name="adeck-foreground",
    ).start()


def _minimize_or_restore_windows(hwnds):
    _allow_foreground_grant()
    visible = [hwnd for hwnd in hwnds if not ctypes.windll.user32.IsIconic(hwnd)]
    if visible:
        for hwnd in visible:
            ctypes.windll.user32.ShowWindow(hwnd, _SW_MINIMIZE)
        return "minimize"
    hwnd = hwnds[0]
    ctypes.windll.user32.ShowWindow(hwnd, _SW_RESTORE)
    _force_window_foreground(hwnd)
    return "restore"


def _close_windows(hwnds):
    for hwnd in hwnds:
        ctypes.windll.user32.PostMessageW(hwnd, _WM_CLOSE, 0, 0)
    return "close"


def _apply_app_relaunch(command, relaunch_mode):
    mode = _normalize_relaunch_mode(relaunch_mode)
    if mode == "new":
        return False
    identity = _win_gui_app_identity(command)
    if identity is None:
        LOGGER.debug("Command is not a toggleable Windows app: %s", command)
        return False
    hwnds = _find_windows_for_app(identity)
    if not hwnds:
        LOGGER.debug("No existing windows for %s", identity["path"])
        return False
    LOGGER.info("App relaunch %s matched %s window(s) for %s", mode, len(hwnds), command)
    if mode == "close":
        _close_windows(hwnds)
    else:
        _minimize_or_restore_windows(hwnds)
    return True


def _launch_win_command(command, relaunch_mode="new", command_kind=""):
    kind = str(command_kind or "").strip().lower()
    if kind != "command" and _apply_app_relaunch(command, relaunch_mode):
        return
    identity = _win_gui_app_identity(command)
    before = _find_windows_for_app(identity) if identity else []
    _allow_foreground_grant()
    text = command.strip()
    plain = os.path.expandvars(text)
    try:
        if re.fullmatch(r"https?://\S+", text, re.IGNORECASE):
            os.startfile(text)
            return

        if re.fullmatch(r"[a-z][a-z0-9+.-]+:\S*", text, re.IGNORECASE) and not re.match(
            r"[a-z]:\\", text, re.IGNORECASE
        ):
            os.startfile(text)
            return

        if _needs_cmd_shell(text):
            subprocess.Popen(text, shell=True)
            return

        executable, params = _parse_win_command(plain)
        resolved = _resolve_win_executable(executable)
        if resolved:
            path = Path(resolved)
            if _uses_explorer_host_launch(path, params):
                subprocess.Popen(["explorer.exe", resolved])
            else:
                _shell_execute_win(resolved, params)
            return

        full_path = Path(plain.strip('"'))
        if full_path.exists():
            os.startfile(str(full_path))
            return

        subprocess.Popen(text, shell=True)
    finally:
        if identity:
            _schedule_bring_app_forward(identity, before)


_APPS_CACHE_LOCK = threading.Lock()
_APPS_CACHE = {"at": 0.0, "payload": None}
_APP_SKIP_NAME = re.compile(
    r"uninstall|help|readme|documentation|eula|release notes|license agreement|"
    r"redistributable|shared framework|targeting pack|prerequisites|"
    r"webview2|asp\.net core|visual c\+\+|desktop runtime|"
    r"software development kit|\bsdk\b|windows kits|"
    r"^python\b|idle \(python|module docs|^node\.js$|"
    r"application verifier|language preferences|"
    r"reset preferences|\bskinned\b|click.?to.?run|"
    r"cert kit|performance analyzer|performance recorder|"
    r"^gpuview$|overlay host|^openal$|send to onenote|"
    r"autodesk access|sticky notes \(new\)",
    re.IGNORECASE,
)
_APP_SKIP_PATH = re.compile(
    r"\\package cache\\|\\windows kits\\|\\clicktorun\\",
    re.IGNORECASE,
)
_APP_SKIP_EXES = {
    "appverif.exe",
    "cmd.exe",
    "cscript.exe",
    "msiexec.exe",
    "node.exe",
    "oalinst.exe",
    "officeclicktorun.exe",
    "onenotem.exe",
    "powershell.exe",
    "pwsh.exe",
    "python.exe",
    "pythonw.exe",
    "setlang.exe",
    "setup.exe",
    "unins000.exe",
    "uninstall.exe",
    "windowsdesktop-runtime-7.0.7-win-x64.exe",
    "wintoast.exe",
    "winsdksetup.exe",
    "wscript.exe",
}
_APP_SKIP_TARGET = re.compile(
    r"(^|\\)(unins\d*|uninstall|setup|msiexec|cmd|powershell|pwsh|wscript|cscript|"
    r"python|pythonw|node|wintoast|oalinst|officeclicktorun|setlang|onenotem|"
    r"appverif|winsdksetup|windowsdesktop-runtime[^\\]*)\.exe$",
    re.IGNORECASE,
)
_BUILTIN_APP_COMMANDS = {
    "calculator": "calc.exe",
    "windows calculator": "calc.exe",
    "paint": "mspaint.exe",
    "notepad": "notepad.exe",
    "file explorer": "explorer.exe",
    "windows explorer": "explorer.exe",
    "settings": "ms-settings:",
    "windows settings": "ms-settings:",
}


def _quote_win_path(path):
    text = str(path).strip()
    if not text:
        return ""
    if " " in text and not (text.startswith('"') and text.endswith('"')):
        return f'"{text}"'
    return text


def _format_app_command(target, arguments=""):
    target = str(target or "").strip().strip('"')
    arguments = str(arguments or "").strip()
    if not target and not arguments:
        return ""
    if not arguments:
        return _quote_win_path(target)[:COMMAND_MAX]
    if not target:
        return arguments[:COMMAND_MAX]
    return f"{_quote_win_path(target)} {arguments}".strip()[:COMMAND_MAX]


def _should_skip_app(name, command):
    if not name or not command:
        return True
    if _APP_SKIP_NAME.search(name):
        return True
    if _APP_SKIP_PATH.search(command.replace("/", "\\")):
        return True
    exe, params = _parse_win_command(command)
    exe_name = Path(os.path.expandvars(exe.strip().strip('"'))).name.lower()
    if exe_name in _APP_SKIP_EXES:
        # Keep wrappers that are real apps launched through pythonw, such as ADeck.
        if exe_name in {"python.exe", "pythonw.exe"}:
            lowered = name.casefold()
            if lowered.startswith("python") or "idle" in lowered or "pydoc" in lowered:
                return True
            return False
        return True
    return bool(_APP_SKIP_TARGET.search(exe.replace("/", "\\")))


def _builtin_windows_apps():
    apps = []
    if os.name != "nt":
        return apps
    for name, command in (
        ("Calculator", "calc.exe"),
        ("Paint", "mspaint.exe"),
        ("Notepad", "notepad.exe"),
        ("File Explorer", "explorer.exe"),
        ("Settings", "ms-settings:"),
    ):
        if command.endswith(":"):
            apps.append({"name": name, "command": command})
            continue
        resolved = _resolve_win_executable(command)
        if resolved or shutil.which(command):
            apps.append({"name": name, "command": command})
    return apps


def _registry_installed_apps():
    apps = []
    if os.name != "nt":
        return apps
    try:
        import winreg
    except ImportError:
        return apps
    roots = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    for hive, location in roots:
        try:
            hive_key = winreg.OpenKey(hive, location)
        except OSError:
            continue
        try:
            index = 0
            while True:
                try:
                    sub_name = winreg.EnumKey(hive_key, index)
                except OSError:
                    break
                index += 1
                try:
                    with winreg.OpenKey(hive_key, sub_name) as sub:
                        name, _ = winreg.QueryValueEx(sub, "DisplayName")
                        icon = ""
                        try:
                            icon, _ = winreg.QueryValueEx(sub, "DisplayIcon")
                        except OSError:
                            icon = ""
                except OSError:
                    continue
                name = str(name or "").strip()
                icon = str(icon or "").strip().strip('"')
                if "," in icon:
                    icon = icon.split(",", 1)[0].strip().strip('"')
                if not name or not icon.lower().endswith(".exe"):
                    continue
                if not Path(os.path.expandvars(icon)).exists():
                    continue
                command = _format_app_command(icon)
                if _should_skip_app(name, command):
                    continue
                apps.append({"name": name, "command": command})
        finally:
            winreg.CloseKey(hive_key)
    return apps


def _read_lnk_string(data, pos, unicode):
    if pos + 2 > len(data):
        return "", pos
    count = int.from_bytes(data[pos : pos + 2], "little")
    pos += 2
    if unicode:
        nbytes = count * 2
        if pos + nbytes > len(data):
            return "", pos
        text = data[pos : pos + nbytes].decode("utf-16le", "ignore").rstrip("\x00")
        return text, pos + nbytes
    if pos + count > len(data):
        return "", pos
    raw = data[pos : pos + count]
    try:
        text = raw.decode("mbcs", "ignore")
    except LookupError:
        text = raw.decode("latin-1", "ignore")
    return text.rstrip("\x00"), pos + count


def _parse_lnk_launch(path):
    try:
        data = Path(path).read_bytes()
    except OSError:
        return "", ""
    if len(data) < 0x4C or data[0:4] != b"L\x00\x00\x00":
        return "", ""
    flags = int.from_bytes(data[0x14:0x18], "little")
    unicode = bool(flags & 0x80)
    pos = 0x4C
    if flags & 0x01:
        if pos + 2 > len(data):
            return "", ""
        idlist_size = int.from_bytes(data[pos : pos + 2], "little")
        pos += 2 + idlist_size
    target = ""
    if flags & 0x02 and pos + 20 <= len(data):
        linkinfo_size = int.from_bytes(data[pos : pos + 4], "little")
        if 20 <= linkinfo_size and pos + linkinfo_size <= len(data):
            linkinfo = data[pos : pos + linkinfo_size]
            local_off = int.from_bytes(linkinfo[16:20], "little")
            if local_off and local_off < len(linkinfo):
                raw = linkinfo[local_off:].split(b"\x00", 1)[0]
                try:
                    target = raw.decode("mbcs", "ignore")
                except LookupError:
                    target = raw.decode("latin-1", "ignore")
            pos += linkinfo_size
    arguments = ""
    for mask in (0x04, 0x08, 0x10, 0x20):
        if not (flags & mask):
            continue
        text, pos = _read_lnk_string(data, pos, unicode)
        if mask == 0x20:
            arguments = text
    return target.strip(), arguments.strip()


def _start_menu_roots():
    roots = []
    programdata = os.environ.get("ProgramData")
    appdata = os.environ.get("APPDATA")
    if programdata:
        roots.append(Path(programdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs")
    if appdata:
        roots.append(Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs")
    return roots


def _start_menu_shortcut_apps():
    apps = []
    if os.name != "nt":
        return apps
    for root in _start_menu_roots():
        if not root.is_dir():
            continue
        try:
            links = root.rglob("*.lnk")
        except OSError:
            continue
        for lnk in links:
            name = lnk.stem.strip()
            if not name:
                continue
            mapped = _BUILTIN_APP_COMMANDS.get(name.casefold())
            if mapped:
                apps.append({"name": name, "command": mapped})
                continue
            target, arguments = _parse_lnk_launch(lnk)
            if not target.lower().endswith(".exe"):
                continue
            if not Path(os.path.expandvars(target)).exists():
                continue
            command = _format_app_command(target, arguments)
            if _should_skip_app(name, command):
                continue
            apps.append({"name": name, "command": command})
    return apps


def _dedupe_installed_apps(apps):
    by_command = {}
    for app in apps:
        name = str(app.get("name") or "").strip()
        command = str(app.get("command") or "").strip()
        if not name or not command or len(command) > COMMAND_MAX:
            continue
        key = command.casefold()
        previous = by_command.get(key)
        if previous is None or len(name) < len(previous["name"]):
            by_command[key] = {"name": name, "command": command}
    unique = sorted(by_command.values(), key=lambda item: item["name"].casefold())
    by_name = {}
    for app in unique:
        key = app["name"].casefold()
        previous = by_name.get(key)
        if previous is None:
            by_name[key] = app
            continue
        prev_exists = Path(os.path.expandvars(previous["command"].strip('"'))).exists()
        curr_exists = Path(os.path.expandvars(app["command"].strip('"'))).exists()
        if curr_exists and not prev_exists:
            by_name[key] = app
    return sorted(by_name.values(), key=lambda item: item["name"].casefold())


def list_installed_apps():
    with _APPS_CACHE_LOCK:
        cached = _APPS_CACHE["payload"]
        if cached is not None and (time.monotonic() - _APPS_CACHE["at"]) < 60:
            return cached
    errors = []
    apps = []
    try:
        apps.extend(_builtin_windows_apps())
    except Exception as error:
        errors.append(f"builtins: {error}")
    try:
        apps.extend(_start_menu_shortcut_apps())
    except Exception as error:
        errors.append(f"start menu: {error}")
    try:
        apps.extend(_registry_installed_apps())
    except Exception as error:
        errors.append(f"registry: {error}")
    payload = {
        "ok": True,
        "apps": _dedupe_installed_apps(apps),
        "error": "; ".join(errors),
    }
    with _APPS_CACHE_LOCK:
        _APPS_CACHE["at"] = time.monotonic()
        _APPS_CACHE["payload"] = payload
    return payload


_ICON_SIZE = 32
_ICON_EXTRACT_LOCK = threading.Lock()
_ICON_APIS_READY = False
_ICON_FILE_SUFFIXES = {".dll", ".exe", ".ico", ".lnk"}
_SHGFI_ICON = 0x000000100
_SHGFI_LARGEICON = 0x000000000
_DI_NORMAL = 0x0003
_BI_RGB = 0
_DIB_RGB_COLORS = 0


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.wintypes.DWORD),
        ("biWidth", ctypes.wintypes.LONG),
        ("biHeight", ctypes.wintypes.LONG),
        ("biPlanes", ctypes.wintypes.WORD),
        ("biBitCount", ctypes.wintypes.WORD),
        ("biCompression", ctypes.wintypes.DWORD),
        ("biSizeImage", ctypes.wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.wintypes.LONG),
        ("biYPelsPerMeter", ctypes.wintypes.LONG),
        ("biClrUsed", ctypes.wintypes.DWORD),
        ("biClrImportant", ctypes.wintypes.DWORD),
    ]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", _BITMAPINFOHEADER),
        ("bmiColors", ctypes.wintypes.DWORD * 3),
    ]


class _SHFILEINFOW(ctypes.Structure):
    _fields_ = [
        ("hIcon", ctypes.wintypes.HICON),
        ("iIcon", ctypes.c_int),
        ("dwAttributes", ctypes.wintypes.DWORD),
        ("szDisplayName", ctypes.wintypes.WCHAR * 260),
        ("szTypeName", ctypes.wintypes.WCHAR * 80),
    ]


def _ensure_icon_apis():
    global _ICON_APIS_READY
    if _ICON_APIS_READY or os.name != "nt":
        return
    shell32 = ctypes.windll.shell32
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    shell32.SHGetFileInfoW.argtypes = [
        ctypes.wintypes.LPCWSTR,
        ctypes.wintypes.DWORD,
        ctypes.POINTER(_SHFILEINFOW),
        ctypes.wintypes.UINT,
        ctypes.wintypes.UINT,
    ]
    shell32.SHGetFileInfoW.restype = ctypes.c_void_p
    shell32.ExtractIconExW.argtypes = [
        ctypes.wintypes.LPCWSTR,
        ctypes.c_int,
        ctypes.POINTER(ctypes.wintypes.HICON),
        ctypes.POINTER(ctypes.wintypes.HICON),
        ctypes.wintypes.UINT,
    ]
    shell32.ExtractIconExW.restype = ctypes.wintypes.UINT
    user32.PrivateExtractIconsW.argtypes = [
        ctypes.wintypes.LPCWSTR,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.POINTER(ctypes.wintypes.HICON),
        ctypes.POINTER(ctypes.wintypes.UINT),
        ctypes.wintypes.UINT,
        ctypes.wintypes.UINT,
    ]
    user32.PrivateExtractIconsW.restype = ctypes.wintypes.UINT
    user32.DestroyIcon.argtypes = [ctypes.wintypes.HICON]
    user32.DestroyIcon.restype = ctypes.wintypes.BOOL
    user32.GetDC.argtypes = [ctypes.wintypes.HWND]
    user32.GetDC.restype = ctypes.wintypes.HDC
    user32.ReleaseDC.argtypes = [ctypes.wintypes.HWND, ctypes.wintypes.HDC]
    user32.DrawIconEx.argtypes = [
        ctypes.wintypes.HDC,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.wintypes.HICON,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.wintypes.UINT,
        ctypes.wintypes.HANDLE,
        ctypes.wintypes.UINT,
    ]
    user32.DrawIconEx.restype = ctypes.wintypes.BOOL
    gdi32.CreateCompatibleDC.argtypes = [ctypes.wintypes.HDC]
    gdi32.CreateCompatibleDC.restype = ctypes.wintypes.HDC
    gdi32.CreateDIBSection.argtypes = [
        ctypes.wintypes.HDC,
        ctypes.POINTER(_BITMAPINFO),
        ctypes.wintypes.UINT,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.wintypes.HANDLE,
        ctypes.wintypes.DWORD,
    ]
    gdi32.CreateDIBSection.restype = ctypes.wintypes.HBITMAP
    gdi32.SelectObject.argtypes = [ctypes.wintypes.HDC, ctypes.wintypes.HANDLE]
    gdi32.SelectObject.restype = ctypes.wintypes.HANDLE
    gdi32.DeleteObject.argtypes = [ctypes.wintypes.HANDLE]
    gdi32.DeleteDC.argtypes = [ctypes.wintypes.HDC]
    _ICON_APIS_READY = True


def _png_from_rgba(width, height, rgba):
    stride = width * 4
    expected = stride * height
    if width <= 0 or height <= 0 or len(rgba) < expected:
        return b""
    def chunk(tag, data):
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    rows = [b"\x00" + rgba[y * stride : (y + 1) * stride] for y in range(height)]
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
        + chunk(b"IEND", b"")
    )


def _placeholder_icon_png(size=_ICON_SIZE):
    row = []
    for y in range(size):
        for x in range(size):
            edge = x < 2 or y < 2 or x >= size - 2 or y >= size - 2
            inner = 8 <= x < size - 8 and 8 <= y < size - 8
            if edge:
                row.extend((20, 20, 18, 255))
            elif inner:
                row.extend((210, 208, 200, 255))
            else:
                row.extend((120, 118, 110, 255))
    return _png_from_rgba(size, size, bytes(row))


def _hicon_to_png(hicon, size=_ICON_SIZE):
    if not hicon:
        return b""
    _ensure_icon_apis()
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    hdc = user32.GetDC(None)
    if not hdc:
        return b""
    memdc = gdi32.CreateCompatibleDC(hdc)
    bits_ptr = ctypes.c_void_p()
    bmi = _BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = size
    bmi.bmiHeader.biHeight = -size
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = _BI_RGB
    hbm = gdi32.CreateDIBSection(
        memdc, ctypes.byref(bmi), _DIB_RGB_COLORS, ctypes.byref(bits_ptr), None, 0
    )
    png = b""
    if hbm and bits_ptr.value:
        old = gdi32.SelectObject(memdc, hbm)
        ctypes.memset(bits_ptr.value, 0, size * size * 4)
        user32.DrawIconEx(memdc, 0, 0, hicon, size, size, 0, None, _DI_NORMAL)
        raw = ctypes.string_at(bits_ptr.value, size * size * 4)
        gdi32.SelectObject(memdc, old)
        pixels = bytearray(raw)
        opaque = True
        for index in range(0, len(pixels), 4):
            pixels[index], pixels[index + 2] = pixels[index + 2], pixels[index]
            if pixels[index + 3]:
                opaque = False
        if opaque:
            for index in range(3, len(pixels), 4):
                pixels[index] = 255
        png = _png_from_rgba(size, size, bytes(pixels))
        gdi32.DeleteObject(hbm)
    if memdc:
        gdi32.DeleteDC(memdc)
    user32.ReleaseDC(None, hdc)
    return png


def _hicon_from_path(path, index=0):
    _ensure_icon_apis()
    info = _SHFILEINFOW()
    result = ctypes.windll.shell32.SHGetFileInfoW(
        path, 0, ctypes.byref(info), ctypes.sizeof(info), _SHGFI_ICON | _SHGFI_LARGEICON
    )
    if result and info.hIcon:
        return info.hIcon
    large = ctypes.wintypes.HICON()
    icon_id = ctypes.wintypes.UINT()
    count = ctypes.windll.user32.PrivateExtractIconsW(
        path, index, _ICON_SIZE, _ICON_SIZE, ctypes.byref(large), ctypes.byref(icon_id), 1, 0
    )
    if count and large.value:
        return large
    large = ctypes.wintypes.HICON()
    small = ctypes.wintypes.HICON()
    count = ctypes.windll.shell32.ExtractIconExW(
        path, index, ctypes.byref(large), ctypes.byref(small), 1
    )
    if small.value:
        ctypes.windll.user32.DestroyIcon(small)
    if count and large.value:
        return large
    return None


def _icon_source_for_command(command):
    text = str(command or "").strip()
    if not text:
        return ""
    if re.match(r"ms-settings:", text, re.IGNORECASE):
        for candidate in (
            os.path.expandvars(r"%SystemRoot%\ImmersiveControlPanel\SystemSettings.exe"),
            os.path.expandvars(r"%SystemRoot%\System32\shell32.dll"),
        ):
            if Path(candidate).is_file():
                return candidate
        return ""
    if re.fullmatch(r"[a-z][a-z0-9+.-]+:\S*", text, re.IGNORECASE) and not re.match(
        r"[a-z]:\\", text, re.IGNORECASE
    ):
        shell32 = os.path.expandvars(r"%SystemRoot%\System32\shell32.dll")
        return shell32 if Path(shell32).is_file() else ""
    executable, _params = _parse_win_command(os.path.expandvars(text))
    resolved = _resolve_win_executable(executable) if executable else None
    path = Path(resolved) if resolved else Path(
        os.path.expandvars((executable or "").strip().strip('"'))
    )
    if path.suffix.lower() in _ICON_FILE_SUFFIXES and path.is_file():
        return str(path)
    return ""


def app_icon_png(command, cache_dir=None):
    placeholder = _placeholder_icon_png()
    if os.name != "nt":
        return placeholder
    source = _icon_source_for_command(command)
    if not source:
        return placeholder
    folder = Path(cache_dir) if cache_dir else ICON_CACHE_DIR
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:24]
    cache_path = folder / f"{digest}.png"
    try:
        source_mtime = Path(source).stat().st_mtime
        if cache_path.is_file() and cache_path.stat().st_mtime >= source_mtime:
            data = cache_path.read_bytes()
            if data.startswith(b"\x89PNG"):
                return data
    except OSError:
        pass
    with _ICON_EXTRACT_LOCK:
        hicon = None
        try:
            hicon = _hicon_from_path(source)
            png = _hicon_to_png(hicon) if hicon else b""
        except Exception as error:
            LOGGER.debug("App icon extract failed for %s: %s", source, error)
            png = b""
        finally:
            if hicon:
                try:
                    ctypes.windll.user32.DestroyIcon(hicon)
                except Exception:
                    pass
    if not png.startswith(b"\x89PNG"):
        return placeholder
    try:
        folder.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(png)
    except OSError:
        pass
    return png


class ConfigStore:
    def __init__(self, path=None, backup_path=None):
        self.path = Path(path) if path else CONFIG_PATH
        self.backup_path = Path(backup_path) if backup_path else self.path.with_name(
            "config.backup.json"
        )
        self.lock = threading.RLock()
        self.config = None
        self.load()

    def _read_valid(self, path):
        with path.open("r", encoding="utf-8") as handle:
            return normalize_config(json.load(handle))

    def _quarantine(self, error):
        stamp = time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)
        target = self.path.with_name(f"config.corrupt-{stamp}.json")
        try:
            os.replace(self.path, target)
            LOGGER.error("Quarantined corrupt config as %s: %s", target.name, error)
        except OSError:
            LOGGER.error("Could not quarantine corrupt config: %s", error)

    def load(self):
        with self.lock:
            if not self.path.exists():
                return
            try:
                self.config = self._read_valid(self.path)
                LOGGER.info("Loaded configuration")
                return
            except Exception as error:
                self._quarantine(error)
            if self.backup_path.exists():
                try:
                    self.config = self._read_valid(self.backup_path)
                    _atomic_json(self.path, self.config)
                    LOGGER.warning("Recovered configuration from backup")
                except Exception as error:
                    LOGGER.error("Backup configuration is invalid: %s", error)

    def save(self, raw):
        config = normalize_config(raw)
        with self.lock:
            backed_up_previous = False
            if self.path.exists():
                try:
                    previous = self._read_valid(self.path)
                    _atomic_json(self.backup_path, previous)
                    backed_up_previous = True
                except Exception as error:
                    self._quarantine(error)
            _atomic_json(self.path, config)
            if not backed_up_previous:
                _atomic_json(self.backup_path, config)
            self.config = config
            return _clone(config)

    def snapshot(self):
        with self.lock:
            return _clone(self.config) if self.config is not None else None

    def command_for(self, index):
        with self.lock:
            if self.config is None or not 0 <= index < SLOT_COUNT:
                return ""
            return active_buttons(self.config)[index]["command"].strip()

    def command_kind_for(self, index):
        with self.lock:
            if self.config is None or not 0 <= index < SLOT_COUNT:
                return ""
            kind = active_buttons(self.config)[index].get("kind") or ""
            return str(kind).strip().lower()

    def app_relaunch_mode(self):
        with self.lock:
            if self.config is None:
                return "new"
            settings = self.config.get("settings") or {}
            if not isinstance(settings, dict):
                return "new"
            return _normalize_relaunch_mode(
                settings.get("appRelaunchMode") or settings.get("app_relaunch_mode")
            )


class ProtocolError(Exception):
    pass


@dataclass
class SyncRequest:
    config: dict
    txid: str = field(default_factory=lambda: secrets.token_hex(6))
    finished: threading.Event = field(default_factory=threading.Event)
    state: str = "sync_failed"
    error: str = ""


class ADeckDevice:
    def __init__(self, store, requested_port=None, identity_path=None):
        self.store = store
        self.requested_port = requested_port or os.environ.get("ADECK_PORT")
        self.identity_path = Path(identity_path) if identity_path else IDENTITY_PATH
        self.identity = self._load_identity()
        self._state_lock = threading.RLock()
        self._connection = None
        self._port = None
        self._firmware = None
        self._last_error = ""
        self._last_sync = None
        self._last_txid = None
        self._stop = threading.Event()
        self._resync = threading.Event()
        self._requests = queue.Queue()
        self.thread = threading.Thread(target=self._run, name="adeck-device", daemon=True)

    def _load_identity(self):
        paths = [
            self.identity_path,
            self.identity_path.with_name("board.json"),
            self.identity_path.with_name("board_identity.json"),
            LOCAL_DATA_DIR / "device.json",
            LOCAL_DATA_DIR / "board.json",
            LOCAL_DATA_DIR / "board_identity.json",
        ]
        for path in paths:
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(value, dict) and isinstance(value.get("board"), dict):
                    value = value["board"]
                if isinstance(value, dict):
                    return value
            except (OSError, ValueError, TypeError, AttributeError):
                continue
        return {}

    @staticmethod
    def _number(value):
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            try:
                text = value.strip()
                if text.lower().startswith("0x"):
                    return int(text, 16)
                if re.fullmatch(r"[0-9A-Fa-f]{4}", text):
                    return int(text, 16)
                return int(text, 10)
            except ValueError:
                return None
        return None

    def start(self):
        self.thread.start()

    def stop(self):
        self._stop.set()
        self._requests.put(None)
        with self._state_lock:
            connection = self._connection
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass
        if self.thread.is_alive():
            self.thread.join(timeout=5)

    def status(self):
        with self._state_lock:
            return {
                "connected": self._connection is not None,
                "port": self._port,
                "firmware": self._firmware,
                "last_sync": self._last_sync,
                "last_transaction_id": self._last_txid,
                "error": self._last_error or None,
            }

    def available_ports(self):
        """Serial ports visible right now, tagged with ADeck-match information."""
        if list_ports is None:
            return []
        ports = []
        for info in list_ports.comports():
            try:
                matches = self._metadata_matches(info)
            except Exception:
                matches = False
            ports.append(
                {
                    "device": info.device,
                    "description": (getattr(info, "description", "") or "").strip(),
                    "manufacturer": (getattr(info, "manufacturer", "") or "").strip(),
                    "serial_number": getattr(info, "serial_number", None),
                    "arduino": getattr(info, "vid", None) in ARDUINO_VIDS,
                    "matches": matches,
                }
            )
        return ports

    def request_reconnect(self, port=None):
        """Drop the serial link (optionally pinning a port) so discovery runs again."""
        if port is not None:
            self.requested_port = port or None
        with self._state_lock:
            connection = self._connection
            self._connection = None
            self._port = None
            self._firmware = None
            self._last_sync = None
            self._last_error = "Reconnecting"
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass
        self._resync.set()
        LOGGER.info("Reconnect requested (port=%s)", self.requested_port or "auto")

    def request_sync(self, config, timeout=5):
        with self._state_lock:
            if self._connection is None:
                self._resync.set()
                return {
                    "sync_state": "offline",
                    "device_synced": False,
                    "transaction_id": None,
                    "acknowledged_transaction_id": None,
                    "sync_error": None,
                }
        request = SyncRequest(_clone(config))
        self._requests.put(request)
        if not request.finished.wait(timeout):
            return {
                "sync_state": "sync_failed",
                "device_synced": False,
                "transaction_id": request.txid,
                "acknowledged_transaction_id": None,
                "sync_error": "Timed out waiting for device acknowledgement",
            }
        return {
            "sync_state": request.state,
            "device_synced": request.state == "synced",
            "transaction_id": request.txid,
            "acknowledged_transaction_id": request.txid if request.state == "synced" else None,
            "sync_error": request.error or None,
        }

    def _metadata_matches(self, info):
        if self.requested_port:
            return info.device.lower() == self.requested_port.lower()
        serial_number = (
            self.identity.get("serial_number")
            or self.identity.get("serialNumber")
            or self.identity.get("serial")
        )
        wanted_vid = self._number(self.identity.get("vid") or self.identity.get("usb_vid"))
        wanted_pid = self._number(self.identity.get("pid") or self.identity.get("usb_pid"))
        if serial_number:
            return (
                str(getattr(info, "serial_number", "") or "") == str(serial_number)
                and getattr(info, "vid", None) in ARDUINO_VIDS
            )
        if wanted_vid is not None:
            return (
                getattr(info, "vid", None) == wanted_vid
                and (wanted_pid is None or getattr(info, "pid", None) == wanted_pid)
                and wanted_vid in ARDUINO_VIDS
            )
        text = " ".join(
            str(getattr(info, field, "") or "")
            for field in ("description", "manufacturer", "product", "hwid")
        ).lower()
        return getattr(info, "vid", None) in ARDUINO_VIDS and (
            "arduino" in text or "uno r4" in text
        )

    def _candidate_ports(self):
        ports = list(list_ports.comports())
        if self.requested_port and not any(
            item.device.lower() == self.requested_port.lower() for item in ports
        ):
            return [(self.requested_port, None)]
        matched = [(item.device, item) for item in ports if self._metadata_matches(item)]
        last_port = (
            self.identity.get("last_port")
            or self.identity.get("port")
            or self.identity.get("address")
        )
        matched.sort(key=lambda item: (item[0] != last_port, item[0]))
        return matched

    def _probe(self, port):
        connection = serial.Serial(port, BAUD, timeout=0.15, write_timeout=1)
        try:
            time.sleep(1.7)
            connection.reset_input_buffer()
            connection.write(b"PING\n")
            connection.flush()
            deadline = time.monotonic() + 1.8
            while time.monotonic() < deadline and not self._stop.is_set():
                line = connection.readline().decode("ascii", errors="ignore").strip()
                if line == f"ADECK_PONG\t{PROTOCOL_VERSION}":
                    return connection
                if line.startswith("PRESS\t"):
                    self._handle_line(line)
        except Exception:
            connection.close()
            raise
        connection.close()
        return None

    def _save_identity(self, port, info):
        identity = dict(self.identity)
        identity["last_port"] = port
        if info is not None:
            for field in ("vid", "pid", "serial_number", "manufacturer", "product"):
                value = getattr(info, field, None)
                if value is not None:
                    identity[field] = value
        try:
            _atomic_json(self.identity_path, identity)
            self.identity = identity
        except OSError as error:
            LOGGER.warning("Could not store board identity: %s", error)

    def _connect(self):
        try:
            candidates = self._candidate_ports()
        except Exception as error:
            with self._state_lock:
                self._last_error = f"Serial discovery failed: {error}"
            LOGGER.warning("Serial discovery failed: %s", error)
            return False
        for port, info in candidates:
            if self._stop.is_set():
                return False
            try:
                connection = self._probe(port)
                if connection is None:
                    continue
                with self._state_lock:
                    self._connection = connection
                    self._port = port
                    self._firmware = PROTOCOL_VERSION
                    self._last_error = ""
                self._save_identity(port, info)
                self._resync.set()
                LOGGER.info("Connected to ADeck on %s", port)
                return True
            except Exception as error:
                LOGGER.debug("Probe failed on %s: %s", port, error)
        with self._state_lock:
            self._last_error = "ADeck not found"
        return False

    def _disconnect(self, error=""):
        with self._state_lock:
            connection = self._connection
            port = self._port
            self._connection = None
            self._port = None
            self._firmware = None
            self._last_sync = False
            if error:
                self._last_error = error
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass
        if port:
            LOGGER.warning("Disconnected from %s: %s", port, error or "connection closed")

    def _run_command(self, index):
        if not 0 <= index < SLOT_COUNT:
            return
        command = self.store.command_for(index)
        if not command:
            return
        getter = getattr(self.store, "app_relaunch_mode", None)
        relaunch_mode = getter() if callable(getter) else "new"
        kind_getter = getattr(self.store, "command_kind_for", None)
        command_kind = kind_getter(index) if callable(kind_getter) else ""
        try:
            LOGGER.info(
                "Dispatching command for key %s [%s/%s]: %s",
                index + 1,
                _normalize_relaunch_mode(relaunch_mode),
                command_kind or "auto",
                command,
            )
            if os.name == "nt":
                _launch_win_command(command, relaunch_mode, command_kind)
            else:
                subprocess.Popen(command, shell=True)
        except Exception as error:
            LOGGER.error("Command for key %s failed: %s", index + 1, error)

    def _handle_line(self, line):
        if line.startswith("PRESS\t"):
            try:
                index = int(line.split("\t", 1)[1])
            except ValueError:
                return
            if 0 <= index < SLOT_COUNT:
                LOGGER.info("Physical press received for key %s", index + 1)
                threading.Thread(
                    target=self._run_command, args=(index,), name=f"adeck-key-{index}", daemon=True
                ).start()
        elif line == f"ADECK_READY\t{PROTOCOL_VERSION}":
            self._resync.set()

    def _sync(self, config, txid):
        frame = config_frame(config, txid)
        with self._state_lock:
            connection = self._connection
        if connection is None:
            raise OSError("ADeck is offline")
        connection.write(frame)
        connection.flush()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not self._stop.is_set():
            line = connection.readline().decode("ascii", errors="ignore").strip()
            if line == f"CFG_OK\t{txid}":
                with self._state_lock:
                    self._last_sync = True
                    self._last_txid = txid
                    self._last_error = ""
                LOGGER.info("Synchronized transaction %s", txid)
                return
            if line.startswith(f"CFG_ERR\t{txid}\t"):
                reason = line.split("\t", 2)[2]
                with self._state_lock:
                    self._last_sync = False
                    self._last_txid = txid
                    self._last_error = f"Device rejected config: {reason}"
                raise ProtocolError(reason)
            if line:
                self._handle_line(line)
        raise TimeoutError("ADeck did not acknowledge the configuration")

    def _complete_request(self, request):
        try:
            self._sync(request.config, request.txid)
            request.state = "synced"
        except ProtocolError as error:
            request.state = "sync_failed"
            request.error = f"Device rejected config: {error}"
            LOGGER.warning("Transaction %s rejected: %s", request.txid, error)
        except Exception as error:
            request.state = "sync_failed"
            request.error = str(error)
            self._disconnect(str(error))
            self._resync.set()
        finally:
            request.finished.set()

    def _run(self):
        while not self._stop.is_set():
            with self._state_lock:
                connected = self._connection is not None
            if not connected:
                if serial is None or list_ports is None:
                    with self._state_lock:
                        self._last_error = "PySerial is not installed"
                    self._stop.wait(3)
                    continue
                if not self._connect():
                    self._stop.wait(2)
                    continue

            if self._resync.is_set():
                self._resync.clear()
                current = self.store.snapshot()
                if current is not None:
                    try:
                        self._sync(current, secrets.token_hex(6))
                    except ProtocolError as error:
                        LOGGER.warning("Automatic resync rejected: %s", error)
                    except Exception as error:
                        self._disconnect(str(error))
                        self._stop.wait(1)
                        continue

            try:
                request = self._requests.get(timeout=0.05)
                if request is None:
                    continue
                self._complete_request(request)
                continue
            except queue.Empty:
                pass

            try:
                with self._state_lock:
                    connection = self._connection
                if connection is not None:
                    line = connection.readline().decode("ascii", errors="ignore").strip()
                    if line:
                        self._handle_line(line)
            except Exception as error:
                self._disconnect(str(error))
                self._stop.wait(1)
        self._disconnect()


class BridgeServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, handler, store, device, control_token):
        super().__init__(address, handler)
        self.store = store
        self.device = device
        self.control_token = control_token
        self.save_lock = threading.Lock()
        self.started_at = time.time()
        # server_address reflects the port actually bound (address may ask for 0).
        self.http_host = self.server_address[0]
        self.http_port = self.server_address[1]


class BridgeHandler(BaseHTTPRequestHandler):
    static_files = {
        "/": "index.html",
        "/index.html": "index.html",
        "/script.js": "script.js",
        "/style.css": "style.css",
        "/sw.js": "sw.js",
        "/manifest.webmanifest": "manifest.webmanifest",
        "/icon-192.png": "icon-192.png",
        "/icon-512.png": "icon-512.png",
        "/icon-maskable-512.png": "icon-maskable-512.png",
        "/favicon.ico": "adeck.ico",
        "/adeck.ico": "adeck.ico",
    }

    def log_message(self, format, *args):
        if debug_enabled():
            LOGGER.debug("%s - %s", self.address_string(), format % args)

    def _host_allowed(self):
        host = self.headers.get("Host", "")
        try:
            return urlparse("//" + host).hostname in LOCAL_HOSTS
        except ValueError:
            return False

    def _origin_allowed(self):
        if not self._host_allowed():
            return False
        origin = self.headers.get("Origin")
        if not origin:
            return True
        if origin == "null":
            return False
        try:
            parsed = urlparse(origin)
            host = urlparse("//" + self.headers["Host"])
            return (
                parsed.scheme == "http"
                and parsed.hostname == host.hostname
                and (parsed.port or 80) == (host.port or 80)
            )
        except ValueError:
            return False

    def _cors(self):
        origin = self.headers.get("Origin")
        if origin and self._origin_allowed():
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-ADeck-Token")

    def _json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _png(self, body, cacheable=False):
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(body)))
        self.send_header(
            "Cache-Control", "private, max-age=86400" if cacheable else "no-store"
        )
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _api_allowed(self):
        if self._origin_allowed():
            return True
        self._json(403, {"ok": False, "error": "Local same-origin request required"})
        return False

    def _system_payload(self):
        device = self.server.device
        store = self.server.store
        config = store.snapshot()
        integration = {}
        task_actions = []
        tasks = []
        control_error = None
        try:
            control = control_module()
            integration = control.integration_state()
            task_actions = sorted(control.TASK_ACTIONS)
            tasks = control.list_tasks(5)
        except Exception as error:
            control_error = str(error)
            LOGGER.warning("Control helper unavailable: %s", error)
        try:
            ports = device.available_ports()
        except Exception as error:
            ports = []
            LOGGER.warning("Port enumeration failed: %s", error)
        arduino_cli = BUNDLED_CLI.is_file() or shutil.which("arduino-cli") is not None
        pyserial = getattr(serial, "__version__", None) if serial is not None else None
        return {
            "ok": True,
            "service": SERVICE_NAME,
            "bridge_version": APP_VERSION,
            "protocol_version": PROTOCOL_VERSION,
            "backend": {
                "pid": os.getpid(),
                "host": self.server.http_host,
                "port": self.server.http_port,
                "uptime_seconds": int(max(0, time.time() - self.server.started_at)),
                "python": sys.version.split()[0],
                "debug": debug_enabled(),
            },
            "device": device.status(),
            "requested_port": device.requested_port,
            "serial_ports": ports,
            "config": {
                "saved": config is not None,
                "path": str(store.path),
                "backup_path": str(store.backup_path),
                "active_profile": config["active_profile"] if config else None,
                "profile_count": len(config["profiles"]) if config else 0,
            },
            "environment": {
                "pyserial": pyserial,
                "venv": VENV_PYTHON.is_file(),
                "arduino_cli": arduino_cli,
                "log_dir": str(LOCAL_DATA_DIR),
                "data_dir": str(DATA_DIR),
                "setup_complete": bool(
                    VENV_PYTHON.is_file() and pyserial and arduino_cli
                ),
            },
            "integration": integration,
            "task_actions": task_actions,
            "tasks": tasks,
            "control_error": control_error,
        }

    def _logs_payload(self, query):
        params = parse_qs(query)
        source = (params.get("source") or ["app"])[0]
        path = LOG_SOURCES.get(source)
        if path is None:
            return None, f"Unknown log source: {source}"
        try:
            requested = int((params.get("lines") or ["200"])[0])
        except (TypeError, ValueError):
            requested = 200
        limit = max(1, min(500, requested))
        try:
            lines = control_module().tail_lines(path, limit)
        except Exception as error:
            return None, str(error)
        return {
            "ok": True,
            "source": source,
            "path": str(path),
            "exists": path.is_file(),
            "lines": lines,
        }, None

    def do_OPTIONS(self):
        if not self._api_allowed():
            return
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path in {"/api/status", "/status"}:
            if not self._api_allowed():
                return
            config = self.server.store.snapshot()
            self._json(
                200,
                {
                    "ok": True,
                    "service": SERVICE_NAME,
                    "bridge_version": APP_VERSION,
                    "config_saved": config is not None,
                    **self.server.device.status(),
                },
            )
            return
        if path == "/api/config":
            if not self._api_allowed():
                return
            config = self.server.store.snapshot()
            self._json(
                200,
                {"ok": True, "has_config": config is not None, "config": config},
            )
            return
        if path == "/api/apps":
            if not self._api_allowed():
                return
            try:
                payload = list_installed_apps()
            except Exception as error:
                LOGGER.warning("Installed app listing failed: %s", error)
                payload = {"ok": True, "apps": [], "error": str(error)}
            self._json(200, payload)
            return
        if path == "/api/app-icon":
            if not self._api_allowed():
                return
            query = parse_qs(urlparse(self.path).query)
            command = (query.get("command") or [""])[0]
            if len(command) > COMMAND_MAX:
                command = ""
            try:
                body = app_icon_png(command)
            except Exception as error:
                LOGGER.debug("App icon request failed: %s", error)
                body = _placeholder_icon_png()
            cacheable = bool(command) and body != _placeholder_icon_png()
            self._png(body, cacheable=cacheable)
            return

        if path == "/api/system":
            if not self._api_allowed():
                return
            self._json(200, self._system_payload())
            return

        if path == "/api/logs":
            if not self._api_allowed():
                return
            payload, error = self._logs_payload(urlparse(self.path).query)
            if payload is None:
                self._json(400, {"ok": False, "error": error})
                return
            self._json(200, payload)
            return

        if path == "/api/tasks":
            if not self._api_allowed():
                return
            try:
                tasks = control_module().list_tasks(10)
            except Exception as error:
                self._json(500, {"ok": False, "error": str(error)})
                return
            self._json(200, {"ok": True, "tasks": tasks})
            return

        if path.startswith("/api/tasks/"):
            if not self._api_allowed():
                return
            task_id = path[len("/api/tasks/") :]
            try:
                task = control_module().read_task(task_id)
            except Exception as error:
                self._json(500, {"ok": False, "error": str(error)})
                return
            if task is None:
                self._json(404, {"ok": False, "error": "Unknown task"})
                return
            self._json(200, {"ok": True, "task": task})
            return

        filename = self.static_files.get(path)
        if filename is not None:
            file_path = WEB_DIR / filename
        elif path.startswith("/fonts/"):
            rel = path[len("/fonts/") :]
            if not rel or ".." in rel or rel.startswith(("/", "\\")):
                self.send_error(404)
                return
            file_path = WEB_DIR / "fonts" / rel
        else:
            self.send_error(404)
            return
        try:
            body = file_path.read_bytes()
        except OSError:
            self.send_error(404)
            return
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _read_config(self):
        if self.headers.get_content_type() != "application/json":
            raise ValueError("Content-Type must be application/json")
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ValueError("Invalid config size") from None
        if length <= 0 or length > MAX_CONFIG_BYTES:
            raise ValueError("Invalid config size")
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("Invalid JSON config") from error

    def _read_json_body(self, maximum=MAX_CONTROL_BYTES):
        if self.headers.get_content_type() != "application/json":
            raise ValueError("Content-Type must be application/json")
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ValueError("Invalid request size") from None
        if length < 0 or length > maximum:
            raise ValueError("Invalid request size")
        if length == 0:
            return {}
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("Invalid JSON body") from error
        if not isinstance(payload, dict):
            raise ValueError("Request body must be an object")
        return payload

    def _handle_control(self, payload):
        """Device/backend/desktop actions used by the ADeck UI."""
        device = self.server.device
        action = str(payload.get("action") or "").strip().lower()
        if not action:
            self._json(400, {"ok": False, "error": "An action is required"})
            return

        if action == "reconnect":
            port = payload.get("port")
            if port is not None:
                port = str(port).strip()
                if port and not SERIAL_PORT_PATTERN.fullmatch(port):
                    self._json(400, {"ok": False, "error": "Invalid serial port name"})
                    return
            device.request_reconnect(port)
            self._json(
                200,
                {
                    "ok": True,
                    "action": action,
                    "message": "Looking for ADeck"
                    + (f" on {device.requested_port}" if device.requested_port else ""),
                    "device": device.status(),
                },
            )
            return

        if action == "resync":
            config = self.server.store.snapshot()
            if config is None:
                self._json(400, {"ok": False, "error": "Nothing has been saved yet"})
                return
            sync = device.request_sync(config)
            self._json(200, {"ok": True, "action": action, **sync, "device": device.status()})
            return

        if action == "open-logs":
            if os.name != "nt":
                self._json(400, {"ok": False, "error": "Only supported on Windows"})
                return
            try:
                LOCAL_DATA_DIR.mkdir(parents=True, exist_ok=True)
                os.startfile(str(LOCAL_DATA_DIR))
            except OSError as error:
                self._json(500, {"ok": False, "error": str(error)})
                return
            self._json(
                200,
                {"ok": True, "action": action, "message": f"Opened {LOCAL_DATA_DIR}"},
            )
            return

        try:
            control = control_module()
        except Exception as error:
            self._json(500, {"ok": False, "error": f"Control helper unavailable: {error}"})
            return

        desktop_actions = {
            "autostart-on": lambda: {"path": control.set_autostart(True)},
            "autostart-off": lambda: {"path": control.set_autostart(False)},
            "create-shortcuts": lambda: {"shortcuts": control.create_app_shortcuts()},
            "remove-shortcuts": lambda: {"removed": control.remove_app_shortcuts()},
            "register-protocol": lambda: {"command": control.register_protocol()},
        }
        if action in desktop_actions:
            try:
                result = desktop_actions[action]()
            except Exception as error:
                LOGGER.warning("Control action %s failed: %s", action, error)
                self._json(400, {"ok": False, "error": str(error)})
                return
            self._json(
                200,
                {
                    "ok": True,
                    "action": action,
                    **result,
                    "integration": control.integration_state(),
                },
            )
            return

        try:
            task = control.start_task(action, debug=debug_enabled())
        except ValueError as error:
            self._json(400, {"ok": False, "error": str(error)})
            return
        except Exception as error:
            LOGGER.exception("Could not start task %s", action)
            self._json(500, {"ok": False, "error": str(error)})
            return
        LOGGER.info("Started %s task %s", action, task.get("id"))
        self._json(200, {"ok": True, "action": action, "task": task})

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/control":
            if not self._api_allowed():
                return
            try:
                payload = self._read_json_body()
            except ValueError as error:
                self._json(400, {"ok": False, "error": str(error)})
                return
            try:
                self._handle_control(payload)
            except Exception as error:
                LOGGER.exception("Control request failed")
                self._json(500, {"ok": False, "error": str(error)})
            return
        if path == "/api/stop":
            if not self._host_allowed() or not secrets.compare_digest(
                self.headers.get("X-ADeck-Token", ""), self.server.control_token
            ):
                self._json(403, {"ok": False, "error": "Invalid control token"})
                return
            self._json(200, {"ok": True, "stopping": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        if path not in {"/api/config", "/flash"}:
            self._json(404, {"ok": False, "error": "Not found"})
            return
        if not self._api_allowed():
            return
        try:
            raw = self._read_config()
            with self.server.save_lock:
                saved = self.server.store.save(raw)
                sync = self.server.device.request_sync(saved)
            self._json(
                200,
                {
                    "ok": True,
                    "saved": True,
                    **sync,
                    **self.server.device.status(),
                },
            )
        except ValueError as error:
            self._json(400, {"ok": False, "error": str(error)})
        except Exception as error:
            LOGGER.exception("Config save failed")
            self._json(500, {"ok": False, "error": str(error)})


class InstanceLock:
    def __init__(self, path=LOCK_PATH):
        self.path = Path(path)
        self.handle = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+b")
        self.handle.seek(0)
        self.handle.write(b"\0")
        self.handle.flush()
        try:
            if os.name == "nt":
                import msvcrt

                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self.handle.close()
            self.handle = None
            raise RuntimeError("ADeck service is already running") from error

    def release(self):
        if self.handle is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        finally:
            self.handle.close()
            self.handle = None


def _control_token():
    LOCAL_DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        token = TOKEN_PATH.read_text(encoding="ascii").strip()
        if re.fullmatch(r"[A-Za-z0-9_-]{32,128}", token):
            return token
    except OSError:
        pass
    token = secrets.token_urlsafe(32)
    TOKEN_PATH.write_text(token, encoding="ascii")
    try:
        os.chmod(TOKEN_PATH, 0o600)
    except OSError:
        pass
    return token


def stop_runtime():
    setup_logging()
    host, port = "127.0.0.1", 8765
    try:
        runtime = json.loads(RUNTIME_PATH.read_text(encoding="utf-8"))
        if runtime.get("host") in LOCAL_HOSTS:
            host = runtime["host"]
        port = int(runtime.get("port", port))
    except (OSError, ValueError, TypeError):
        pass
    try:
        token = TOKEN_PATH.read_text(encoding="ascii").strip()
    except OSError:
        print("ADeck service is not running")
        return 0
    request = urllib.request.Request(
        f"http://{'[' + host + ']' if ':' in host else host}:{port}/api/stop",
        method="POST",
        headers={"X-ADeck-Token": token},
    )
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            if response.status != 200:
                raise RuntimeError(f"Stop request returned HTTP {response.status}")
        print("ADeck service stopped")
        return 0
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"ADeck refused the stop request: HTTP {error.code}") from error
    except (urllib.error.URLError, TimeoutError):
        print("ADeck service is not running")
        return 0


def serve(args):
    if args.host not in LOCAL_HOSTS:
        raise ValueError("ADeck may only listen on localhost")
    if not 1 <= args.port <= 65535:
        raise ValueError("Port must be between 1 and 65535")
    if args.debug:
        os.environ["ADECK_DEBUG"] = "1"
    setup_logging(debug=args.debug or debug_enabled())
    lock = InstanceLock()
    lock.acquire()
    store = ConfigStore()
    device = ADeckDevice(store, args.device_port)
    server = None
    old_handlers = {}
    try:
        token = _control_token()
        server = BridgeServer((args.host, args.port), BridgeHandler, store, device, token)
        _atomic_json(
            RUNTIME_PATH,
            {"pid": os.getpid(), "host": args.host, "port": args.port, "version": APP_VERSION},
        )
        device.start()
        display_host = f"[{args.host}]" if ":" in args.host else args.host
        url = f"http://{display_host}:{args.port}/"
        LOGGER.info("Runtime started at %s", url)
        print("ADeck is running at", url)

        def request_shutdown(_signum=None, _frame=None):
            if server is not None:
                threading.Thread(target=server.shutdown, daemon=True).start()

        if threading.current_thread() is threading.main_thread():
            for signum in (signal.SIGINT, signal.SIGTERM):
                old_handlers[signum] = signal.getsignal(signum)
                signal.signal(signum, request_shutdown)
        if args.open:
            timer = threading.Timer(0.5, lambda: webbrowser.open(url))
            timer.daemon = True
            timer.start()
        server.serve_forever(poll_interval=0.2)
    finally:
        LOGGER.info("Runtime stopping")
        if server is not None:
            server.server_close()
        device.stop()
        try:
            runtime = json.loads(RUNTIME_PATH.read_text(encoding="utf-8"))
            if runtime.get("pid") == os.getpid():
                RUNTIME_PATH.unlink(missing_ok=True)
        except (OSError, ValueError, TypeError):
            pass
        for signum, handler in old_handlers.items():
            signal.signal(signum, handler)
        lock.release()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="ADeck local service")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--device-port")
    parser.add_argument("--open", action="store_true")
    parser.add_argument("--stop", action="store_true")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="verbose serial/HTTP logging (or set ADECK_DEBUG=1)",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        return stop_runtime() if args.stop else (serve(args) or 0)
    except Exception as error:
        setup_logging()
        LOGGER.error("%s", error)
        print("Error:", error)
        return 1


if __name__ == "__main__":
    sys.exit(main())
