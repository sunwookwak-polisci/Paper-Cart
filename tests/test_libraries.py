import sqlite3
from pathlib import Path

import pytest

from paper_cart.config import ConfigError
from paper_cart.db import LibraryUnavailable, connect, get_setting, init_db, set_setting
from paper_cart.libraries import (
    install_library_file,
    list_library_names,
    normalize_library_name,
    read_active_name,
    recover_library_backups,
    rename_library_file,
    validate_library_file,
    write_active_name,
)


def _library(folder: Path, name: str, shelf: str) -> Path:
    path = folder / name
    init_db(path)
    set_setting(path, "shelf", shelf)
    return path


def test_normalize_library_name_rejects_empty_and_paths():
    assert normalize_library_name("notes") == "notes.sqlite"
    assert normalize_library_name("notes.sqlite") == "notes.sqlite"
    assert normalize_library_name("My notes") == "My notes.sqlite"
    for raw in ("", "   ", ".", "..", ".sqlite", "../library.sqlite", "a/b.sqlite", "a\\b.sqlite"):
        with pytest.raises(ConfigError):
            normalize_library_name(raw)


def test_connect_does_not_create_a_missing_file(tmp_path):
    missing = tmp_path / "missing.sqlite"
    with pytest.raises(LibraryUnavailable):
        with connect(missing):
            pass
    assert not missing.exists()


def test_list_shows_sqlite_files_and_skips_other_names(tmp_path):
    _library(tmp_path, "library.sqlite", "main")
    _library(tmp_path, "notes.sqlite", "notes")
    (tmp_path / "notes.txt").write_text("leave", encoding="utf-8")
    (tmp_path / ".hidden.sqlite").write_bytes(b"nope")
    assert list_library_names(tmp_path) == ["library.sqlite", "notes.sqlite"]


def test_read_active_name_prefers_the_saved_file(tmp_path):
    _library(tmp_path, "library.sqlite", "main")
    _library(tmp_path, "notes.sqlite", "notes")
    assert read_active_name(tmp_path) == "library.sqlite"
    write_active_name(tmp_path, "notes.sqlite")
    assert read_active_name(tmp_path) == "notes.sqlite"


def test_missing_saved_name_does_not_drop_other_files(tmp_path):
    _library(tmp_path, "notes.sqlite", "notes")
    write_active_name(tmp_path, "gone.sqlite")
    assert read_active_name(tmp_path) == "notes.sqlite"
    assert not (tmp_path / "library.sqlite").exists()
    assert get_setting(tmp_path / "notes.sqlite", "shelf", "") == "notes"


def test_rename_rejects_empty_and_collisions_and_keeps_other_files(tmp_path):
    current = _library(tmp_path, "library.sqlite", "main")
    other = _library(tmp_path, "notes.sqlite", "notes")
    before_current = current.read_bytes()
    before_other = other.read_bytes()

    with pytest.raises(ConfigError):
        rename_library_file(tmp_path, "library.sqlite", "   ")
    with pytest.raises(ConfigError):
        rename_library_file(tmp_path, "library.sqlite", "notes.sqlite")
    with pytest.raises(ConfigError):
        rename_library_file(tmp_path, "library.sqlite", "Notes")

    assert current.read_bytes() == before_current
    assert other.read_bytes() == before_other
    assert list_library_names(tmp_path) == ["library.sqlite", "notes.sqlite"]


def test_rename_keeps_the_other_file(tmp_path):
    _library(tmp_path, "library.sqlite", "main")
    other = _library(tmp_path, "notes.sqlite", "notes")
    before_other = other.read_bytes()
    renamed = rename_library_file(tmp_path, "library.sqlite", "archive")
    assert renamed == "archive.sqlite"
    assert get_setting(tmp_path / "archive.sqlite", "shelf", "") == "main"
    assert not (tmp_path / "library.sqlite").exists()
    assert other.read_bytes() == before_other


def test_invalid_upload_is_rejected_before_the_current_file_changes(tmp_path):
    current = _library(tmp_path, "library.sqlite", "main")
    other = _library(tmp_path, "notes.sqlite", "notes")
    before_current = current.read_bytes()
    before_other = other.read_bytes()
    incoming = tmp_path / ".incoming.partial"
    incoming.write_bytes(b"this is not a library")

    with pytest.raises(ConfigError):
        install_library_file(tmp_path, "library.sqlite", incoming)

    assert current.read_bytes() == before_current
    assert other.read_bytes() == before_other
    assert incoming.is_file()
    assert not list(tmp_path.glob(".*.previous"))


def test_replace_restores_the_previous_file_when_the_new_one_fails(tmp_path):
    current = _library(tmp_path, "library.sqlite", "old")
    other = _library(tmp_path, "notes.sqlite", "notes")
    incoming = _library(tmp_path, ".incoming.sqlite", "new")
    before_other = other.read_bytes()
    calls = {"n": 0}
    real = validate_library_file

    def fail_after_swap(path: Path) -> None:
        real(path)
        calls["n"] += 1
        if path.name == "library.sqlite" and calls["n"] > 1:
            raise ConfigError("fail after swap")

    with pytest.raises(ConfigError, match="fail after swap"):
        install_library_file(tmp_path, "library.sqlite", incoming, validate=fail_after_swap)

    assert get_setting(current, "shelf", "") == "old"
    assert other.read_bytes() == before_other
    assert not list(tmp_path.glob(".*.previous"))
    assert not incoming.exists()


def test_replace_drops_the_previous_file_only_after_the_new_one_is_valid(tmp_path):
    current = _library(tmp_path, "library.sqlite", "old")
    other = _library(tmp_path, "notes.sqlite", "notes")
    incoming = _library(tmp_path, ".incoming.sqlite", "new")
    before_other = other.read_bytes()

    installed = install_library_file(tmp_path, "library.sqlite", incoming)

    assert installed == "library.sqlite"
    assert get_setting(current, "shelf", "") == "new"
    assert other.read_bytes() == before_other
    assert not list(tmp_path.glob(".*.previous"))
    assert [name for name in list_library_names(tmp_path)] == ["library.sqlite", "notes.sqlite"]


def test_import_can_add_a_new_file_without_touching_the_others(tmp_path):
    current = _library(tmp_path, "library.sqlite", "main")
    other = _library(tmp_path, "notes.sqlite", "notes")
    incoming = _library(tmp_path, ".incoming.sqlite", "extra")
    before_current = current.read_bytes()
    before_other = other.read_bytes()

    installed = install_library_file(tmp_path, "extra.sqlite", incoming)

    assert installed == "extra.sqlite"
    assert get_setting(tmp_path / "extra.sqlite", "shelf", "") == "extra"
    assert current.read_bytes() == before_current
    assert other.read_bytes() == before_other


def test_recover_puts_back_a_parked_file(tmp_path):
    current = _library(tmp_path, "library.sqlite", "kept")
    current.replace(tmp_path / ".library.sqlite.previous")
    assert not current.exists()

    recover_library_backups(tmp_path)

    assert get_setting(current, "shelf", "") == "kept"
    assert not (tmp_path / ".library.sqlite.previous").exists()


def test_recover_keeps_the_previous_file_when_the_replacement_is_invalid(tmp_path):
    current = _library(tmp_path, "library.sqlite", "kept")
    current.replace(tmp_path / ".library.sqlite.previous")
    current.write_bytes(b"not a library")

    recover_library_backups(tmp_path)

    assert get_setting(current, "shelf", "") == "kept"
    assert not (tmp_path / ".library.sqlite.previous").exists()


def test_recover_drops_the_previous_file_when_the_replacement_is_valid(tmp_path):
    current = _library(tmp_path, "library.sqlite", "new")
    parked = _library(tmp_path, ".library.sqlite.previous", "old")
    assert parked.name.startswith(".")

    recover_library_backups(tmp_path)

    assert get_setting(current, "shelf", "") == "new"
    assert not parked.exists()


def test_plain_sqlite_without_library_tables_is_rejected(tmp_path):
    path = tmp_path / "empty.sqlite"
    connection = sqlite3.connect(path)
    connection.close()
    with pytest.raises(ConfigError):
        validate_library_file(path)
