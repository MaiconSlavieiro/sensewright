---
name: ts4-modding-best-practices
description: >-
  Use this skill whenever developing, debugging, or reviewing mods for The Sims 4 (TS4). 
  It provides architectural guidelines, strict constraints of the TS4 engine (Python 3.7, single-threading),
  integration patterns (sidecars, native hooks), and UI/state management best practices.
---

# The Sims 4 (TS4) Modding Best Practices

This guide outlines the critical engineering principles, architectural patterns, and limitations you must adhere to when building robust, complex mods for The Sims 4.

## 1. Setup & Environment
*   **Decompiling Scripts:** TS4 does not provide official API documentation. Always decompile the game’s Python scripts (`base`, `core`, `simulation`) on each major update to reference EA's original logic.
*   **IDE Choice:** PyCharm is the industry standard for TS4 modding because its indexing and code completion are essential for navigating decompiled game files.
*   **Python Version:** TS4 runs on **Python 3.7.0**.
    *   ❌ Do not use the walrus operator (`:=`).
    *   ❌ Do not use `match/case` (requires 3.10+).
    *   ❌ Do not use union type syntax like `int | str` (requires 3.10+).
    *   ❌ Do not use `f-strings` with `=` debug syntax (e.g., `f"{x=}"`, requires 3.8+).
    *   ❌ Do not use `from __future__ import annotations`. It causes parsing errors in the TS4 runtime.
    *   ✅ `dataclasses` and `typing` (pre-3.8 syntax) are available and encouraged.
*   **Sandboxing & Standard Library:** The environment is partially sandboxed. File system access is restricted. Many standard libraries (like `sqlite3`, `socket` behavior variations) can act unpredictably across different players' OS/Antivirus setups.
*   **Dependencies:** You cannot easily `pip install` packages. Stick to the standard library, or rely on established core libraries like **Sims 4 Community Library (S4CL)** and **Lot 51 Core Library**.

## 2. Architecture & Threading (The Dual-Process Model)

The TS4 engine is strictly **single-threaded**. Any blocking operation (like network requests, heavy LLM processing, or large I/O) on the main thread will instantly freeze the game, ruining the player's experience.

*   **Rule of Thumb:** The `GAME_TICK` (main thread) should only be used to read game state and dispatch non-blocking events.
*   **The Sidecar Pattern:** For heavy computation (like AI, SQLite FTS5 search, complex routing), implement a **Dual-Process Architecture**:
    1.  **Mod (Python 3.7):** Runs inside TS4. Uses a `queue.Queue` to hand off payloads to a background `daemon=True` worker thread.
    2.  **Worker Thread:** Handles HTTP requests (`urllib.request`) to communicate with an external local server.
    3.  **Sidecar (Python 3.12+):** An external process (e.g., FastAPI) running locally. Handles all heavy lifting, external API calls, and database operations.
*   **Autoboot Resilience:** Starting the sidecar via `subprocess.Popen` inside TS4 is risky (often blocked by antivirus or causes zombie processes). Provide a robust fallback: 
    *   Try `subprocess.Popen` with `CREATE_NO_WINDOW` (Windows).
    *   Fail gracefully if blocked.
    *   Instruct the player to use an external launcher executable if needed.

## 3. Native Hooks, XML Injector & UI

Do not fight the engine. Hook into it diegetically.

*   **Interactions:** Know the difference between `ImmediateSuperInteractions` (instant clicks), `SuperInteractions` (routed animations), and `SocialMixerInteractions` (dialogue wheel inside social contexts).
*   **Avoid Tuning Overrides (Monkey-Patching):** Never override core game XML Tuning files if possible. This causes inevitable conflicts with other mods.
*   **Use XML Injector OR Core Libraries:** For adding custom interactions, you have two safe paths that avoid monkey-patching:
    *   **XML Injector:** The community standard for pure XML tuning injections without writing custom Python.
    *   **S4CL / Lot 51 Core Library:** If your mod already depends on these, you can use their built-in Python-level interaction registration and snippet injection features to achieve the same result programmatically.
*   **Diegetic UI:** Do not try to build complex custom UI modais from scratch. Use what the game provides:
    *   **Moodlets (Buffs):** Use Buffs with dynamic tooltips (via `TunableLocalizedStringFactory` and `{0.String}` tokens) to convey state or thoughts.
    *   **Sentiments:** Use the `RelationshipService` to add Sentiments to represent long-term feelings between Sims.
    *   **Notifications:** Use `UiDialogNotification` for discrete alerts.
    *   **Traits & Likes/Dislikes:** Hook into the `trait_tracker` to evolve Sims' preferences organically.

## 4. State Management & Lifecycle

TS4 players save often, use "Save As", and sometimes experience crashes. Your mod's external state must perfectly align with the game's save slots.

*   **The Shadow DB Pattern:** If keeping state in a sidecar (e.g., SQLite):
    *   Maintain a `.working.db` (current active session) and a `.committed.db` (the last hard save).
    *   Listen to TS4 lifecycle events: `zone_transition`, `session-start`, `save`.
*   **Save/Load Handling:**
    *   On `save`: Flush RAM buffers, copy `.working.db` to `.committed.db`. If "Save As" (new save ID), ensure the old `.committed.db` is preserved untouched.
    *   On `session-start`: Discard any existing `.working.db`, clone from `.committed.db` to prevent corruption if the game crashed previously.
*   **Garbage Collection:** Clear out spatial intents and temporary queues on `zone_transition` (loading screens between lots).

## 5. Defensive Programming & Observability

*   **Catch-All Handlers & sims4.logger:** Wrap critical hooks and tool executors in `try...except Exception` blocks and log the traceback using `sims4.log.Logger`. An uncaught exception in a core hook will silently break the entire game loop without throwing a visible error to the player.
*   **Time Management:** Be acutely aware of **Wall-Clock** (real life seconds) vs **Sim-Clock** (`sim_minutes`, `world_sim_tick`). 
    *   Use Wall-Clock for timeouts, rate limits, and infrastructure.
    *   Use Sim-Clock for game mechanics, cooldowns, expiration of intents, and scheduling actions.
*   **Pause Handling:** Always check the `clock_speed`. If the game is paused (`clock_speed == 0`), your mod must freeze game-affecting timers and pause autonomous action dispatches to respect the player's pause.
*   **Trace IDs:** Inject a unique `trace_id` at the origin of an event (e.g., a tick or a chat message) and pass it through all queues, HTTP requests, and sidecar logs. This is mandatory for debugging asynchronous systems.
*   **Log Rotation:** Mod logs can grow massive during 6+ hour play sessions. Always use `RotatingFileHandler` (e.g., 10MB limit, max 3 backups) for both the Mod and the Sidecar to prevent filling the user's disk.

## 6. General Software Engineering & Project Best Practices

To ensure long-term maintainability and readability, strictly follow these general programming guidelines:

*   **Type Hinting:** Even within the Python 3.7 limits, aggressively use the `typing` module (`List`, `Dict`, `Optional`, `Any`). This serves as living documentation and prevents a massive class of bugs when integrating the Sidecar and the Mod.
*   **Decoupling & Modularity:** Do not write "god classes" or massive 1000-line `main.py` files.
    *   **Mod Side:** Separate concerns into distinct modules (e.g., `interactions.py`, `hooks.py`, `state.py`, `network.py`).
    *   **Sidecar Side:** Use a clean architecture. Separate FastAPI routers (`routers/`), business logic (`services/`), and data access (`repositories/`).
*   **Isolate Game API calls:** The TS4 API is volatile. Wrap direct game engine calls in your own helper functions or facade classes so that when an EA patch breaks an API, you only have to update it in one place, rather than searching across the entire codebase.
*   **Explicit Error Handling:** Never use bare `except:` clauses. Always catch specific exceptions (`except ValueError:` etc.) or at least `except Exception as e:` and log the precise context. Fail gracefully and recover locally.
*   **Meaningful Naming & Documentation:**
    *   Use descriptive, unabbreviated variable names (`sim_world_tick` instead of `swt`).
    *   Write clear docstrings for all non-trivial functions explaining the *Why*, not just the *What*.
    *   Document expected payloads and side effects, especially in cross-process boundaries (HTTP and Queues).
*   **Stateless Services:** Treat the Sidecar as a stateless processor where possible. All persistent data should live in the SQLite database (Shadow DB). This allows the Sidecar to be restarted instantly without losing data or risking out-of-sync states with the game.
