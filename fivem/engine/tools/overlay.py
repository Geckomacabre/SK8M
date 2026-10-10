"""The engine's source as the runtime builds it: the fetched crates, copied, with SK8V's patches and then this
project's patches applied; and beside it the files of SK8V's own runtime that this one builds in.

upstream/ is never edited. overlay/skate is made again from upstream/2010-rust-rewrite-mashup/skate each time. Onto
it go, in name order, SK8V's own changes to the engine (patches/skate at the top of this repository: moving
geometry, seams, steps, lips, skitching, what the host is told for sounds and the HUD ...) and then every
patches/*.patch of this folder (the way SK8V builds its own overlay). runtime/Cargo.toml points at the overlay.

overlay/sk8v gets the parts of SK8V's runtime (rust/skatev-runtime/src) that turn GTA's collision triangles into
a world for the engine: the grind rails found in them, ramp toes, doubled faces, the material table. overlay/svwc
gets SK8V's reader of its collision file (rust/svwc). bake/ builds both in.

SK8V is looked for in sk8v/ beside this folder's tools/ (a link, for a copy of this folder kept outside the
repository) and then at the top of the repository this folder is in.

usage: python overlay.py            (prints the patches applied)
       python overlay.py --diff     (prints the overlay's difference from the engine with SK8V's patches as a
                                     patch: how this folder's patches are made)
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SOURCE = os.path.join(ROOT, "upstream", "2010-rust-rewrite-mashup", "skate")
DEST = os.path.join(ROOT, "overlay", "skate")
PATCHES = os.path.join(ROOT, "patches")
SK8V = [os.path.join(ROOT, "sk8v"), os.path.join(ROOT, "..", "..")]
SK8V_SOURCES = ["rails.rs", "curbs.rs", "grid.rs", "plies.rs", "materials.rs"]


def git(args, cwd):
    # (the overlay may sit inside a repository: git must not look above it, or that repository's line-ending rules
    # rewrite the copied sources and the patches stop applying)
    env = dict(os.environ, GIT_CEILING_DIRECTORIES=os.path.dirname(cwd))
    return subprocess.run(["git"] + args, cwd=cwd, env=env, capture_output=True, text=True)


def listed(folder):
    return [os.path.join(folder, f) for f in sorted(os.listdir(folder)) if f.endswith(".patch")]


def make(dest, patches):
    shutil.rmtree(dest, ignore_errors=True)
    os.makedirs(dest)
    shutil.copy2(os.path.join(SOURCE, "Cargo.toml"), dest)
    shutil.copytree(os.path.join(SOURCE, "crates"), os.path.join(dest, "crates"))
    for patch in patches:
        r = git(["apply", "--whitespace=nowarn", "-p1", patch], dest)
        if r.returncode != 0:
            sys.exit("patch %s does not apply:\n%s" % (os.path.basename(patch), r.stderr))


def main():
    if not os.path.isdir(os.path.join(SOURCE, "crates")):
        sys.exit("%s is not there: fetch the engine's sources first (README)" % SOURCE)
    sk8v = next((folder for folder in SK8V if os.path.isdir(os.path.join(folder, "patches", "skate"))), None)
    if not sk8v:
        sys.exit("SK8V is not there (patches/skate, rust/skatev-runtime): looked in %s" % " and ".join(os.path.normpath(f) for f in SK8V))
    theirs = listed(os.path.join(sk8v, "patches", "skate"))
    if "--diff" in sys.argv:
        with tempfile.TemporaryDirectory() as scratch:
            base = os.path.join(scratch, "skate")
            make(base, theirs)
            r = subprocess.run(["git", "diff", "--no-index", "--no-color", os.path.join(base, "crates"), os.path.join(DEST, "crates")],
                               capture_output=True, text=True, encoding="utf-8")
        # (git names the two folders in full, quoted: the patch has to name files inside the engine's own tree)
        def inside(match):
            return match.group(1) + "/crates/" + match.group(2)
        out = []
        for line in r.stdout.splitlines():
            if line.startswith(("diff --git ", "--- ", "+++ ")):
                line = re.sub(r'"?([ab])/[^"\n]*?crates/([^"\s]+)"?', inside, line)
            out.append(line)
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
        sys.stdout.write("\n".join(out) + "\n")
        return
    ours = listed(PATCHES) if os.path.isdir(PATCHES) else []
    make(DEST, theirs + ours)
    parts = os.path.join(ROOT, "overlay", "sk8v")
    shutil.rmtree(parts, ignore_errors=True)
    os.makedirs(parts)
    for name in SK8V_SOURCES:
        shutil.copy2(os.path.join(sk8v, "rust", "skatev-runtime", "src", name), parts)
    shutil.rmtree(os.path.join(ROOT, "overlay", "svwc"), ignore_errors=True)
    shutil.copytree(os.path.join(sk8v, "rust", "svwc"), os.path.join(ROOT, "overlay", "svwc"),
                    ignore=shutil.ignore_patterns("target", "examples"))
    for patch in ours:
        print("patched:", os.path.basename(patch))
    print("overlay ready: %s (%d patches of SK8V, %d of this folder)" % (DEST, len(theirs), len(ours)))


if __name__ == "__main__":
    main()
