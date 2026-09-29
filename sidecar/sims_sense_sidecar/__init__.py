"""SimsSense sidecar — orchestration host (FastAPI).

This package NEVER imports game modules. It talks to the mod only over HTTP on
localhost, using the versioned protocol defined in ``schemas``.
"""

__version__ = "0.1.0"
