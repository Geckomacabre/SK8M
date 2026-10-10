"""Decode Skate 3's animation banks into one CSV per clip, from YOUR copy of the game.

  on    miscload\\data\\anim\\OnBoard.abin    riding, tricks, grinds, grabs, bails    -> onboard_csv, onboard_meta.csv
  off   miscload\\data\\anim\\OffBoard.abin   standing, walking, running, getting on  -> offboard_csv, offboard_meta.csv

The banks come out of the game's miscload.big (eb_extract.py) into the work folder (paths.py). The decoder is the
Skate-Modding-Team's AnimTest with the patch in tools/animtest (its README says how to build it); `animtest` in
local_paths.json says where the built program is. Each CSV has a row per frame and bone: the bone's rotation and
translation as the clip stores them (offsets from the rest pose, RIG_TPOSE); the meta file has each clip's frame
rate, length, base speed and root motion.

usage: python decode_anims.py [on] [off] [--out <folder>]      (no bank named = both; --out: not the work folder)
"""
import os
import re
import subprocess
import sys
import tempfile

import paths

BANKS = {"on": ("OnBoard.abin", "onboard"), "off": ("OffBoard.abin", "offboard")}
HEADER = "name,fps,frames,base_speed,traj_tx,traj_ty,traj_tz,traj_qx,traj_qy,traj_qz,traj_qw\n"


def run(bank, stdin_text, env=None):
    """AnimTest is an interactive program: it reads what to do from a FILE on its standard input."""
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, newline="\r\n") as f:
        f.write(stdin_text)
    try:
        with open(f.name, "rb") as stdin:
            return subprocess.run([paths.ANIMTEST, bank], stdin=stdin, capture_output=True, text=True,
                                  errors="replace", env=dict(os.environ, **(env or {})))
    finally:
        os.remove(f.name)


def decode(which, out_root):
    file, stem = BANKS[which]
    bank = paths.work("miscload", "data", "anim", file)
    if not os.path.exists(bank):
        sys.exit("%s is not there: extract miscload.big into %s first (eb_extract.py)" % (bank, paths.work("miscload")))
    out, meta = os.path.join(out_root, stem + "_csv"), os.path.join(out_root, stem + "_meta.csv")
    os.makedirs(out, exist_ok=True)
    entries = re.findall(r"\[(\d+)\] \((\w)\) \[\w+\] (\S+)", run(bank, "q\n").stdout)
    if not entries:
        sys.exit("%s listed no clips in %s: is `animtest` in local_paths.json the patched build?" % (paths.ANIMTEST, bank))
    open(os.path.join(out_root, stem + "_list.txt"), "w").write("\n".join("%s %s %s" % e for e in entries) + "\n")
    script = "".join("%s\n%s\n" % (i, os.path.join(out, name + ".csv")) for i, kind, name in entries) + "q\n"
    open(meta, "w").write(HEADER)
    run(bank, script, {"META_OUT": meta})
    done = [f for f in os.listdir(out) if f.endswith(".csv")]
    print("%s: %d entries, %d clips written to %s, %d meta rows" % (
        file, len(entries), len(done), out, sum(1 for _ in open(meta)) - 1))


def main():
    args = sys.argv[1:]
    out_root = paths.WORK
    if "--out" in args:
        out_root = args[args.index("--out") + 1]
        del args[args.index("--out"):args.index("--out") + 2]
    for which in args or ["on", "off"]:
        if which not in BANKS:
            sys.exit(__doc__)
        decode(which, out_root)


if __name__ == "__main__":
    main()
