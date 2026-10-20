"""Run the portal under uvicorn."""

from __future__ import annotations

import uvicorn
from alerts_bi_shared.logging_setup import log
from alerts_bi_shared.versions import APP_VERSION

from .app import build_portal
from .config import PortalSettings

__all__ = ["serve"]


def serve(settings: PortalSettings) -> None:
    """Serve until interrupted; view queries use the configured SQL connection."""
    log.info(
        "portal.listening",
        "Review portal {version} on http://{host}:{port}, reading {database}; it admits "
        "clients from {allowed_networks}",
        version=APP_VERSION,
        host=settings.host,
        port=settings.port,
        database=settings.database,
        login=settings.sql.user,
        allowed_networks=[str(network) for network in settings.allowed_networks],
    )
    uvicorn.run(
        build_portal(settings),
        host=settings.host,
        port=settings.port,
        log_level="warning",
        # Uvicorn's own warnings and errors go through the shared log format.
        log_config=None,
        access_log=False,
        server_header=False,
    )
