"""Sensewright v2 sidecar.

A local FastAPI companion process for the Sensewright The Sims 4 mod. It owns
all heavy lifting — LLM calls, the SQLite "Shadow DB" (FTS5 memory), the God
Director, the World Layer and the Web Studio — while the in-game mod only reads
game state and dispatches Intents on the main thread.

The sidecar runs on Python 3.12+ and never blocks the game: the mod talks to it
over a local HTTP wire (127.0.0.1:8765) from a dedicated daemon worker thread.
"""

__version__ = "2.0.0"

SERVER_HOST_DEFAULT = "127.0.0.1"
SERVER_PORT_DEFAULT = 8765
