# The engine

Skate 3's own engine, built as one WebAssembly file so that it can run inside FiveM.

The engine is not ours and is not copied here. It is the Rust rewrite of Skate 3's skating that
[SK8V](https://github.com/becaring/SK8V) builds on: `skate-core`, `skate-data` and `skate-host` from
[2010-rust-rewrite-mashup](https://github.com/chasmlol/2010-rust-rewrite-mashup) by chasmlol (Apache-2.0), with the
data export tools of [skate-3-rust-engine](https://github.com/SK8-ENGINE/skate-3-rust-engine). This folder holds
what is needed to run it somewhere new:

| Folder | What it is |
|---|---|
| `runtime/` | The engine behind a small C interface (load, tick with a pad, read the pose), compiled to WebAssembly. |
| `shim/` | Stand-ins for three crates the engine names but does not need through that interface: `bevy` (it uses the math types, `Transform`, log macros and one derive), `zstd` (its own map files) and `socket2` (its network sockets). |
| `web/` | `wasi_mem.js`: the 14 system calls the engine makes, over files held in memory. `engine.js`: loads the engine and its data in a browser. `index.html`: a test page that draws the board and the rider's bones. |
| `tools/` | `engine_data.py`: makes the engine's data folder from your own disc. `stage_web.py`: puts the build and the data where the page loads them. |
| `probe/` | The engine run natively on a flat floor with a scripted pad, as a check of the data and the toolchain. |
| `test/` | The same scripted ride on the WebAssembly build, under Node. |

## Where this stands

- The engine loads the data of a **PS3** disc and rides: three pushes take it to 8.5 m/s, the left stick carves, a
  flick of the right stick pops an ollie 1.2 m up and it lands. The native build, the WebAssembly build under Node
  and the WebAssembly build in a browser give the same numbers.
- One tick takes about 1.5 ms in a browser. The engine runs 60 ticks a second.
- It reads 18 files of the game's data, about 26 MB.

Not done yet: the FiveM side (the pad in, GTA's ground in as triangles, the board and the rider out), and the map's
collision, which has to be baked from the server owner's GTA V files.

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

| Call | What it does |
|---|---|
| `sk8m_load(root, triangles, rails, place, heading)` | Loads the data folder and builds the world from triangles (9 floats each) and grind rails (lists of points). |
| `sk8m_world(triangles, rails)` | Replaces the world. |
| `sk8m_place(x, y, z, heading)` | Puts the rider somewhere. |
| `sk8m_tick(buttons, lt, rt, lx, ly, rx, ry)` | One tick (1/60 s) with the pad as XInput reports it. |
| `sk8m_pose(out)` | The board's place in the world (a matrix), its velocity, the engine's camera, and every bone of the rider against the board. |
| `sk8m_state`, `sk8m_bone_names`, `sk8m_error` | What the rider is doing, the bones' names, why a call failed. |
