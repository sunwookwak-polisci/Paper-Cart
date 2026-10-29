"""Several library files in one folder.

One sqlite file is active. The others stay in the folder when the active
file changes, when a file is renamed, and when a file is imported.
"""

from __future__ import annotations

import os
import re
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path

from paper_cart.config import ConfigError
from paper_cart.db import init_db, library_lock

DEFAULT_LIBRARY_NAME = "library.sqlite"
ACTIVE_NAME_FILE = "active-library"
MAX_LIBRARY_BYTES = 512 * 1024 * 1024
_LIBRARY_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,80}\.sqlite\Z", re.IGNORECASE)
_REQUIRED_COLUMNS = {
    "journals": {"id", "title", "primary_issn", "issns"},
    "papers": {"doi", "title", "status"},
    "settings": {"key", "value"},
    "cart_items": {"id", "title", "issns"},
}


class LibraryFileError(ConfigError):
    """A library file could not be listed, saved, or opened."""


class LibraryBusy(Exception):
    """An update is using the library, so files cannot change yet."""


BUSY_MESSAGE = "An update is running. Try again when it finishes."


def normalize_library_name(raw: str) -> str:
    """Return a sqlite file name in the library folder, or raise."""
    name = raw.strip()
    if not name or any(character in name for character in "\x00\n\r\t"):
        raise LibraryFileError("Enter a library name.")
    if name in {".", ".."} or name.startswith(".") or "/" in name or "\\" in name:
        raise LibraryFileError("Enter a file name, not a path.")
    if not name.lower().endswith(".sqlite"):
        name = f"{name}.sqlite"
    if not _LIBRARY_NAME.fullmatch(name):
        raise LibraryFileError(
            "Use letters, numbers, spaces, dots, hyphens, or underscores."
        )
    return name


def list_library_names(folder: Path) -> list[str]:
    """Sqlite library files in this folder, in case-insensitive order."""
    if not folder.is_dir():
        return []
    names: list[str] = []
    for path in folder.iterdir():
        if not path.is_file() or path.name.startswith("."):
            continue
        try:
            normalized = normalize_library_name(path.name)
        except ConfigError:
            continue
        if normalized != path.name:
            continue
        names.append(path.name)
    names.sort(key=str.casefold)
    return names


def read_active_name(folder: Path) -> str:
    """The sqlite file this folder should open.

    A missing custom choice falls back to library.sqlite when that file
    exists, otherwise to another library file already in the folder.
    """
    names = list_library_names(folder)
    saved = _read_pointer(folder)
    if saved:
        for name in names:
            if name == saved or name.casefold() == saved.casefold():
                return name
    for name in names:
        if name.casefold() == DEFAULT_LIBRARY_NAME.casefold():
            return name
    if names:
        return names[0]
    return DEFAULT_LIBRARY_NAME


def active_library_path(folder: Path) -> Path:
    return folder / read_active_name(folder)


def write_active_name(folder: Path, name: str) -> None:
    """Remember which sqlite file the next launch opens."""
    normalized = normalize_library_name(name)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / ACTIVE_NAME_FILE
    temporary = folder / ".active-library.tmp"
    temporary.write_text(f"{normalized}\n", encoding="utf-8")
    temporary.replace(target)


def matching_library_name(folder: Path, name: str) -> str | None:
    """The on-disk name that matches, ignoring letter case."""
    folded = name.casefold()
    for current in list_library_names(folder):
        if current.casefold() == folded:
            return current
    return None


def import_target_name(folder: Path, explicit: str, upload_name: str | None) -> str:
    raw = explicit.strip()
    if not raw:
        raw = Path(upload_name or "").name
    if not raw or raw in {".", ".."}:
        raise LibraryFileError("Enter a library name.")
    normalized = normalize_library_name(raw)
    return matching_library_name(folder, normalized) or normalized


def validate_library_file(path: Path) -> None:
    """Raise when the file is not a Paper Cart library. The file is not changed."""
    try:
        with path.open("rb") as handle:
            header = handle.read(16)
    except OSError as exc:
        raise LibraryFileError("That file could not be read.") from exc
    if header != b"SQLite format 3\x00":
        raise LibraryFileError("That file is not a library.")
    try:
        connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise LibraryFileError("That file is not a library.") from exc
    try:
        row = connection.execute("PRAGMA integrity_check").fetchone()
        if row is None or row[0] != "ok":
            raise LibraryFileError("That file is not a valid library.")
        tables = {
            found[0]
            for found in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        if not set(_REQUIRED_COLUMNS) <= tables:
            raise LibraryFileError("That file is not a Paper Cart library.")
        for table, columns in _REQUIRED_COLUMNS.items():
            found = {info[1] for info in connection.execute(f"PRAGMA table_info({table})")}
            if not columns <= found:
                raise LibraryFileError("That file is not a Paper Cart library.")
    except sqlite3.Error as exc:
        raise LibraryFileError("That file is not a valid library.") from exc
    finally:
        connection.close()


def snapshot_library(db_path: Path, destination: Path) -> None:
    """Write a consistent copy of the active library. The original stays put."""
    with library_lock():
        if not db_path.is_file():
            raise LibraryFileError("The library file is not in this folder.")
        source = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)
        copied = sqlite3.connect(destination)
        try:
            with copied:
                source.backup(copied)
        finally:
            copied.close()
            source.close()


def export_library_copy(db_path: Path) -> Path:
    """A temporary snapshot of the active library. The caller deletes it."""
    handle, raw = tempfile.mkstemp(prefix="paper-cart-export-", suffix=".sqlite")
    os.close(handle)
    destination = Path(raw)
    try:
        snapshot_library(db_path, destination)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return destination


def recover_library_backups(folder: Path) -> None:
    """Put a parked previous file back when a swap did not finish.

    A previous file is removed only when the replacement is already valid.
    """
    if not folder.is_dir():
        return
    for path in list(folder.iterdir()):
        library_name = _parked_library_name(path)
        if library_name is None:
            continue
        _recover_one(folder, library_name)


def install_library_file(
    folder: Path,
    name: str,
    source: Path,
    *,
    validate=validate_library_file,
) -> str:
    """Move a validated library into this folder.

    When the name is already there, the previous file stays on disk until
    the replacement has been checked. Other sqlite files are not touched.
    Returns the on-disk file name.
    """
    normalized = normalize_library_name(name)
    target_name = matching_library_name(folder, normalized) or normalized
    target = folder / target_name
    if target.exists() and not target.is_file():
        raise LibraryFileError("That file name could not be used.")
    validate(source)
    parked = _park(target)
    moved = False
    try:
        os.replace(source, target)
        moved = True
        validate(target)
    except Exception:
        _restore_parked(parked, new_file=target if moved else None)
        raise
    else:
        _drop_parked(parked)
    return target_name


def rename_library_file(folder: Path, old: str, new: str) -> str:
    """Rename one sqlite file inside the folder. Other files stay put."""
    names = list_library_names(folder)
    if old not in names:
        raise LibraryFileError("That library is not in this folder.")
    new_name = normalize_library_name(new)
    for current in names:
        if current.casefold() == new_name.casefold() and current != old:
            raise LibraryFileError("A library file in this folder already has that name.")
    if new_name == old:
        return old
    source = folder / old
    target = folder / new_name
    temporary = folder / f".{old}.renaming"
    if temporary.exists():
        raise LibraryFileError("That library could not be renamed. Try again.")
    os.replace(source, temporary)
    try:
        os.replace(temporary, target)
    except OSError as exc:
        if temporary.exists() and not source.exists():
            os.replace(temporary, source)
        raise LibraryFileError("That library could not be renamed.") from exc
    for suffix in ("-wal", "-shm"):
        sidecar = folder / f"{old}{suffix}"
        destination = folder / f"{new_name}{suffix}"
        if sidecar.is_file():
            os.replace(sidecar, destination)
    return new_name


def activate_library_file(folder: Path, name: str) -> Path:
    """Point the folder at an existing library file without changing the others."""
    names = list_library_names(folder)
    if name not in names:
        raise LibraryFileError("That library is not in this folder.")
    path = folder / name
    validate_library_file(path)
    init_db(path)
    write_active_name(folder, name)
    return path


def _read_pointer(folder: Path) -> str | None:
    try:
        text = (folder / ACTIVE_NAME_FILE).read_text(encoding="utf-8")
    except OSError:
        return None
    text = text.strip()
    if not text:
        return None
    try:
        return normalize_library_name(text)
    except ConfigError:
        return None


def _parked_library_name(path: Path) -> str | None:
    if not path.is_file() or not path.name.startswith(".") or not path.name.endswith(".previous"):
        return None
    library_name = path.name[1 : -len(".previous")]
    try:
        normalized = normalize_library_name(library_name)
    except ConfigError:
        return None
    if normalized != library_name:
        return None
    return library_name


@dataclass
class _Parked:
    target: Path
    backup: Path
    wal: Path
    wal_backup: Path
    shm: Path
    shm_backup: Path
    parked: bool = False


def _park(target: Path) -> _Parked:
    backup = target.with_name(f".{target.name}.previous")
    wal = Path(f"{target}-wal")
    shm = Path(f"{target}-shm")
    wal_backup = target.with_name(f".{target.name}.previous-wal")
    shm_backup = target.with_name(f".{target.name}.previous-shm")
    parked = _Parked(target, backup, wal, wal_backup, shm, shm_backup)
    if target.parent.is_dir() and (backup.exists() or wal_backup.exists() or shm_backup.exists()):
        recover_library_backups(target.parent)
    if not target.exists():
        return parked
    if not target.is_file():
        raise LibraryFileError("That file name could not be used.")
    if backup.exists():
        raise LibraryFileError("A previous library file is still being put back. Try again.")
    _checkpoint(target)
    os.replace(target, backup)
    parked.parked = True
    try:
        if wal.exists():
            os.replace(wal, wal_backup)
        if shm.exists():
            os.replace(shm, shm_backup)
    except OSError:
        _restore_parked(parked, new_file=None)
        raise
    return parked


def _checkpoint(path: Path) -> None:
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=rw", uri=True)
    try:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.commit()
    finally:
        connection.close()


def _restore_parked(parked: _Parked, *, new_file: Path | None) -> None:
    if new_file is not None and new_file.is_file() and new_file != parked.backup:
        new_file.unlink()
    if parked.parked and parked.backup.is_file():
        os.replace(parked.backup, parked.target)
    if parked.wal_backup.exists():
        if parked.wal.exists():
            parked.wal.unlink()
        os.replace(parked.wal_backup, parked.wal)
    if parked.shm_backup.exists():
        if parked.shm.exists():
            parked.shm.unlink()
        os.replace(parked.shm_backup, parked.shm)


def _drop_parked(parked: _Parked) -> None:
    parked.backup.unlink(missing_ok=True)
    parked.wal_backup.unlink(missing_ok=True)
    parked.shm_backup.unlink(missing_ok=True)


def _recover_one(folder: Path, library_name: str) -> None:
    target = folder / library_name
    backup = folder / f".{library_name}.previous"
    wal = Path(f"{target}-wal")
    shm = Path(f"{target}-shm")
    wal_backup = folder / f".{library_name}.previous-wal"
    shm_backup = folder / f".{library_name}.previous-shm"
    if not backup.is_file():
        return
    if not target.exists():
        os.replace(backup, target)
        if wal_backup.is_file() and not wal.exists():
            os.replace(wal_backup, wal)
        if shm_backup.is_file() and not shm.exists():
            os.replace(shm_backup, shm)
        return
    try:
        validate_library_file(target)
    except ConfigError:
        invalid = folder / f".{library_name}.invalid"
        os.replace(target, invalid)
        os.replace(backup, target)
        invalid.unlink(missing_ok=True)
        if wal_backup.exists():
            if wal.exists():
                wal.unlink()
            os.replace(wal_backup, wal)
        if shm_backup.exists():
            if shm.exists():
                shm.unlink()
            os.replace(shm_backup, shm)
    else:
        backup.unlink()
        wal_backup.unlink(missing_ok=True)
        shm_backup.unlink(missing_ok=True)
