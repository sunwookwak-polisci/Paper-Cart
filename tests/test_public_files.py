import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EMAIL = re.compile(r"[\w.+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")


def test_gitignore_blocks_personal_files():
    ignored = {
        line.strip()
        for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    assert "data/" in ignored
    assert "*.sqlite" in ignored
    assert ".env" in ignored


def test_example_config_has_no_email():
    data = tomllib.loads((ROOT / "config.example.toml").read_text(encoding="utf-8"))
    assert data["contact_email"] == ""


def test_public_docs_stay_generic():
    for path in (ROOT / "README.md", ROOT / "packaging" / "homebrew" / "README.md", ROOT / "config.example.toml"):
        text = path.read_text(encoding="utf-8")
        assert not EMAIL.search(text), path.name
        assert "/users/" not in text.lower(), path.name
