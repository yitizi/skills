from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
QUERY_SCRIPT = SKILL_DIR / "scripts" / "tc-query.ps1"
CREDENTIAL_SCRIPT = SKILL_DIR / "scripts" / "tc-credential.ps1"
PS_SCRIPTS = (
    QUERY_SCRIPT,
    CREDENTIAL_SCRIPT,
    SKILL_DIR / "scripts" / "tc-doctor.ps1",
    SKILL_DIR / "scripts" / "deliverable" / "import.ps1",
)


def powershell_engines() -> list[str]:
    names = ("powershell.exe", "pwsh.exe", "pwsh")
    found: list[str] = []
    for name in names:
        path = shutil.which(name)
        if path and path.lower() not in {item.lower() for item in found}:
            found.append(path)
    return found


class Handler(BaseHTTPRequestHandler):
    expected_auth = "Basic " + base64.b64encode("测试用户:密码".encode()).decode()

    def _write_json(self, value: dict) -> None:
        encoded = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/httpAuth/app/rest/projects?"):
            self._write_json(
                {
                    "project": [
                        {"id": "HenanAccounting", "name": "河南会计", "description": "生产项目"}
                    ]
                }
            )
            return
        self._write_json(
            {
                "message": "中文响应-河南-🚀",
                "version": "2020.1.5",
                "path": self.path,
                "authOk": self.headers.get("Authorization") == self.expected_auth,
            }
        )

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        self._write_json(
            {
                "received": json.loads(body),
                "authOk": self.headers.get("Authorization") == self.expected_auth,
            }
        )

    def log_message(self, *_args) -> None:
        return


class ProxyHandler(BaseHTTPRequestHandler):
    expected_auth = Handler.expected_auth

    def do_GET(self) -> None:  # noqa: N802
        encoded = json.dumps(
            {
                "viaProxy": True,
                "target": self.path,
                "authOk": self.headers.get("Authorization") == self.expected_auth,
                "message": "代理中文响应",
            },
            ensure_ascii=False,
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, *_args) -> None:
        return


class TeamCityWindowsUtf8Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.server_url = f"http://127.0.0.1:{cls.server.server_port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.proxy_server = ThreadingHTTPServer(("127.0.0.1", 0), ProxyHandler)
        cls.proxy_url = f"http://127.0.0.1:{cls.proxy_server.server_port}"
        cls.proxy_thread = threading.Thread(target=cls.proxy_server.serve_forever, daemon=True)
        cls.proxy_thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        cls.proxy_server.shutdown()
        cls.proxy_server.server_close()
        cls.proxy_thread.join(timeout=5)

    def _run_query(self, engine: str, *args: str) -> subprocess.CompletedProcess[bytes]:
        cmd = [
            engine,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(QUERY_SCRIPT),
            "-TcUrl",
            self.server_url,
            "-Username",
            "测试用户",
            "-Password",
            "密码",
            *args,
        ]
        return subprocess.run(cmd, capture_output=True, check=False)

    def test_powershell_sources_are_utf8_with_bom(self) -> None:
        for path in PS_SCRIPTS:
            data = path.read_bytes()
            self.assertTrue(data.startswith(b"\xef\xbb\xbf"), path)
            data[3:].decode("utf-8", errors="strict")

    def test_get_and_post_round_trip_in_each_engine(self) -> None:
        engines = powershell_engines()
        self.assertTrue(engines, "PowerShell was not found")

        for engine in engines:
            with self.subTest(engine=engine), tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                get_file = tmp_path / "response.json"
                result = self._run_query(
                    engine,
                    "-Path",
                    "server",
                    "-OutFile",
                    str(get_file),
                )
                self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
                response = json.loads(get_file.read_text(encoding="utf-8"))
                self.assertEqual(response["message"], "中文响应-河南-🚀")
                self.assertTrue(response["authOk"])

                payload_file = tmp_path / "payload.json"
                payload_file.write_text(
                    json.dumps({"branchName": "refs/heads/功能分支", "region": "华东"}, ensure_ascii=False),
                    encoding="utf-8",
                )
                post_file = tmp_path / "post-response.json"
                result = self._run_query(
                    engine,
                    "-Path",
                    "buildQueue",
                    "-Method",
                    "POST",
                    "-BodyFile",
                    str(payload_file),
                    "-OutFile",
                    str(post_file),
                )
                self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
                response = json.loads(post_file.read_text(encoding="utf-8"))
                self.assertEqual(response["received"]["branchName"], "refs/heads/功能分支")
                self.assertEqual(response["received"]["region"], "华东")
                self.assertTrue(response["authOk"])

    def test_stdout_is_raw_utf8(self) -> None:
        engine = powershell_engines()[0]
        result = self._run_query(engine, "-Path", "server")
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        response = json.loads(result.stdout.decode("utf-8-sig"))
        self.assertEqual(response["message"], "中文响应-河南-🚀")

    def test_explicit_proxy_is_scoped_to_tc_query(self) -> None:
        for engine in powershell_engines():
            with self.subTest(engine=engine), tempfile.TemporaryDirectory() as tmp:
                response_file = Path(tmp) / "proxy-response.json"
                result = subprocess.run(
                    [
                        engine,
                        "-NoProfile",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-File",
                        str(QUERY_SCRIPT),
                        "-TcUrl",
                        "http://teamcity.invalid:8111",
                        "-Username",
                        "测试用户",
                        "-Password",
                        "密码",
                        "-Proxy",
                        self.proxy_url,
                        "-Path",
                        "server",
                        "-OutFile",
                        str(response_file),
                    ],
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
                response = json.loads(response_file.read_text(encoding="utf-8"))
                self.assertTrue(response["viaProxy"])
                self.assertTrue(response["authOk"])
                self.assertEqual(response["message"], "代理中文响应")

    def test_credential_check_reads_utf8_config(self) -> None:
        engine = powershell_engines()[0]
        with tempfile.TemporaryDirectory() as profile:
            config_dir = Path(profile) / ".claude" / "skill-config" / "teamcity"
            config_dir.mkdir(parents=True)
            (config_dir / "config.env").write_text(
                "TC_URL=http://teamcity.example.test\nTC_USER=测试用户",
                encoding="utf-8",
            )
            (Path(profile) / ".netrc").write_text(
                "machine teamcity.example.test login 测试用户 password 密码",
                encoding="utf-8",
            )
            env = os.environ.copy()
            env["USERPROFILE"] = profile
            result = subprocess.run(
                [
                    engine,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(CREDENTIAL_SCRIPT),
                    "-Action",
                    "check",
                ],
                capture_output=True,
                env=env,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
            self.assertIn("CONFIGURED|http://teamcity.example.test", result.stdout.decode("utf-8-sig"))

    def test_python_search_helper_uses_file_based_powershell_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as profile:
            config_dir = Path(profile) / ".claude" / "skill-config" / "teamcity"
            config_dir.mkdir(parents=True)
            (config_dir / "config.env").write_text(
                f"TC_URL={self.server_url}\nTC_USER=测试用户",
                encoding="utf-8",
            )
            (Path(profile) / ".netrc").write_text(
                "machine 127.0.0.1 login 测试用户 password 密码",
                encoding="utf-8",
            )
            env = os.environ.copy()
            env["USERPROFILE"] = profile
            result = subprocess.run(
                [
                    sys.executable,
                    str(SKILL_DIR / "scripts" / "tc-search.py"),
                    "projects",
                    "河南",
                ],
                capture_output=True,
                env=env,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
            output = result.stdout.decode("utf-8")
            self.assertIn("河南会计", output)
            self.assertIn("HenanAccounting", output)

    def test_online_doctor_parses_utf8_server_response(self) -> None:
        engine = powershell_engines()[0]
        with tempfile.TemporaryDirectory() as profile:
            config_dir = Path(profile) / ".claude" / "skill-config" / "teamcity"
            config_dir.mkdir(parents=True)
            (config_dir / "config.env").write_text(
                f"TC_URL={self.server_url}\nTC_USER=测试用户",
                encoding="utf-8",
            )
            (Path(profile) / ".netrc").write_text(
                "machine 127.0.0.1 login 测试用户 password 密码",
                encoding="utf-8",
            )
            env = os.environ.copy()
            env["USERPROFILE"] = profile
            result = subprocess.run(
                [
                    engine,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(SKILL_DIR / "scripts" / "tc-doctor.ps1"),
                    "-Online",
                ],
                capture_output=True,
                env=env,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
            output = result.stdout.decode("utf-8-sig")
            self.assertIn("Online query passed; TeamCity version 2020.1.5.", output)
            self.assertIn("SUMMARY|failures=0", output)

    def test_packaged_import_is_ps51_safe_and_dry_run_needs_no_password(self) -> None:
        engine = powershell_engines()[0]
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            export_file = tmp_path / "template.json"
            export_file.write_text(
                json.dumps(
                    {
                        "meta": {
                            "id": "模板_Test",
                            "name": "中文模板",
                            "version": 7,
                            "exportedAt": "2026-08-29T00:00:00",
                            "type": "template",
                        },
                        "parameters": {"property": [{"name": "region", "value": "华东"}]},
                        "steps": {"step": []},
                        "features": {"feature": []},
                        "triggers": {"trigger": []},
                        "settings": {"property": []},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            output_root = tmp_path / "artifact"
            result = subprocess.run(
                [
                    sys.executable,
                    str(SKILL_DIR / "scripts" / "tc-package.py"),
                    str(export_file),
                    "-o",
                    str(output_root),
                ],
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
            package_dir = next(output_root.iterdir())
            import_script = package_dir / "import.ps1"
            self.assertTrue(import_script.read_bytes().startswith(b"\xef\xbb\xbf"))

            result = subprocess.run(
                [
                    engine,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(import_script),
                    "-TcUrl",
                    "http://teamcity.invalid",
                    "-Username",
                    "测试用户",
                    "-TargetId",
                    "目标模板",
                    "-DryRun",
                ],
                cwd=package_dir,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
            output = result.stdout.decode("utf-8-sig")
            self.assertIn("中文模板", output)
            self.assertIn("DRY RUN: no changes made.", output)


if __name__ == "__main__":
    unittest.main()
