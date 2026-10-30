"""Open the local Paper Cart server."""

from __future__ import annotations

import argparse
import signal
import socket
import threading
import webbrowser
from pathlib import Path

import httpx
import uvicorn

from paper_cart import __version__
from paper_cart.config import resolve_data_dir
from paper_cart.homebrew import announce_homebrew_update
from paper_cart.web import APP_ID, create_app, start_startup_refresh

HOST = "127.0.0.1"
PORT = 8000
PORT_TRIES = 10


def running_instance(port: int, *, host: str = HOST) -> bool:
    """True when Paper Cart already answers on this port."""
    try:
        response = httpx.get(f"http://{host}:{port}/healthz", timeout=1.0, trust_env=False)
    except httpx.HTTPError:
        return False
    if response.status_code != 200:
        return False
    try:
        return response.json().get("app") == APP_ID
    except ValueError:
        return False


def port_is_free(port: int, *, host: str = HOST) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((host, port))
        except OSError:
            return False
    return True


def choose_port(start: int = PORT, tries: int = PORT_TRIES, *, host: str = HOST) -> tuple[int, bool]:
    """Return (port, already_running) for the first usable port from start."""
    for port in range(start, start + tries):
        if running_instance(port, host=host):
            return port, True
        if port_is_free(port, host=host):
            return port, False
    raise SystemExit(
        f"Paper Cart could not find a free port between {start} and {start + tries - 1}."
    )


class QuietServer(uvicorn.Server):
    async def shutdown(self, sockets: list[socket.socket] | None = None) -> None:
        await super().shutdown(sockets)
        # A second Ctrl+C makes uvicorn skip the app's lifespan shutdown, and
        # Starlette then logs the lifespan task's cancellation as an error.
        if self.force_exit:
            await self.lifespan.shutdown()


def open_browser(url: str, delay: float = 0.6) -> None:
    opener = threading.Timer(delay, lambda: webbrowser.open(url))
    opener.daemon = True
    opener.start()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="paper-cart",
        description="Open Paper Cart in your browser.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        help="folder for the library and config.toml for this launch "
        "(overrides Settings, PAPER_CART_DATA, and the per-user folder)",
    )
    parser.add_argument(
        "--no-browser", action="store_true", help="start the server without opening a browser"
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    newer_version = announce_homebrew_update()
    port, already_running = choose_port()
    url = f"http://{HOST}:{port}"
    if already_running:
        print(f"Paper Cart is already open at {url}")
        if not args.no_browser:
            webbrowser.open(url)
        return

    data_dir, source = resolve_data_dir(args.data_dir)
    data_dir = data_dir.resolve()
    application = create_app(data_dir)
    application.state.data_dir_source = source
    application.state.newer_version = newer_version
    server = QuietServer(uvicorn.Config(application, host=HOST, port=port, log_level="warning"))

    def shutdown() -> None:
        server.should_exit = True

    application.state.shutdown = shutdown
    start_startup_refresh(application)
    if not args.no_browser:
        open_browser(url)
    print(f"Paper Cart is at {url}")
    print(f"Library folder: {data_dir}")
    print(f"Library file: {application.state.db_path.name}")
    print("Press Ctrl+C here, or use Quit in the app, to stop it.")
    interrupted = False
    try:
        server.run()
    except KeyboardInterrupt:
        interrupted = True
    finally:
        # Another Ctrl+C while Python exits ends the process without a traceback.
        signal.signal(signal.SIGINT, signal.SIG_DFL)
    if interrupted:
        print("\nPaper Cart has stopped.")
        raise SystemExit(130)
    print("Paper Cart has stopped.")
