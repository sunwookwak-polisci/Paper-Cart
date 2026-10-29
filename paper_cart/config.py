"""Local, untracked settings."""

from __future__ import annotations

import os
import sys
import tempfile
import tomllib
from pathlib import Path

APP_NAME = "Paper Cart"
DATA_DIR_FILE = "data-dir"


class ConfigError(Exception):
    """A local setting could not be used."""


def default_data_dir() -> Path:
    """The per-user folder an installed copy keeps its library in."""
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / APP_NAME
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", "").strip()
        return (Path(base) if base else home / "AppData" / "Roaming") / APP_NAME
    base = os.environ.get("XDG_DATA_HOME", "").strip()
    return (Path(base) if base else home / ".local" / "share") / "paper-cart"


def data_dir_preference_path() -> Path:
    """Where the in-app folder choice is stored.

    This stays in the per-user folder so the next launch can find it before
    opening whichever library the user picked.
    """
    return default_data_dir() / DATA_DIR_FILE


def read_saved_data_dir() -> Path | None:
    """The folder saved in Settings, or None when it is missing or unusable."""
    try:
        text = data_dir_preference_path().read_text(encoding="utf-8")
    except OSError:
        return None
    text = text.strip()
    if not text or any(character in text for character in "\x00\n\r"):
        return None
    folder = Path(text).expanduser()
    if not folder.is_absolute():
        return None
    if folder.exists() and not folder.is_dir():
        return None
    library = folder / "library.sqlite"
    if library.exists() and not library.is_file():
        return None
    return folder


def validate_data_dir_choice(folder: Path | str) -> Path:
    """Check that a folder can hold a library. Does not copy or replace one."""
    raw = str(folder).strip()
    if not raw or any(character in raw for character in "\x00\n\r"):
        raise ConfigError("Enter a folder path.")
    target = Path(raw).expanduser()
    if not target.is_absolute():
        raise ConfigError("Enter a full folder path.")
    try:
        target = target.resolve()
    except OSError as exc:
        raise ConfigError("That folder could not be used.") from exc
    if target.exists() and not target.is_dir():
        raise ConfigError("That path is a file. Choose a folder.")
    library = target / "library.sqlite"
    if library.exists() and not library.is_file():
        raise ConfigError("That folder could not be used.")
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ConfigError("Paper Cart cannot create that folder.") from exc
    if not target.is_dir():
        raise ConfigError("That path is a file. Choose a folder.")
    try:
        with tempfile.NamedTemporaryFile(dir=target, prefix=".paper-cart-", delete=True):
            pass
    except OSError as exc:
        raise ConfigError("Paper Cart cannot write to that folder.") from exc
    return target


def save_data_dir_preference(folder: Path | str) -> Path:
    """Remember a folder for the next launch.

    The current library is not moved, copied, deleted, or replaced.
    """
    target = validate_data_dir_choice(folder)
    path = data_dir_preference_path()
    temporary = path.with_name(f".{DATA_DIR_FILE}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(f"{target}\n", encoding="utf-8")
        temporary.replace(path)
    except OSError as exc:
        raise ConfigError("The library folder could not be saved.") from exc
    finally:
        temporary.unlink(missing_ok=True)
    return target


def resolve_data_dir(explicit: Path | None = None) -> tuple[Path, str]:
    """Pick the library folder and say why.

    `--data-dir`, then PAPER_CART_DATA, then an existing ./data library,
    then the folder saved in Settings, then the per-user folder.
    The ./data check keeps a source checkout that already has a library
    reading the same file it always has.
    """
    if explicit is not None:
        return explicit.expanduser(), "flag"
    override = os.environ.get("PAPER_CART_DATA", "").strip()
    if override:
        return Path(override).expanduser(), "env"
    checkout = Path.cwd() / "data"
    if (checkout / "library.sqlite").is_file():
        return checkout, "checkout"
    saved = read_saved_data_dir()
    if saved is not None:
        return saved, "saved"
    return default_data_dir(), "default"


def data_dir_from_env() -> Path:
    """The library folder for this launch, ignoring a `--data-dir` flag."""
    return resolve_data_dir(None)[0]


def load_contact_email(path: Path) -> str | None:
    """Return a contact email for Crossref, or None when the file is absent or blank.

    The address is optional. It is never written by this program.
    """
    if not path.is_file():
        return None
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError("The local config file could not be read.") from exc
    if not isinstance(data, dict):
        raise ConfigError("The local config file could not be read.")
    email = str(data.get("contact_email") or "").strip()
    if not email:
        return None
    if "@" not in email or any(character.isspace() for character in email):
        raise ConfigError("The contact email in the local config file is not valid.")
    return email
