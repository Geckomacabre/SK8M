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
| [`fivem/skate3-sp/cwtool`](fivem/skate3-sp/cwtool) | A small command-line program around CodeWalker's file library, used to write the files GTA V loads. |
| [`fivem/engine`](fivem/engine) | Skate 3's own engine (the one SK8V runs) built as WebAssembly. The FiveM server runs it; getting on the board uses it when the server has it. |
| [`fivem/TRICKS.md`](fivem/TRICKS.md) | Which of Skate 3's tricks are built. |
| [`fivem/GUIDE.md`](fivem/GUIDE.md) | Step by step: installing the resource and building `skate3_assets`. |

With `skate3_assets` running beside `skateboard`, the rider plays Skate 3's own clips. Without it, `skateboard` still
works on its own.

**Keep `skate3_assets` private.** It is made from your disc. A FiveM server sends its resources to every player who
joins, so do not upload it and do not run it on a server for people who do not own the game.

## Getting started

**[The guide](fivem/GUIDE.md)** walks through everything, from an empty server to riding:

1. **The `skateboard` resource**: copy `fivem/skateboard` into your server's `resources` folder and add
   `ensure skateboard` to `server.cfg`. Ten minutes, no Skate 3 files needed.
2. **`skate3_assets`**: built once from your own Skate 3, about an hour the first time. The guide lists the tools it
   needs and where to get each of them.

Not in the repository yet: the step that catalogues Skate 3's own deck, truck and wheel models. Until it is,
`skate3_assets` is built without them and the rider uses GTA's skateboard prop.

## The real engine, in FiveM

SK8V is further along than this resource because it does not rewrite Skate 3's skating: it runs the game's own
logic, rebuilt in Rust by chasmlol, and gives it GTA's world. SK8V does that through hooks into the game's
executable, which a FiveM resource cannot use. The engine itself has no such limit. [`fivem/engine`](fivem/engine)
builds it as one WebAssembly file, and that is where this project is heading: the resource's own Lua physics and
trick logic give way to the engine's.

FiveM's in-game browser has WebAssembly switched off, so the engine runs on the **server**. A player's game sends
its pad; the server sends back where the board is. The Skate 3 data the engine reads stays on the server and is
never sent to players.

The engine is built with SK8V's own 43 patches to it, and the world it rides is GTA's own collision: the server
owner bakes the map once from their GTA V with SK8V's tools, with SK8V's rail finder run over all of it, so a
kerb is a kerb and ledges and handrails grind. Where a player's game finds the ground somewhere else than the
baked map has it (a map the server adds), the ground is a grid of heights that game finds with rays.

Done: the engine loads a PS3 disc's data and rides (pushes, carving, ollies) with identical results natively,
under Node and in a browser; the server script runs it for several riders; getting on the board starts it
(`Config.Engine`), and it has been ridden through Los Santos on a live server on the rays' ground. The baked map
and the rider playing the clip the engine names pass their checks outside the game and have not been watched in
the game yet. To do: blending between clips, smoothing between the server's answers (FXServer sends them 20
times a second), props and vehicles in the engine's world, sounds and score from the engine, other players
seeing the board.

Three things differ from SK8V. A FiveM script cannot set a character's bones, so the rider is shown by playing
the converted clips the engine picks, not its exact blended pose. GTA's collision is baked ahead of time instead
of being read from the running game, so it is Story Mode's map and has no props in it. And what a player does
reaches the engine over the network, a few hundredths of a second plus their ping later.

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
