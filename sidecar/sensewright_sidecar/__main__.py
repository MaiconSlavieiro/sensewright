"""Sensewright sidecar entry point.

Run with: ``python -m sensewright_sidecar`` (from the ``sidecar`` directory).
The sidecar serves the REST API on 127.0.0.1:8765 and the Web Studio at /ui.
"""
from __future__ import annotations

import os
import sys


def main() -> None:
    # Allow running from the sidecar directory without installing the package.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    from sensewright_sidecar.config import get_config
    from sensewright_sidecar.observability.logging import setup_logging

    config = get_config()
    setup_logging(config.log_level)

    import uvicorn

    uvicorn.run(
        "sensewright_sidecar.server:app",
        host=config.server_host,
        port=config.server_port,
        log_level=config.log_level.lower(),
    )


if __name__ == "__main__":
    main()
