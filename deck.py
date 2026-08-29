"""Local HTTP/config/serial runtime for ADeck."""

import argparse
import json
import logging
import mimetypes
import os
import queue
import re
import secrets
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import urlparse

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
            slots[index] = {
                "key": index + 1,
                "label": label,
                "command": command,
                "color": color.lower(),
            }

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
        try:
            plain_path = os.path.expandvars(command.strip().strip('"'))
            if os.name == "nt" and Path(plain_path).exists():
                os.startfile(plain_path)
            elif os.name == "nt" and re.fullmatch(r"https?://\S+", command, re.IGNORECASE):
                os.startfile(command)
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


class BridgeHandler(BaseHTTPRequestHandler):
    static_files = {
        "/": "index.html",
        "/index.html": "index.html",
        "/script.js": "script.js",
        "/style.css": "style.css",
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

    def _api_allowed(self):
        if self._origin_allowed():
            return True
        self._json(403, {"ok": False, "error": "Local same-origin request required"})
        return False

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

    def do_POST(self):
        path = urlparse(self.path).path
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
