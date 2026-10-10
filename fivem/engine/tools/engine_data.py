"""The data Skate 3's engine reads, from YOUR copy of the game (the PS3 disc's files work).

Runs the engine's own export step (upstream/skate-3-rust-engine-donor, tools/asset_pipeline: the `core` step) on
the disc's archives: the animation banks, the state graphs, the Flick-It patterns, the camera files and the tuning
vault. Then adds the three small files the engine checks for that a PS3 disc does not give in the form it expects.
Everything is written to the folder you name and stays on your machine.

usage: python engine_data.py <PS3_GAME\\USRDIR> <out folder>
       (the out folder gets assets\\private\\...; the engine is pointed at <out folder>\\assets)
"""
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
DONOR = HERE.parent / "upstream" / "skate-3-rust-engine-donor"

# The pad mapping the engine implements (skate-data/src/input_config.rs: BUTTON_NAMES and GAMEPLAY). The engine has
# this mapping in its code and reads input.cfg only to check that the file agrees with it. The PS3 disc's file says
# the same thing for a PS3 pad (Cross, L1, ...) and with other button numbers; the host hands the engine an Xbox-
# layout pad, so the file it checks is written here in that layout. Nothing in it comes from a game file.
BUTTON_NAMES = ["DPadU", "DPadD", "DPadL", "DPadR", "Start", "Back", "LStick", "RStick", "LBumper", "RBumper",
                "LTrigger", "RTrigger", "A", "B", "X", "Y", "LStickR", "LStickL", "LStickU", "LStickD",
                "RStickR", "RStickL", "RStickU", "RStickD"]
GAMEPLAY = [("GP_LStickX", "LStickR - LStickL"), ("GP_LStickY", "LStickU - LStickD"), ("GP_LStickIn", "LStick"),
            ("GP_RStickX", "RStickR - RStickL"), ("GP_RStickY", "RStickU - RStickD"), ("GP_RStickIn", "RStick"),
            ("GP_LTrigger", "LTrigger"), ("GP_RTrigger", "RTrigger"), ("GP_LBumper", "LBumper"),
            ("GP_RBumper", "RBumper"), ("GP_UDPad", "DPadU"), ("GP_DDPad", "DPadD"), ("GP_LDPad", "DPadL"),
            ("GP_RDPad", "DPadR"), ("GP_XFace", "X"), ("GP_YFace", "Y"), ("GP_AFace", "A"), ("GP_BFace", "B")]
GAME_JSON = ('{"version":1,"character_scene":"private/skater.glb","initial_animation":"R_IDLE_HCOM_000",'
             '"action_graph":"private/stock/data/state/ActionGraph_OnBoard.stategraph",'
             '"motion_graph":"private/stock/data/state/MotionGraph_OnBoard.stategraph"}')


def write_pad_mapping(path):
    disc = path.with_name("input.ps3.cfg")
    if path.exists() and not disc.exists():
        path.rename(disc)      # (the disc's own file, kept beside it)
    lines = ["// Xbox-layout pad mapping for the Skate engine's check (written by engine_data.py)"]
    lines += ["%s = Button%d;" % (name, i) for i, name in enumerate(BUTTON_NAMES)]
    lines += ["%s = %s;" % pair for pair in GAMEPLAY]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    game, out = Path(sys.argv[1]), Path(sys.argv[2])
    if not (game / "data" / "big" / "miscload.big").is_file():
        sys.exit("%s has no data\\big\\miscload.big: name the disc's USRDIR folder" % game)
    if not DONOR.is_dir():
        sys.exit("%s is not there: fetch the engine's sources first (README)" % DONOR)
    sys.path.insert(0, str(DONOR))
    from tools.asset_pipeline import asset_exports as exports
    shutil.rmtree(out / "assets", ignore_errors=True)    # (this script's own output of an earlier run)
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="engine-data-", dir=out.parent) as work, \
            (out / "conversion.log").open("w", encoding="utf-8") as log:
        try:
            exports.core(game, out, Path(work), lambda t: print(t, flush=True), log)
        except Exception:
            traceback.print_exc()
            return 1
    private = out / "assets" / "private"
    stock = private / "stock"
    write_pad_mapping(stock / "data" / "config" / "input.cfg")
    (private / "game.json").write_text(GAME_JSON, encoding="utf-8")
    # The engine only checks that a skater model is there; its bridge never opens it (the host draws the rider).
    (private / "skater.glb").touch()
    for rel in ("skater-collections.json", "physics-skeletons.json", "data/config/input.cfg",
                "data/anim/OnBoard.abin", "data/state/ActionGraph_OnBoard.stategraph",
                "data/state/MotionGraph_OnBoard.stategraph"):
        p = stock / rel
        print("%-52s %s" % (rel, ("%d bytes" % p.stat().st_size) if p.is_file() else "MISSING"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
