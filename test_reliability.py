import json
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

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
    def __init__(self):
        self.writes = []
        self.replies = []
        self.closed = False

    def write(self, payload):
        self.writes.append(payload)
        txid = payload.split(b"\n", 1)[0].decode("ascii").split("\t")[1]
        self.replies.append(f"CFG_OK\t{txid}\n".encode("ascii"))

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

    def status(self):
        return {
            "connected": False,
            "port": None,
            "firmware": None,
            "last_sync": None,
            "last_transaction_id": None,
            "error": None,
        }

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


if __name__ == "__main__":
    unittest.main()
