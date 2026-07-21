from __future__ import annotations

import argparse
import os
import secrets
import threading
import webbrowser

import uvicorn

from app.config import Settings


def main() -> None:
    parser = argparse.ArgumentParser(prog="carivyo")
    subparsers = parser.add_subparsers(dest="command")
    start = subparsers.add_parser("start", help="Start the local Carivyo workspace")
    start.add_argument("--host", default="127.0.0.1")
    start.add_argument("--port", type=int, default=8420)
    start.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if args.command not in {None, "start"}:
        parser.error("Unknown command")
    host = getattr(args, "host", "127.0.0.1")
    if host not in {"127.0.0.1", "::1", "localhost"}:
        parser.error("Carivyo can only bind to a loopback host")
    bootstrap_token = os.environ.setdefault(
        "CARIVYO_BOOTSTRAP_TOKEN",
        secrets.token_urlsafe(32),
    )
    launch_url = (
        f"http://{host}:{getattr(args, 'port', 8420)}/"
        f"#bootstrap={bootstrap_token}"
    )
    print(f"Open Carivyo: {launch_url}")
    if not getattr(args, "no_browser", False):
        threading.Timer(
            1.2, lambda: webbrowser.open(launch_url)
        ).start()
    uvicorn.run(
        "app.main:app",
        host=host,
        port=getattr(args, "port", 8420),
        app_dir=str(Settings().project_root / "backend"),
        reload=False,
    )
