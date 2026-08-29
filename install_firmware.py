"""Install and verify ADeck firmware on an Arduino UNO R4 WiFi."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import serial


BASE_DIR = Path(__file__).resolve().parent
SKETCH_DIR = BASE_DIR / "firmware" / "ADeck"
BUILD_DIR = BASE_DIR / ".build" / "ADeck"
TOOLS_DIR = BASE_DIR / ".tools"
BUNDLED_CLI_DIR = TOOLS_DIR / "arduino-cli"
BUNDLED_CLI = BUNDLED_CLI_DIR / "arduino-cli.exe"
CLI_DOWNLOAD_URL = (
    "https://downloads.arduino.cc/arduino-cli/"
    "arduino-cli_latest_Windows_64bit.zip"
)
TARGET_FQBN = "arduino:renesas_uno:unor4wifi"
TARGET_CORE = "arduino:renesas_uno"
REQUIRED_LIBRARIES = ("GFX Library for Arduino", "Adafruit TouchScreen")
HEALTH_URL = "http://127.0.0.1:8765/api/status"
PROTOCOL_REPLY = "ADECK_PONG\t2"
IDENTITY_PATH = (
    Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ADeck" / "board.json"
)


class InstallError(RuntimeError):
    pass


class CliError(InstallError):
    def __init__(self, command: Iterable[object], result: subprocess.CompletedProcess[str]):
        detail = (result.stderr or result.stdout or "").strip()
        if len(detail) > 1200:
            detail = detail[-1200:]
        super().__init__(
            f"Arduino CLI failed ({result.returncode}): "
            f"{' '.join(str(part) for part in command)}"
            + (f"\n{detail}" if detail else "")
        )
        self.result = result


@dataclass(frozen=True)
class PortInfo:
    port: str
    fqbn: str | None
    board_name: str | None
    serial_number: str | None
    vid: str | None
    pid: str | None
    protocol: str | None


def stage(name: str) -> None:
    print(f"\n==> {name}", flush=True)


def verbose_enabled() -> bool:
    value = os.environ.get("ADECK_DEBUG", "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def quiet_enabled() -> bool:
    if verbose_enabled():
        return False
    value = os.environ.get("ADECK_QUIET", "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def run_process(
    command: list[object],
    *,
    timeout: float | None = None,
    check: bool = True,
    quiet: bool | None = None,
) -> subprocess.CompletedProcess[str]:
    display = [str(part) for part in command]
    silenced = quiet_enabled() if quiet is None else quiet
    if not silenced:
        print(">", subprocess.list2cmdline(display), flush=True)
    try:
        result = subprocess.run(
            display,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise InstallError(f"Could not run {display[0]}: {error}") from error
    if check and result.returncode:
        raise CliError(command, result)
    return result


def parse_json_output(result: subprocess.CompletedProcess[str], label: str) -> Any:
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise InstallError(f"{label} did not return valid JSON: {error}") from error


def find_value(value: Any, keys: set[str]) -> str | None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key.casefold() in keys and item not in (None, ""):
                return str(item)
        for item in value.values():
            found = find_value(item, keys)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = find_value(item, keys)
            if found:
                return found
    return None


def validate_cli(path: Path) -> str:
    if not path.is_file():
        raise InstallError(f"Arduino CLI is missing: {path}")
    result = run_process([path, "version", "--format", "json"], timeout=15)
    payload = parse_json_output(result, "arduino-cli version")
    version = find_value(payload, {"versionstring", "version"})
    application = find_value(payload, {"application"})
    if not version or (application and application.casefold() != "arduino-cli"):
        raise InstallError(f"Unexpected Arduino CLI version response from {path}")
    return version


def download_bundled_cli() -> tuple[Path, str]:
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    install_dir = TOOLS_DIR / f".arduino-cli-new-{uuid.uuid4().hex}"
    backup_dir = TOOLS_DIR / f".arduino-cli-old-{uuid.uuid4().hex}"

    try:
        with tempfile.TemporaryDirectory(prefix="adeck-cli-") as temp:
            archive = Path(temp) / "arduino-cli.zip"
            print("Downloading the latest Arduino CLI...", flush=True)
            try:
                with urllib.request.urlopen(CLI_DOWNLOAD_URL, timeout=60) as response:
                    with archive.open("wb") as handle:
                        shutil.copyfileobj(response, handle)
            except (OSError, urllib.error.URLError) as error:
                raise InstallError(f"Arduino CLI download failed: {error}") from error

            if not zipfile.is_zipfile(archive):
                raise InstallError("The Arduino CLI download is not a valid ZIP archive")
            install_dir.mkdir()
            with zipfile.ZipFile(archive) as bundle:
                bundle.extractall(install_dir)

        candidates = list(install_dir.rglob("arduino-cli.exe"))
        if len(candidates) != 1:
            raise InstallError("The Arduino CLI archive has unexpected contents")
        if candidates[0].parent != install_dir:
            shutil.copy2(candidates[0], install_dir / "arduino-cli.exe")
        version = validate_cli(install_dir / "arduino-cli.exe")

        if BUNDLED_CLI_DIR.exists():
            BUNDLED_CLI_DIR.replace(backup_dir)
        try:
            install_dir.replace(BUNDLED_CLI_DIR)
        except Exception:
            if backup_dir.exists() and not BUNDLED_CLI_DIR.exists():
                backup_dir.replace(BUNDLED_CLI_DIR)
            raise
        shutil.rmtree(backup_dir, ignore_errors=True)
        return BUNDLED_CLI, version
    finally:
        shutil.rmtree(install_dir, ignore_errors=True)


def resolve_cli() -> Path:
    try:
        version = validate_cli(BUNDLED_CLI)
        print(f"Using bundled Arduino CLI {version}", flush=True)
        return BUNDLED_CLI
    except InstallError as bundled_error:
        print(f"Bundled Arduino CLI needs repair: {bundled_error}", flush=True)

    try:
        path, version = download_bundled_cli()
        print(f"Installed bundled Arduino CLI {version}", flush=True)
        return path
    except InstallError as repair_error:
        path_value = shutil.which("arduino-cli")
        if path_value:
            path = Path(path_value)
            try:
                version = validate_cli(path)
                print(
                    f"Bundled CLI repair failed; using Arduino CLI {version} from PATH",
                    flush=True,
                )
                return path
            except InstallError:
                pass
        raise InstallError(
            f"Could not prepare Arduino CLI. {repair_error}"
        ) from repair_error


def collect_values(value: Any, key_name: str) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key.casefold() == key_name.casefold() and item not in (None, ""):
                found.add(str(item))
            else:
                found.update(collect_values(item, key_name))
    elif isinstance(value, list):
        for item in value:
            found.update(collect_values(item, key_name))
    return found


def prepare_dependencies(cli: Path) -> None:
    core_payload = parse_json_output(
        run_process([cli, "core", "list", "--format", "json"]),
        "arduino-cli core list",
    )
    installed_cores = collect_values(core_payload, "id")

    library_payload = parse_json_output(
        run_process([cli, "lib", "list", "--format", "json"]),
        "arduino-cli lib list",
    )
    installed_libraries = {
        name.casefold() for name in collect_values(library_payload, "name")
    }
    missing_libraries = [
        name for name in REQUIRED_LIBRARIES if name.casefold() not in installed_libraries
    ]

    if TARGET_CORE not in installed_cores or missing_libraries:
        run_process([cli, "core", "update-index"])
    if TARGET_CORE not in installed_cores:
        run_process([cli, "core", "install", TARGET_CORE])
    else:
        print(f"Core already installed: {TARGET_CORE}", flush=True)

    for library in REQUIRED_LIBRARIES:
        if library in missing_libraries:
            run_process([cli, "lib", "install", library])
        else:
            print(f"Library already installed: {library}", flush=True)


def normalize_usb_id(value: object) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip().lower()
    if text.startswith("0x"):
        text = text[2:]
    return text.zfill(4)


def property_value(properties: Any, *names: str) -> str | None:
    wanted = {name.casefold() for name in names}
    if isinstance(properties, dict):
        for key, value in properties.items():
            if key.casefold() in wanted and value not in (None, ""):
                return str(value)
    elif isinstance(properties, list):
        for item in properties:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or item.get("name") or "").casefold()
            if key in wanted and item.get("value") not in (None, ""):
                return str(item["value"])
    return None


def board_entries(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("detected_ports"), list):
        return [item for item in payload["detected_ports"] if isinstance(item, dict)]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    found: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        if isinstance(payload.get("port"), dict):
            found.append(payload)
        else:
            for item in payload.values():
                found.extend(board_entries(item))
    return found


def list_ports(cli: Path) -> list[PortInfo]:
    payload = parse_json_output(
        run_process([cli, "board", "list", "--format", "json"]),
        "arduino-cli board list",
    )
    ports: list[PortInfo] = []
    seen: set[tuple[str, str | None]] = set()
    for entry in board_entries(payload):
        port_data = entry.get("port") or {}
        address = port_data.get("address") or port_data.get("label")
        if not address:
            continue
        properties = port_data.get("properties") or {}
        serial_number = property_value(
            properties, "serialNumber", "serial_number", "serial"
        )
        vid = normalize_usb_id(property_value(properties, "vid"))
        pid = normalize_usb_id(property_value(properties, "pid"))
        matches = entry.get("matching_boards") or entry.get("boards") or [None]
        if not matches:
            matches = [None]
        for board in matches:
            board = board if isinstance(board, dict) else {}
            fqbn = board.get("fqbn")
            key = (str(address).upper(), str(fqbn) if fqbn else None)
            if key in seen:
                continue
            seen.add(key)
            ports.append(
                PortInfo(
                    port=str(address),
                    fqbn=str(fqbn) if fqbn else None,
                    board_name=str(board.get("name")) if board.get("name") else None,
                    serial_number=serial_number,
                    vid=vid,
                    pid=pid,
                    protocol=(
                        str(port_data.get("protocol"))
                        if port_data.get("protocol")
                        else None
                    ),
                )
            )
    return ports


def detect_target_board(cli: Path) -> PortInfo:
    matches = [item for item in list_ports(cli) if item.fqbn == TARGET_FQBN]
    by_port = {item.port.upper(): item for item in matches}
    if not by_port:
        raise InstallError(
            "No Arduino UNO R4 WiFi was found. Connect it by USB and close "
            "Arduino Serial Monitor. Only arduino:renesas_uno:unor4wifi is supported."
        )
    if len(by_port) > 1:
        ports = ", ".join(sorted(item.port for item in by_port.values()))
        raise InstallError(
            f"More than one UNO R4 WiFi is connected ({ports}). "
            "Leave only the ADeck connected and run the installer again."
        )
    board = next(iter(by_port.values()))
    if not board.serial_number and not (board.vid and board.pid):
        raise InstallError(
            "The UNO R4 WiFi was identified, but Arduino CLI did not report a "
            "USB serial number or VID/PID. Upload was cancelled to avoid targeting "
            "an untraceable COM port."
        )
    print(
        f"Detected {board.board_name or 'Arduino UNO R4 WiFi'} on {board.port}",
        flush=True,
    )
    return board


def health_is_up() -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=0.7) as response:
            return response.status < 500
    except urllib.error.HTTPError:
        return True
    except (OSError, urllib.error.URLError):
        return False


def stop_runtime() -> None:
    deck = BASE_DIR / "deck.py"
    if not deck.is_file():
        raise InstallError(f"Runtime entry point is missing: {deck}")
    result = run_process([sys.executable, deck, "--stop"], timeout=20, check=False)
    if result.returncode:
        detail = (result.stderr or result.stdout or "").strip()
        raise InstallError(
            "ADeck runtime shutdown failed"
            + (f": {detail}" if detail else f" (exit {result.returncode})")
        )

    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        if not health_is_up():
            return
        time.sleep(0.4)
    raise InstallError(
        "ADeck runtime is still responding after shutdown; firmware upload was cancelled."
    )


def wait_for_port_release(port: str) -> None:
    deadline = time.monotonic() + 12
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        connection = serial.Serial()
        connection.port = port
        connection.baudrate = 115200
        connection.timeout = 0.2
        connection.write_timeout = 0.2
        connection.dtr = False
        try:
            connection.open()
            connection.close()
            print(f"Serial port is available: {port}", flush=True)
            return
        except (OSError, serial.SerialException) as error:
            last_error = error
            time.sleep(0.4)
        finally:
            if connection.is_open:
                connection.close()
    raise InstallError(
        f"{port} is still in use after stopping ADeck. "
        f"Close Serial Monitor or other serial programs. Last error: {last_error}"
    )


def compile_firmware(cli: Path) -> None:
    sketch = SKETCH_DIR / "ADeck.ino"
    if not sketch.is_file():
        raise InstallError(f"Canonical firmware sketch is missing: {sketch}")
    shutil.rmtree(BUILD_DIR, ignore_errors=True)
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    run_process(
        [
            cli,
            "compile",
            "--fqbn",
            TARGET_FQBN,
            "--build-path",
            BUILD_DIR,
            SKETCH_DIR,
        ]
    )


def upload_once(cli: Path, port: str) -> None:
    run_process(
        [
            cli,
            "upload",
            "--port",
            port,
            "--fqbn",
            TARGET_FQBN,
            "--input-dir",
            BUILD_DIR,
            "--verify",
            SKETCH_DIR,
        ]
    )


def identity_score(candidate: PortInfo, original: PortInfo) -> int:
    score = 0
    if (
        original.serial_number
        and candidate.serial_number
        and original.serial_number.casefold() == candidate.serial_number.casefold()
    ):
        score += 100
    if original.vid and candidate.vid and original.vid == candidate.vid:
        score += 20
        if original.pid and candidate.pid and original.pid == candidate.pid:
            score += 35
    if candidate.fqbn == TARGET_FQBN:
        score += 45
    return score


def matching_port(
    ports: list[PortInfo],
    original: PortInfo,
    *,
    changed_from: str | None = None,
) -> PortInfo | None:
    candidates = [
        item
        for item in ports
        if not changed_from or item.port.casefold() != changed_from.casefold()
    ]
    scored = sorted(
        ((identity_score(item, original), item) for item in candidates),
        key=lambda pair: pair[0],
        reverse=True,
    )
    if not scored:
        return None
    score, candidate = scored[0]
    if score >= 65:
        return candidate
    if changed_from and score >= 20 and len(scored) == 1:
        return candidate
    return None


def wait_for_matching_port(
    cli: Path,
    original: PortInfo,
    timeout: float,
    *,
    changed_from: str | None = None,
) -> PortInfo | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            match = matching_port(
                list_ports(cli), original, changed_from=changed_from
            )
            if match:
                return match
        except InstallError:
            pass
        time.sleep(0.6)
    return None


def touch_1200_bps(port: str) -> None:
    print(f"Requesting bootloader mode on {port}...", flush=True)
    connection = serial.Serial()
    connection.port = port
    connection.baudrate = 1200
    connection.timeout = 0.2
    connection.dtr = False
    try:
        connection.open()
        time.sleep(0.2)
    except (OSError, serial.SerialException) as error:
        raise InstallError(f"Could not request bootloader mode on {port}: {error}") from error
    finally:
        if connection.is_open:
            connection.close()


def upload_with_recovery(cli: Path, board: PortInfo) -> str:
    current_port = board.port
    last_error: InstallError | None = None

    try:
        upload_once(cli, current_port)
        return current_port
    except InstallError as error:
        last_error = error
        print("Initial upload did not complete; checking for a re-enumerated port.", flush=True)

    moved = wait_for_matching_port(
        cli, board, 8, changed_from=current_port
    )
    if moved:
        current_port = moved.port
        print(f"Board re-enumerated as {current_port}; retrying upload.", flush=True)
        try:
            upload_once(cli, current_port)
            return current_port
        except InstallError as error:
            last_error = error

    try:
        touch_1200_bps(current_port)
        bootloader = wait_for_matching_port(
            cli, board, 12, changed_from=current_port
        )
        if bootloader:
            current_port = bootloader.port
            print(f"Bootloader found on {current_port}; retrying upload.", flush=True)
            try:
                upload_once(cli, current_port)
                return current_port
            except InstallError as error:
                last_error = error
    except InstallError as error:
        last_error = error

    if not sys.stdin.isatty():
        raise InstallError(
            "Automatic bootloader recovery failed. Double-press RESET on the UNO R4 "
            "WiFi, then rerun the installer from an interactive PowerShell window."
        ) from last_error

    print(
        "\nAutomatic recovery failed. Double-press RESET on the UNO R4 WiFi now.",
        flush=True,
    )
    input("Press Enter immediately after the double reset to scan for the bootloader...")
    recovery = wait_for_matching_port(cli, board, 20)
    if not recovery:
        raise InstallError(
            "The UNO R4 WiFi bootloader was not detected within 20 seconds. "
            "Close serial applications, reconnect USB, and run the installer again."
        ) from last_error

    try:
        upload_once(cli, recovery.port)
        return recovery.port
    except InstallError as error:
        raise InstallError(
            "Upload failed after the one allowed double-reset recovery attempt.\n"
            f"{error}"
        ) from error


def ping_firmware(port: str) -> bool:
    connection = serial.Serial()
    connection.port = port
    connection.baudrate = 115200
    connection.timeout = 0.25
    connection.write_timeout = 1
    connection.dtr = False
    try:
        connection.open()
        time.sleep(1.7)
        connection.reset_input_buffer()
        connection.write(b"PING\n")
        connection.flush()
        deadline = time.monotonic() + 2.5
        while time.monotonic() < deadline:
            line = connection.readline().decode("ascii", errors="ignore").strip()
            if line == PROTOCOL_REPLY:
                return True
        return False
    except (OSError, serial.SerialException):
        return False
    finally:
        if connection.is_open:
            connection.close()


def verify_firmware(cli: Path, board: PortInfo, upload_port: str) -> PortInfo:
    deadline = time.monotonic() + 30
    last_ports: list[str] = []
    while time.monotonic() < deadline:
        try:
            ports = list_ports(cli)
        except InstallError:
            time.sleep(0.6)
            continue
        last_ports = [item.port for item in ports]
        candidates = [
            item
            for item in ports
            if item.fqbn == TARGET_FQBN and identity_score(item, board) >= 65
        ]
        candidates.sort(key=lambda item: item.port.casefold() != upload_port.casefold())
        for candidate in candidates:
            if ping_firmware(candidate.port):
                print(
                    f"Verified {PROTOCOL_REPLY.replace(chr(9), ' ')} on {candidate.port}",
                    flush=True,
                )
                return candidate
        time.sleep(0.8)
    detail = ", ".join(last_ports) if last_ports else "no serial ports"
    raise InstallError(
        "Upload completed, but the ADeck v2 PING/PONG handshake failed after "
        f"30 seconds ({detail}). Installation cannot continue."
    )


def save_identity(board: PortInfo) -> None:
    IDENTITY_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        **asdict(board),
        "fqbn": TARGET_FQBN,
        "last_port": board.port,
        "protocol_version": 2,
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }
    temp_path = IDENTITY_PATH.with_suffix(f".{uuid.uuid4().hex}.tmp")
    temp_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(temp_path, IDENTITY_PATH)
    print(f"Saved board identity to {IDENTITY_PATH}", flush=True)


def backend_reports_connected() -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=0.7) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return bool(
            isinstance(payload, dict)
            and payload.get("ok") is True
            and payload.get("service") == "ADeck"
            and payload.get("connected") is True
        )
    except (OSError, urllib.error.URLError, ValueError, TypeError):
        return False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install ADeck firmware on an Arduino UNO R4 WiFi"
    )
    parser.add_argument(
        "--cli-only",
        action="store_true",
        help="validate or repair Arduino CLI, then exit without touching hardware",
    )
    parser.add_argument(
        "--if-needed",
        action="store_true",
        help="skip compile/upload when the board already answers ADECK_PONG",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        stage("Arduino CLI")
        cli = resolve_cli()
        if args.cli_only:
            return 0

        if args.if_needed and backend_reports_connected():
            print(
                "ADeck firmware already verified through the running backend; "
                "skipping reflash.",
                flush=True,
            )
            return 0

        stage("Stop ADeck runtime")
        stop_runtime()

        stage("Arduino dependencies")
        prepare_dependencies(cli)

        stage("UNO R4 WiFi detection")
        board = detect_target_board(cli)
        wait_for_port_release(board.port)

        if args.if_needed and ping_firmware(board.port):
            save_identity(board)
            print(
                f"\nExisting firmware already replies {PROTOCOL_REPLY.replace(chr(9), ' ')} "
                f"on {board.port}; skipping reflash.",
                flush=True,
            )
            return 0

        stage("Firmware compile")
        compile_firmware(cli)

        stage("Firmware upload")
        upload_port = upload_with_recovery(cli, board)

        stage("Firmware verification")
        verified_board = verify_firmware(cli, board, upload_port)
        save_identity(verified_board)
        print("\nADeck firmware is installed and verified.", flush=True)
        return 0
    except (InstallError, KeyboardInterrupt) as error:
        message = "Installation cancelled." if isinstance(error, KeyboardInterrupt) else str(error)
        print(f"\nFirmware installation failed: {message}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
