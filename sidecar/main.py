"""Sensewright sidecar entry point.

Run with: ``python main.py`` (from the ``sidecar`` directory). This is a thin
wrapper around ``sensewright_sidecar.__main__`` so the documented ``python
main.py`` command keeps working.
"""

import os
import sys

if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from sensewright_sidecar.__main__ import main
    main()
