# Homebrew packaging

`paper-cart.rb` is the formula for a personal tap. It installs Paper Cart into its own
Python 3.13 environment from prebuilt wheels (no compiling, no Rust) and puts
`paper-cart` on the PATH. It is written by `formula.py` from `uv.lock`; don't edit it by hand.

The formula downloads the wheel attached to a tagged GitHub release of
[sunwookwak-polisci/Paper-Cart](https://github.com/sunwookwak-polisci/Paper-Cart). Until a release
and tap are published, install with uv (see the main README).

## One-time setup

1. Create the tap repo `sunwookwak-polisci/homebrew-paper-cart` with an empty `Formula/` folder.
2. In this repository's settings, add:
   - variable `HOMEBREW_TAP` = `sunwookwak-polisci/homebrew-paper-cart`
   - secret `HOMEBREW_TAP_TOKEN` = a fine-grained token with Contents read and write on the tap repo only

## Releasing

1. Bump `version` in `pyproject.toml` and `__version__` in `paper_cart/__init__.py`, then:

   ```bash
   uv lock
   uv run python packaging/homebrew/formula.py
   uv run pytest
   ```

2. Commit, push, then tag: `git tag v0.2.0 && git push origin v0.2.0`.

The `Release` workflow (`.github/workflows/release.yml`) checks the tag matches the version,
runs the tests, builds the wheel, creates the GitHub release with the wheel attached,
writes the formula with the wheel's checksum, and pushes it to the tap.

Users install and update with:

```bash
brew tap sunwookwak-polisci/paper-cart
brew install sunwookwak-polisci/paper-cart/paper-cart
brew upgrade paper-cart
```

`brew tap sunwookwak-polisci/paper-cart` adds the `sunwookwak-polisci/homebrew-paper-cart` repo.

## Supported Macs

Apple silicon and Intel, using Homebrew's `python@3.13`. Two dependencies (`markupsafe`,
`pydantic-core`) have separate wheels per chip; `formula.py` picks both from `uv.lock`
and stops with an error if one is missing.
