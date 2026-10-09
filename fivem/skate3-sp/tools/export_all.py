"""Convert every decoded Skate 3 on-board clip into GTA clip dictionaries, grouped by family, and compile them.

Dictionary names: skate3@<family> (e.g. skate3@g for grinds). Everything is written under
~\\skate3-extract\\ycd_all (local only, never shipped).

usage: python export_all.py [family ...]      (no arguments = every family; e.g. `export_all.py r mirror`)
"""
import csv
import json
import os
import subprocess
import sys

import s3_to_ycd

import paths  # noqa: E402
OUT = paths.work(r"ycd_all")
CWTOOL = paths.CWTOOL
SKATEBOARD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "skateboard")
FLIPS = ('OLLIE', 'NOLLIE', 'KICKFLIP', 'HEELFLIP', 'POPSHUVIT', 'FSPOPSHUVIT', '360FLIP', 'VARIALKICKFLIP',
         'VARIALHEELFLIP', 'HARDFLIP', '360HARDFLIP', 'INWARDHEELFLIP', '360INWARDHEELFLIP', 'LASERFLIP',
         '360POPSHUVIT', 'FS360POPSHUVIT', 'FAKIE')


def controller_clips():
    """Every clip the skateboard controller can play (skateboard/s3.lua, S3.clipNames), upper case. Read from the
    Lua itself so the asset build and the controller cannot drift apart."""
    from lupa import lua54
    lua = lua54.LuaRuntime(unpack_returned_tuples=True)
    for name in ('config.lua', 's3.lua'):
        lua.execute(open(os.path.join(SKATEBOARD, name), encoding='utf-8').read())
    return sorted({str(n).upper() for n in lua.eval('S3.clipNames()').values()})


def family(name):
    p = name.split('_')[0]
    if name.startswith('GR_'):
        return 'gr'
    if p in FLIPS:
        return 'flip'
    if p in ('R', 'G', 'B', 'T', 'M', 'L', 'N', 'W', 'F', 'PRO', 'TKDWN', 'INVERT'):
        return p.lower()
    return 'misc'


def main():
    meta = list(csv.DictReader(open(s3_to_ycd.META)))
    groups = {}
    for r in meta:
        if r['name'] == 'RIG_TPOSE':
            continue
        groups.setdefault(family(r['name']), []).append(r['name'])
    groups['r'] += list(s3_to_ycd.SWEEPS)  # baked riding blends (lean scrub clips)
    groups['r'] += s3_to_ycd.step_names()  # the same blends as static poses (plain clips sync to other players)

    # Skate 3's on-board clips are authored GOOFY (right foot forward; skate3-sp/tests/handedness.py) and the game
    # plays them left-right mirrored for the other stance. Everything the controller plays gets a mirrored copy,
    # <clip>_mir in the dictionary skate3@mirror: that is what a REGULAR rider plays. Gestures (B_GSTR) only move
    # the arms and are not mirrored.
    have = {c for clips in groups.values() for c in clips}
    played = controller_clips()
    # the off-board bank (standing, walking, running with the board in the hand, getting off and on): only the clips
    # the controller plays are converted, into the dictionary skate3@ob
    off = set(s3_to_ycd.load_off_meta())
    groups['ob'] = [c for c in played if c in off and c not in have]
    have |= set(groups['ob'])
    missing = [c for c in played if c not in have]
    if missing:
        sys.exit(f"skateboard/s3.lua plays {len(missing)} clips that are not in the Skate 3 data: {' '.join(missing[:12])}")
    groups['mirror'] = [c + s3_to_ycd.MIRROR_SUFFIX for c in played if not c.startswith('B_GSTR_')]
    print(f"controller plays {len(played)} clips, {len(groups['mirror'])} get a mirrored copy", flush=True)

    only = set(sys.argv[1:])
    # a partial run (only some families) keeps the index entries of the others
    index_path = os.path.join(OUT, 'clip_index.json')
    index = {}
    if only and os.path.exists(index_path):
        index = {c: d for c, d in json.load(open(index_path)).items() if d[len('skate3@'):] not in only}
    failed = []
    for fam, clips in sorted(groups.items()):
        if only and fam not in only:
            continue
        dict_name = 'skate3@' + fam
        xml, _ = s3_to_ycd.convert(dict_name, clips, OUT)
        r = subprocess.run([CWTOOL], input=json.dumps({"cmd": "tobin", "in": xml}), capture_output=True, text=True)
        res = json.loads(r.stdout or '{}')
        good = res.get("ok", res.get("output") is not None)
        print(f'{dict_name}: {len(clips)} clips, ok={good} '
              f'bytes={res.get("bytes_out")} {res.get("error", "")[:200]}', flush=True)
        if not good:
            failed.append(dict_name)
        for c in clips:
            index[c.lower()] = dict_name
    json.dump(index, open(index_path, 'w'), indent=0)
    if failed:
        sys.exit("FAILED to compile: " + " ".join(failed))


if __name__ == '__main__':
    main()
