# The engine

Skate 3's own engine, built as one WebAssembly file so that a FiveM server can run it.

FiveM's in-game browser has WebAssembly switched off, so the engine cannot run on the player's side. It runs on
the server (`fivem/skateboard/engine_server.js`): the player's game sends its pad and the ground round the board,
the server sends back where the board is. The game's data stays on the server and is never sent to players.

The world the board rides is GTA's own collision, baked once from the server owner's GTA V into one file with
SK8V's tools: kerbs are kerbs, and ledges, kerb edges and handrails are grind rails.

The engine is not ours and is not copied here. It is the Rust rewrite of Skate 3's skating that
[SK8V](https://github.com/becaring/SK8V) builds on: `skate-core`, `skate-data` and `skate-host` from
[2010-rust-rewrite-mashup](https://github.com/chasmlol/2010-rust-rewrite-mashup) by chasmlol (Apache-2.0), with the
data export tools of [skate-3-rust-engine](https://github.com/SK8-ENGINE/skate-3-rust-engine). This folder holds
what is needed to run it somewhere new:

| Folder | What it is |
|---|---|
| `runtime/` | The engine behind a small C interface (load a rider, tick with a pad, read the pose), compiled to WebAssembly. One instance carries any number of riders. |
| `bake/` | `sk8m-bake`: GTA's collision made ready for the engine, for the whole map at once. It is SK8V's area build (its rail finder, ramp toes, doubled faces and material table, built in from SK8V's own files) run ahead of time, because a FiveM server has one thread and cannot do it while people ride. |
| `shim/` | Stand-ins for crates the engine names but does not need through that interface: `bevy` (it uses the math types, `Transform`, log macros and one derive), `zstd` (its own map files) and `socket2` (its network sockets); and `bevy_math` (glam's vectors) for SK8V's geometry files. |
| `web/` | A desktop browser has WebAssembly, so the engine can be watched there: `wasi_mem.js` (the 14 system calls the engine makes, over files held in memory), `engine.js` (loads the engine and its data), `ground.js` (a grid of heights as triangles), `index.html` (a test page that draws the board and the rider's bones). |
| `tools/` | `overlay.py`: copies the fetched engine and applies SK8V's 43 patches (`patches/skate` at the top of this repository) and then `patches/` to the copy, which is what the runtime builds. `engine_data.py`: makes the engine's data folder from your own disc. `stage_web.py`: puts the build and the data where the page loads them. `bake_collision.py`: bakes the map from your own GTA V. |
| `patches/` | This project's changes to the engine, applied after SK8V's, one patch each. So far one: the engine keeps the list of clips its pose was blended from, so that a host can ask for it. |
| `probe/` | The engine run natively on a flat floor with a scripted pad, as a check of the data and the toolchain. |
| `test/` | Under Node: the same scripted ride on the WebAssembly build (`ride_*.mjs`), ground handed over as a grid (`ground_node.mjs`), the clips the engine plays through a ride (`clips_node.mjs`), which end of the engine's board is the nose (`nose_node.mjs`), the server script itself with FiveM stood in for (`server_node.cjs`), and the server script on a baked map (`world_node.cjs`: on a map the test writes itself, and on your real one at a place you name). |

## Where this stands

- The engine loads the data of a **PS3** disc and rides: three pushes take it to 8.5 m/s, the left stick carves, a
  flick of the right stick pops an ollie 1.2 m up and it lands. The native build, the WebAssembly build under Node
  and the WebAssembly build in a browser give the same numbers.
- One tick takes about 1.5 ms. The engine runs 60 ticks a second.
- It reads 18 files of the game's data, about 26 MB.
- The engine is built with SK8V's 43 patches (moving geometry, seams, steps, ramp lips, skitching, what a host is
  told for sounds and a HUD ...). The scripted ride gives the same numbers with them as without. Of what they add
  for a host, only the surface tags and the no-grind mark of the map are used so far.
- In FiveM: the server script runs it (riders are made when the resource starts, ten seconds each, and used
  again and again), the player's script sends the pad and draws the board and the camera from the answers.
- The map: `world.sk8w`, baked from GTA V (54.8 million triangles and 1.02 million rails for the whole map, 630 MB,
  five minutes to make). A rider has the 56 m square of it round the board and gets a new piece when the board
  comes within 14 m of its edge. A new piece takes the engine 40 to 100 ms in a town (it welds the corners and
  finds every edge's neighbour), and the server's one thread does nothing else meanwhile: every rider at speed
  stalls the server that long every two or three seconds. The player's game carries the board on by its speed
  through the gap. This is the first thing to make better (the engine on a thread of its own, or a cheaper
  build). It is the map of Story Mode. Where a player's game finds the ground
  somewhere else (a map the server adds, a place only Online changes), that rider's ground is from then on a grid
  of heights their game finds with rays, as it is on a server with no baked map: there a kerb is a ramp and
  nothing grinds. This passes its checks outside the game and has not been ridden in the game yet.
- Not in the world yet: props, vehicles and people (SK8V hands those to the engine every frame). The board goes
  through them.
- The rider: a FiveM script cannot set a ped's bones, so the engine's own pose (several clips blended, with the
  feet and hands placed on top) cannot be shown. The server sends the name of the clip that has most of the pose
  and the time in it; the player's script holds the converted clip of `skate3_assets` at that time and stands the
  ped where that clip has the board. This passes its checks outside the game and has not been watched in the
  game yet.
- FXServer runs a script's timers about 20 times a second, so the answers reach a player 20 times a second (the
  engine still makes its 60 ticks).

Not done yet: blending between clips and smoothing between answers, other players seeing the board, props and
vehicles in the engine's world, and the rest of what SK8V's patches give a host (sounds from the engine, the
score, skitching).

## Build

You need [Git](https://git-scm.com/downloads), [Rust](https://rustup.rs/) 1.98.1,
[Node.js](https://nodejs.org/) 22 or newer, Python 3.11 or newer, and your own Skate 3 disc files.

```bat
git init upstream\2010-rust-rewrite-mashup
git -C upstream\2010-rust-rewrite-mashup fetch --depth 1 https://github.com/chasmlol/2010-rust-rewrite-mashup ab43b8a9e923bdc4ad7effb874f6efec155577f1
git -C upstream\2010-rust-rewrite-mashup checkout FETCH_HEAD

git init upstream\skate-3-rust-engine-donor
git -C upstream\skate-3-rust-engine-donor fetch --depth 1 https://github.com/SK8-ENGINE/skate-3-rust-engine cb7968930f14dad38457e98720d1a274e469eec2
git -C upstream\skate-3-rust-engine-donor checkout FETCH_HEAD

python tools\overlay.py

rustup target add wasm32-wasip1
cd runtime
cargo build --release --target wasm32-wasip1
cd ..

python tools\engine_data.py <your PS3_GAME\USRDIR> <a work folder>
python tools\stage_web.py <the work folder>\assets runtime\target\wasm32-wasip1\release\sk8m_runtime.wasm
```

Those are the revisions SK8V pins. `overlay.py` leaves `upstream/` as fetched and makes `overlay/`, the copy with
SK8V's patches and `patches/` applied; run it again after changing a patch. The last command runs the engine once and prints its top speed and the height of
its ollie (10.637 m/s and 1.257 m on a US PS3 disc).

To see it, serve `web/` from a local web server (`python -m http.server --directory web`) and open the page.
W pushes, A and D steer, the arrow keys are the right stick. A controller works as it does in Skate 3.

## Bake the map

Once, on a PC with GTA V (Legacy) installed. It needs three of SK8V's tools: `rage.exe` (reads the archive keys
out of your own `GTA5.exe`), `sk8v-rpf.exe` (takes the collision files out of the archives) and
`skatev-world-cache.exe` (makes them one tiled file). SK8V's own setup builds them (`BOOTSTRAP.bat` at the top of
this repository, which also builds the Story Mode plugin and needs Visual Studio's C++ tools and CMake). To build
only these three, from the top of the repository, after the engine build above:

```bat
for %r in (rage-formats:0488fc99d2d911c4da59288e1286a559e2bc7d45 rpf-archive-rs:edd77588ed7fcf3cdd51949e7d3e647204c76036 rage-cli:d87aa3d6539ba9c98ebbcdce273317172663d67c rage-render:b62485d3e0172d8e2bbcfda5d00c59630bdf65f1) do for /f "tokens=1,2 delims=:" %a in ("%r") do git init upstream\%a && git -C upstream\%a fetch --depth 1 https://github.com/VIRUXE/%a %b && git -C upstream\%a checkout FETCH_HEAD

cargo build --release --manifest-path upstream\rage-cli\Cargo.toml --config "patch.crates-io.rpf-archive.path='upstream/rpf-archive-rs'" --config "patch.crates-io.rage-formats.path='upstream/rage-formats'" --config "patch.crates-io.rage-render.path='upstream/rage-render'"

mkdir build\overlay
mklink /J build\overlay\skate fivem\engine\overlay\skate
cd rust
cargo build --release -p skatev-world-cache -p gta-archives
cd ..
```

(Those four are the revisions SK8V pins in `upstreams.lock.json`. The link is there because SK8V's Rust workspace
names its own copy of the patched engine; the two tools do not use it.) Put `rage.exe` (from
`upstream\rage-cli\target\release`), `sk8v-rpf.exe` and `skatev-world-cache.exe` (from `rust\target\release`) in
one folder. Then:

```bat
cd fivem\engine
python tools\bake_collision.py "<your GTA V folder>" <the folder with the three tools> <a work folder>
cd bake
cargo build --release
target\release\sk8m-bake <the work folder>\collision.svwc <the work folder>\world.sk8w
```

The first takes about two minutes and three gigabytes of the work folder (given back at the end), the second three
minutes. Put `world.sk8w` into `skate3_assets\engine\` on the server (a build of `skate3_assets` keeps it there),
or anywhere and `set skateboard_engine_world "<the file>"` in server.cfg. The server reads the tiles round each
rider from it; it is never sent to a player. `node test\world_node.cjs ..\skateboard\engine_server.js
<skate3_assets> <world.sk8w> <x> <y> <z>` puts a rider on it at a place of yours and prints what happens.

## The data stays private

`web/data` is made from your disc, like `skate3_assets`, and `world.sk8w` from your GTA V. Both are ignored by git.
Do not upload them.

## The interface

All numbers are in Skate 3's space: metres, y up.

Every call but the last names a rider by a number the host picks.

| Call | What it does |
|---|---|
| `sk8m_load(id, root, triangles, rails, place, heading)` | A rider: loads the data folder and builds their world from triangles (9 floats each) and grind rails (lists of points). About ten seconds. |
| `sk8m_world(id, triangles, rails)` | Replaces the rider's world. About 4 ms for 3200 triangles. |
| `sk8m_area(id, triangles, tags, count, rails)` | Replaces the rider's world with a piece of the baked map: triangles and rails in GTA's axes (z up) from the place the rider's space starts at, and the engine's surface tag for each triangle. |
| `sk8m_place(id, x, y, z, heading)` | Puts the rider somewhere, standing. |
| `sk8m_tick(id, buttons, lt, rt, lx, ly, rx, ry)` | One tick (1/60 s) with the pad as XInput reports it. |
| `sk8m_pose(id, out)` | The board's place in the world (a matrix), its velocity, the engine's camera, and every bone of the rider against the board. |
| `sk8m_clips(id, out)` | The clips this tick's pose is blended from, the largest share first: name, time in the clip, share, whether it is played mirrored. For a host that cannot set bones and plays the clips itself. |
| `sk8m_close(id)` | The rider is done with. |
| `sk8m_state`, `sk8m_bone_names`, `sk8m_error` | What the rider is doing, the bones' names, why a call failed. |
