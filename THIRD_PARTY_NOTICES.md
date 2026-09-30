# Third-party notices

Sensewright is released under the MIT License (see `LICENSE`). It **depends on**
two community libraries at runtime (installed by the player, not bundled) and
adapts a small amount of source code from the projects below. Their notices are
reproduced here as required by their licenses.

---

## Sims 4 Community Library (S4CL) - runtime dependency

- Source: <https://github.com/DeviantGameMods/Sims4CommunityLibrary>
- License: Creative Commons Attribution 4.0 International (CC BY 4.0)
- Copyright (c) ColonolNutty / DeviantGameMods

Used for notifications, native dialogs, the immediate-super-interaction base
class and (forward) tuning-id utilities. The library is **not** redistributed
with Sensewright; players install it at the Mods root. Attribution: Sensewright's
`integrations.py` is written against S4CL's public API.

## Lot 51 Core Library - runtime dependency

- Source: <https://github.com/lot51/core-library>
- Site: <https://lot51.cc/core>
- License: MIT
- Copyright (c) 2022 Lot 51

Used for the event bus (zone load/unload, game tick, save), the custom service
manager and logger/config helpers. Not redistributed; players install it at the
Mods root.

---

## SimAI (`dnavaria/sims4ai`)

- Source: <https://github.com/dnavaria/sims4ai>
- License: MIT
- Copyright (c) 2026 SimAI contributors

Adapted in Sensewright (both files carry a short in-source attribution):

- `mod/sensewright_mod/player_activity.py` — the "wrap
  `Sim.push_super_affordance` and classify the push by `context.source`" approach;
  adapted from `sims4_ai_mod/ai_sim_mod/interaction_subscriber.py`. Sensewright
  changes the behaviour so unknown sources do **not** arm the player lock (the
  agent's own `SOURCE_SCRIPT` pushes must not throttle the agent).
- `mod/sensewright_mod/tool_executor.py` — `_cancel_running_interaction()`
  (cancelling `queue.running` with the `cancel(finishing_type=…,
  cancel_reason_msg=…)` signature and its `TypeError` fallback) and the
  `queue.run_super(affordance, target=…)` fallback in `_push_affordance()`;
  adapted from `sims4_ai_mod/ai_sim_mod/tool_executor.py`.

```text
MIT License

Copyright (c) 2026 SimAI contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
