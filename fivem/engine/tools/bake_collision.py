"""Bake GTA V's map collision into one file of triangles the server's engine reads: collision.svwc.

Skate 3's engine needs the triangles the board rides on. A FiveM script cannot read the game's collision, only
cast rays at it, and rays half a metre apart make a kerb into a ramp and find nothing to grind. So the map is baked
once, on the server owner's PC, from their own GTA V, with SK8V's tools (the same ones its setup runs):

  rage.exe              (rage-cli)             reads the archive keys out of your GTA5.exe
  sk8v-rpf.exe          (rust/gta-archives)    takes the collision files (.ybn) out of the archives
  skatev-world-cache    (rust/world-cache)     makes them one tiled file, 64 m tiles, GTA's own material numbers

What is baked is the map as Story Mode has it: the base game, then every update pack that patches the map, in the
game's own order (dlclist.xml), a pack's archive only when the pack switches it on. Places that only Online
changes (the casino, heist doors) and maps a server adds are NOT in it: the player's game checks the ground it
stands on against the bake and the rays are used wherever the two disagree.

usage: python bake_collision.py <GTA V folder> <tools folder> <work folder> [--keep]
  <tools folder>  where rage.exe, sk8v-rpf.exe and skatev-world-cache.exe are (README: how to build them)
  <work folder>   gets keys/, base/, layers/ (about 3 GB, deleted again unless --keep) and collision.svwc
"""
import os
import re
import shutil
import subprocess
import sys
import time


def run(exe, *args, quiet=False):
    r = subprocess.run([exe, *map(str, args)], capture_output=True, text=True, errors="replace")
    out = (r.stdout + r.stderr).strip()
    # (a pack's unrelated empty entries make the extractor exit 1 after writing everything else)
    if r.returncode and not re.search(r"Extracted: [1-9]", out) and not quiet:
        sys.exit("%s failed (%d):\n%s" % (os.path.basename(exe), r.returncode, out[-1500:]))
    return out


def count(folder, ext=".ybn"):
    return sum(name.lower().endswith(ext) for _, _, names in os.walk(folder) for name in names)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 3:
        sys.exit(__doc__)
    gta, tools, work = (os.path.abspath(a) for a in args)
    rage, rpf, cache = (os.path.join(tools, n) for n in ("rage.exe", "sk8v-rpf.exe", "skatev-world-cache.exe"))
    for path in (os.path.join(gta, "GTA5.exe"), rage, rpf, cache):
        if not os.path.isfile(path):
            sys.exit("%s is not there" % path)
    keys, base, layers = (os.path.join(work, n) for n in ("keys", "base", "layers"))
    began = time.time()

    if not os.path.isfile(os.path.join(keys, "gtav_aes_key.dat")):
        os.makedirs(keys, exist_ok=True)
        run(rage, "--no-update-check", "--exe", os.path.join(gta, "GTA5.exe"), "extract-keys", "-o", keys)
    print("keys: read from GTA5.exe")

    def extract(archive, dest, *patterns):
        os.makedirs(dest, exist_ok=True)
        return run(rpf, "--keys", keys, "extract", archive, *patterns, "-o", dest, "--recursive", quiet=True)

    # the base game
    for name in sorted(os.listdir(gta)):
        if re.fullmatch(r"x64[a-z]\.rpf", name.lower()):
            dest = os.path.join(base, name)
            if not os.path.isdir(dest):
                extract(os.path.join(gta, name), dest + ".part", "*.ybn")
                os.rename(dest + ".part", dest)
            print("base %s: %d collision files" % (name, count(dest)), flush=True)

    # the update packs in the game's order, then update.rpf itself (it has the last word)
    update = os.path.join(gta, "update", "update.rpf")
    lists = os.path.join(work, "lists")
    extract(update, lists, "*common/data/dlclist.xml")
    found = [os.path.join(d, n) for d, _, names in os.walk(lists) for n in names if n.lower() == "dlclist.xml"]
    if not found:
        sys.exit("no dlclist.xml in update.rpf")
    packs = [m.lower() for m in re.findall(r"dlcpacks:[/\\]+([^/\\<]+)", open(found[0], encoding="utf-8", errors="replace").read())]
    order = []
    for i, pack in enumerate(packs):
        archive = os.path.join(gta, "update", "x64", "dlcpacks", pack, "dlc.rpf")
        if not os.path.isfile(archive):
            continue
        name = "%03d_%s" % (i, pack)
        dest = os.path.join(layers, name)
        if not os.path.isdir(dest):
            extract(archive, dest + ".part", "*.ybn", "content.xml", "setup2.xml")
            os.rename(dest + ".part", dest)
        if count(dest):
            order.append(name)
            print("pack %s: %d collision files" % (pack, count(dest)), flush=True)
    dest = os.path.join(layers, "999_update")
    if not os.path.isdir(dest):
        extract(update, dest + ".part", "*.ybn")
        os.rename(dest + ".part", dest)
    order.append("999_update")
    print("update.rpf: %d collision files" % count(dest), flush=True)
    with open(os.path.join(layers, "layers.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(order) + "\n")

    out = os.path.join(work, "collision.svwc")
    text = run(cache, out, "--layers", layers, base)
    print("\n".join(text.splitlines()[-12:]))
    if not os.path.isfile(out):
        sys.exit("no collision.svwc was written")
    print("%s: %.0f MB, %.0f minutes" % (out, os.path.getsize(out) / 1e6, (time.time() - began) / 60))
    if "--keep" not in sys.argv:
        for folder in (base, layers, lists):
            shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    main()
