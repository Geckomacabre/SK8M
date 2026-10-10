"""Build the LOCAL-ONLY FiveM resource `skate3_assets` from your own converted Skate 3 clips.

It contains the clip dictionaries converted from YOUR Skate 3 disc, so it must never be published or put on a
server other people join (FiveM sends streamed files to every connecting player).

usage: python build_fivem_assets.py [resources_dir] [--sounds]     (--sounds: convert the sounds again)
       (default output: ~\\skate3-extract\\fivem\\skate3_assets)
"""
import glob
import json
import os
import shutil
import sys

import build_board
import build_sounds
import build_tuning

import paths  # noqa: E402
SRC = paths.work(r"ycd_all")
JOYSTICK = paths.work(r"miscload\data\joystick")  # Skate 3's Flick-It gesture patterns
DEFAULT_OUT = paths.work(r"fivem")

MANIFEST = """fx_version 'cerulean'
game 'gta5'
lua54 'yes'

name 'skate3_assets'
description 'LOCAL ONLY - Skate 3 animations converted from your own disc. Do not publish or share.'

client_scripts { 'tracks/*.lua', 'clip_index.lua', 'flick_patterns.lua', 'tuning.lua', %(sounds)s%(decks)s's3_player.lua' }
%(files)s%(board)s"""
BOARD_FILES = """
-- Skate 3's own board: one model per deck, trucks and wheels (stream/s3_*.ydr), their archetypes, and the pictures
-- the skate shop's page shows (https://cfx-nui-skate3_assets/decks/...)
data_file 'DLC_ITYP_REQUEST' 'stream/s3_boards.ytyp'
-- (the server needs the parts' ids and prices too: it is the one that says who owns what)
server_scripts { 'decks.lua', 'decks_server.lua' }
files { 'decks/catalog.json', 'decks/thumbs/**/*.png', 'decks/preview/*.webp', 'decks/logos/*.png', 'decks/base/*.png' }
"""
SOUND_FILES = """
-- the sound player of the skateboard resource fetches these (https://cfx-nui-skate3_assets/sounds/...)
files { 'sounds/*.ogg' }
"""


def read_pat(path, prefix=''):
    """Skate 3 .pat file -> (global settings, [ {name, tol, coords} ]). Coordinates are raw stick values:
    x right = +, y DOWN = +. prefix: dropped from the pattern names (the sideways sets are named 90_Ollie ...)."""
    settings, patterns, cur = {}, [], None
    for line in open(path):
        parts = line.split()
        if not parts:
            continue
        if parts[0] == 'pattern':
            name = parts[1][len(prefix):] if prefix and parts[1].startswith(prefix) else parts[1]
            cur = {'name': name, 'tol': None, 'coords': []}
            patterns.append(cur)
        elif parts[0] == 'tolerance_dist' and cur:
            cur['tol'] = float(parts[1])
        elif parts[0] == 'coord' and cur:
            cur['coords'].append((float(parts[1]), float(parts[2])))
        elif parts[0].startswith('global_'):
            settings[parts[0][len('global_'):]] = float(parts[1])
    for p in patterns:
        p['tol'] = p['tol'] if p['tol'] is not None else settings.get('tolerance_dist', 0.4)
    return settings, patterns


def patterns_lua(sets):
    out = ["-- Skate 3's Flick-It gesture patterns (data/joystick/*.pat from your own disc). Each pattern is a path of",
           "-- stick positions the stick has to pass within `tol` of, in order; several patterns can share a name.",
           "-- Raw stick space: x right = +, y DOWN = +. ground = on the ground and on straight grinds, air = late",
           "-- flips, ground90 / groundN90 = sideways on a rail (the same gestures turned with the board), grab = finger",
           "-- flips (the right stick while grabbing), left = the LEFT stick's gestures (flips of the body, 180 slides).",
           "Skate3FlickPatterns = {"]
    for key, (settings, patterns) in sets.items():
        out.append(f"  {key} = {{ settings = {{ " + ", ".join(f"{k} = {v:g}" for k, v in sorted(settings.items()))
                   + " },")
        for p in patterns:
            coords = ", ".join(f"{{{x:.4f}, {y:.4f}}}" for x, y in p['coords'])
            out.append(f"    {{ name = '{p['name']}', tol = {p['tol']:g}, coords = {{ {coords} }} }},")
        out.append("  },")
    out.append("}")
    return "\n".join(out) + "\n"
TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fivem_template")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    out_root = args[0] if args else DEFAULT_OUT
    res = os.path.join(out_root, "skate3_assets")
    for sub in ("stream", "tracks"):
        os.makedirs(os.path.join(res, sub), exist_ok=True)
    for ycd in glob.glob(os.path.join(SRC, "*.ycd")):
        shutil.copy2(ycd, os.path.join(res, "stream", os.path.basename(ycd)))
    for lua in glob.glob(os.path.join(SRC, "*_board.lua")):
        shutil.copy2(lua, os.path.join(res, "tracks", os.path.basename(lua).replace("@", "_")))
    index = json.load(open(os.path.join(SRC, "clip_index.json")))
    with open(os.path.join(res, "clip_index.lua"), "w") as f:
        f.write("-- clip name -> animation dictionary\nSkate3ClipDict = {\n")
        for clip, d in sorted(index.items()):
            f.write(f'  ["{clip}"] = "{d}",\n')
        f.write("}\n")
    sets = {'ground': read_pat(os.path.join(JOYSTICK, 'skater.pat')),
            'air': read_pat(os.path.join(JOYSTICK, 'skater_air.pat')),
            'ground90': read_pat(os.path.join(JOYSTICK, 'skater90.pat'), '90_'),
            'groundN90': read_pat(os.path.join(JOYSTICK, 'skaterN90.pat'), 'N90_'),
            'grab': read_pat(os.path.join(JOYSTICK, 'skater_fingerflip.pat')),
            'left': read_pat(os.path.join(JOYSTICK, 'skaterls.pat'))}
    open(os.path.join(res, "flick_patterns.lua"), "w").write(patterns_lua(sets))
    tuning = build_tuning.write(os.path.join(res, "tuning.lua"))  # Skate 3's own tuning numbers (local only too)
    shutil.copy2(os.path.join(TEMPLATE, "s3_player.lua"), os.path.join(res, "s3_player.lua"))
    # Skate 3's own board sounds (local only too). Slow to convert, so an existing pack is kept: --sounds redoes it.
    have_sounds = os.path.exists(os.path.join(res, "sounds.lua")) and "--sounds" not in sys.argv
    if not have_sounds and os.path.isdir(build_sounds.AUDIO):
        build_sounds.write(res)
        have_sounds = True
    # Skate 3's own board (decks, trucks, wheels) when --no-board is not given: slow the first time, then only what changed
    have_board = "--no-board" not in sys.argv
    if have_board:
        board = build_board.main()
        for f in os.listdir(board["gta"]):
            shutil.copy2(os.path.join(board["gta"], f), os.path.join(res, "stream", f))
        for f in os.listdir(os.path.join(res, "stream")):   # (models of parts that are gone)
            if f.startswith("s3_") and not os.path.exists(os.path.join(board["gta"], f)):
                os.remove(os.path.join(res, "stream", f))
        shutil.copy2(board["lua"], os.path.join(res, "decks.lua"))
        open(os.path.join(res, "decks_server.lua"), "w").write(
            "-- Skate 3's board parts for server scripts (the same table the client export gives)\n"
            "exports('Decks', function() return Skate3Decks end)\n")
        shutil.copytree(os.path.join(board["web"], "decks"), os.path.join(res, "decks"), dirs_exist_ok=True)
    # Skate 3's own engine, when it has been built and staged (fivem/engine/tools/stage_web.py): the skateboard
    # resource's SERVER script runs it from this folder. Nothing in it is in the manifest, so none of it is ever
    # sent to a player.
    have_engine = (os.path.exists(os.path.join(paths.ENGINE, "sk8m_runtime.wasm"))
                   and os.path.exists(os.path.join(paths.ENGINE, "data", "files.json")))
    # (the baked map, fivem/engine/tools/bake_collision.py, is put beside the engine by hand and is 600 MB: it is
    # kept through a build)
    world, aside = os.path.join(res, "engine", "world.sk8w"), os.path.join(res, "world.sk8w.kept")
    if os.path.exists(world):
        os.replace(world, aside)
    shutil.rmtree(os.path.join(res, "engine"), ignore_errors=True)
    if have_engine:
        os.makedirs(os.path.join(res, "engine"))
        shutil.copy2(os.path.join(paths.ENGINE, "sk8m_runtime.wasm"), os.path.join(res, "engine", "sk8m_runtime.wasm"))
        shutil.copytree(os.path.join(paths.ENGINE, "data"), os.path.join(res, "engine", "data"))
        for folder, _, names in os.walk(os.path.join(res, "engine", "data")):   # (empty files are not served:
            for name in names:                                                  # the page makes those itself)
                if os.path.getsize(os.path.join(folder, name)) == 0:
                    os.remove(os.path.join(folder, name))
    if os.path.exists(aside):
        os.makedirs(os.path.join(res, "engine"), exist_ok=True)
        os.replace(aside, world)
    if os.path.exists(os.path.join(res, "engine.lua")):      # (of the build that ran the engine in the page)
        os.remove(os.path.join(res, "engine.lua"))
    open(os.path.join(res, "fxmanifest.lua"), "w").write(MANIFEST % {
        "sounds": "'sounds.lua', " if have_sounds else "",
        "decks": "'decks.lua', " if have_board else "",
        "board": BOARD_FILES if have_board else "",
        "files": SOUND_FILES if have_sounds else ""})
    open(os.path.join(res, "README_LOCAL_ONLY.txt"), "w").write(
        "Generated from your own Skate 3 disc by skate3-sp/tools. Keep this resource private:\n"
        "do not upload it, and do not run it on a server other people can join.\n")
    print("built", res, "with", len(glob.glob(os.path.join(res, "stream", "*.ycd"))), "dictionaries,",
          len(index), "clips,", len(tuning["scoring"]["base"]), "trick scores,", len(tuning["camera"]["shots"]),
          "camera shots,", len(glob.glob(os.path.join(res, "sounds", "*.ogg"))), "sound files")


if __name__ == "__main__":
    main()
