# Sensewright — TS4 script decompiler (modern zip layout).
# Python 3.10+ (developer tool only; never shipped in the .ts4script).
#
# Modern TS4 (Python 3.7) ships its server scripts as .pyc archives under
# Data\Simulation\Gameplay\{base,core,simulation}.zip. This script extracts a
# curated list of modules and decompiles them with decompyle3 into research/ts4/
# (gitignored — proprietary EA code is never committed).

from __future__ import annotations

import argparse
import os
import sys
import warnings
import zipfile

CURATED = [
    "sims4/commands.pyc",
    "sims4/log.pyc",
    "sims/sim.pyc",
    "sims/sim_info.pyc",
    "socials/group.pyc",
    "interactions/base/interaction.pyc",
    "interactions/context.pyc",
    "interactions/choices.pyc",
    "relationships/relationship_tracker.pyc",
    "relationships/relationship_service.pyc",
    "situations/situation.pyc",
    "situations/situation_manager.pyc",
    "situations/base_situation.pyc",
    "buffs/buff.pyc",
    "buffs/buff_display_type.pyc",
    "objects/game_object.pyc",
    "objects/definition.pyc",
    "ui/ui_dialog.pyc",
    "ui/ui_dialog_notification.pyc",
    "balloon/balloon_request.pyc",
    "balloon/passive_balloons.pyc",
    "statistics/commodity.pyc",
    "statistics/commodity_tracker.pyc",
    "server_commands/interaction_commands.pyc",
    "server_commands/autonomy_commands.pyc",
]

TS4_ROOTS = [
    r"C:\Program Files\EA Games\The Sims 4",
    r"C:\Program Files (x86)\Origin Games\The Sims 4",
]


def find_ts4_root() -> str:
    for root in TS4_ROOTS:
        sim_zip = os.path.join(root, "Data", "Simulation", "Gameplay", "simulation.zip")
        if os.path.exists(sim_zip):
            return root
    raise SystemExit("Could not find The Sims 4 installation.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Decompile TS4 scripts.")
    parser.add_argument("--output", default=os.path.join("research", "ts4"))
    parser.add_argument("--all", action="store_true", help="extract every module")
    args = parser.parse_args()

    root = find_ts4_root()
    gameplay = os.path.join(root, "Data", "Simulation", "Gameplay")
    zips = [os.path.join(gameplay, n) for n in ("base.zip", "core.zip", "simulation.zip")]

    out_dir = os.path.abspath(args.output)
    os.makedirs(out_dir, exist_ok=True)

    extracted = 0
    for zip_path in zips:
        if not os.path.exists(zip_path):
            continue
        pkg = os.path.splitext(os.path.basename(zip_path))[0]
        with zipfile.ZipFile(zip_path) as zf:
            for name in zf.namelist():
                if not name.endswith(".pyc"):
                    continue
                if not args.all and name not in CURATED:
                    continue
                dst = os.path.join(out_dir, pkg, *name.split("/"))
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                with zf.open(name) as src, open(dst, "wb") as out:
                    out.write(src.read())
                extracted += 1

    print("Extracted %d modules to %s" % (extracted, out_dir))

    # Decompile after all extraction so the decompyle3 import happens once.
    warnings.filterwarnings("ignore")
    try:
        from decompyle3 import decompile_file  # type: ignore
    except ImportError:
        print("decompyle3 not installed — run: python -m pip install decompyle3")
        return 2

    decompiled = 0
    for dirpath, _dirs, files in os.walk(out_dir):
        for fn in files:
            if not fn.endswith(".pyc"):
                continue
            pyc = os.path.join(dirpath, fn)
            py = os.path.splitext(pyc)[0] + ".py"
            try:
                with open(py, "w", encoding="utf-8") as out:
                    decompile_file(pyc, out)
                decompiled += 1
            except Exception as exc:  # noqa: BLE001 — best-effort reference
                print("  decompile failed: %s (%s)" % (fn, exc))

    print("Decompiled %d / %d modules" % (decompiled, extracted))
    print("Output: %s" % out_dir)
    print("NOTE: research/ts4/ is gitignored (proprietary EA code).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
