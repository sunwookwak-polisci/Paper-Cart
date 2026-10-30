import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from paper_cart import cli

ROOT = Path(__file__).resolve().parents[1]

# The `paper-cart` entry point on a port the test picks, so a Paper Cart already
# open on 8000 cannot answer in its place.
LAUNCH = (
    "import sys\n"
    "from paper_cart import cli\n"
    "port = int(sys.argv[1])\n"
    "cli.choose_port = lambda: (port, False)\n"
    "sys.exit(cli.main(sys.argv[2:]))\n"
)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((cli.HOST, 0))
        return probe.getsockname()[1]


def launch(tmp_path: Path, port: int) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-c", LAUNCH, str(port), "--no-browser", "--data-dir", str(tmp_path)],
        cwd=ROOT,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def wait_until_serving(process: subprocess.Popen, port: int) -> None:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if process.poll() is not None:
            out, err = process.communicate()
            pytest.fail(f"paper-cart exited before serving:\n{out}{err}")
        try:
            if httpx.get(f"http://{cli.HOST}:{port}/healthz", timeout=1.0, trust_env=False).is_success:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.1)
    pytest.fail("paper-cart did not start serving")


@pytest.fixture
def paper_cart(tmp_path):
    port = free_port()
    process = launch(tmp_path, port)
    try:
        wait_until_serving(process, port)
        yield process, port
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate()


def test_choose_port_reuses_a_running_app(monkeypatch):
    monkeypatch.setattr(cli, "running_instance", lambda port, host=cli.HOST: port == 8001)
    monkeypatch.setattr(cli, "port_is_free", lambda port, host=cli.HOST: port == 8002)
    assert cli.choose_port(8000) == (8001, True)


def test_choose_port_skips_ports_in_use(monkeypatch):
    monkeypatch.setattr(cli, "running_instance", lambda port, host=cli.HOST: False)
    monkeypatch.setattr(cli, "port_is_free", lambda port, host=cli.HOST: port >= 8002)
    assert cli.choose_port(8000) == (8002, False)


def test_choose_port_gives_up(monkeypatch):
    monkeypatch.setattr(cli, "running_instance", lambda port, host=cli.HOST: False)
    monkeypatch.setattr(cli, "port_is_free", lambda port, host=cli.HOST: False)
    with pytest.raises(SystemExit):
        cli.choose_port(8000, tries=3)


def test_server_stays_on_localhost():
    assert cli.HOST == "127.0.0.1"


def test_port_is_free_sees_a_bound_socket():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as holder:
        holder.bind((cli.HOST, 0))
        holder.listen()
        port = holder.getsockname()[1]
        assert not cli.port_is_free(port)
        assert not cli.running_instance(port)


@pytest.mark.parametrize("presses", [1, 2])
def test_ctrl_c_stops_without_a_traceback(paper_cart, presses):
    process, _ = paper_cart
    for _ in range(presses):
        process.send_signal(signal.SIGINT)
        time.sleep(0.05)
    out, err = process.communicate(timeout=20)
    assert "Traceback" not in err
    assert "ERROR" not in err
    assert "Paper Cart has stopped." in out
    assert process.returncode == 130


def test_quit_stops_with_exit_code_zero(paper_cart):
    process, port = paper_cart
    assert httpx.post(f"http://{cli.HOST}:{port}/quit", trust_env=False).status_code == 200
    out, err = process.communicate(timeout=20)
    assert "Traceback" not in err
    assert "Paper Cart has stopped." in out
    assert process.returncode == 0


def test_a_busy_port_still_reports_the_error(tmp_path):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as holder:
        holder.bind((cli.HOST, 0))
        holder.listen()
        process = launch(tmp_path, holder.getsockname()[1])
        try:
            out, err = process.communicate(timeout=20)
        finally:
            process.kill()
    assert "address already in use" in err.lower()
    assert "Paper Cart has stopped." not in out
    assert process.returncode != 0
