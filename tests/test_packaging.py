import importlib.util
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORMULA = ROOT / "packaging" / "homebrew" / "paper-cart.rb"


def _formula_module():
    spec = importlib.util.spec_from_file_location("formula", FORMULA.with_name("formula.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_console_script_points_at_cli_main():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["scripts"]["paper-cart"] == "paper_cart.cli:main"


def test_formula_matches_uv_lock():
    formula = _formula_module()
    expected = formula.render(formula.DEFAULT_REPO, formula.current_sha())
    assert FORMULA.read_text(encoding="utf-8") == expected, (
        "Run: uv run python packaging/homebrew/formula.py"
    )


def test_formula_uses_only_prebuilt_wheels():
    text = FORMULA.read_text(encoding="utf-8")
    assert ".tar.gz" not in text
    assert 'depends_on "rust"' not in text
    assert "on_arm do" in text and "on_intel do" in text


def test_formula_version_matches_package():
    from paper_cart import __version__

    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["version"] == __version__
    assert f"/v{__version__}/paper_cart-{__version__}-py3-none-any.whl" in FORMULA.read_text(encoding="utf-8")
