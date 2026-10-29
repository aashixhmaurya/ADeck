import ctypes
import ctypes.wintypes
import hashlib
import json
import logging
import mimetypes
import os
import re
import shutil
import struct
import subprocess
import sys
import threading
import time
import zlib
from logging.handlers import RotatingFileHandler
from pathlib import Path

APP_VERSION = "2.1.0"
SERVICE_NAME = "ADeck"
PROTOCOL_VERSION = "2"
PY_DIR = Path(__file__).resolve().parent
BASE_DIR = PY_DIR.parent
WEB_DIR = BASE_DIR / "web app"
DATA_DIR = Path(os.environ.get("APPDATA", Path.home())) / "ADeck"
LOCAL_DATA_DIR = (
    Path(os.environ["LOCALAPPDATA"]) / "ADeck"
    if os.environ.get("LOCALAPPDATA")
    else DATA_DIR
)
CONFIG_PATH = DATA_DIR / "config.json"

IDENTITY_PATH = LOCAL_DATA_DIR / "board.json"
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

DEFAULT_THEME_ID = "adeck-classic"
DEFAULT_ROTATION = 1
VALID_ROTATIONS = frozenset({0, 1, 2, 3})

_ROTATION_DEGREES = {1: 0, 0: 90, 2: 180, 3: 270}

_THEMES = [
    {
        "id": "adeck-classic",
        "name": "Space",
        "short": "Space",
        "description": "Dark display with slow drifting stars behind colourful app keys. Calm deep-space background.",
        "bgEffect": "stars",
        "web": {
            "light": {
                "--bg": "#b8c7c8",
                "--bg-2": "#d8e0df",
                "--bg-3": "#9dadae",
                "--ink": "#080d0e",
                "--ink-2": "#1b2324",
                "--muted": "#556366",
                "--line": "#080d0e",
                "--accent": "#b3121f",
                "--sage": "#2f5c5e",
                "--danger": "#8f0f1a",
                "--ok": "#2f5c5e",
                "--slot-empty": "#1b2324",
                "--screen": "#080d0e",
                "--bezel": "#111718",
                "--bezel-edge": "#1b2324",
                "--panel-focus": "#e7eeee",
                "--on-dark": "#e7eeee",
                "--code-bg": "#080d0e",
                "--code-fg": "#d8e0df",
                "--toast-shadow": "#080d0e",
                "--active-bg": "#080d0e",
                "--active-fg": "#e7eeee",
                "--hover-bg": "#d8e0df",
                "--btn-solid-bg": "#080d0e",
                "--btn-solid-fg": "#e7eeee",
            },
            "dark": {
                "--bg": "#080d0e",
                "--bg-2": "#111718",
                "--bg-3": "#1b2324",
                "--ink": "#e7eeee",
                "--ink-2": "#b6c4c5",
                "--muted": "#718082",
                "--line": "#2b3637",
                "--accent": "#e32636",
                "--sage": "#66a3a8",
                "--danger": "#f08a8a",
                "--ok": "#66a3a8",
                "--slot-empty": "#1b2324",
                "--screen": "#05090a",
                "--bezel": "#111718",
                "--bezel-edge": "#2b3637",
                "--panel-focus": "#1b2324",
                "--on-dark": "#e7eeee",
                "--code-bg": "#05090a",
                "--code-fg": "#cfe0e0",
                "--toast-shadow": "#000000",
                "--active-bg": "#1b2324",
                "--active-fg": "#e7eeee",
                "--hover-bg": "#151d1e",
                "--btn-solid-bg": "#1b2324",
                "--btn-solid-fg": "#e7eeee",
            },
        },
        "tft": {
            "background": "#080d0e",
            "text": "#e7eeee",
            "textMuted": "#445355",
            "accent": "#e32636",
            "accentSecondary": "#3d4a4c",
            "selected": "#ffffff",
            "pressed": "#2a1216",
        },
    },
    {
        "id": "cyber",
        "name": "Cyber",
        "short": "Cyber",
        "description": "Deep space and electric cyan. Cool, high-contrast, built for a dark room.",
        "web": {
            "light": {
                "--bg": "#edf4f9",
                "--bg-2": "#ddeaf3",
                "--bg-3": "#c4d8e7",
                "--ink": "#04121c",
                "--ink-2": "#0a2030",
                "--muted": "#46647a",
                "--line": "#0b1b28",
                "--accent": "#0e7490",
                "--sage": "#0f766e",
                "--danger": "#b42318",
                "--ok": "#0f766e",
                "--slot-empty": "#c2d2de",
                "--screen": "#04070e",
                "--bezel": "#0c1520",
                "--bezel-edge": "#22384e",
                "--panel-focus": "#ffffff",
                "--on-dark": "#edf4f9",
                "--code-bg": "#04060c",
                "--code-fg": "#a5e8f2",
                "--toast-shadow": "#04121c",
                "--active-bg": "#062b3a",
                "--active-fg": "#eafbff",
                "--hover-bg": "#d2e4ef",
                "--btn-solid-bg": "#0e7490",
                "--btn-solid-fg": "#ffffff",
            },
            "dark": {
                "--bg": "#070a12",
                "--bg-2": "#0d1220",
                "--bg-3": "#141b2c",
                "--ink": "#e6f6ff",
                "--ink-2": "#b9d4e4",
                "--muted": "#6c8aa0",
                "--line": "#1e2a3d",
                "--accent": "#22d3ee",
                "--sage": "#34d399",
                "--danger": "#ff5c7a",
                "--ok": "#34d399",
                "--slot-empty": "#1a2438",
                "--screen": "#04060c",
                "--bezel": "#0a0f1a",
                "--bezel-edge": "#21304a",
                "--panel-focus": "#131c2e",
                "--on-dark": "#e6f6ff",
                "--code-bg": "#04060c",
                "--code-fg": "#9fe8f5",
                "--toast-shadow": "#000208",
                "--active-bg": "#10243a",
                "--active-fg": "#eafbff",
                "--hover-bg": "#111a2a",
                "--btn-solid-bg": "#22d3ee",
                "--btn-solid-fg": "#04121a",
            },
        },
        "tft": {
            "background": "#05070e",
            "text": "#d7f7ff",
            "textMuted": "#2a3a4a",
            "accent": "#22d3ee",
            "accentSecondary": "#7c3aed",
            "selected": "#67e8f9",
            "pressed": "#101c33",
        },
    },
    {
        "id": "terminal",
        "name": "Terminal",
        "short": "Terminal",
        "description": "Phosphor console. Deep green on near-black, the way a terminal should read.",
        "web": {
            "light": {
                "--bg": "#edf5ee",
                "--bg-2": "#ddebe0",
                "--bg-3": "#c2d9c8",
                "--ink": "#06170d",
                "--ink-2": "#0b2a17",
                "--muted": "#3f6b4e",
                "--line": "#0b2a17",
                "--accent": "#10703a",
                "--sage": "#10703a",
                "--danger": "#a32318",
                "--ok": "#10703a",
                "--slot-empty": "#c2d6c8",
                "--screen": "#020604",
                "--bezel": "#08130d",
                "--bezel-edge": "#1e4630",
                "--panel-focus": "#ffffff",
                "--on-dark": "#edf5ee",
                "--code-bg": "#020604",
                "--code-fg": "#8fe8a8",
                "--toast-shadow": "#06170d",
                "--active-bg": "#0b3a21",
                "--active-fg": "#e4fbea",
                "--hover-bg": "#d2e6d7",
                "--btn-solid-bg": "#10703a",
                "--btn-solid-fg": "#ffffff",
            },
            "dark": {
                "--bg": "#040a07",
                "--bg-2": "#0a1410",
                "--bg-3": "#122119",
                "--ink": "#b8f0c8",
                "--ink-2": "#8fd3a4",
                "--muted": "#4e7a5e",
                "--line": "#1b3a28",
                "--accent": "#34d058",
                "--sage": "#6ee787",
                "--danger": "#e5534b",
                "--ok": "#6ee787",
                "--slot-empty": "#14261b",
                "--screen": "#020604",
                "--bezel": "#06100b",
                "--bezel-edge": "#1e4630",
                "--panel-focus": "#102016",
                "--on-dark": "#b8f0c8",
                "--code-bg": "#020604",
                "--code-fg": "#7be495",
                "--toast-shadow": "#000000",
                "--active-bg": "#0f2a1b",
                "--active-fg": "#c8f7d6",
                "--hover-bg": "#0c1e14",
                "--btn-solid-bg": "#34d058",
                "--btn-solid-fg": "#04140a",
            },
        },
        "tft": {
            "background": "#020604",
            "text": "#b6f2c4",
            "textMuted": "#17452b",
            "accent": "#34d058",
            "accentSecondary": "#0e7a3c",
            "selected": "#7be495",
            "pressed": "#06251a",
        },
    },
    {
        "id": "retro",
        "name": "Retro Arcade",
        "short": "Retro",
        "description": "Cabinet panel. Warm amber and orange, cyan trim, chunky and nostalgic.",
        "web": {
            "light": {
                "--bg": "#f6eee2",
                "--bg-2": "#ebdfcc",
                "--bg-3": "#d8c6ab",
                "--ink": "#1e120a",
                "--ink-2": "#35200f",
                "--muted": "#6e4b2a",
                "--line": "#1e120a",
                "--accent": "#a8500a",
                "--sage": "#0f7280",
                "--danger": "#a32318",
                "--ok": "#4f7a22",
                "--slot-empty": "#d6c4a8",
                "--screen": "#100a08",
                "--bezel": "#1c130d",
                "--bezel-edge": "#4a3221",
                "--panel-focus": "#ffffff",
                "--on-dark": "#f6eee2",
                "--code-bg": "#14100c",
                "--code-fg": "#ffc978",
                "--toast-shadow": "#1e120a",
                "--active-bg": "#6b3a12",
                "--active-fg": "#fff1dc",
                "--hover-bg": "#e2d2ba",
                "--btn-solid-bg": "#a8500a",
                "--btn-solid-fg": "#ffffff",
            },
            "dark": {
                "--bg": "#17100c",
                "--bg-2": "#20160f",
                "--bg-3": "#2c1f16",
                "--ink": "#ffe6c2",
                "--ink-2": "#e8c79a",
                "--muted": "#a97f55",
                "--line": "#3e2a1c",
                "--accent": "#ff9e2c",
                "--sage": "#23b5c9",
                "--danger": "#e5533b",
                "--ok": "#7fbf4d",
                "--slot-empty": "#33241a",
                "--screen": "#100a08",
                "--bezel": "#1c130d",
                "--bezel-edge": "#4a3221",
                "--panel-focus": "#2a1c13",
                "--on-dark": "#ffe6c2",
                "--code-bg": "#100a08",
                "--code-fg": "#ffc978",
                "--toast-shadow": "#0a0604",
                "--active-bg": "#3a2415",
                "--active-fg": "#fff1dc",
                "--hover-bg": "#2a1c13",
                "--btn-solid-bg": "#ff9e2c",
                "--btn-solid-fg": "#1a0f07",
            },
        },
        "tft": {
            "background": "#100a08",
            "text": "#ffe9c7",
            "textMuted": "#5a3d24",
            "accent": "#ff9e2c",
            "accentSecondary": "#23b5c9",
            "selected": "#ffc978",
            "pressed": "#2a1710",
        },
    },
]

TFT_THEME_KEYS = (
    "background",
    "text",
    "textMuted",
    "accent",
    "accentSecondary",
    "selected",
    "pressed",
)

THEMES = {theme["id"]: theme for theme in _THEMES}

def theme_for(theme_id):

    key = str(theme_id or "").strip().lower()
    return THEMES.get(key) or THEMES[DEFAULT_THEME_ID]

def theme_bg_effect(theme_id):

    effect = str(theme_for(theme_id).get("bgEffect") or "").strip().lower()
    return effect if effect in {"stars"} else ""

def theme_payload():
    return {
        "ok": True,
        "default": DEFAULT_THEME_ID,
        "order": [theme["id"] for theme in _THEMES],
        "tftKeys": list(TFT_THEME_KEYS),
        "themes": [
            {
                "id": theme["id"],
                "name": theme["name"],
                "short": theme["short"],
                "description": theme["description"],
                "bgEffect": theme.get("bgEffect") or "",
                "web": theme["web"],
                "tft": theme["tft"],
            }
            for theme in _THEMES
        ],
    }

def control_module():

    if str(PY_DIR) not in sys.path:
        sys.path.insert(0, str(PY_DIR))
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

        raw_theme = raw_profile.get("theme")
        theme = theme_for(raw_theme if isinstance(raw_theme, str) else "")["id"]

        raw_background = raw_profile.get("background")
        if raw_background is None or raw_background == "":
            background = theme_for(theme)["tft"]["background"].lower()
        elif isinstance(raw_background, str) and COLOR_PATTERN.fullmatch(raw_background):
            background = raw_background.lower()
        else:
            raise ValueError(f'Profile "{name}" background must be #RRGGBB')

        raw_rotation = raw_profile.get("rotation")
        if raw_rotation is None or raw_rotation == "":
            rotation = DEFAULT_ROTATION
        else:
            try:
                rotation = int(raw_rotation)
            except (TypeError, ValueError) as error:
                raise ValueError(
                    f'Profile "{name}" rotation must be 0, 1, 2, or 3'
                ) from error
            if rotation not in VALID_ROTATIONS:
                raise ValueError(
                    f'Profile "{name}" rotation must be 0, 1, 2, or 3'
                )

        profile = {
            "name": name,
            "theme": theme,
            "background": background,
            "rotation": rotation,
            "buttons": [slots[index] for index in range(SLOT_COUNT)],
        }
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

def active_theme_id(config):

    if not config:
        return DEFAULT_THEME_ID
    try:
        active = config["active_profile"]
        profile = next(item for item in config["profiles"] if item["name"] == active)
    except (KeyError, TypeError, StopIteration):
        return DEFAULT_THEME_ID
    return theme_for(profile.get("theme"))["id"]

def active_background(config):

    if not config:
        return theme_background(DEFAULT_THEME_ID)
    try:
        active = config["active_profile"]
        profile = next(item for item in config["profiles"] if item["name"] == active)
    except (KeyError, TypeError, StopIteration):
        return theme_background(DEFAULT_THEME_ID)
    background = profile.get("background")
    if isinstance(background, str) and COLOR_PATTERN.fullmatch(background):
        return background.lower()
    return theme_background(theme_for(profile.get("theme"))["id"])

def normalize_rotation(value):

    if value is None or value == "":
        return DEFAULT_ROTATION
    try:
        rotation = int(value)
    except (TypeError, ValueError):
        return DEFAULT_ROTATION
    return rotation if rotation in VALID_ROTATIONS else DEFAULT_ROTATION

def active_rotation(config):

    if not config:
        return DEFAULT_ROTATION
    try:
        active = config["active_profile"]
        profile = next(item for item in config["profiles"] if item["name"] == active)
    except (KeyError, TypeError, StopIteration):
        return DEFAULT_ROTATION
    return normalize_rotation(profile.get("rotation"))

def rotation_degrees(rotation):

    return _ROTATION_DEGREES.get(normalize_rotation(rotation), 0)

def next_rotation(rotation):

    order = (1, 0, 2, 3)
    current = normalize_rotation(rotation)
    try:
        index = order.index(current)
    except ValueError:
        index = 0
    return order[(index + 1) % len(order)]

def rotation_frame(rotation, txid):

    value = normalize_rotation(rotation)
    return f"CFG_ROTATE\t{txid}\t{value}\n".encode("ascii")

SLEEP_TIMEOUTS = frozenset({0, 30, 60, 300})
SLEEP_W = 128
SLEEP_H = 96
SLEEP_CHUNK = 16
SLEEP_IMAGE_HEX_LEN = SLEEP_W * SLEEP_H * 4

def normalize_sleep_timeout(value):
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return 60
    return seconds if seconds in SLEEP_TIMEOUTS else 60

def normalize_sleep_mode(value):
    key = str(value or "").strip().lower()
    return "image" if key == "image" else "black"

def sleep_image_hex(value):
    text = str(value or "").strip().upper()
    if len(text) != SLEEP_IMAGE_HEX_LEN:
        return ""
    if any(ch not in "0123456789ABCDEF" for ch in text):
        return ""
    return text

def active_sleep_timeout(config):
    if not config:
        return 60
    settings = config.get("settings") or {}
    if not isinstance(settings, dict):
        return 60
    return normalize_sleep_timeout(settings.get("sleepTimeout"))

def active_sleep_mode(config):
    if not config:
        return "black"
    settings = config.get("settings") or {}
    if not isinstance(settings, dict):
        return "black"
    mode = normalize_sleep_mode(settings.get("sleepMode"))
    if mode == "image" and not sleep_image_hex(settings.get("sleepImage")):
        return "black"
    return mode

def sleep_frame(seconds, mode, txid):
    timeout = normalize_sleep_timeout(seconds)
    flag = 1 if normalize_sleep_mode(mode) == "image" else 0
    return f"CFG_SLEEP\t{txid}\t{timeout}\t{flag}\n".encode("ascii")

def sleep_image_frame(hex_pixels, txid):
    payload = sleep_image_hex(hex_pixels)
    if not payload:
        return b""
    lines = [f"CFG_SLEEPIMG_BEGIN\t{txid}\t{SLEEP_W}\t{SLEEP_H}"]
    row_stride = SLEEP_W * 4
    for row in range(SLEEP_H):
        start = row * row_stride
        row_hex = payload[start : start + row_stride]
        offset = 0
        while offset < SLEEP_W:
            count = SLEEP_W - offset if SLEEP_W - offset < SLEEP_CHUNK else SLEEP_CHUNK
            chunk = row_hex[offset * 4 : (offset + count) * 4]
            lines.append(f"CFG_SLEEPIMG_ROW\t{txid}\t{row}\t{offset}\t{chunk}")
            offset += count
    lines.append(f"CFG_SLEEPIMG_END\t{txid}")
    return ("\n".join(lines) + "\n").encode("ascii")

def _crc16_next(crc, value):
    crc ^= value << 8
    for _ in range(8):
        crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc

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
            crc = _crc16_next(crc, value)
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

def theme_values(theme_id, background=None):

    tft = theme_for(theme_id)["tft"]
    values = []
    for key in TFT_THEME_KEYS:
        if (
            key == "background"
            and isinstance(background, str)
            and COLOR_PATTERN.fullmatch(background)
        ):
            values.append(_hex_rgb_tuple(background))
        else:
            values.append(_hex_rgb_tuple(tft[key]))
    return values

def theme_background(theme_id, background=None):

    if isinstance(background, str) and COLOR_PATTERN.fullmatch(background):
        return background.lower()
    return theme_for(theme_id)["tft"]["background"]

def theme_crc(values):
    crc = 0xFFFF
    for index, (red, green, blue) in enumerate(values):
        for value in (index, red, green, blue):
            crc = _crc16_next(crc, value)
    return crc

def theme_frame(theme_id, txid, background=None):

    values = theme_values(theme_id, background)
    effect = theme_bg_effect(theme_id)
    if effect:
        lines = [f"CFG_THEME_BEGIN\t{txid}\t{len(values)}\t{effect}"]
    else:
        lines = [f"CFG_THEME_BEGIN\t{txid}\t{len(values)}"]
    for index, (red, green, blue) in enumerate(values):
        lines.append(
            f"CFG_THEME_VALUE\t{txid}\t{index}\t#{red:02X}{green:02X}{blue:02X}"
        )
    lines.append(f"CFG_THEME_END\t{txid}\t{theme_crc(values):04X}")
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
_TFT_ICON_SIZE = 32

_ICON_ROWS_PER_CHUNK = 8
_ICON_CHUNK_DELAY = 0.004
_ICON_ATTEMPTS = 3
_ICON_ACK_TIMEOUT = 1.5

_THEME_ATTEMPTS = 2
_THEME_ACK_TIMEOUT = 1.5
_ROTATE_ATTEMPTS = 2
_ROTATE_ACK_TIMEOUT = 1.5
_SLEEP_ATTEMPTS = 2
_SLEEP_ACK_TIMEOUT = 1.5
_SLEEPIMG_ACK_TIMEOUT = 8.0
_SLEEPIMG_ROW_DELAY = 0.008
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

_PLACEHOLDER_CACHE = {}

def _placeholder_icon_png(size=_ICON_SIZE):

    cached = _PLACEHOLDER_CACHE.get(size)
    if cached is not None:
        return cached
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
    png = _png_from_rgba(size, size, bytes(row))
    _PLACEHOLDER_CACHE[size] = png
    return png

def _hicon_to_rgba(hicon, size=_ICON_SIZE):
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
    rgba = b""
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
        rgba = bytes(pixels)
        gdi32.DeleteObject(hbm)
    if memdc:
        gdi32.DeleteDC(memdc)
    user32.ReleaseDC(None, hdc)
    return rgba

def _hicon_to_png(hicon, size=_ICON_SIZE):
    rgba = _hicon_to_rgba(hicon, size)
    return _png_from_rgba(size, size, rgba) if rgba else b""

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

def _hex_rgb_tuple(value):
    text = str(value or "").strip()
    if len(text) == 7 and text[0] == "#":
        try:
            return (int(text[1:3], 16), int(text[3:5], 16), int(text[5:7], 16))
        except ValueError:
            pass
    return (0, 0, 0)

def _extract_icon_rgba(source, size=_TFT_ICON_SIZE):
    if not source:
        return b""
    with _ICON_EXTRACT_LOCK:
        hicon = None
        try:
            hicon = _hicon_from_path(source)
            return _hicon_to_rgba(hicon, size) if hicon else b""
        except Exception as error:
            LOGGER.debug("TFT icon extract failed for %s: %s", source, error)
            return b""
        finally:
            if hicon:
                try:
                    ctypes.windll.user32.DestroyIcon(hicon)
                except Exception:
                    pass

def _rgba_to_rgb565(rgba, width, height, background=(0, 0, 0)):
    expected = width * height * 4
    if not rgba or len(rgba) < expected:
        return b""
    br, bg, bb = background
    out = bytearray(width * height * 2)
    for pixel in range(width * height):
        offset = pixel * 4
        alpha = rgba[offset + 3] / 255.0
        red = int(rgba[offset] * alpha + br * (1.0 - alpha))
        green = int(rgba[offset + 1] * alpha + bg * (1.0 - alpha))
        blue = int(rgba[offset + 2] * alpha + bb * (1.0 - alpha))
        packed = ((red & 0xF8) << 8) | ((green & 0xFC) << 3) | (blue >> 3)
        out[pixel * 2] = (packed >> 8) & 0xFF
        out[pixel * 2 + 1] = packed & 0xFF
    return bytes(out)

def app_icon_rgb565(command, background="#000000"):
    if str(command or "").strip() == "" or os.name != "nt":
        return b""
    source = _icon_source_for_command(command)
    if not source:
        return b""
    rgba = _extract_icon_rgba(source, _TFT_ICON_SIZE)
    if len(rgba) != _TFT_ICON_SIZE * _TFT_ICON_SIZE * 4:
        return b""
    return _rgba_to_rgb565(
        rgba, _TFT_ICON_SIZE, _TFT_ICON_SIZE, _hex_rgb_tuple(background)
    )

def _dominant_color_from_rgba(rgba, width, height):

    expected = width * height * 4
    if not rgba or len(rgba) < expected:
        return "#c5c5c3"
    counts = {}
    for pixel in range(width * height):
        offset = pixel * 4
        alpha = rgba[offset + 3]
        if alpha < 64:
            continue
        red, green, blue = rgba[offset], rgba[offset + 1], rgba[offset + 2]
        if red < 24 and green < 24 and blue < 24:
            continue
        if red > 235 and green > 235 and blue > 235:
            continue

        key = (red & 0xF8, green & 0xF8, blue & 0xF8)
        counts[key] = counts.get(key, 0) + 1
    if not counts:
        return "#c5c5c3"
    red, green, blue = max(counts.items(), key=lambda item: item[1])[0]
    return f"#{red:02x}{green:02x}{blue:02x}"

def dominant_icon_color(command):

    fallback = "#c5c5c3"
    if str(command or "").strip() == "" or os.name != "nt":
        return fallback
    source = _icon_source_for_command(command)
    if not source:
        return fallback
    rgba = _extract_icon_rgba(source, _TFT_ICON_SIZE)
    if len(rgba) != _TFT_ICON_SIZE * _TFT_ICON_SIZE * 4:
        return fallback
    return _dominant_color_from_rgba(rgba, _TFT_ICON_SIZE, _TFT_ICON_SIZE)

def slot_icon_frame(index, button, txid, background="#000000"):
    if not isinstance(button, dict):
        return b""
    if str(button.get("kind") or "").strip().lower() != "app":
        return b""
    command = str(button.get("command") or "").strip()
    if not command:
        return b""

    pixels = app_icon_rgb565(command, background)
    row_bytes = _TFT_ICON_SIZE * 2
    if len(pixels) != _TFT_ICON_SIZE * row_bytes:
        return b""
    lines = [f"CFG_ICON_BEGIN\t{txid}\t{index}\t{_TFT_ICON_SIZE}"]
    for row in range(_TFT_ICON_SIZE):
        chunk = pixels[row * row_bytes : (row + 1) * row_bytes]
        lines.append(
            f"CFG_ICON_ROW\t{txid}\t{index}\t{row}\t{chunk.hex().upper()}"
        )
    lines.append(f"CFG_ICON_END\t{txid}\t{index}")
    return ("\n".join(lines) + "\n").encode("ascii")

def app_icon_frames(buttons, txid, background="#000000"):
    frames = []
    for index, button in enumerate(buttons or []):
        frame = slot_icon_frame(index, button, txid, background)
        if frame:
            frames.append((index, frame))
    return frames
