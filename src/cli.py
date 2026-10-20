"""Launch the independent, read-only review portal."""

from __future__ import annotations

import argparse
import sys

from alerts_bi_shared.config.env import load_dotenv
from alerts_bi_shared.logging_setup import configure_logging, log

from .config import load_portal_settings
from .server import serve


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve the read-only Alerts BI review portal.")
    parser.add_argument("--host", help="bind address; PORTAL_HOST, else 127.0.0.1")
    parser.add_argument("--port", type=int, help="bind port; PORTAL_PORT, else 8100")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # LOG_LEVEL and LOG_FORMAT may come from .env, so read it before configuring logging.
    load_dotenv()
    configure_logging("portal")
    settings = load_portal_settings(host=args.host, port=args.port)
    serve(settings)
    return 0


def run_cli() -> None:
    try:
        sys.exit(main())
    except Exception as exc:
        log.error("portal.cli_failed", "The portal stopped with an error", exc=exc)
        sys.exit(1)
