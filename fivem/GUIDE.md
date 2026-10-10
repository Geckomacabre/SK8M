# SK8M guide

How to get SK8M onto your FiveM server, from nothing to riding.

There are two parts, and you can stop after the first:

1. **The `skateboard` resource.** Ten minutes. Skate 3's controls and tricks with GTA's stock animations. Needs no
   Skate 3 files.
2. **The `skate3_assets` resource.** About an hour the first time. You build it from your own copy of Skate 3, and it
   adds Skate 3's own animations, Flick-It gesture patterns, tuning numbers and board sounds.

## What you need

| | For | Where |
|---|---|---|
| A FiveM server you run | both parts | [FiveM server setup](https://docs.fivem.net/docs/server-manual/setting-up-a-server/) |
| A controller | playing | The controls are Skate 3's. Keyboard and mouse work as stand-ins. |
| ox_inventory (optional) | the board as an item, the skate shop | [ox_inventory](https://github.com/overextended/ox_inventory) |
| **Your own copy of Skate 3 for PlayStation 3** | part 2 | You need the disc's files as a `PS3_GAME` folder. Tested with the US release. |
| Your own copy of GTA V | part 2 | The one FiveM already uses. |
| Python 3.11 or newer | part 2 | [python.org](https://www.python.org/downloads/) |
| ffmpeg | part 2 (sounds) | [ffmpeg.org](https://ffmpeg.org/download.html), on your `PATH` |
| Git | part 2 | [git-scm.com](https://git-scm.com/downloads) |
| .NET 8 SDK | part 2 (building `cwtool`) | [dotnet.microsoft.com](https://dotnet.microsoft.com/download/dotnet/8.0) |
| Visual Studio 2022 with "Desktop development with C++" | part 2 (building the animation decoder) | [visualstudio.microsoft.com](https://visualstudio.microsoft.com/downloads/) |
| OpenIV | part 2 (one file out of GTA V) | [openiv.com](https://openiv.com/) |

Part 2 is Windows only.

No Skate 3 or GTA V files are in this repository. Everything in part 2 is made on your PC from your own copies.

## Part 1: the `skateboard` resource

1. Download this repository (Code > Download ZIP, or `git clone`).
2. Copy the folder `fivem/skateboard` into your server's `resources` folder.
3. Add this line to `server.cfg`:
   ```
   ensure skateboard
   ```
4. Restart the server and join.
5. Press **F6** (keyboard) or **D-pad right** (controller). A board drops and you are on it.

If your server runs ox_inventory, you need the `skateboard` item to ride. Adding the item, the helmet and the skate
shop are covered in the resource's [README](skateboard/README.md), along with every control and setting.

The basics:

| | Controller | Keyboard and mouse |
|---|---|---|
| Get on / off | D-pad right (Y also steps off) | F6 (F also steps off) |
| Push | A or X | W |
| Brake | B | S |
| Steer | left stick | A / D |
| Ollie | right stick down, then flick up | Space |
| Kickflip / heelflip | down, then flick up-left / up-right | Q / E |
| Manual | hold the right stick part of the way down | hold Shift |
| Grab | hold a trigger in the air | hold a mouse button |
| Grind | land on a rail or a ledge edge | |

## Part 2: build `skate3_assets` from your Skate 3

You do this once. Later updates of SK8M only need steps 7 to 9 again.

All commands are run in a terminal from the folder `fivem/skate3-sp` of this repository.

### 1. Put your Skate 3 files in place

Copy your disc's `PS3_GAME` folder to `fivem/PS3_GAME`. If you have the disc as an image file,
[7-Zip](https://www.7-zip.org/) opens it.

You should now have `fivem/PS3_GAME/USRDIR/data/big/miscload.big`.

### 2. Install the Python packages

```bat
pip install lupa numpy pillow
```

### 3. Build the two helper programs

Each has its own short instructions:

- **cwtool** turns the converted animations into files GTA V loads: [`cwtool/README.md`](skate3-sp/cwtool/README.md)
- **animtest** reads Skate 3's animation banks: [`tools/animtest/README.md`](skate3-sp/tools/animtest/README.md)

### 4. Tell the tools where things are

Copy `tools/local_paths.example.json` to `tools/local_paths.json` and edit it:

```json
{
  "work": "C:\\skate3-work",
  "cwtool": "C:\\path\\to\\cwtool\\bin\\cwtool.exe",
  "animtest": "C:\\path\\to\\animtest\\build\\animtest.exe"
}
```

`work` is an empty folder of your choice with a few GB free. Everything taken from your games is written there, never
into the repository. The steps below call it `<work>`.

### 5. Unpack the game's archives and decode the animations

```bat
python tools\eb_extract.py ..\PS3_GAME\USRDIR\data\big\miscload.big <work>\miscload
python tools\eb_extract.py ..\PS3_GAME\USRDIR\data\big\db.big <work>\db
python tools\decode_anims.py
```

The last command writes about 3,300 clips as CSV files into `<work>\onboard_csv` and `<work>\offboard_csv`. It takes
a minute or two.

### 6. Export GTA V's skeleton

The converter fits Skate 3's poses onto GTA's body, so it needs GTA's skeleton from your own game.

1. Open your GTA V folder in OpenIV.
2. Go to `x64v.rpf` > `models` > `cdimages` > `streamedpeds_players.rpf`.
3. Extract `player_one.yft` to any folder.
4. Run:
   ```bat
   python tools\export_gta_rig.py C:\path\to\player_one.yft
   ```

This writes `tools\gta_ped_rig.json`.

### 7. Convert the animations

```bat
python tools\export_all.py
```

About six minutes. It should print one line per clip dictionary, each ending in `ok=True`.

### 8. Build the resource

```bat
python tools\build_fivem_assets.py --no-board
```

The resource is written to `<work>\fivem\skate3_assets`. It also converts the board sounds and reads Skate 3's tuning
numbers.

`--no-board` leaves out Skate 3's own deck, truck and wheel models: the step that catalogues them is not in the
repository yet. You ride GTA's skateboard prop instead.

### 9. Put it on your server

1. Copy `<work>\fivem\skate3_assets` into your server's `resources` folder.
2. In `server.cfg`, start it **before** `skateboard`:
   ```
   ensure skate3_assets
   ensure skateboard
   ```
3. Restart the server.

Get on the board. The rider now stands, pushes and tricks with Skate 3's animations. To check, type `/skatetest runway`
as a server admin: it takes you to the airport runway, rides a scripted routine, brings you back and prints a
`RESULT:` line in the F8 console.

## Keep `skate3_assets` private

`skate3_assets` is made from your Skate 3 disc. A FiveM server sends its resources to every player who joins. Do not
upload it anywhere, do not share it, and do not run it on a server for people who do not own the game. The
`skateboard` resource has none of that in it and can be shared freely.

## If something goes wrong

| What you see | What to do |
|---|---|
| Nothing happens on F6 | Check the F8 console for a red error from `skateboard`. With ox_inventory running you need the `skateboard` item (resource README). |
| The rider stands in GTA's pose, no Skate 3 animations | `skate3_assets` is not running, or it started after `skateboard`. Check the order in `server.cfg`. |
| `decode_anims.py` says it listed no clips | `animtest` in `local_paths.json` does not point at the program you built, or it was built without the patch. |
| `export_all.py` stops with "ok=False" | `cwtool` in `local_paths.json` is wrong, or the .NET 8 runtime is missing. |
| `export_all.py` cannot find `gta_ped_rig.json` | Do step 6. |
| `build_fivem_assets.py` stops with an ffmpeg error | `ffmpeg` is not on your `PATH`. Install it, open a new terminal and run step 8 again. |
| A trick does not come out | The gestures are Skate 3's own stick paths. The resource README lists them. |

## What to expect

SK8M is work in progress. The ride, flips, grabs, grinds, manuals, ramps and bowls, the off-board mode and the skate
shop are built and pass the project's offline tests, but not every part has been checked in the game yet. `TRICKS.md`
lists which of Skate 3's tricks are in.

For GTA V Story Mode, use [SK8V](https://github.com/becaring/SK8V), the project SK8M is forked from. It runs Skate 3's
real engine and is further along.
