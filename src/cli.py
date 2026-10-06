"""Launch the independent, read-only review portal."""

from __future__ import annotations

import argparse
import sys

from alerts_bi_shared.logging_setup import log, redact_error

from .config import load_portal_settings
from .server import serve


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve the read-only Alerts BI review portal.")
    parser.add_argument("--host", help="bind address; PORTAL_HOST, else 127.0.0.1")
    parser.add_argument("--port", type=int, help="bind port; PORTAL_PORT, else 8100")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = load_portal_settings(host=args.host, port=args.port)
    sys.stdout.write(
        f"alerts-bi-portal on http://{settings.host}:{settings.port} (ctrl-c to stop)\n"
    )
    serve(settings)
    return 0


def run_cli() -> None:
    try:
        sys.exit(main())
    except Exception as exc:
        error = redact_error(exc)
        log.error("portal.cli_failed", error=error)
        sys.stderr.write(f"{error}\n")
        sys.exit(1)
