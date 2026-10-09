# SK8M

**Skate 3's skating, in FiveM.**

SK8M brings *Skate 3*'s Flick-It controls, tricks, grinds, grabs, manuals, skitching, bails and its own animations to
GTA V multiplayer as a FiveM resource written in Lua. It is a fork of [SK8V](https://github.com/becaring/SK8V), which
runs Skate 3's engine inside GTA V **Story Mode**. SK8V does not support FiveM; SK8M is the FiveM side.

Everything SK8M adds is in [`fivem/`](fivem). The rest of this repository is SK8V's source, unchanged.

## You need your own Skate 3

**No Skate 3 or GTA V assets are in this repository**: no animations, sounds, models, textures, tuning numbers,
executables or keys. As with SK8V, you supply your own copies of both games, and everything taken from them is
converted on your machine and stays there.

SK8M reads a **Skate 3 PS3 disc dump** (the `PS3_GAME` folder). SK8V itself uses the Xbox 360 disc.

## What is in `fivem/`

| Folder | What it is |
|---|---|
| [`fivem/skateboard`](fivem/skateboard) | The FiveM resource. New code only, safe to share. It runs by itself with GTA's stock animations. Controls, install and settings are in its [README](fivem/skateboard/README.md). |
| [`fivem/skate3-sp/tools`](fivem/skate3-sp/tools) | The converters. From your own disc they build a second, **private** resource, `skate3_assets`: Skate 3's clips as GTA clip dictionaries, its Flick-It gesture patterns, tuning numbers, board sounds and board models. |
| [`fivem/skate3-sp/fivem_template`](fivem/skate3-sp/fivem_template) | The player script that goes into `skate3_assets`. |
| [`fivem/skate3-sp/tests`](fivem/skate3-sp/tests) | Offline tests: both resources run in a simulator (Python + Lua 5.4) that checks every native call against FiveM's native reference. |
| [`fivem/TRICKS.md`](fivem/TRICKS.md) | Which of Skate 3's tricks are built. |

With `skate3_assets` running beside `skateboard`, the rider plays Skate 3's own clips. Without it, `skateboard` still
works on its own.

**Keep `skate3_assets` private.** It is made from your disc. A FiveM server sends its resources to every player who
joins, so do not upload it and do not run it on a server for people who do not own the game.

## Install the resource

1. Copy `fivem/skateboard` into your server's `resources` folder.
2. Add `ensure skateboard` to `server.cfg` and restart.

The rest (the inventory item, the skate shop, controls, settings) is in the resource's
[README](fivem/skateboard/README.md).

## Build `skate3_assets` from your own disc

Windows, Python 3.11 or newer with `lupa`, `numpy` and `Pillow`, and `ffmpeg` on the path.
Run the commands from `fivem/skate3-sp`.

1. Put your disc dump's `PS3_GAME` folder at `fivem/PS3_GAME` (git ignores it).
2. Copy `fivem/skate3-sp/tools/local_paths.example.json` to `local_paths.json` and set your folders. What each one is
   for is explained in [`paths.py`](fivem/skate3-sp/tools/paths.py).
3. Dump the game's tuning vault: `python tools/vlt/vlt_parse.py --dump <work>\vlt\dump`.
4. Convert the clips: `python tools/export_all.py`.
5. Build the resource: `python tools/build_fivem_assets.py`. It is written to `<work>\fivem\skate3_assets`.
6. Copy `skate3_assets` to your own server and `ensure` it before `skateboard`.

Each tool says what it reads and writes at the top of its file.

### Not in the repository yet

Two inputs of step 4 have no tool here, so the build does not run end to end from a fresh clone:

- **The animation decoder.** `export_all.py` reads Skate 3's clip banks (`OnBoard.abin`, `OffBoard.abin`) already
  decoded to CSV (`onboard_csv`, `offboard_csv` and their `*_meta.csv` in the work folder). The decoder is not
  included.
- **GTA's skeleton.** `s3_to_ycd.py` reads `tools/gta_ped_rig.json`: the rest pose of the ped skeleton (`player_one`)
  from your own GTA V. Per bone it holds `name`, `tag`, `parent`, `head`, `world_q`, `local_q`, `local_t`, in the
  armature space of a Sollumz import in Blender. An exporter is not included.

Compiling clip dictionaries and models needs a command-line wrapper around CodeWalker.Core (`cwtool` in
`local_paths.json`). The tools send it one JSON command on standard input, for example
`{"cmd": "tobin", "in": "<file>.ycd.xml"}`.

## How the animations are fitted

Skate 3's skeleton and GTA's have their joints at different places in the body. Copying bone rotations alone leaves
the hips 8 cm low, every sole tipped 11 degrees into the deck and a grabbing hand 10 cm from the board. The converter
fits the GTA body with the method of SK8V's `rust/skatev-runtime/src/ped.rs`: GTA keeps its own bone lengths, the hip
joints go where Skate 3's are, the feet stay flat, each ankle is put on Skate 3's by a two-bone solve, and a hand is
put on Skate 3's while it touches the board or the ground. `tests/retarget_fit.py` measures the result against Skate
3's own joints.

## Tests

From `fivem/skate3-sp/tests`, with `skate3_assets` built:

```powershell
python ridetest.py
python retarget_fit.py
python ycd_roundtrip.py
```

`ridetest.py [scenario ...]` runs the ride scenarios. The simulator needs FiveM's native reference
(`fivem_natives.json`, `fivem_natives_cfx.json`) in the folder named `native_db` in `local_paths.json`.

## Status

Work in progress. The ride, the trick families listed in `TRICKS.md`, grinds, grabs, ramps and bowls, the off-board
mode and the skate shop are built and pass the offline tests. Not all of it has been checked in the game yet.

## License

SK8M's own code (the `fivem/` folder) is [Apache-2.0](LICENSE), like SK8V. Third-party components keep their own
licenses and are credited in [NOTICE](NOTICE).

SK8M is an unofficial fan project, unaffiliated with EA, Rockstar Games, or Take-Two Interactive. No GTA V or Skate 3
retail assets, executables, keys, or proprietary SDK redistributables are included; supply your own game copies.

## Credits

- [SK8V](https://github.com/becaring/SK8V) by becaring: the project this is forked from, and the source of the body
  fitting method and of the ground material sorting used here. For Story Mode, use SK8V.
- Everyone credited in SK8V's [NOTICE](NOTICE).
- The Skate-Modding-Team's published vault key list, which names most of the tuning fields the vault parser reads.
