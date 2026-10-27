import argparse
import json
import mimetypes
import os
import queue
import re
import secrets
import shutil
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
from pathlib import Path
from urllib.parse import parse_qs, urlparse

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    serial = None
    list_ports = None

from deck_core import (
    APP_VERSION,
    ARDUINO_VIDS,
    BAUD,
    BASE_DIR,
    BUNDLED_CLI,
    COMMAND_MAX,
    CONFIG_PATH,
    DATA_DIR,
    IDENTITY_PATH,
    LOCAL_DATA_DIR,
    LOCAL_HOSTS,
    LOCK_PATH,
    LOG_SOURCES,
    LOGGER,
    MAX_CONFIG_BYTES,
    MAX_CONTROL_BYTES,
    PROTOCOL_VERSION,
    RUNTIME_PATH,
    SERIAL_PORT_PATTERN,
    SERVICE_NAME,
    SLOT_COUNT,
    TFT_THEME_KEYS,
    THEMES,
    TOKEN_PATH,
    VENV_PYTHON,
    WEB_DIR,
    active_background,
    active_buttons,
    active_rotation,
    active_theme_id,
    app_icon_frames,
    app_icon_png,
    app_icon_rgb565,
    config_frame,
    control_module,
    crc16_ccitt_false,
    debug_enabled,
    dominant_icon_color,
    list_installed_apps,
    next_rotation,
    normalize_config,
    normalize_rotation,
    rotation_degrees,
    rotation_frame,
    setup_logging,
    slot_icon_frame,
    theme_background,
    theme_bg_effect,
    theme_crc,
    theme_for,
    theme_frame,
    theme_payload,
    theme_values,
    validate_config,
)
from deck_core import (
    _FOREGROUND_LATE_WINDOW_WAIT,
    _FOREGROUND_NEW_WINDOW_WAIT,
    _FOREGROUND_POLL,
    _ICON_ACK_TIMEOUT,
    _ICON_ATTEMPTS,
    _ICON_CHUNK_DELAY,
    _ICON_ROWS_PER_CHUNK,
    _ROTATE_ACK_TIMEOUT,
    _ROTATE_ATTEMPTS,
    _THEME_ACK_TIMEOUT,
    _THEME_ATTEMPTS,
    _apply_app_relaunch,
    _atomic_json,
    _bring_app_windows_forward,
    _clone,
    _dominant_color_from_rgba,
    _find_windows_for_app,
    _force_window_foreground,
    _hex_rgb_tuple,
    _launch_win_command,
    _normalize_relaunch_mode,
    _parse_lnk_launch,
    _placeholder_icon_png,
    _schedule_bring_app_forward,
    _shell_execute_win,
    _uses_explorer_host_launch,
    _win_gui_app_identity,
    _window_class_name,
)

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
        self._tft_icons = False
        self._tft_theme = False
        self._tft_rotate = False
        self._theme_id = None
        self._rotation = None
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
            LOCAL_DATA_DIR / "board.json",
            LOCAL_DATA_DIR / "device.json",
            LOCAL_DATA_DIR / "board_identity.json",
            DATA_DIR / "board.json",
            DATA_DIR / "device.json",
            DATA_DIR / "board_identity.json",
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
                "theme": self._theme_id,
                "rotation": self._rotation,
                "last_sync": self._last_sync,
                "last_transaction_id": self._last_txid,
                "error": self._last_error or None,
            }

    def available_ports(self):

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

        if port is not None:
            self.requested_port = port or None
        with self._state_lock:
            connection = self._connection
            self._connection = None
            self._port = None
            self._firmware = None
            self._tft_icons = False
            self._tft_theme = False
            self._tft_rotate = False
            self._theme_id = None
            self._rotation = None
            self._last_sync = None
            self._last_error = "Reconnecting"
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass
        self._resync.set()
        LOGGER.info("Reconnect requested (port=%s)", self.requested_port or "auto")

    def request_sync(self, config, timeout=12):
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
                    self._tft_icons = False
                    self._tft_theme = False
                    self._tft_rotate = False
                    caps_deadline = time.monotonic() + 0.35
                    while time.monotonic() < caps_deadline and not self._stop.is_set():
                        extra = connection.readline().decode(
                            "ascii", errors="ignore"
                        ).strip()
                        if extra == "ADECK_CAPS\tICON":
                            self._tft_icons = True
                        elif extra == "ADECK_CAPS\tTHEME":
                            self._tft_theme = True
                        elif extra == "ADECK_CAPS\tROTATE":
                            self._tft_rotate = True
                        elif extra.startswith("PRESS\t"):
                            self._handle_line(extra)
                        if self._tft_icons and self._tft_theme and self._tft_rotate:
                            break

                    return connection
                if line.startswith("PRESS\t"):
                    self._handle_line(line)
                if line == "ADECK_CAPS\tICON":
                    self._tft_icons = True
                if line == "ADECK_CAPS\tTHEME":
                    self._tft_theme = True
                if line == "ADECK_CAPS\tROTATE":
                    self._tft_rotate = True
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
            self._tft_icons = False
            self._tft_theme = False
            self._tft_rotate = False
            self._theme_id = None
            self._rotation = None
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
        elif line == "ADECK_CAPS\tICON":
            with self._state_lock:
                self._tft_icons = True
        elif line == "ADECK_CAPS\tTHEME":
            with self._state_lock:
                self._tft_theme = True
        elif line == "ADECK_CAPS\tROTATE":
            with self._state_lock:
                self._tft_rotate = True
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
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not self._stop.is_set():
            line = connection.readline().decode("ascii", errors="ignore").strip()
            if line == f"CFG_OK\t{txid}":
                with self._state_lock:
                    self._last_sync = True
                    self._last_txid = txid
                    self._last_error = ""
                LOGGER.info("Synchronized transaction %s", txid)

                wanted = active_theme_id(config)
                background = active_background(config)
                in_force = self._push_theme(
                    connection, wanted, txid, background=background
                )
                self._push_rotation(connection, active_rotation(config), txid)

                blend = (
                    theme_background(in_force, background)
                    if in_force
                    else "#000000"
                )
                self._push_app_icons(
                    connection,
                    active_buttons(config),
                    txid,
                    blend,
                )
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

    def _push_theme(self, connection, theme_id, txid, background=None):

        with self._state_lock:
            capable = self._tft_theme
        if connection is None or not capable:
            return None
        expected = f"CFG_THEME_OK\t{txid}"
        rejected = f"CFG_THEME_ERR\t{txid}\t"
        frame = theme_frame(theme_id, txid, background=background)
        for attempt in range(1, _THEME_ATTEMPTS + 1):
            if self._stop.is_set():
                return self._theme_id
            try:
                connection.write(frame)
                connection.flush()
                deadline = time.monotonic() + _THEME_ACK_TIMEOUT
                while time.monotonic() < deadline and not self._stop.is_set():
                    reply = connection.readline().decode("ascii", errors="ignore").strip()
                    if reply == expected:
                        with self._state_lock:
                            self._theme_id = theme_id
                        LOGGER.info("Applied theme %s", theme_id)
                        return theme_id
                    if reply.startswith(rejected):

                        LOGGER.debug("Theme rejected: %s", reply)
                        break
                    if reply.startswith("PRESS\t") or reply.startswith("ADECK_CAPS\t"):
                        self._handle_line(reply)
            except Exception as error:
                LOGGER.debug("Theme write failed: %s", error)
                return self._theme_id
        LOGGER.warning(
            "Theme %s was not accepted by the board; it keeps its previous colours",
            theme_id,
        )
        return self._theme_id

    def _push_rotation(self, connection, rotation, txid):

        with self._state_lock:
            capable = self._tft_rotate
        if connection is None or not capable:
            return None
        value = normalize_rotation(rotation)
        expected = f"CFG_ROTATE_OK\t{txid}"
        rejected = f"CFG_ROTATE_ERR\t{txid}\t"
        frame = rotation_frame(value, txid)
        for attempt in range(1, _ROTATE_ATTEMPTS + 1):
            if self._stop.is_set():
                return self._rotation
            try:
                connection.write(frame)
                connection.flush()
                deadline = time.monotonic() + _ROTATE_ACK_TIMEOUT
                while time.monotonic() < deadline and not self._stop.is_set():
                    reply = connection.readline().decode("ascii", errors="ignore").strip()
                    if reply == expected:
                        with self._state_lock:
                            self._rotation = value
                        LOGGER.info(
                            "Applied rotation %s (%s°)", value, rotation_degrees(value)
                        )
                        return value
                    if reply.startswith(rejected):
                        LOGGER.debug("Rotation rejected: %s", reply)
                        break
                    if reply.startswith("PRESS\t") or reply.startswith("ADECK_CAPS\t"):
                        self._handle_line(reply)
            except Exception as error:
                LOGGER.debug("Rotation write failed: %s", error)
                return self._rotation
        LOGGER.warning(
            "Rotation %s was not accepted by the board; it keeps its previous orientation",
            value,
        )
        return self._rotation

    def _push_app_icons(self, connection, buttons, txid, background="#000000"):
        with self._state_lock:
            capable = self._tft_icons
        if connection is None or not capable:
            return
        try:
            frames = app_icon_frames(buttons, txid, background)
        except Exception as error:
            LOGGER.debug("TFT app icons skipped: %s", error)
            return
        missing = []
        for index, frame in frames:
            if not self._send_icon(connection, index, frame, txid):
                missing.append(index)
        if missing:
            LOGGER.warning(
                "TFT icon(s) never accepted for key(s) %s in transaction %s",
                ", ".join(str(index + 1) for index in missing),
                txid,
            )
        elif frames:
            LOGGER.info(
                "Pushed %s TFT app icon(s) for transaction %s", len(frames), txid
            )

    def _send_icon(self, connection, index, frame, txid):

        expected = f"CFG_ICON_OK\t{txid}\t{index}"
        rejected = f"CFG_ICON_ERR\t{txid}\t{index}\t"
        lines = [line for line in frame.split(b"\n") if line]
        for attempt in range(1, _ICON_ATTEMPTS + 1):
            if self._stop.is_set():
                return False
            try:
                for start in range(0, len(lines), _ICON_ROWS_PER_CHUNK):
                    chunk = lines[start : start + _ICON_ROWS_PER_CHUNK]
                    connection.write(b"\n".join(chunk) + b"\n")
                    connection.flush()
                    time.sleep(_ICON_CHUNK_DELAY)
                deadline = time.monotonic() + _ICON_ACK_TIMEOUT
                while time.monotonic() < deadline and not self._stop.is_set():
                    reply = connection.readline().decode("ascii", errors="ignore").strip()
                    if reply == expected:
                        if attempt > 1:
                            LOGGER.info(
                                "TFT icon accepted for key %s (attempt %s)",
                                index + 1,
                                attempt,
                            )
                        else:
                            LOGGER.info("TFT icon accepted for key %s", index + 1)
                        return True
                    if reply.startswith(rejected):

                        LOGGER.debug(
                            "TFT icon rejected for key %s: %s", index + 1, reply
                        )
                        break
                    if reply.startswith("PRESS\t") or reply == "ADECK_CAPS\tICON":
                        self._handle_line(reply)
                    elif reply.startswith("CFG_ERR\t"):
                        LOGGER.debug("Device error during icon push: %s", reply)
            except Exception as error:
                LOGGER.debug("TFT app icon write failed: %s", error)
                return False
        return False

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

        self.http_host = self.server_address[0]
        self.http_port = self.server_address[1]

class BridgeHandler(BaseHTTPRequestHandler):
    static_files = {
        "/": "index.html",
        "/index.html": "index.html",
        "/core.js": "core.js",
        "/ui.js": "ui.js",
        "/system.js": "system.js",
        "/theme.css": "theme.css",
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
        if path == "/api/themes":
            if not self._api_allowed():
                return
            self._json(200, theme_payload())
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

        if path == "/api/app-color":
            if not self._api_allowed():
                return
            query = parse_qs(urlparse(self.path).query)
            command = (query.get("command") or [""])[0]
            if len(command) > COMMAND_MAX:
                command = ""
            try:
                color = dominant_icon_color(command)
            except Exception as error:
                LOGGER.debug("App colour request failed: %s", error)
                color = "#c5c5c3"
            self._json(200, {"ok": True, "command": command, "color": color})
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
