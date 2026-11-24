"""System tests for `scripts/start.sh` and `scripts/stop.sh` lifecycle and guards (TC-040)."""

from __future__ import annotations

import http.client
import json
import os
import signal
import socket
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
START_SH = ROOT / "scripts" / "start.sh"
STOP_SH = ROOT / "scripts" / "stop.sh"


def _free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
    finally:
        sock.close()


def _is_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@pytest.mark.loopback
def test_tc040_start_stop_lifecycle_and_guards(tmp_path: Path) -> None:
    pid_file = tmp_path / "casper.pid"
    log_file = tmp_path / "casper.log"
    other_pid_file = tmp_path / "other.pid"
    port = _free_port()

    env = {
        **os.environ,
        "CASPER_PID_FILE": str(pid_file),
        "CASPER_LOG_FILE": str(log_file),
    }

    server_pid: int | None = None
    try:
        start_res = subprocess.run(
            ["bash", str(START_SH), "--background", "--no-install", "--port", str(port)],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert start_res.returncode == 0, start_res.stderr
        assert pid_file.is_file()
        server_pid = int(pid_file.read_text(encoding="utf-8").strip())
        assert _is_pid_alive(server_pid)

        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            conn.request("GET", "/api/options")
            resp = conn.getresponse()
            body = resp.read().decode("utf-8")
            assert resp.status == 200
            payload = json.loads(body)
            assert isinstance(payload, dict)
            assert {"personas", "structures", "modalities"} <= set(payload)
        finally:
            conn.close()

        double_res = subprocess.run(
            ["bash", str(START_SH), "--background", "--no-install", "--port", str(port)],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert double_res.returncode == 1
        assert double_res.stderr.strip()

        busy_env = {**env, "CASPER_PID_FILE": str(other_pid_file)}
        busy_res = subprocess.run(
            ["bash", str(START_SH), "--background", "--no-install", "--port", str(port)],
            cwd=str(ROOT),
            env=busy_env,
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert busy_res.returncode == 1
        assert "already in use" in busy_res.stderr.lower()

        stop_res = subprocess.run(
            ["bash", str(STOP_SH)],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert stop_res.returncode == 0, stop_res.stderr
        assert not pid_file.exists()
        assert not _is_pid_alive(server_pid)
        server_pid = None

        stop_again_res = subprocess.run(
            ["bash", str(STOP_SH)],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert stop_again_res.returncode == 0, stop_again_res.stderr
    finally:
        if pid_file.exists():
            subprocess.run(
                ["bash", str(STOP_SH)],
                cwd=str(ROOT),
                env=env,
                capture_output=True,
                text=True,
                timeout=15,
            )
        if server_pid is not None and _is_pid_alive(server_pid):
            os.kill(server_pid, signal.SIGTERM)


def test_tc040_stop_refuses_non_casper_pid(tmp_path: Path) -> None:
    pid_file = tmp_path / "non_casper.pid"
    env = {**os.environ, "CASPER_PID_FILE": str(pid_file)}

    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        pid_file.write_text(f"{proc.pid}\n", encoding="utf-8")
        res = subprocess.run(
            ["bash", str(STOP_SH)],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert res.returncode == 1
        assert proc.poll() is None
    finally:
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=5)
