import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import adeck_control
import deck
import install_firmware


def sample_config(active="Main"):
    colors = ("#112233", "#445566", "#778899", "#aabbcc", "#ddeeff", "#010203")
    labels = ("ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX")
    return {
        "active_profile": active,
        "settings": {"theme": "dark", "wifiMode": "off"},
        "profiles": [
            {
                "id": "main",
                "name": "Main",
                "buttons": [
                    {
                        "key": index + 1,
                        "label": labels[index],
                        "command": f"command-{index}",
                        "color": colors[index],
                    }
                    for index in range(6)
                ],
            }
        ],
    }


class FakeSerial:
    """Stands in for the board, including its habit of losing icon rows.

    rows_to_drop counts how many icon frames are swallowed whole (no
    CFG_ICON_OK, and the board says CFG_ICON_ERR the way the real firmware
    does), so retries can be exercised without hardware.

    theme_errors makes the board refuse a theme transaction for the given
    number of frames, the way the firmware answers CFG_THEME_ERR.
    """

    def __init__(self, rows_to_drop=0, theme_errors=0):
        self.writes = []
        self.replies = []
        self.closed = False
        self.frames_to_drop = rows_to_drop
        self.icon_frames = 0
        self.theme_errors = theme_errors
        self.theme_frames = 0

    def write(self, payload):
        self.writes.append(payload)
        try:
            lines = payload.decode("ascii").splitlines()
        except UnicodeDecodeError:
            return
        for line in lines:
            parts = line.split("\t")
            if not parts:
                continue
            if parts[0] == "CFG_BEGIN" and len(parts) > 1:
                self.replies.append(f"CFG_OK\t{parts[1]}\n".encode("ascii"))
            elif parts[0] == "CFG_THEME_END" and len(parts) > 1:
                self.theme_frames += 1
                if self.theme_frames <= self.theme_errors:
                    self.replies.append(
                        f"CFG_THEME_ERR\t{parts[1]}\tCRC_MISMATCH\n".encode("ascii")
                    )
                else:
                    self.replies.append(f"CFG_THEME_OK\t{parts[1]}\n".encode("ascii"))
            elif parts[0] == "CFG_ICON_END" and len(parts) > 2:
                self.icon_frames += 1
                if self.icon_frames <= self.frames_to_drop:
                    self.replies.append(
                        f"CFG_ICON_ERR\t{parts[1]}\t{parts[2]}\tINCOMPLETE\n".encode("ascii")
                    )
                else:
                    self.replies.append(
                        f"CFG_ICON_OK\t{parts[1]}\t{parts[2]}\n".encode("ascii")
                    )

    def flush(self):
        pass

    def readline(self):
        return self.replies.pop(0) if self.replies else b""

    def close(self):
        self.closed = True


class StubDevice:
    def __init__(self):
        self.lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.calls = []
        self.requested_port = None
        self.reconnects = []

    def status(self):
        return {
            "connected": False,
            "port": None,
            "firmware": None,
            "last_sync": None,
            "last_transaction_id": None,
            "error": None,
        }

    def available_ports(self):
        return [
            {
                "device": "COM9",
                "description": "Arduino UNO R4 WiFi",
                "manufacturer": "Arduino",
                "serial_number": "ABC",
                "arduino": True,
                "matches": True,
            }
        ]

    def request_reconnect(self, port=None):
        self.reconnects.append(port)
        if port is not None:
            self.requested_port = port or None

    def request_sync(self, config):
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(0.03)
        self.calls.append(config["active_profile"])
        with self.lock:
            self.active -= 1
        return {
            "sync_state": "offline",
            "device_synced": False,
            "transaction_id": None,
            "acknowledged_transaction_id": None,
            "sync_error": None,
        }


class ReliabilityTests(unittest.TestCase):
    def test_config_validation_mapping_and_atomic_backup(self):
        normalized = deck.normalize_config(sample_config())
        self.assertEqual(normalized["version"], 2)
        self.assertEqual(deck.active_buttons(normalized)[2]["command"], "command-2")
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "config.json"
            backup = Path(temp) / "config.backup.json"
            store = deck.ConfigStore(path, backup)
            store.save(sample_config())
            changed = sample_config()
            changed["profiles"][0]["buttons"][0]["label"] = "CHANGED"
            store.save(changed)
            self.assertEqual(json.loads(backup.read_text())["profiles"][0]["buttons"][0]["label"], "ONE")
            self.assertEqual(store.command_for(0), "command-0")

    def test_duplicate_names_and_bad_slots_are_rejected(self):
        duplicate = sample_config()
        duplicate["profiles"].append(
            {"name": "main", "buttons": duplicate["profiles"][0]["buttons"]}
        )
        with self.assertRaisesRegex(ValueError, "unique"):
            deck.normalize_config(duplicate)
        invalid = sample_config()
        invalid["profiles"][0]["buttons"][5]["key"] = 5
        with self.assertRaisesRegex(ValueError, "unique"):
            deck.normalize_config(invalid)

    def test_protocol_v2_golden_frame_and_ack(self):
        config = deck.normalize_config(sample_config())
        expected = (
            b"CFG_BEGIN\tabc123\t6\n"
            b"CFG_SLOT\tabc123\t0\t#112233\tONE\n"
            b"CFG_SLOT\tabc123\t1\t#445566\tTWO\n"
            b"CFG_SLOT\tabc123\t2\t#778899\tTHREE\n"
            b"CFG_SLOT\tabc123\t3\t#AABBCC\tFOUR\n"
            b"CFG_SLOT\tabc123\t4\t#DDEEFF\tFIVE\n"
            b"CFG_SLOT\tabc123\t5\t#010203\tSIX\n"
            b"CFG_END\tabc123\t1589\n"
        )
        self.assertEqual(deck.config_frame(config, "abc123"), expected)
        store = mock.Mock()
        device = deck.ADeckDevice(store, identity_path=Path(tempfile.gettempdir()) / "unused.json")
        connection = FakeSerial()
        device._connection = connection
        device._sync(config, "abc123")
        self.assertEqual(connection.writes, [expected])
        self.assertTrue(device.status()["last_sync"])

    def test_reconnect_and_press_command_dispatch(self):
        with tempfile.TemporaryDirectory() as temp:
            store = mock.Mock()
            store.command_for.return_value = "echo tested"
            identity = Path(temp) / "device.json"
            device = deck.ADeckDevice(store, identity_path=identity)
            info = SimpleNamespace(
                device="COM9",
                vid=0x2341,
                pid=0x1002,
                serial_number="ABC",
                manufacturer="Arduino",
                product="UNO R4 WiFi",
            )
            connection = FakeSerial()
            with (
                mock.patch.object(device, "_candidate_ports", return_value=[("COM9", info)]),
                mock.patch.object(device, "_probe", return_value=connection),
            ):
                self.assertTrue(device._connect())
            self.assertEqual(device.status()["port"], "COM9")
            self.assertEqual(json.loads(identity.read_text())["serial_number"], "ABC")
            with mock.patch("deck.subprocess.Popen") as popen:
                device._run_command(2)
                popen.assert_called_once_with("echo tested", shell=True)
            with mock.patch.object(device, "_run_command") as run_command:
                device._handle_line("PRESS\t2")
                deadline = time.monotonic() + 1
                while not run_command.called and time.monotonic() < deadline:
                    time.sleep(0.01)
                run_command.assert_called_once_with(2)
            device._disconnect("test")
            self.assertTrue(connection.closed)

    def test_http_get_post_and_concurrent_save_serialization(self):
        with tempfile.TemporaryDirectory() as temp:
            store = deck.ConfigStore(Path(temp) / "config.json")
            device = StubDevice()
            server = deck.BridgeServer(
                ("127.0.0.1", 0), deck.BridgeHandler, store, device, "token"
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_address[1]}"
            try:
                with urllib.request.urlopen(base + "/api/status") as response:
                    status = json.load(response)
                self.assertEqual(status["service"], "ADeck")
                self.assertFalse(status["config_saved"])

                def post():
                    request = urllib.request.Request(
                        base + "/api/config",
                        data=json.dumps(sample_config()).encode(),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(request) as response:
                        return json.load(response)

                results = []
                workers = [threading.Thread(target=lambda: results.append(post())) for _ in range(2)]
                for worker in workers:
                    worker.start()
                for worker in workers:
                    worker.join()
                self.assertEqual(device.max_active, 1)
                self.assertTrue(all(item["saved"] for item in results))
                with urllib.request.urlopen(base + "/api/config") as response:
                    saved = json.load(response)
                self.assertEqual(saved["config"]["active_profile"], "Main")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_installer_json_detection_and_runtime_stop_command(self):
        payload = {
            "detected_ports": [
                {
                    "port": {
                        "address": "COM7",
                        "protocol": "serial",
                        "properties": {
                            "serialNumber": "XYZ",
                            "vid": "0x2341",
                            "pid": "0x1002",
                        },
                    },
                    "matching_boards": [
                        {
                            "name": "Arduino UNO R4 WiFi",
                            "fqbn": install_firmware.TARGET_FQBN,
                        }
                    ],
                }
            ]
        }
        completed = subprocess.CompletedProcess([], 0, json.dumps(payload), "")
        with mock.patch.object(install_firmware, "run_process", return_value=completed):
            ports = install_firmware.list_ports(Path("arduino-cli"))
        self.assertEqual(ports[0].port, "COM7")
        self.assertEqual(ports[0].serial_number, "XYZ")
        self.assertEqual(ports[0].vid, "2341")
        stopped = subprocess.CompletedProcess([], 0, "ADeck service stopped", "")
        with (
            mock.patch.object(install_firmware, "run_process", return_value=stopped) as run,
            mock.patch.object(install_firmware, "health_is_up", return_value=False),
        ):
            install_firmware.stop_runtime()
        command = run.call_args.args[0]
        self.assertEqual(command[-1], "--stop")
        self.assertEqual(Path(command[-2]).name, "deck.py")


    def test_installable_app_assets_are_present_and_served(self):
        web = deck.WEB_DIR
        manifest = json.loads((web / "manifest.webmanifest").read_text(encoding="utf-8"))
        self.assertEqual(manifest["display"], "standalone")
        self.assertEqual(manifest["start_url"], "/")
        sizes = {icon["sizes"] for icon in manifest["icons"]}
        self.assertIn("192x192", sizes)
        self.assertIn("512x512", sizes)
        self.assertIn(
            "maskable", {icon.get("purpose") for icon in manifest["icons"]}
        )
        for icon in manifest["icons"]:
            asset = web / icon["src"].lstrip("/")
            self.assertTrue(asset.is_file(), icon["src"])
            self.assertEqual(asset.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual((web / "adeck.ico").read_bytes()[:4], b"\x00\x00\x01\x00")

        worker = (web / "sw.js").read_text(encoding="utf-8")
        self.assertIn('addEventListener("fetch"', worker)
        self.assertIn('url.pathname.startsWith("/api/")', worker)

        markup = (web / "index.html").read_text(encoding="utf-8")
        self.assertIn('rel="manifest"', markup)
        self.assertIn('data-page="system"', markup)

        with tempfile.TemporaryDirectory() as temp:
            store = deck.ConfigStore(Path(temp) / "config.json")
            server = deck.BridgeServer(
                ("127.0.0.1", 0), deck.BridgeHandler, store, StubDevice(), "token"
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_address[1]}"
            try:
                with urllib.request.urlopen(base + "/manifest.webmanifest") as response:
                    self.assertEqual(
                        response.headers.get_content_type(), "application/manifest+json"
                    )
                    self.assertEqual(json.load(response)["short_name"], "ADeck")
                with urllib.request.urlopen(base + "/sw.js") as response:
                    self.assertEqual(response.headers.get_content_type(), "text/javascript")
                for path in ("/icon-192.png", "/icon-512.png", "/favicon.ico"):
                    with urllib.request.urlopen(base + path) as response:
                        self.assertEqual(response.status, 200)
                        self.assertTrue(len(response.read()) > 100, path)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_system_logs_control_and_task_endpoints(self):
        started = []
        known_actions = {"check": None, "repair": None, "restart": None}

        def fake_start_task(action, debug=False):
            if action not in known_actions:
                raise ValueError(f"Unknown task action: {action}")
            started.append(action)
            return {"id": "20260101-000000-abcd", "action": action, "state": "running"}

        fake_control = SimpleNamespace(
            TASK_ACTIONS=known_actions,
            integration_state=lambda: {
                "desktop_shortcut": True,
                "autostart": False,
                "protocol_handler": True,
            },
            list_tasks=lambda limit=10: [{"id": "20260101-000000-abcd", "state": "done"}],
            tail_lines=lambda path, limit=200: ["line one", "line two"],
            read_task=lambda task_id, lines=400: (
                {"id": task_id, "state": "done", "exit_code": 0, "output": ["done"]}
                if task_id == "20260101-000000-abcd"
                else None
            ),
            start_task=fake_start_task,
            set_autostart=lambda enabled: "C:/startup/ADeck.lnk" if enabled else None,
        )
        with tempfile.TemporaryDirectory() as temp:
            store = deck.ConfigStore(Path(temp) / "config.json")
            store.save(sample_config())
            device = StubDevice()
            server = deck.BridgeServer(
                ("127.0.0.1", 0), deck.BridgeHandler, store, device, "token"
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_address[1]}"

            def post(payload, expect=200):
                request = urllib.request.Request(
                    base + "/api/control",
                    data=json.dumps(payload).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                try:
                    with urllib.request.urlopen(request) as response:
                        self.assertEqual(response.status, expect)
                        return json.load(response)
                except urllib.error.HTTPError as error:
                    self.assertEqual(error.code, expect)
                    return json.load(error)

            try:
                with mock.patch.object(deck, "control_module", return_value=fake_control):
                    with urllib.request.urlopen(base + "/api/system") as response:
                        system = json.load(response)
                    self.assertTrue(system["ok"])
                    self.assertEqual(system["backend"]["port"], server.server_address[1])
                    self.assertEqual(system["config"]["profile_count"], 1)
                    self.assertTrue(system["config"]["saved"])
                    self.assertEqual(system["serial_ports"][0]["device"], "COM9")
                    self.assertTrue(system["integration"]["protocol_handler"])
                    self.assertIsNone(system["control_error"])

                    with urllib.request.urlopen(base + "/api/logs?source=app&lines=2") as response:
                        logs = json.load(response)
                    self.assertEqual(logs["lines"], ["line one", "line two"])
                    with self.assertRaises(urllib.error.HTTPError) as bad_source:
                        urllib.request.urlopen(base + "/api/logs?source=secrets")
                    self.assertEqual(bad_source.exception.code, 400)

                    with urllib.request.urlopen(base + "/api/tasks") as response:
                        self.assertEqual(len(json.load(response)["tasks"]), 1)
                    with urllib.request.urlopen(
                        base + "/api/tasks/20260101-000000-abcd"
                    ) as response:
                        self.assertEqual(json.load(response)["task"]["exit_code"], 0)
                    with self.assertRaises(urllib.error.HTTPError) as missing:
                        urllib.request.urlopen(base + "/api/tasks/20260101-000000-ffff")
                    self.assertEqual(missing.exception.code, 404)

                    self.assertEqual(post({}, 400)["error"], "An action is required")
                    self.assertIn("Unknown task action", post({"action": "nope"}, 400)["error"])
                    self.assertEqual(
                        post({"action": "reconnect", "port": "COM4 & del"}, 400)["error"],
                        "Invalid serial port name",
                    )

                    self.assertTrue(post({"action": "reconnect"})["ok"])
                    self.assertTrue(post({"action": "reconnect", "port": "COM9"})["ok"])
                    self.assertEqual(device.reconnects, [None, "COM9"])

                    resync = post({"action": "resync"})
                    self.assertEqual(resync["sync_state"], "offline")

                    task = post({"action": "repair"})
                    self.assertEqual(task["task"]["action"], "repair")
                    self.assertEqual(started, ["repair"])

                    autostart = post({"action": "autostart-on"})
                    self.assertEqual(autostart["path"], "C:/startup/ADeck.lnk")

                # A saved config must still round-trip while the new routes exist.
                with urllib.request.urlopen(base + "/api/config") as response:
                    self.assertEqual(json.load(response)["config"]["active_profile"], "Main")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_task_records_survive_and_report_exit_state(self):
        with tempfile.TemporaryDirectory() as temp:
            tasks_dir = Path(temp) / "tasks"
            with mock.patch.object(adeck_control, "TASKS_DIR", tasks_dir):
                tasks_dir.mkdir(parents=True)
                task_id = "20260101-010101-beef"
                json_path, log_path = adeck_control._task_paths(task_id)
                adeck_control._write_json(
                    json_path,
                    {"id": task_id, "action": "check", "state": "running", "pid": 1},
                )
                log_path.write_text("first\nsecond\nthird\n", encoding="utf-8")

                record = adeck_control.read_task(task_id, lines=2)
                self.assertEqual(record["state"], "running")
                self.assertEqual(record["output"], ["second", "third"])
                self.assertIsNone(adeck_control.read_task("../etc/passwd"))
                self.assertIsNone(adeck_control.read_task("20260101-010101-0000"))
                self.assertEqual(len(adeck_control.list_tasks()), 1)

                # A task that stops reporting must not look like it is still running.
                old = time.time() - (adeck_control.TASK_STALE_SECONDS + 60)
                os.utime(json_path, (old, old))
                os.utime(log_path, (old, old))
                self.assertEqual(adeck_control.read_task(task_id)["state"], "unknown")

                with (
                    mock.patch.dict(
                        adeck_control.TASK_ACTIONS, {"check": lambda debug: 7}, clear=False
                    ),
                    mock.patch.object(adeck_control, "backend_healthy", return_value=True),
                ):
                    self.assertEqual(adeck_control.cmd_task(task_id, "check"), 7)
                finished = adeck_control.read_task(task_id)
                self.assertEqual(finished["state"], "done")
                self.assertEqual(finished["exit_code"], 7)
                self.assertEqual(adeck_control.cmd_task(task_id, "not-an-action"), 2)

    def test_launcher_helpers_parse_windows_values(self):
        self.assertEqual(
            adeck_control._read_powershell_json('{"desktop":"C:\\\\x\\\\ADeck.lnk"}'),
            {"desktop": "C:\\x\\ADeck.lnk"},
        )
        self.assertEqual(adeck_control._read_powershell_json("not json"), {})
        self.assertIsNone(adeck_control._executable_from_command(""))
        self.assertIsNone(
            adeck_control._executable_from_command('"C:\\nope\\missing.exe" -- "%1"')
        )
        real = Path(sys.executable)
        self.assertEqual(
            adeck_control._executable_from_command(f'"{real}" --app=http://x'), real
        )
        self.assertEqual(adeck_control._executable_from_command(str(real)), real)
        target, arguments = adeck_control._launcher_target()
        self.assertTrue(target.endswith("pythonw.exe"))
        self.assertIn("adeck_control.py", arguments)
        self.assertTrue(arguments.endswith(" app"))
        self.assertIn("adeck_control.py", adeck_control._protocol_command())
        self.assertNotIn("stop", adeck_control.TASK_RESTORE_SERVICE)

    def test_app_relaunch_detects_gui_apps_not_shell_commands(self):
        self.assertEqual(deck._normalize_relaunch_mode("minimize"), "minimize")
        self.assertEqual(deck._normalize_relaunch_mode("close"), "close")
        self.assertEqual(deck._normalize_relaunch_mode("bogus"), "new")
        self.assertIsNone(deck._win_gui_app_identity("git status"))
        self.assertIsNone(deck._win_gui_app_identity("git add ."))
        self.assertIsNone(deck._win_gui_app_identity("echo tested"))
        self.assertIsNone(deck._win_gui_app_identity("https://example.com"))
        notepad = deck._win_gui_app_identity("notepad.exe")
        self.assertIsNotNone(notepad)
        self.assertIn("notepad.exe", notepad["names"])
        paint = deck._win_gui_app_identity("mspaint.exe")
        self.assertIsNotNone(paint)
        self.assertIn("mspaint.exe", paint["names"])
        explorer = deck._win_gui_app_identity("explorer.exe")
        self.assertIsNotNone(explorer)
        self.assertIn("explorer.exe", explorer["names"])
        for hwnd in deck._find_windows_for_app(explorer):
            self.assertIn(deck._window_class_name(hwnd).lower(), {"cabinetwclass", "explorewclass"})
        vscode = r"C:\Users\maury\AppData\Local\Programs\Microsoft VS Code\Code.exe"
        if Path(vscode).exists():
            identity = deck._win_gui_app_identity(vscode)
            self.assertIsNotNone(identity)
            self.assertTrue(identity["path"].lower().endswith("code.exe"))
        store = mock.Mock()
        store.config = {
            "settings": {"appRelaunchMode": "minimize"},
            "profiles": [],
        }
        real_store = deck.ConfigStore.__new__(deck.ConfigStore)
        real_store.lock = threading.RLock()
        real_store.config = {"settings": {"appRelaunchMode": "close"}}
        self.assertEqual(real_store.app_relaunch_mode(), "close")
        real_store.config = {"settings": {}}
        self.assertEqual(real_store.app_relaunch_mode(), "new")

    def test_launch_brings_gui_apps_to_foreground(self):
        self.assertFalse(
            deck._uses_explorer_host_launch(Path(r"C:\Windows\explorer.exe"), "")
        )
        self.assertTrue(
            deck._uses_explorer_host_launch(Path(r"C:\Windows\notepad.exe"), "")
        )
        self.assertFalse(
            deck._uses_explorer_host_launch(Path(r"C:\Windows\notepad.exe"), "/a")
        )
        identity = {"path": r"C:\Windows\notepad.exe", "names": {"notepad.exe"}}
        with (
            mock.patch.object(deck, "_FOREGROUND_LATE_WINDOW_WAIT", 0),
            mock.patch.object(deck, "_FOREGROUND_POLL", 0),
            mock.patch.object(deck, "_FOREGROUND_NEW_WINDOW_WAIT", 10),
            mock.patch.object(deck, "_find_windows_for_app", return_value=[111, 222]),
            mock.patch.object(deck, "_force_window_foreground", return_value=True) as force,
            mock.patch("ctypes.windll.user32.GetForegroundWindow", return_value=222),
        ):
            self.assertTrue(deck._bring_app_windows_forward(identity, [111], timeout=0.4))
            force.assert_called_with(222)

        with (
            mock.patch.object(deck, "_shell_execute_win") as shell,
            mock.patch.object(deck, "_schedule_bring_app_forward") as sched,
            mock.patch.object(deck, "_apply_app_relaunch", return_value=False),
            mock.patch("deck.subprocess.Popen") as popen,
        ):
            deck._launch_win_command("explorer.exe", "new", "app")
            shell.assert_called()
            self.assertTrue(str(shell.call_args[0][0]).lower().endswith("explorer.exe"))
            self.assertFalse(shell.call_args[0][1] if len(shell.call_args[0]) > 1 else False)
            popen.assert_not_called()
            sched.assert_called()
            self.assertIn("explorer.exe", sched.call_args[0][0]["names"])

            popen.reset_mock()
            shell.reset_mock()
            sched.reset_mock()
            deck._launch_win_command("notepad.exe", "new", "app")
            popen.assert_called()
            argv = popen.call_args[0][0]
            self.assertEqual(argv[0], "explorer.exe")
            self.assertTrue(str(argv[1]).lower().endswith("notepad.exe"))
            shell.assert_not_called()
            sched.assert_called()
            self.assertIn("notepad.exe", sched.call_args[0][0]["names"])

    def test_app_picker_kind_and_installed_app_listing(self):
        config = sample_config()
        config["profiles"][0]["buttons"][0]["kind"] = "app"
        config["profiles"][0]["buttons"][0]["command"] = "notepad.exe"
        config["profiles"][0]["buttons"][1]["kind"] = "command"
        config["profiles"][0]["buttons"][1]["command"] = "git status"
        normalized = deck.normalize_config(config)
        self.assertEqual(normalized["profiles"][0]["buttons"][0]["kind"], "app")
        self.assertEqual(normalized["profiles"][0]["buttons"][1]["kind"], "command")
        self.assertNotIn("kind", normalized["profiles"][0]["buttons"][2])

        with mock.patch.object(deck, "_apply_app_relaunch") as relaunch:
            relaunch.return_value = True
            deck._launch_win_command("notepad.exe", "close", "command")
            relaunch.assert_not_called()
            deck._launch_win_command("notepad.exe", "close", "app")
            relaunch.assert_called_once()
            relaunch.reset_mock()
            deck._launch_win_command("notepad.exe", "close", "")
            relaunch.assert_called_once()

        with tempfile.TemporaryDirectory() as temp:
            store = deck.ConfigStore(Path(temp) / "config.json")
            store.save(config)
            self.assertEqual(store.command_kind_for(0), "app")
            self.assertEqual(store.command_kind_for(1), "command")
            self.assertEqual(store.command_for(1), "git status")
            device = StubDevice()
            server = deck.BridgeServer(
                ("127.0.0.1", 0), deck.BridgeHandler, store, device, "token"
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_address[1]}"
            try:
                with urllib.request.urlopen(base + "/api/apps") as response:
                    payload = json.load(response)
                self.assertTrue(payload["ok"])
                self.assertIsInstance(payload["apps"], list)
                commands = {item["command"].lower() for item in payload["apps"]}
                names = {item["name"].lower() for item in payload["apps"]}
                self.assertTrue(
                    {"calc.exe", "mspaint.exe", "notepad.exe", "explorer.exe"} & commands
                )
                self.assertIn("settings", names)
                self.assertIn("ms-settings:", commands)
                yt_lnk = (
                    Path.home()
                    / "AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Brave Apps/YouTube Music.lnk"
                )
                if yt_lnk.is_file():
                    target, args = deck._parse_lnk_launch(yt_lnk)
                    self.assertTrue(target.lower().endswith(".exe"))
                    self.assertIn("--app-id=", args)
                    self.assertTrue(any("youtube music" in name for name in names))
                self.assertTrue(all("name" in item and "command" in item for item in payload["apps"]))
                self.assertFalse(any("package cache" in item["command"].lower() for item in payload["apps"]))
                self.assertFalse(any(item["name"].lower().startswith("python") for item in payload["apps"]))
                self.assertFalse(any("desktop runtime" in item["name"].lower() for item in payload["apps"]))

                with tempfile.TemporaryDirectory() as icons:
                    notepad_png = deck.app_icon_png("notepad.exe", cache_dir=icons)
                    explorer_png = deck.app_icon_png("explorer.exe", cache_dir=icons)
                    settings_png = deck.app_icon_png("ms-settings:", cache_dir=icons)
                    missing_png = deck.app_icon_png("___no_such_app___", cache_dir=icons)
                    placeholder = deck._placeholder_icon_png()
                self.assertTrue(notepad_png.startswith(b"\x89PNG"))
                self.assertTrue(explorer_png.startswith(b"\x89PNG"))
                self.assertTrue(settings_png.startswith(b"\x89PNG"))
                self.assertEqual(missing_png, placeholder)
                self.assertNotEqual(notepad_png, placeholder)
                self.assertGreater(len(notepad_png), 80)
                with urllib.request.urlopen(base + "/api/app-icon?command=notepad.exe") as response:
                    self.assertIn("image/png", response.headers.get("Content-Type", ""))
                    icon_body = response.read()
                self.assertTrue(icon_body.startswith(b"\x89PNG"))
                self.assertGreater(len(icon_body), 80)
                with urllib.request.urlopen(base + "/api/app-icon?command=___no_such_app___") as response:
                    fallback_body = response.read()
                self.assertEqual(fallback_body, placeholder)
                style = (deck.WEB_DIR / "style.css").read_text(encoding="utf-8")
                script = (deck.WEB_DIR / "script.js").read_text(encoding="utf-8")
                self.assertIn(".dialog-panel.app-picker-panel", style)
                self.assertIn("780px", style)
                self.assertIn("app-picker-icon", style)
                self.assertIn("app-picker-icon", script)
                self.assertIn("/api/app-icon?command=", script)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_installed_app_icons_feed_existing_tft_pipeline(self):
        config = sample_config()
        config["profiles"][0]["buttons"][0]["kind"] = "app"
        config["profiles"][0]["buttons"][0]["command"] = "notepad.exe"
        config["profiles"][0]["buttons"][1]["kind"] = "command"
        config["profiles"][0]["buttons"][1]["command"] = "git status"
        normalized = deck.normalize_config(config)
        frame = deck.config_frame(normalized, "abc123")
        self.assertIn(b"CFG_SLOT\tabc123\t0\t#112233\tONE\n", frame)
        self.assertNotIn(b"CFG_ICON", frame)

        self.assertEqual(deck.slot_icon_frame(1, normalized["profiles"][0]["buttons"][1], "abc123"), b"")
        self.assertEqual(
            deck.slot_icon_frame(2, normalized["profiles"][0]["buttons"][2], "abc123"),
            b"",
        )
        self.assertEqual(
            deck.app_icon_frames(
                [{"kind": "command", "command": "git status", "color": "#000000"}],
                "abc123",
            ),
            [],
        )
        self.assertEqual(
            deck.app_icon_frames(
                [{"kind": "app", "command": "", "color": "#000000"}],
                "abc123",
            ),
            [],
        )
        self.assertEqual(deck.app_icon_rgb565("___no_such_app___"), b"")
        self.assertEqual(
            deck.slot_icon_frame(
                0,
                {"kind": "command", "command": "git status", "color": "#112233"},
                "abc123",
            ),
            b"",
        )

        pixels = deck.app_icon_rgb565("notepad.exe", "#112233")
        self.assertEqual(len(pixels), 32 * 32 * 2)
        self.assertTrue(any(pixels))
        icon_frame = deck.slot_icon_frame(0, normalized["profiles"][0]["buttons"][0], "abc123")
        self.assertTrue(icon_frame.startswith(b"CFG_ICON_BEGIN\tabc123\t0\t32\n"))
        self.assertIn(b"CFG_ICON_ROW\tabc123\t0\t0\t", icon_frame)
        self.assertTrue(icon_frame.endswith(b"CFG_ICON_END\tabc123\t0\n"))
        self.assertEqual(icon_frame.count(b"CFG_ICON_ROW"), 32)

        store = mock.Mock()
        device = deck.ADeckDevice(store, identity_path=Path(tempfile.gettempdir()) / "unused-icon.json")
        connection = FakeSerial()
        device._connection = connection
        device._tft_icons = True
        device._sync(normalized, "abc123")
        self.assertEqual(connection.writes[0], frame)
        joined = b"".join(connection.writes)
        self.assertIn(b"CFG_ICON_BEGIN\tabc123\t0\t32\n", joined)
        self.assertNotIn(b"CFG_ICON_BEGIN\tabc123\t1\t", joined)
        self.assertTrue(device.status()["last_sync"])

        device_off = deck.ADeckDevice(store, identity_path=Path(tempfile.gettempdir()) / "unused-icon-off.json")
        connection_off = FakeSerial()
        device_off._connection = connection_off
        device_off._tft_icons = False
        device_off._sync(normalized, "abc123")
        self.assertEqual(connection_off.writes, [frame])

    def _icon_device(self, name):
        store = mock.Mock()
        device = deck.ADeckDevice(
            store, identity_path=Path(tempfile.gettempdir()) / name
        )
        return device

    def _app_config(self):
        config = sample_config()
        config["profiles"][0]["buttons"][0]["kind"] = "app"
        config["profiles"][0]["buttons"][0]["command"] = "notepad.exe"
        return deck.normalize_config(config)

    def test_dropped_tft_icon_is_retried_until_the_board_takes_it(self):
        normalized = self._app_config()
        device = self._icon_device("retry-icon.json")
        # the board loses the first two attempts at the same icon
        connection = FakeSerial(rows_to_drop=2)
        device._connection = connection
        device._tft_icons = True

        device._sync(normalized, "abc123")

        self.assertEqual(connection.icon_frames, 3)
        self.assertTrue(device.status()["last_sync"])

    def test_tft_icon_that_never_lands_is_reported(self):
        normalized = self._app_config()
        device = self._icon_device("missing-icon.json")
        connection = FakeSerial(rows_to_drop=deck._ICON_ATTEMPTS)
        device._connection = connection
        device._tft_icons = True

        with self.assertLogs("adeck", level="WARNING") as captured:
            device._sync(normalized, "abc123")

        self.assertEqual(connection.icon_frames, deck._ICON_ATTEMPTS)
        self.assertTrue(
            any("never accepted for key(s) 1" in line for line in captured.output),
            captured.output,
        )

        firmware = (deck.BASE_DIR / "firmware" / "ADeck" / "ADeck.ino").read_text(encoding="utf-8")
        self.assertIn("CFG_ICON_BEGIN", firmware)
        self.assertIn("CFG_ICON_OK", firmware)
        self.assertIn("ADECK_CAPS\\tICON", firmware)
        self.assertIn("draw16bitRGBBitmap", firmware)
        self.assertIn("slotHasIcon", firmware)

    # --- themes ----------------------------------------------------------

    def test_the_four_built_in_themes_are_complete_and_stable(self):
        payload = deck.theme_payload()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["default"], "adeck-classic")
        self.assertEqual(
            payload["order"], ["adeck-classic", "cyber", "terminal", "retro"]
        )
        self.assertEqual(
            [theme["id"] for theme in payload["themes"]], payload["order"]
        )
        self.assertEqual(
            list(payload["tftKeys"]),
            [
                "background",
                "text",
                "textMuted",
                "accent",
                "accentSecondary",
                "selected",
                "pressed",
            ],
        )

        token_sets = set()
        for theme in payload["themes"]:
            self.assertTrue(theme["name"])
            self.assertTrue(theme["short"])
            self.assertTrue(theme["description"])
            for mode in ("light", "dark"):
                palette = theme["web"][mode]
                token_sets.add(frozenset(palette))
                for token, value in palette.items():
                    self.assertTrue(token.startswith("--"), (theme["id"], token))
                    self.assertRegex(value, r"^#[0-9a-fA-F]{6}$")
            panel = theme["tft"]
            self.assertEqual(set(panel), set(payload["tftKeys"]))
            for value in panel.values():
                self.assertRegex(value, r"^#[0-9a-fA-F]{6}$")
        # one shape for every theme, so the picker never has to guess at a token
        self.assertEqual(len(token_sets), 1, token_sets)

    def test_classic_theme_matches_the_shipped_stylesheet(self):
        """The default theme and the shipped stylesheet must agree on tokens.

        The stylesheet keeps the original classic look - it is only what paints
        before the live theme vars land - so the two no longer share values. A
        token one side reads and the other never defines is still a bug though.
        """
        style = (deck.WEB_DIR / "style.css").read_text(encoding="utf-8")

        def block(selector):
            start = style.index(selector)
            body = style[style.index("{", start) + 1 : style.index("}", start)]
            found = {}
            for line in body.splitlines():
                line = line.strip()
                if not line.startswith("--") or ":" not in line:
                    continue
                name, value = line.split(":", 1)
                found[name.strip()] = value.strip().rstrip(";").strip()
            return found

        classic = deck.THEMES["adeck-classic"]["web"]
        blocks = {
            "light": block('[data-theme="light"] {'),
            "dark": block('[data-theme="dark"] {'),
        }
        # five of the tokens are only ever read by dark-scoped rules, so a light
        # palette holding them is expected - they just have to exist somewhere
        known = set(blocks["light"]) | set(blocks["dark"])
        for mode, shipped in blocks.items():
            colours = {t for t, v in shipped.items() if v.startswith("#")}
            self.assertTrue(colours, mode)
            # no colour the stylesheet paints with may be missing from the theme
            self.assertEqual(colours - set(classic[mode]), set(), mode)
            # and nothing sits in the palette that the stylesheet never reads
            self.assertEqual(set(classic[mode]) - known, set(), mode)

    def test_workspace_theme_falls_back_safely(self):
        config = sample_config()
        normalized = deck.normalize_config(config)
        # an old workspace has no theme of its own and picks up the default
        self.assertEqual(normalized["profiles"][0]["theme"], "adeck-classic")

        config["profiles"][0]["theme"] = "cyber"
        self.assertEqual(deck.normalize_config(config)["profiles"][0]["theme"], "cyber")

        # mixed case, padding and rubbish all land somewhere valid
        for raw, expected in (
            ("  CYBER ", "cyber"),
            ("terminal", "terminal"),
            ("retro", "retro"),
            ("neon-dreams", "adeck-classic"),
            ("", "adeck-classic"),
            (7, "adeck-classic"),
            (None, "adeck-classic"),
        ):
            config["profiles"][0]["theme"] = raw
            self.assertEqual(
                deck.normalize_config(config)["profiles"][0]["theme"], expected, raw
            )

        self.assertEqual(deck.theme_for("nope")["id"], "adeck-classic")
        self.assertEqual(deck.theme_for(None)["id"], "adeck-classic")

    def test_active_theme_follows_the_active_workspace(self):
        config = sample_config()
        buttons = [
            {"key": i + 1, "label": f"K{i}", "command": f"c{i}", "color": "#112233"}
            for i in range(6)
        ]
        config["profiles"] = [
            {"id": "a", "name": "Main", "theme": "cyber", "buttons": buttons},
            {"id": "b", "name": "Work", "theme": "terminal", "buttons": buttons},
        ]
        config["active_profile"] = "Main"
        normalized = deck.normalize_config(config)
        self.assertEqual(deck.active_theme_id(normalized), "cyber")
        normalized["active_profile"] = "Work"
        self.assertEqual(deck.active_theme_id(normalized), "terminal")
        # a config that cannot be read at all still answers with the default
        self.assertEqual(deck.active_theme_id(None), "adeck-classic")
        self.assertEqual(deck.active_theme_id({"profiles": []}), "adeck-classic")

    def test_theme_frame_shape_and_crc(self):
        frame = deck.theme_frame("cyber", "abc123").decode("ascii")
        lines = frame.splitlines()
        self.assertEqual(lines[0], "CFG_THEME_BEGIN\tabc123\t7")
        self.assertEqual(lines[-1][: len("CFG_THEME_END\tabc123\t")], "CFG_THEME_END\tabc123\t")
        self.assertTrue(frame.endswith("\n"))

        panel = deck.THEMES["cyber"]["tft"]
        for index, key in enumerate(deck.TFT_THEME_KEYS):
            self.assertIn(
                f"CFG_THEME_VALUE\tabc123\t{index}\t{panel[key].upper()}", lines
            )
        self.assertEqual(len(lines), 9)

        # the crc is over the same RGB triples in the same order the board sees
        values = deck.theme_values("cyber")
        self.assertEqual(values, [deck._hex_rgb_tuple(panel[key]) for key in deck.TFT_THEME_KEYS])
        expected = f"{deck.theme_crc(values):04X}"
        self.assertEqual(lines[-1], f"CFG_THEME_END\tabc123\t{expected}")

        # a different theme is a different frame, not the same one relabelled
        self.assertNotEqual(
            deck.theme_frame("cyber", "abc123"), deck.theme_frame("retro", "abc123")
        )

    def _theme_config(self):
        config = sample_config()
        config["profiles"][0]["buttons"][0]["kind"] = "app"
        config["profiles"][0]["buttons"][0]["command"] = "notepad.exe"
        config["profiles"][0]["theme"] = "cyber"
        return deck.normalize_config(config)

    def test_theme_reaches_a_board_that_announced_it(self):
        normalized = self._theme_config()
        device = self._icon_device("theme-on.json")
        connection = FakeSerial()
        device._connection = connection
        device._tft_icons = True
        device._tft_theme = True

        device._sync(normalized, "abc123")

        self.assertEqual(connection.writes[0], deck.config_frame(normalized, "abc123"))
        self.assertEqual(connection.writes[1], deck.theme_frame("cyber", "abc123"))
        # the theme lands before the icons, because the icons are blended
        # against the background it names
        self.assertTrue(connection.writes[2].startswith(b"CFG_ICON_BEGIN\tabc123\t0\t32\n"))
        self.assertEqual(device.status()["theme"], "cyber")
        self.assertTrue(device.status()["last_sync"])

        background = deck.theme_background("cyber")
        self.assertEqual(background, "#05070e")
        buttons = deck.active_buttons(normalized)
        expected = deck.app_icon_frames(buttons, "abc123", background)
        self.assertTrue(expected)
        # icons go down in chunks because the board only has a 256 byte receive
        # buffer, so the bytes are held end to end rather than write by write
        self.assertEqual(
            b"".join(frame for _, frame in expected), b"".join(connection.writes[2:])
        )

    def test_theme_is_left_alone_on_a_board_that_does_not_announce_it(self):
        """Older firmware keeps working: no theme frame, same icons as before."""
        normalized = self._theme_config()
        device = self._icon_device("theme-off.json")
        connection = FakeSerial()
        device._connection = connection
        device._tft_icons = True
        device._tft_theme = False

        device._sync(normalized, "abc123")

        self.assertEqual(connection.writes[0], deck.config_frame(normalized, "abc123"))
        joined = b"".join(connection.writes)
        self.assertNotIn(b"CFG_THEME", joined)
        self.assertIsNone(device.status()["theme"])
        # and the icons are the black-blended ones, exactly as they always were
        buttons = deck.active_buttons(normalized)
        expected = deck.app_icon_frames(buttons, "abc123", "#000000")
        self.assertEqual(
            b"".join(frame for _, frame in expected), b"".join(connection.writes[1:])
        )

    def test_a_rejected_theme_is_retried_and_never_takes_the_slots_down(self):
        normalized = self._theme_config()
        device = self._icon_device("theme-retry.json")
        connection = FakeSerial(theme_errors=1)
        device._connection = connection
        device._tft_icons = True
        device._tft_theme = True

        device._sync(normalized, "abc123")

        self.assertEqual(connection.theme_frames, 2)
        self.assertEqual(device.status()["theme"], "cyber")
        self.assertTrue(device.status()["last_sync"])

    def test_a_theme_that_never_lands_leaves_the_workspace_alone(self):
        normalized = self._theme_config()
        device = self._icon_device("theme-lost.json")
        connection = FakeSerial(theme_errors=deck._THEME_ATTEMPTS)
        device._connection = connection
        device._tft_icons = True
        device._tft_theme = True

        with self.assertLogs("adeck", level="WARNING") as captured:
            device._sync(normalized, "abc123")

        self.assertEqual(connection.theme_frames, deck._THEME_ATTEMPTS)
        self.assertTrue(
            any("was not accepted by the board" in line for line in captured.output),
            captured.output,
        )
        # the slots still went through: a refused theme is not a failed sync
        self.assertTrue(device.status()["last_sync"])
        self.assertIsNone(device.status()["theme"])

    def test_themes_endpoint_serves_the_registry(self):
        with tempfile.TemporaryDirectory() as temp:
            store = deck.ConfigStore(Path(temp) / "config.json")
            server = deck.BridgeServer(
                ("127.0.0.1", 0), deck.BridgeHandler, store, StubDevice(), "token"
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_address[1]}"
            try:
                with urllib.request.urlopen(base + "/api/themes") as response:
                    self.assertIn(
                        "application/json", response.headers.get("Content-Type", "")
                    )
                    payload = json.load(response)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["default"], "adeck-classic")
        self.assertEqual(len(payload["themes"]), 4)
        self.assertEqual(payload["themes"][1]["id"], "cyber")

    def test_firmware_parses_the_theme_transaction(self):
        firmware = (deck.BASE_DIR / "firmware" / "ADeck" / "ADeck.ino").read_text(encoding="utf-8")
        for token in (
            "CFG_THEME_BEGIN",
            "CFG_THEME_VALUE",
            "CFG_THEME_END",
            "CFG_THEME_OK",
            "CFG_THEME_ERR",
            "ADECK_CAPS\\tTHEME",
            "THEME_BACKGROUND",
            "THEME_TEXT",
            "THEME_SELECTED",
            "THEME_PRESSED",
            "ThemeConfig",
        ):
            self.assertIn(token, firmware, token)
        # the theme is carried in the persisted record, so a power cycle keeps it
        self.assertIn("uint16_t theme[THEME_COUNT];", firmware)
        self.assertIn("CONFIG_VERSION = 3", firmware)

    def test_web_theme_layer_is_wired_up(self):
        script = (deck.WEB_DIR / "script.js").read_text(encoding="utf-8")
        style = (deck.WEB_DIR / "style.css").read_text(encoding="utf-8")
        page = (deck.WEB_DIR / "index.html").read_text(encoding="utf-8")
        for token in (
            '"/api/themes"',
            "applyDeckTheme",
            "normalizeThemeId",
            "data-deck-theme",
            "themeId",
        ):
            self.assertIn(token, script, token)
        self.assertIn("themeModal", page)
        self.assertIn("themeBtn", page)
        self.assertIn(".theme-card", style)
        self.assertIn(".theme-tft", style)


if __name__ == "__main__":
    unittest.main()
