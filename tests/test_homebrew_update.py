import json
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from paper_cart import cli, homebrew

NOTICE = "Paper Cart 0.1.1 is available. Run brew upgrade paper-cart."


@pytest.fixture(autouse=True)
def no_release_lookup(monkeypatch, tmp_path):
    """Keep tests off the network and out of the real per-user folder."""
    monkeypatch.setattr(homebrew, "default_data_dir", lambda: tmp_path / "user-data")

    def fail(*args, **kwargs):
        raise AssertionError("GitHub should not be asked unless a test fakes it")

    monkeypatch.setattr(homebrew.httpx, "get", fail)


def _fake_release(monkeypatch, tag: str | None = "v0.1.1", status: int = 200) -> list:
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        body = {"tag_name": tag} if tag is not None else {}
        return httpx.Response(status, json=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(homebrew.httpx, "get", get)
    return calls


def _formula(version: str, *, url_only: bool = False) -> str:
    url = (
        "  url "
        f'"https://github.com/sunwookwak-polisci/Paper-Cart/releases/download/v{version}/'
        f'paper_cart-{version}-py3-none-any.whl", using: :nounzip\n'
    )
    if url_only:
        return f"class PaperCart < Formula\n{url}end\n"
    return f'class PaperCart < Formula\n{url}  version "{version}"\nend\n'


def _cellar(tmp_path: Path, version: str = "0.1.0") -> Path:
    libexec = tmp_path / "opt" / "homebrew" / "Cellar" / "paper-cart" / version / "libexec"
    libexec.mkdir(parents=True)
    return libexec


def _prefix(libexec: Path) -> Path:
    return libexec.parents[3]


def _write_formula(libexec: Path, version: str, *, url_only: bool = False, shard: bool = False) -> Path:
    formula = _prefix(libexec) / "Library" / "Taps" / "sunwookwak-polisci" / "homebrew-paper-cart"
    if shard:
        path = formula / "Formula" / "p" / "paper-cart.rb"
    else:
        path = formula / "Formula" / "paper-cart.rb"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_formula(version, url_only=url_only), encoding="utf-8")
    return path


def _receipt(libexec: Path, formula: Path, tap: str = "sunwookwak-polisci/paper-cart") -> None:
    receipt = libexec.parent / "INSTALL_RECEIPT.json"
    receipt.write_text(
        json.dumps({"source": {"path": str(formula), "tap": tap}}),
        encoding="utf-8",
    )


def _forbid_brew(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args, **kwargs):
        raise AssertionError(f"brew should not run: {args!r} {kwargs!r}")

    monkeypatch.setattr(homebrew.subprocess, "run", fail)


def test_checkout_and_uv_installs_stay_quiet(monkeypatch, tmp_path, capsys):
    _forbid_brew(monkeypatch)
    homebrew.announce_homebrew_update()
    homebrew.announce_homebrew_update(tmp_path / ".local" / "share" / "uv" / "tools" / "paper-cart")
    checkout = tmp_path / "Paper-Cart" / ".venv" / "bin" / "paper-cart"
    checkout.parent.mkdir(parents=True)
    homebrew.announce_homebrew_update(checkout)
    python = tmp_path / "opt" / "homebrew" / "Cellar" / "python@3.13" / "3.13.1" / "bin" / "python"
    python.parent.mkdir(parents=True)
    homebrew.announce_homebrew_update(python)
    assert capsys.readouterr().out == ""


def test_tap_formula_prints_one_line_when_newer(monkeypatch, tmp_path, capsys):
    _forbid_brew(monkeypatch)
    monkeypatch.setattr(homebrew, "__version__", "0.1.0")
    libexec = _cellar(tmp_path)
    formula = _write_formula(libexec, "0.1.1")
    _receipt(libexec, formula)
    homebrew.announce_homebrew_update(libexec)
    assert capsys.readouterr().out == NOTICE + "\n"


def test_same_or_older_formula_prints_nothing(monkeypatch, tmp_path, capsys):
    _forbid_brew(monkeypatch)
    _fake_release(monkeypatch, "v0.1.0")
    monkeypatch.setattr(homebrew, "__version__", "0.1.0")
    libexec = _cellar(tmp_path)
    formula = _write_formula(libexec, "0.1.0")
    _receipt(libexec, formula)
    homebrew.announce_homebrew_update(libexec)
    formula.write_text(_formula("0.0.9"), encoding="utf-8")
    homebrew.announce_homebrew_update(libexec)
    assert capsys.readouterr().out == ""


def test_version_order_handles_double_digits_and_revisions(monkeypatch, tmp_path, capsys):
    _forbid_brew(monkeypatch)
    monkeypatch.setattr(homebrew, "__version__", "0.1.9")
    libexec = _cellar(tmp_path, "0.1.9")
    formula = _write_formula(libexec, "0.1.10")
    _receipt(libexec, formula)
    homebrew.announce_homebrew_update(libexec)
    _fake_release(monkeypatch, "v0.1.0")
    formula.write_text(_formula("0.1.0_1"), encoding="utf-8")
    monkeypatch.setattr(homebrew, "__version__", "0.1.0")
    homebrew.announce_homebrew_update(libexec)
    text = capsys.readouterr().out.splitlines()
    assert text == [
        "Paper Cart 0.1.10 is available. Run brew upgrade paper-cart.",
        "Paper Cart 0.1.0_1 is available. Run brew upgrade paper-cart.",
    ]


def test_url_only_and_sharded_formulae(monkeypatch, tmp_path, capsys):
    _forbid_brew(monkeypatch)
    monkeypatch.setattr(homebrew, "__version__", "0.1.0")
    libexec = _cellar(tmp_path)
    formula = _write_formula(libexec, "0.1.1", url_only=True, shard=True)
    _receipt(libexec, formula)
    homebrew.announce_homebrew_update(libexec)
    assert capsys.readouterr().out == NOTICE + "\n"


def test_receipt_path_outside_the_tap_is_ignored(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(homebrew, "__version__", "0.1.0")
    libexec = _cellar(tmp_path)
    keg_copy = libexec.parent / ".brew" / "paper-cart.rb"
    keg_copy.parent.mkdir()
    keg_copy.write_text(_formula("0.1.0"), encoding="utf-8")
    _receipt(libexec, keg_copy, tap="")
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        payload = {
            "formulae": [
                {
                    "name": "sunwookwak-polisci/paper-cart/paper-cart",
                    "installed_versions": ["0.1.0"],
                    "current_version": "0.1.1",
                    "pinned": False,
                    "pinned_version": None,
                }
            ],
            "casks": [],
        }
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload))

    monkeypatch.setattr(homebrew.subprocess, "run", fake_run)
    homebrew.announce_homebrew_update(libexec)
    assert capsys.readouterr().out == NOTICE + "\n"
    command, kwargs = calls[0]
    assert command == ["brew", "outdated", "--formula", "--json=v2", "paper-cart"]
    assert kwargs["timeout"] == homebrew.BREW_TIMEOUT_SECONDS
    assert kwargs["timeout"] <= 3
    assert kwargs["env"]["HOMEBREW_NO_AUTO_UPDATE"] == "1"
    assert kwargs["env"]["HOMEBREW_NO_INSTALL_FROM_API"] == "1"
    assert kwargs["env"]["HOMEBREW_NO_ANALYTICS"] == "1"
    assert kwargs["stdin"] is subprocess.DEVNULL


def test_known_tap_answers_without_a_receipt(monkeypatch, tmp_path, capsys):
    _forbid_brew(monkeypatch)
    monkeypatch.setattr(homebrew, "__version__", "0.1.0")
    libexec = _cellar(tmp_path)
    _write_formula(libexec, "0.1.1")
    homebrew.announce_homebrew_update(libexec)
    assert capsys.readouterr().out == NOTICE + "\n"


def test_brew_failure_and_current_version_print_nothing(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(homebrew, "__version__", "0.1.0")
    _fake_release(monkeypatch, "v0.1.0")
    libexec = _cellar(tmp_path)

    def timeout(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs.get("timeout", 2))

    monkeypatch.setattr(homebrew.subprocess, "run", timeout)
    homebrew.announce_homebrew_update(libexec)

    def missing(command, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(homebrew.subprocess, "run", missing)
    homebrew.announce_homebrew_update(libexec)

    def failed(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="error")

    monkeypatch.setattr(homebrew.subprocess, "run", failed)
    homebrew.announce_homebrew_update(libexec)

    def current(command, **kwargs):
        payload = {"formulae": [], "casks": []}
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload))

    monkeypatch.setattr(homebrew.subprocess, "run", current)
    homebrew.announce_homebrew_update(libexec)

    def text(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout="paper-cart (0.1.0) < 0.1.0\n")

    monkeypatch.setattr(homebrew.subprocess, "run", text)
    homebrew.announce_homebrew_update(libexec)
    assert capsys.readouterr().out == ""


def test_brew_text_reports_a_newer_version(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(homebrew, "__version__", "0.1.0")
    libexec = _cellar(tmp_path)

    def text(command, **kwargs):
        return subprocess.CompletedProcess(
            command, 0, stdout="sunwookwak-polisci/paper-cart/paper-cart (0.1.0) < 0.1.1\n"
        )

    monkeypatch.setattr(homebrew.subprocess, "run", text)
    homebrew.announce_homebrew_update(libexec)
    assert capsys.readouterr().out == NOTICE + "\n"


def test_unreadable_formula_does_not_stop_startup(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(homebrew, "__version__", "0.1.0")
    libexec = _cellar(tmp_path)
    formula = _write_formula(libexec, '0.1.1\nrm -rf /')
    _receipt(libexec, formula)

    def text(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout="paper-cart (0.1.0) < 0.1.1\n")

    monkeypatch.setattr(homebrew.subprocess, "run", text)
    homebrew.announce_homebrew_update(libexec)
    assert capsys.readouterr().out == NOTICE + "\n"


def test_announce_swallows_unexpected_errors(monkeypatch, capsys):
    def boom(install_path=None):
        raise RuntimeError("checker failed")

    monkeypatch.setattr(homebrew, "newer_homebrew_version", boom)
    homebrew.announce_homebrew_update()
    assert capsys.readouterr().out == ""


def test_newer_release_is_announced_before_the_tap_is_updated(monkeypatch, tmp_path, capsys):
    _forbid_brew(monkeypatch)
    monkeypatch.setattr(homebrew, "__version__", "0.1.0")
    libexec = _cellar(tmp_path)
    formula = _write_formula(libexec, "0.1.0")
    _receipt(libexec, formula)
    calls = _fake_release(monkeypatch, "v0.1.1")
    homebrew.announce_homebrew_update(libexec)
    assert capsys.readouterr().out == NOTICE + "\n"
    url, kwargs = calls[0]
    assert url == "https://api.github.com/repos/sunwookwak-polisci/Paper-Cart/releases/latest"
    assert kwargs["timeout"] <= 3


def test_release_is_asked_for_at_most_once_a_day(monkeypatch, tmp_path, capsys):
    _forbid_brew(monkeypatch)
    monkeypatch.setattr(homebrew, "__version__", "0.1.0")
    libexec = _cellar(tmp_path)
    _receipt(libexec, _write_formula(libexec, "0.1.0"))
    calls = _fake_release(monkeypatch, "v0.1.1")
    homebrew.announce_homebrew_update(libexec)
    homebrew.announce_homebrew_update(libexec)
    assert len(calls) == 1
    assert capsys.readouterr().out == (NOTICE + "\n") * 2

    saved = tmp_path / "user-data" / homebrew.RELEASE_CHECK_FILE
    saved.write_text(json.dumps({"checked": time.time() - 25 * 60 * 60, "version": "0.1.1"}))
    _fake_release(monkeypatch, "v0.1.2")
    assert homebrew.newer_homebrew_version(libexec) == "0.1.2"


def test_a_failed_release_lookup_is_quiet_and_not_retried_that_day(monkeypatch, tmp_path, capsys):
    _forbid_brew(monkeypatch)
    monkeypatch.setattr(homebrew, "__version__", "0.1.0")
    libexec = _cellar(tmp_path)
    _receipt(libexec, _write_formula(libexec, "0.1.0"))
    calls = []

    def offline(url, **kwargs):
        calls.append(url)
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(homebrew.httpx, "get", offline)
    homebrew.announce_homebrew_update(libexec)
    homebrew.announce_homebrew_update(libexec)
    assert len(calls) == 1
    for tag, status in (("v0.1.1", 404), (None, 200), ("v0.1.1\nrm -rf /", 200)):
        (tmp_path / "user-data" / homebrew.RELEASE_CHECK_FILE).unlink()
        _fake_release(monkeypatch, tag, status)
        homebrew.announce_homebrew_update(libexec)
    assert capsys.readouterr().out == ""


def test_newer_tap_formula_skips_the_release_lookup(monkeypatch, tmp_path, capsys):
    _forbid_brew(monkeypatch)
    monkeypatch.setattr(homebrew, "__version__", "0.1.0")
    libexec = _cellar(tmp_path)
    _receipt(libexec, _write_formula(libexec, "0.1.1"))
    homebrew.announce_homebrew_update(libexec)
    assert capsys.readouterr().out == NOTICE + "\n"
    assert not (tmp_path / "user-data" / homebrew.RELEASE_CHECK_FILE).exists()


def test_main_prints_the_notice_then_starts_on_localhost(monkeypatch, capsys, tmp_path):
    app = SimpleNamespace(state=SimpleNamespace(db_path=tmp_path / "library.sqlite"))
    monkeypatch.setattr(cli, "announce_homebrew_update", lambda: print(NOTICE))
    monkeypatch.setattr(cli, "choose_port", lambda: (8000, False))
    monkeypatch.setattr(cli, "resolve_data_dir", lambda override: (tmp_path, "flag"))
    monkeypatch.setattr(cli, "create_app", lambda data_dir: app)
    monkeypatch.setattr(cli, "start_startup_refresh", lambda application: None)

    class FakeServer:
        def __init__(self, config):
            assert config.host == "127.0.0.1"
            assert config.port == 8000

        def run(self):
            return None

    monkeypatch.setattr(cli, "QuietServer", FakeServer)
    cli.main(["--no-browser"])
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == NOTICE
    assert "Paper Cart is at http://127.0.0.1:8000" in lines
    assert cli.HOST == "127.0.0.1"


def test_main_still_notifies_when_the_app_is_already_open(monkeypatch, capsys):
    monkeypatch.setattr(cli, "announce_homebrew_update", lambda: print(NOTICE))
    monkeypatch.setattr(cli, "choose_port", lambda: (8000, True))
    cli.main(["--no-browser"])
    lines = capsys.readouterr().out.splitlines()
    assert lines == [NOTICE, "Paper Cart is already open at http://127.0.0.1:8000"]
