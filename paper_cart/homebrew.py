"""One-line Homebrew upgrade notice for a Cellar install of Paper Cart.

uv tool installs and git checkouts are left alone. The newer version comes
from the local tap formula when that file is present, and otherwise from
`brew outdated` with auto-update and the formulae API turned off. This
module does not contact the network itself. `brew` is stopped after a
short timeout so startup can continue.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from paper_cart import __version__

FORMULA = "paper-cart"
TAP = "sunwookwak-polisci/paper-cart"
BREW_TIMEOUT_SECONDS = 2

_VERSION_LINE = re.compile(r'(?m)^  version "([^"]+)"')
_URL_VERSION = re.compile(
    r'(?m)^  url "https://github\.com/[^"]+/releases/download/v([^"/]+)/paper_cart-'
)
_SAFE_VERSION = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._+-]{0,40}$")
_OUTDATED_TEXT = re.compile(
    r"(?m)^(?:\S+/)?paper-cart(?:\s+\([^)]*\))?\s*(?:<|->)\s*(\S+)\s*$"
)


def announce_homebrew_update(install_path: Path | None = None) -> None:
    """Print one line when this Homebrew install is older than the formula."""
    try:
        version = newer_homebrew_version(install_path)
    except Exception:
        return
    if version:
        print(f"Paper Cart {version} is available. Run brew upgrade paper-cart.")


def newer_homebrew_version(install_path: Path | None = None) -> str | None:
    """Return the newer formula version, or None when there is nothing to print."""
    located = _locate(install_path)
    if located is None:
        return None
    keg, prefix = located
    available = _tap_version(keg, prefix)
    if available is None:
        available = _brew_outdated_version()
    if available and _is_newer(available, __version__):
        return available
    return None


def _locate(install_path: Path | None) -> tuple[Path, Path] | None:
    if install_path is not None:
        return _keg_and_prefix(install_path)
    for candidate in (Path(sys.prefix), Path(sys.executable), Path(sys.argv[0]), Path(__file__)):
        located = _keg_and_prefix(candidate)
        if located is not None:
            return located
    return None


def _keg_and_prefix(path: Path) -> tuple[Path, Path] | None:
    """Return (Cellar/paper-cart/<version>, Homebrew prefix) when path is inside one."""
    try:
        resolved = path.resolve()
    except OSError:
        return None
    parts = resolved.parts
    try:
        index = parts.index("Cellar")
    except ValueError:
        return None
    if parts[index + 1 : index + 2] != (FORMULA,):
        return None
    if index == 0 or index + 2 >= len(parts):
        return None
    keg = Path(*parts[: index + 3])
    prefix = Path(*parts[:index])
    return keg, prefix


def _tap_version(keg: Path, prefix: Path) -> str | None:
    """Version declared by the local tap formula, or None when that file is unavailable."""
    receipt_path, receipt_tap = _receipt_source(keg)
    if receipt_path is not None and _is_tap_formula(receipt_path, prefix):
        version = _version_in_formula(receipt_path)
        if version:
            return version
    seen: set[Path] = set()
    for tap in (receipt_tap, TAP):
        if not tap:
            continue
        directory = _tap_directory(prefix, tap)
        if directory is None:
            continue
        resolved = directory.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        formula = _formula_file(directory)
        if formula is None:
            continue
        version = _version_in_formula(formula)
        if version:
            return version
    return None


def _receipt_source(keg: Path) -> tuple[Path | None, str | None]:
    try:
        data = json.loads((keg / "INSTALL_RECEIPT.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, None
    source = data.get("source")
    if not isinstance(source, dict):
        return None, None
    raw_path = source.get("path")
    path = Path(raw_path) if isinstance(raw_path, str) and raw_path else None
    tap = source.get("tap")
    if not isinstance(tap, str) or tap.count("/") != 1:
        tap = None
    return path, tap


def _is_tap_formula(path: Path, prefix: Path) -> bool:
    if path.name != f"{FORMULA}.rb":
        return False
    try:
        resolved = path.resolve()
        taps = (prefix / "Library" / "Taps").resolve()
        resolved.relative_to(taps)
    except (OSError, ValueError):
        return False
    return resolved.is_file()


def _tap_directory(prefix: Path, tap: str) -> Path | None:
    user, _, repo = tap.partition("/")
    if not user or not repo or "/" in repo:
        return None
    if not repo.lower().startswith("homebrew-"):
        repo = f"homebrew-{repo}"
    user_dir = _match_child(prefix / "Library" / "Taps", user)
    if user_dir is None:
        return None
    return _match_child(user_dir, repo)


def _match_child(parent: Path, name: str) -> Path | None:
    direct = parent / name
    if direct.is_dir():
        return direct
    if not parent.is_dir():
        return None
    wanted = name.lower()
    try:
        children = list(parent.iterdir())
    except OSError:
        return None
    for child in children:
        if child.name.lower() == wanted and child.is_dir():
            return child
    return None


def _formula_file(tap_dir: Path) -> Path | None:
    names = [
        tap_dir / "Formula" / f"{FORMULA}.rb",
        tap_dir / "HomebrewFormula" / f"{FORMULA}.rb",
        tap_dir / f"{FORMULA}.rb",
    ]
    for base in (tap_dir / "Formula", tap_dir / "HomebrewFormula"):
        if base.is_dir():
            names.extend(sorted(base.glob(f"*/{FORMULA}.rb")))
    for path in names:
        if path.is_file():
            return path
    return None


def _version_in_formula(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    match = _VERSION_LINE.search(text) or _URL_VERSION.search(text)
    if not match:
        return None
    version = match.group(1).strip()
    if _SAFE_VERSION.fullmatch(version):
        return version
    return None


def _brew_env() -> dict[str, str]:
    env = os.environ.copy()
    env["HOMEBREW_NO_AUTO_UPDATE"] = "1"
    env["HOMEBREW_NO_INSTALL_FROM_API"] = "1"
    env["HOMEBREW_NO_ANALYTICS"] = "1"
    env["HOMEBREW_NO_ENV_HINTS"] = "1"
    env["HOMEBREW_NO_COLOR"] = "1"
    return env


def _brew_outdated_version() -> str | None:
    command = ["brew", "outdated", "--formula", "--json=v2", FORMULA]
    try:
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=BREW_TIMEOUT_SECONDS,
            env=_brew_env(),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    stdout = completed.stdout or ""
    if completed.returncode != 0 and not stdout.strip():
        return None
    return _parse_outdated(stdout)


def _parse_outdated(stdout: str) -> str | None:
    text = stdout.strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None
    version = _version_from_json(data)
    if version:
        return version
    match = _OUTDATED_TEXT.search(text)
    if not match:
        return None
    found = match.group(1)
    if _SAFE_VERSION.fullmatch(found):
        return found
    return None


def _version_from_json(data: object) -> str | None:
    if isinstance(data, dict):
        items = data.get("formulae")
    elif isinstance(data, list):
        items = data
    else:
        return None
    if not isinstance(items, list):
        return None
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not isinstance(name, str):
            continue
        if name != FORMULA and not name.endswith("/" + FORMULA):
            continue
        current = item.get("current_version")
        if isinstance(current, str) and _SAFE_VERSION.fullmatch(current):
            return current
    return None


def _is_newer(available: str, installed: str) -> bool:
    if not _SAFE_VERSION.fullmatch(available):
        return False
    return _numbers(available) > _numbers(installed)


def _numbers(version: str) -> tuple[int, ...]:
    return tuple(int(piece) for piece in re.findall(r"\d+", version))
