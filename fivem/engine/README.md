# The engine

Skate 3's own engine, built as one WebAssembly file so that a FiveM server can run it.

FiveM's in-game browser has WebAssembly switched off, so the engine cannot run on the player's side. It runs on
the server (`fivem/skateboard/engine_server.js`): the player's game sends its pad and the ground round the board,
the server sends back where the board is. The game's data stays on the server and is never sent to players.

The engine is not ours and is not copied here. It is the Rust rewrite of Skate 3's skating that
[SK8V](https://github.com/becaring/SK8V) builds on: `skate-core`, `skate-data` and `skate-host` from
[2010-rust-rewrite-mashup](https://github.com/chasmlol/2010-rust-rewrite-mashup) by chasmlol (Apache-2.0), with the
data export tools of [skate-3-rust-engine](https://github.com/SK8-ENGINE/skate-3-rust-engine). This folder holds
what is needed to run it somewhere new:

| Folder | What it is |
|---|---|
| `runtime/` | The engine behind a small C interface (load a rider, tick with a pad, read the pose), compiled to WebAssembly. One instance carries any number of riders. |
| `shim/` | Stand-ins for three crates the engine names but does not need through that interface: `bevy` (it uses the math types, `Transform`, log macros and one derive), `zstd` (its own map files) and `socket2` (its network sockets). |
| `web/` | A desktop browser has WebAssembly, so the engine can be watched there: `wasi_mem.js` (the 14 system calls the engine makes, over files held in memory), `engine.js` (loads the engine and its data), `ground.js` (a grid of heights as triangles), `index.html` (a test page that draws the board and the rider's bones). |
| `tools/` | `engine_data.py`: makes the engine's data folder from your own disc. `stage_web.py`: puts the build and the data where the page loads them. |
| `probe/` | The engine run natively on a flat floor with a scripted pad, as a check of the data and the toolchain. |
| `test/` | Under Node: the same scripted ride on the WebAssembly build (`ride_*.mjs`), ground handed over as a grid (`ground_node.mjs`), and the server script itself with FiveM stood in for (`server_node.cjs`). |

## Where this stands

- The engine loads the data of a **PS3** disc and rides: three pushes take it to 8.5 m/s, the left stick carves, a
  flick of the right stick pops an ollie 1.2 m up and it lands. The native build, the WebAssembly build under Node
  and the WebAssembly build in a browser give the same numbers.
- One tick takes about 1.5 ms. The engine runs 60 ticks a second.
- It reads 18 files of the game's data, about 26 MB.
- In FiveM: the server script runs it (riders are made when the resource starts, ten seconds each, and used
  again and again), the player's script sends the pad and a grid of ground heights found by rays, and draws the
  board and the camera from the answers.

Not done yet: the rider's animations (the rider is held in the riding stance), anything to grind, other players
seeing the board, and the map's real collision, which has to be baked from the server owner's GTA V files (rays
half a metre apart make kerbs into ramps).

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

rustup target add wasm32-wasip1
cd runtime
cargo build --release --target wasm32-wasip1
cd ..

python tools\engine_data.py <your PS3_GAME\USRDIR> <a work folder>
python tools\stage_web.py <the work folder>\assets runtime\target\wasm32-wasip1\release\sk8m_runtime.wasm
```

Those are the revisions SK8V pins. The last command runs the engine once and prints its top speed and the height of
its ollie (10.637 m/s and 1.257 m on a US PS3 disc).

To see it, serve `web/` from a local web server (`python -m http.server --directory web`) and open the page.
W pushes, A and D steer, the arrow keys are the right stick. A controller works as it does in Skate 3.

## The data stays private

`web/data` is made from your disc, like `skate3_assets`. It is ignored by git. Do not upload it.

## The interface

All numbers are in Skate 3's space: metres, y up.

Every call but the last names a rider by a number the host picks.

| Call | What it does |
|---|---|
| `sk8m_load(id, root, triangles, rails, place, heading)` | A rider: loads the data folder and builds their world from triangles (9 floats each) and grind rails (lists of points). About ten seconds. |
| `sk8m_world(id, triangles, rails)` | Replaces the rider's world. About 4 ms for 3200 triangles. |
| `sk8m_place(id, x, y, z, heading)` | Puts the rider somewhere, standing. |
| `sk8m_tick(id, buttons, lt, rt, lx, ly, rx, ry)` | One tick (1/60 s) with the pad as XInput reports it. |
| `sk8m_pose(id, out)` | The board's place in the world (a matrix), its velocity, the engine's camera, and every bone of the rider against the board. |
| `sk8m_close(id)` | The rider is done with. |
| `sk8m_state`, `sk8m_bone_names`, `sk8m_error` | What the rider is doing, the bones' names, why a call failed. |
