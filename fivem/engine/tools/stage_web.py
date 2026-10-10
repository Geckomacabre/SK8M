"""Put the built engine and the data files it reads where the browser page (and later the FiveM resource) loads them.

Runs the engine once under Node on the in-memory file layer (test/ride_mem.mjs): that checks the build rides, and
lists the files the engine really opens (18 of the 2,000 in the data folder, about 26 MB). Those are copied to
web/data with their list (files.json), and the .wasm to web/.

usage: python stage_web.py <assets folder> <sk8m_runtime.wasm>
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WEB = os.path.join(ROOT, "web")


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    assets, wasm = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    listing = os.path.join(tempfile.mkdtemp(), "files.json")
    r = subprocess.run(["node", "--no-warnings", os.path.join(ROOT, "test", "ride_mem.mjs"), wasm, assets, listing],
                       capture_output=True, text=True)
    print(r.stdout.strip().splitlines()[0] if r.stdout.strip() else r.stderr[-2000:])
    if r.returncode != 0 or not os.path.exists(listing):
        sys.exit("the engine did not run: " + r.stderr[-2000:])
    files = json.load(open(listing))
    real = {}
    for folder, _, names in os.walk(assets):
        for name in names:
            rel = os.path.relpath(os.path.join(folder, name), assets).replace(os.sep, "/")
            real[rel.lower()] = rel
    data = os.path.join(WEB, "data")
    shutil.rmtree(data, ignore_errors=True)
    total = 0
    for f in files:
        dst = os.path.join(data, f["path"])
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(os.path.join(assets, real[f["path"]]), dst)
        total += f["bytes"]
    json.dump(files, open(os.path.join(data, "files.json"), "w"))
    shutil.copy2(wasm, os.path.join(WEB, "sk8m_runtime.wasm"))
    print("%d files, %.1f MB, and the engine (%.1f MB) staged in %s" % (
        len(files), total / 1e6, os.path.getsize(wasm) / 1e6, WEB))


if __name__ == "__main__":
    main()
