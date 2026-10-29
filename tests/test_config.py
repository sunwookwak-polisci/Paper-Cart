from pathlib import Path

import pytest

from paper_cart import cli, config
from paper_cart.db import init_db, list_journals, subscribe_journal
from paper_cart.web import create_app


def test_default_data_dir_on_macos(monkeypatch, tmp_path):
    monkeypatch.setattr(config.sys, "platform", "darwin")
    monkeypatch.setattr(config.Path, "home", lambda: tmp_path)
    assert config.default_data_dir() == tmp_path / "Library" / "Application Support" / "Paper Cart"


def test_default_data_dir_on_linux_follows_xdg(monkeypatch, tmp_path):
    monkeypatch.setattr(config.sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert config.default_data_dir() == tmp_path / "xdg" / "paper-cart"


def test_env_override_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("PAPER_CART_DATA", str(tmp_path / "elsewhere"))
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "library.sqlite").write_bytes(b"")
    assert config.data_dir_from_env() == tmp_path / "elsewhere"


def test_existing_checkout_library_is_kept(monkeypatch, tmp_path):
    monkeypatch.delenv("PAPER_CART_DATA", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "library.sqlite").write_bytes(b"")
    assert config.data_dir_from_env() == Path.cwd() / "data"


def test_without_a_checkout_library_the_user_folder_is_used(monkeypatch, tmp_path):
    monkeypatch.delenv("PAPER_CART_DATA", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "default_data_dir", lambda: tmp_path / "user")
    assert config.data_dir_from_env() == tmp_path / "user"


def test_cli_accepts_data_dir_and_no_browser(tmp_path):
    args = cli.parse_args(["--data-dir", str(tmp_path), "--no-browser"])
    assert args.data_dir == tmp_path
    assert args.no_browser


def _use_user_folder(monkeypatch, tmp_path):
    monkeypatch.delenv("PAPER_CART_DATA", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "default_data_dir", lambda: tmp_path / "user")


def test_saved_folder_is_used_on_the_next_launch(monkeypatch, tmp_path):
    _use_user_folder(monkeypatch, tmp_path)
    old = tmp_path / "old"
    chosen = tmp_path / "chosen"
    init_db(old / "library.sqlite")
    subscribe_journal(
        old / "library.sqlite",
        title="Kept Journal",
        issns=("1111-1111",),
        publisher="",
    )
    (old / "marker.txt").write_text("keep", encoding="utf-8")
    before = (old / "library.sqlite").read_bytes()

    saved = config.save_data_dir_preference(chosen)

    assert saved == chosen.resolve()
    assert config.data_dir_preference_path().read_text(encoding="utf-8") == f"{saved}\n"
    assert (old / "library.sqlite").read_bytes() == before
    assert (old / "marker.txt").read_text(encoding="utf-8") == "keep"
    assert not (chosen / "library.sqlite").exists()
    assert not (chosen / "marker.txt").exists()
    assert not (old / "data-dir").exists()
    folder, source = config.resolve_data_dir(None)
    assert folder == saved
    assert source == "saved"

    app = create_app(folder)
    assert list_journals(app.state.db_path) == []
    assert (chosen / "library.sqlite").is_file()
    assert (old / "library.sqlite").read_bytes() == before
    assert [journal.title for journal in list_journals(old / "library.sqlite")] == ["Kept Journal"]


def test_saved_folder_keeps_its_own_library(monkeypatch, tmp_path):
    _use_user_folder(monkeypatch, tmp_path)
    old = tmp_path / "old"
    chosen = tmp_path / "chosen"
    init_db(old / "library.sqlite")
    init_db(chosen / "library.sqlite")
    subscribe_journal(
        old / "library.sqlite",
        title="Kept Journal",
        issns=("1111-1111",),
        publisher="",
    )
    subscribe_journal(
        chosen / "library.sqlite",
        title="Other Journal",
        issns=("2222-2222",),
        publisher="",
    )
    before_old = (old / "library.sqlite").read_bytes()
    before_chosen = (chosen / "library.sqlite").read_bytes()

    config.save_data_dir_preference(chosen)

    assert (old / "library.sqlite").read_bytes() == before_old
    assert (chosen / "library.sqlite").read_bytes() == before_chosen
    app = create_app(config.data_dir_from_env())
    assert [journal.title for journal in list_journals(app.state.db_path)] == ["Other Journal"]
    assert (old / "library.sqlite").read_bytes() == before_old


def test_env_checkout_and_flag_win_over_the_saved_folder(monkeypatch, tmp_path):
    _use_user_folder(monkeypatch, tmp_path)
    chosen = tmp_path / "chosen"
    config.save_data_dir_preference(chosen)

    monkeypatch.setenv("PAPER_CART_DATA", str(tmp_path / "from-env"))
    assert config.resolve_data_dir(None) == (tmp_path / "from-env", "env")
    monkeypatch.delenv("PAPER_CART_DATA", raising=False)

    checkout = tmp_path / "repo"
    (checkout / "data").mkdir(parents=True)
    (checkout / "data" / "library.sqlite").write_bytes(b"keep")
    monkeypatch.chdir(checkout)
    assert config.resolve_data_dir(None) == (checkout / "data", "checkout")

    flagged = tmp_path / "flagged"
    assert config.resolve_data_dir(flagged) == (flagged, "flag")


def test_unusable_saved_folder_falls_back_to_the_user_folder(monkeypatch, tmp_path):
    _use_user_folder(monkeypatch, tmp_path)
    preference = config.data_dir_preference_path()
    preference.parent.mkdir(parents=True)
    preference.write_text("relative/folder\n", encoding="utf-8")
    assert config.data_dir_from_env() == tmp_path / "user"

    blocked = tmp_path / "not-a-folder"
    blocked.write_text("x", encoding="utf-8")
    preference.write_text(f"{blocked}\n", encoding="utf-8")
    assert config.data_dir_from_env() == tmp_path / "user"


def test_save_rejects_a_file_and_a_relative_path(monkeypatch, tmp_path):
    _use_user_folder(monkeypatch, tmp_path)
    blocked = tmp_path / "not-a-folder"
    blocked.write_text("leave", encoding="utf-8")
    with pytest.raises(config.ConfigError, match="Choose a folder"):
        config.save_data_dir_preference(blocked)
    with pytest.raises(config.ConfigError, match="full folder path"):
        config.save_data_dir_preference(Path("relative/folder"))
    with pytest.raises(config.ConfigError, match="Enter a folder path"):
        config.save_data_dir_preference("  ")
    assert not config.data_dir_preference_path().exists()
    assert blocked.read_text(encoding="utf-8") == "leave"
