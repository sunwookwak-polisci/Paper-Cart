"""Write paper-cart.rb from uv.lock.

Every dependency comes from a prebuilt wheel, so installing needs neither Rust
nor network access during the build. Packages without a pure-Python wheel get
separate Apple silicon and Intel wheels for Python 3.13.

After changing dependencies:

    uv lock
    uv run python packaging/homebrew/formula.py

The release workflow also passes --repo and --sha256 for the tagged wheel.
"""

from __future__ import annotations

import argparse
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FORMULA = Path(__file__).with_name("paper-cart.rb")
DEFAULT_REPO = "sunwookwak-polisci/Paper-Cart"
PLACEHOLDER_SHA = "0" * 64
PYTHON_TAG = "cp313"
PLATFORMS = {"arm": "_arm64.whl", "intel": "_x86_64.whl"}

TEMPLATE = '''\
# Homebrew formula for Paper Cart, written by packaging/homebrew/formula.py.
# Do not edit by hand. The release workflow copies it to the tap as Formula/paper-cart.rb.
class PaperCart < Formula
  desc "Follow journals you choose and keep the papers you mean to read"
  homepage "https://github.com/{repo}"
  url "https://github.com/{repo}/releases/download/v{version}/paper_cart-{version}-py3-none-any.whl", using: :nounzip
  version "{version}"
  sha256 "{sha256}"

  depends_on "uv" => :build
  depends_on :macos
  depends_on "python@3.13"

{resources}
  def install
    ENV["UV_CACHE_DIR"] = buildpath/"uv-cache"
    ENV["UV_PYTHON_DOWNLOADS"] = "never"
    resources.each {{ |r| r.stage(buildpath/"wheels") }}
    system "uv", "venv", "--python", Formula["python@3.13"].opt_bin/"python3.13", libexec
    system "uv", "pip", "install", "--python", libexec/"bin/python", "--no-index", "--no-deps",
           *Dir[buildpath/"*.whl", buildpath/"wheels/*.whl"]
    bin.install_symlink libexec/"bin/paper-cart"
  end

  def caveats
    <<~EOS
      Start Paper Cart with:
        paper-cart
      Your library starts in:
        ~/Library/Application Support/Paper Cart
      Choose another folder in Settings. Quit and start Paper Cart again to use it.
      Upgrading or uninstalling the formula leaves the library folder alone.
    EOS
  end

  test do
    assert_match version.to_s, shell_output("#{{bin}}/paper-cart --version")
    system libexec/"bin/python", "-c", "import paper_cart.web"
  end
end
'''


def runtime_packages(lock_path: Path = ROOT / "uv.lock") -> list[dict]:
    """Locked packages the app needs at runtime on macOS, sorted by name."""
    packages = {entry["name"]: entry for entry in tomllib.loads(lock_path.read_text("utf-8"))["package"]}
    wanted: set[str] = set()
    pending = [dep["name"] for dep in packages["paper-cart"].get("dependencies", [])]
    while pending:
        name = pending.pop()
        if name in wanted:
            continue
        wanted.add(name)
        for dep in packages[name].get("dependencies", []):
            if "win32" in dep.get("marker", "") and "!=" not in dep.get("marker", ""):
                continue
            pending.append(dep["name"])
    return [packages[name] for name in sorted(wanted)]


def _block(name: str, wheel: dict, indent: str = "  ") -> str:
    digest = wheel["hash"].removeprefix("sha256:")
    return (
        f'{indent}resource "{name}" do\n'
        f'{indent}  url "{wheel["url"]}", using: :nounzip\n'
        f'{indent}  sha256 "{digest}"\n'
        f"{indent}end\n"
    )


def pick_wheels(package: dict) -> dict[str, dict]:
    """{"any": wheel} for pure Python, else {"arm": wheel, "intel": wheel}."""
    wheels = package.get("wheels", [])
    for wheel in wheels:
        if wheel["url"].endswith("-py3-none-any.whl"):
            return {"any": wheel}
    picked = {}
    for platform, suffix in PLATFORMS.items():
        matches = [
            wheel
            for wheel in wheels
            if f"-{PYTHON_TAG}-{PYTHON_TAG}-macosx_" in wheel["url"] and wheel["url"].endswith(suffix)
        ]
        if not matches:
            raise SystemExit(f"{package['name']} has no {PYTHON_TAG} macOS {platform} wheel in uv.lock.")
        picked[platform] = matches[0]
    return picked


def resource_blocks(lock_path: Path = ROOT / "uv.lock") -> str:
    common, arm, intel = [], [], []
    for package in runtime_packages(lock_path):
        picked = pick_wheels(package)
        if "any" in picked:
            common.append(_block(package["name"], picked["any"]))
        else:
            arm.append(_block(package["name"], picked["arm"], "    "))
            intel.append(_block(package["name"], picked["intel"], "    "))
    blocks = list(common)
    if arm:
        blocks.append("  on_arm do\n" + "\n".join(arm) + "  end\n")
        blocks.append("  on_intel do\n" + "\n".join(intel) + "  end\n")
    return "\n".join(blocks)


def project_version() -> str:
    return tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["project"]["version"]


def render(repo: str, sha256: str, lock_path: Path = ROOT / "uv.lock") -> str:
    return TEMPLATE.format(
        repo=repo, version=project_version(), sha256=sha256, resources=resource_blocks(lock_path)
    )


def current_sha(formula: Path = FORMULA) -> str:
    """Keep the checksum already in the file when only dependencies change."""
    if formula.is_file():
        match = re.search(r'^  sha256 "([0-9a-f]{64})"$', formula.read_text("utf-8"), re.M)
        if match:
            return match.group(1)
    return PLACEHOLDER_SHA


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", default=DEFAULT_REPO, help="GitHub owner/name that hosts the release")
    parser.add_argument("--sha256", help="checksum of the released wheel")
    parser.add_argument("--output", type=Path, default=FORMULA)
    args = parser.parse_args()
    args.output.write_text(render(args.repo, args.sha256 or current_sha(args.output)), "utf-8")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
