# skateboard (FiveM): Skate 3 style skating

Skate 3's control scheme rebuilt for FiveM: Flick-It tricks on the right stick, push-powered speed, manuals, grinds, grabs, late flips and switch stance. Tricks chain into lines with a multiplier. Riding uses a low follow cam. Bail and you ragdoll and lose the line.

No Skate 3 files are in this resource. Everything here is new code, and the board and ramps are GTA V props. The optional `skate3_assets` resource (below) adds Skate 3's own animations, Flick-It gesture patterns and tuning numbers, converted from your own copy of the game.

## Install
1. Copy this `skateboard` folder into your server's `resources/` folder.
2. Add `ensure skateboard` to `server.cfg`, then restart the server.

## Getting a board (ox_inventory)
While ox_inventory is running you need a `skateboard` item to skate. Without ox_inventory, anyone can skate with F6.

1. Add this to `ox_inventory/data/items.lua`:
```lua
['skateboard'] = {
    label = 'Skateboard',
    weight = 2500,
    stack = false,
    close = true,
    consume = 0,
    description = 'Use it to drop your board and ride. F6 or F to step off, G or "Pick up" to put it away.',
    client = { export = 'skateboard.useBoard' },
},
```
2. Put an icon named `skateboard.png` into `ox_inventory/web/images/` (any picture of a board will do; the repository ships none).
3. Get one: either `/giveitem <your server id> skateboard 1` (admin), or add `{ name = 'skateboard', price = 250 },` to a shop's `inventory` list in `ox_inventory/data/shops.lua`.

How it works:
- Use the item, or press F6, to drop your board and get on it.
- Step off with F6 or F. The board stays on the ground.
- Next to the board, press E to ride it or G to pick it up. With ox_target you get "Ride skateboard" and "Pick up skateboard" options instead.
- Using the item while you're riding steps you off and puts the board away.
- The item never leaves your inventory, so you can't lose it or duplicate it. The server checks that you own it before a board appears.

## Controls
The layout is Skate 3's. A controller is the way to play; the keyboard and mouse columns are stand-ins.

| Action | Controller | Keyboard & mouse |
|---|---|---|
| Get on / off | D-pad right (step off: Y too) | F6 (step off: F too) |
| Push | A = right foot, X = left foot (tap for one kick, hold to keep pushing) | W |
| Brake (foot drag, then a foot down) | B | S |
| Carve; spin in the air; lean on a rail | left stick | A / D |
| **Flick-It** | right stick | mouse moves a virtual stick |
| Crouch | pull the right stick all the way down (up for nollies) | |
| Ollie | down, then flick up | mouse down then up, or Space |
| Kickflip / Heelflip (regular stance) | down, then up-left / up-right | Q / E work too |
| Shuvits, varials, hardflips, 360 flips ... | Skate 3's own stick paths (see below) | R = pop shuvit |
| Manual / Nose manual | hold the right stick part of the way down / up | hold Shift / Ctrl |
| Late flip | flick again in the air | |
| Grab | hold RT / LT in the air; where the right stick is held when the hand goes on picks the grab | hold the mouse buttons (Ctrl / Shift pick it) |
| Grind | land on a rail or ledge edge | |
| Ground grab, coffin (Skate 3 clips) | hold RT / LT while rolling; both, then A + X as well, to lie down | mouse buttons; both, then Shift + Space |
| Boneless / fastplant (Skate 3 clips) | with one hand on the board: the front / back foot's push button | Space (fastplant) |
| Hippy jump (Skate 3 clips) | hold A + X, let go | |
| Revert (Skate 3 clips) | sweep the left stick through the bottom half of its circle | |
| Dark catch (Skate 3 clips) | RB during a flip; RB again to let the board turn back | Space |
| Both feet off in a grab (Skate 3 clips) | B while grabbing | S |
| Hang on to a car (skitch) | hold RB behind a car; left stick moves along it; let go of RB to let go (left stick forward = sling past it, back = drop behind) | hold H |
| Helmet on / off | use the `skate_helmet` item, or `/skatehelmet` | |
| Gesture (Skate 3 clips only) | D-pad left | G |

For a goofy rider the left / right stick directions and the two triggers swap, as in Skate 3. `/skatestance` switches between regular and goofy (it applies the next time you get on); `Config.Goofy` sets the default.

Tricks with `skate3_assets` running (Skate 3's own gesture patterns, 78 of them): Ollie, Kickflip, Heelflip, Pop Shuvit, FS Pop Shuvit, Varial Kickflip, Varial Heelflip, Hardflip, Inward Heelflip, 360 Pop Shuvit, FS 360 Pop Shuvit, 360 Flip, Laser Flip, 360 Hardflip, 360 Inward Heelflip, the nollie version of each, and six late flips. Without `skate3_assets` a simpler built-in reader gives ten of them.

With `skate3_assets` every trick in Skate 3's own list (its scoring table, 300 names) is worked through one family at a time; `TRICKS.md` beside the project's journal says what is in and what is not. What can be done to a flip:
- **More flips**: keep the stick where the flick ended. A kickflip or heelflip (and their nollies) goes on turning while it is held and there is the time left to fall: double, triple, quad. The strongest pop on the flat has the time for a double.
- **Underflip**: flick again straight after the first flick. The board is kicked back the other way. Kickflips, heelflips, pop shuvits and their nollies.
- **Dark catch**: press a push button (A or X; Space) straight after the flick: the board is caught upside down. Kickflips and heelflips (after half a flip, or one and a half, ... with the flick held), 360 flips, laser flips, 360 hardflips, 360 inward heelflips. Then: a late-flip gesture turns it the right way up again (a trick), the button again does so for nothing, landing it on a rail is a darkslide, landing it on the ground puts the rider off the board (no fall).
- **One foot**: in a plain jump hold a push button: that foot comes off the board.

Pop height comes from the crouch, as in Skate 3: hold the stick in the crouch for a moment (0.2 s is enough) before you flick and you get the strongest pop and the high version of the trick; flick straight through and you get the weakest pop and the low version. Out of a manual and off a rail the pop is a fixed medium one.

Grabs (regular stance; the triggers swap for goofy). **Which grab is settled when the hand goes on, by where the right stick is held then**; the stick moved afterwards tweaks the grab you have.

| Stick held when the trigger goes down | RT (back hand) | LT (front hand) |
|---|---|---|
| not held | FS Grab | BS Grab |
| up | Tail Grab | Seatbelt |
| down | Crail | Nose Grab |
| right (regular; left for goofy) | Stalefish | Mute |

Both triggers = Double Grab. With Skate 3's clips, on top of a grab:
- the stick: FS grab up / down / to the sides = Nosebone / Tailbone / Stiffy / Tuck Knee; BS grab = Melon / Japan / Cross Bone / Method; stalefish and mute have a nosebone, tailbone and tuck knee; tail, nose, crail and seatbelt grabs have a shifty to each side (they last while the stick is held out)
- a push button: that foot off the board (FS, BS, tail and nose grabs); both, or Y, on a tail or nose grab: an airwalk
- Y: both feet off: No Foot Air on an FS grab, Christ Air on a BS grab, Superman on a double grab (so Y steps off the board in the air only with no hand on it)
- the other trigger on a nose grab: Rocket Air
- a flick of the right stick: a finger flip (the board flipped by hand and caught): straight across the stick for the plain one, a quarter roll for the varial one or to change over (FS grab to stalefish, BS grab to mute and back, crail to tail grab, seatbelt to nose grab)

Landing with a hand still on the board plays the grab landing, and the hand is then on the board on the ground: **ground grabs** (FS, BS, double; the rider crouches down to it and carves; no push, brake or ollie meanwhile). With both hands on the board, both push buttons as well put the rider on their back on it: the **coffin**. Let the push buttons go to sit up. With one hand on the board the front foot's push button is a **boneless**, the back foot's a **fastplant**. The front foot's push button followed at once by a flick is a **no comply**.

Grinds: which one you get depends on how you land on the rail, as on a real board: the truck that is on it and the way the nose points from it.
- Along the rail: 50-50. Hold the right stick down in the air for a 5-0, up for a Nosegrind.
- At an angle with the stick up (front truck, tail up): Crooked with the nose over the rail, Overcrook with it back on your side. With the stick down (back truck, nose up): Salad with the nose over the rail. Board level: the back truck with the nose hanging over the rail is a Feeble, on your side a Smith; land with the rail under the front half of the board and it is the front truck: Willy, Overwilly.
- Turned across it (spin about 90 degrees with the left stick): Boardslide (nose over the rail) or Lipslide. Stick up / down in the air: Noseslide / Tailslide, and with the board gone over the rail instead of short of it the Noseblunt / Bluntslide.
- A board caught upside down (a dark catch) landed on a rail: Darkslide. A flick on it pops out of it, the board coming the right way up.
- Frontside / backside is named from which side of you the rail was and which way you face.
- A trigger on the rail puts that hand on the board (most grinds have a grab or two; board, lip and dark slides have a double).
The left stick leans the rider on the rail. There is no balance meter, as in Skate 3: you ride it out, drop off the end, or flick to pop off (sideways on a rail the flick directions turn with the board, pull towards the tail). Sliding off the end of a rail the board swings back into its line.

The **hippy jump**: hold both push buttons (the crouch), let go: the rider jumps and the board rolls on underneath. A **revert**: sweep the left stick through the bottom half of its circle and the board slides round half a turn; you roll on backwards.

Not in: powerslides (Skate 3's are its physics letting the wheels go in a hard turn, a brake or a crooked landing; this board has no sideways slip to let go, and no button of its own would be Skate 3's), kick turns at a standstill, foot plants off walls and handplants (those two need the board to ride up walls, which it does not).

A foot comes off the board in the air on a new press of its push button, not because a push button was still held from the ground.

Grind lock: jump beside a rail or a ledge edge that runs your way and the board drifts onto it while it is in the air, as in Skate 3. How far away the rail may be is `Config.GrindLockDist`, or Skate 3's own reach for the difficulty you picked (wide on easy, a hand's width on hardcore). `Config.GrindLock = false` switches it off.

Fakie and switch: land a 180 and you roll backwards (fakie); after 0.6 s, or as soon as you push, the rider turns round on the board and rides switch. Tricks are named Fakie / Switch accordingly.

Lines: tricks, manuals, grinds and grabs chain into a line; roll on without tricking and the line is banked. On its own the resource uses the placeholder points in `Config.TrickScores` (banked after 1 second at score x number of tricks). With Skate 3's tuning it uses Skate 3's points tables instead: see below.

Banks, ramps and bowls: the board rides the face that is under it, whatever its slope, up to the straight-up top of a quarter pipe, and the rider and the board stand square to that face. Gravity pulls along it: along the board it speeds it up or slows it down, across the board it bends its line down the hill, so a ride across a bank or along a bowl's wall curves down and back out (not on ground that is all but level: a street's camber does not steer the board). A wall is something that stands up out of the face the board is on; a ramp's curve is not. With speed left at the top of a ramp steeper than 50 degrees the board goes up into the air and comes down on the ramp again, backwards unless the rider turns half round (the left stick); a pop on the way up goes higher. `Config.VertFace`, `Config.CarveMinSpeed`, `Config.CarveFrom` / `CarveFull` and `Config.AirAlign` are its numbers (see `config.lua`), and `surface.lua` is its geometry.

Leaving the ground: off a lip, a ledge or the end of a slope the board flies on the way it was going, up or down, and a pop is added on top of that. The ground may fall away 12 cm under the wheels and still be followed; off anything higher, a kerb included, the board falls. Where the ground bends away (the top of a ramp, the brow of a bank) the board flies on if it is fast enough to clear the ground beyond by more than those 12 cm, and rolls over it otherwise. A fall shorter than 0.2 s is no jump: nothing is made of the landing.

In the air (Skate 3 clips): the rider tucks at the top and reaches for the ground with the legs a quarter of a second before the board comes down, so it lands legs out and the landing takes the weight. `Config.AirExtendTime = 0` leaves the legs tucked.

Steering: the stick asks for a rate of turn and the board comes to it over a few frames; it is not a switch.

Bails: landing in the middle of a flip, landing too far off the way the board rolls, falling from too high, or hitting a wall at speed. A bail throws the rider off without injury (`Config.BailHurts = true` brings the injuries back). Just before the board comes down, a rider who has let go of the left stick squares up with the board's line by himself, as in Skate 3 (`AutoSpinSpeed`, `AutoSpinTime`).

Rails and ledges are found whichever way they point, a rail that bends is followed, and a grind ends where the rail does.

On the screen: nothing but the game. Skate 3 shows no speed, no points and no trick names while you free skate, so they are off: `Config.ShowSpeed`, `Config.ShowTricks` (trick names, line and score) and `Config.ShowBails` (why you bailed) switch them on. The points are counted either way.

`/skateshop place | remove | list` is for the server's admins too: a player with the ace `skateboard.admin`, `skateboard.dev`, `command.skateshop` or `group.admin` (the command checks this itself; it does not need `command.skateshop` handed out).

The test tools below (`/skateramp`, `/skatetest`, and skate3_assets' `/s3...` commands) are for the server's admins: players with the ace `skateboard.dev` or `group.admin` (`add_ace group.admin skateboard.dev allow`). `Config.TestCommands = true` opens them to everyone (a private server), `false` to nobody. Who may get on a board at all (not cuffed, downed, ragdolled, swimming; with qbx_medical not dead or in last stand) can be narrowed with `Config.CanRide = function(ped) ... end`.

Ramps: `/skateramp kicker|flat|funbox|halfpipe|quarter|rail|spine` spawns a ramp in front of you, and `/skateramp clear` removes them. `/skatecam` toggles the follow cam. `/skatemode easy|normal|hardcore` picks Skate 3's difficulty (with its tuning, below).

The toggle and gesture keys can be rebound in **Settings > Key Bindings > FiveM**. That menu is for keys: the controller's buttons for the two are `Config.PadToggle` and `Config.PadGesture` (the game's control numbers; D-pad right and left), read only while a controller is in use.

`/skatetest` rides a scripted routine (push, roll, brake, ollies, a kickflip, a shuvit, a manual, a grab, (with Skate 3 clips: a tweaked grab, a double kickflip, a dark catch, a ground grab into the coffin, a foot plant, a hippy jump,) a 180 to fakie and switch, a grind on a rail it spawns) and prints what the game did at each step in the F8 console and FiveM's log, ending in a line that starts with `RESULT:`. It needs 30 m of flat, clear ground; `/skatetest runway` goes to the airport for it and brings you back. With Skate 3 clips its last step is a revert.

## Helmets and the skate shop
Helmet: with ox_inventory, add this item to `ox_inventory/data/items.lua` (using it puts the helmet on, using it
again takes it off and gives the hat back):

```lua
['skate_helmet'] = {
    label = 'Skate Helmet', weight = 300, stack = false, close = true, consume = 0,
    client = { export = 'skateboard.useHelmet' },
},
```

The helmet is one of the game's own head props: by default the helmet the game gives the character, or any head
prop picked with `/skatehelmet <number> [texture]`, `/skatehelmet next`, `/skatehelmet prev` (remembered per
player; `/skatehelmet default` goes back). Without ox_inventory `/skatehelmet` alone puts it on and takes it off.

Skate shop: an admin (the ace `command.skateshop`) stands where the shopkeeper should be and types
`/skateshop place`; `/skateshop remove` takes the nearest one away, `/skateshop list` shows them. The server
remembers them. The shopkeeper sells `Config.Shop.items` through ox_inventory's shop window and lets players step
through helmets. Fixed shops can be listed in `Config.Shop.locations`.

## Real Skate 3 animations (optional, private servers only)
This resource ships with stock GTA poses. If you own Skate 3 you can convert its animations from your own copy into a second resource, `skate3_assets` (see `skate3-sp/tools`). While `skate3_assets` is running, the rider uses Skate 3's own clips, chained the way Skate 3's motion graph chains them:

- rolling: the lean follows your steering
- pushing: push-off, contact and recover clips for as long as you hold the button, the high-speed versions once you roll fast, the mongo versions for the front foot; the board gains its speed while the foot is on the ground
- braking: the foot drag, then standing with a foot down
- right stick down: the crouch, with the shuvit wind-up when the stick is held round to a side; the flick plays the takeoff clip on the ground, then the board leaves
- each trick: takeoff, in-air and catch clips, with the board turned by Skate 3's own board data
- air idle, late flips, landings (straight, after a spin, sketchy, with a grab), manuals, the stance switch
- every grab with its tweaks, feet-off versions and finger flips; ground grabs, the coffin, boneless, fastplant, no comply, hippy jump, revert
- flips that go on (double, triple, quad), underflips, dark catches and the flips out of them
- 17 grinds and slides with their leaning versions, their grabs, and the darkslide

Install: copy `skate3_assets` next to `skateboard` and add `ensure skate3_assets` **before** `ensure skateboard`. FiveM sends a resource's files to every player who joins, so `skate3_assets` belongs on a private server only. `skateboard` itself contains no Skate 3 data and is fine to share.

### Skate 3's own sounds
This resource has no sound files and makes no sounds up. With `skate3_assets` running the board sounds like Skate 3 because the sounds are Skate 3's: `skate3-sp/tools/build_sounds.py` decodes them from your copy of the game (EALayer3, decoded by `eal3.py`) into `skate3_assets/sounds`. Without that pack the board is silent.

- Rolling: Skate 3 has one long recording per surface of a board rolling from slow to fast, and plays the part that fits the speed. So does the ride: one unbroken stream of the recording from the right place, held to your speed in pitch and loudness, and re-seated with a cross-fade every second or two. GTA's surface under the wheels picks the recording (smooth concrete, rough concrete, aggregate, smooth asphalt, rough asphalt, metal, wood); a new surface has to be under the wheels for 0.4 s before it counts, and the two recordings cross-fade.
- Wheels spinning down in the air and in a manual.
- The pop, the landing (a hop or a drop), the board whipping round in a flip trick, the push, metal struck when you land on a metal rail, a body hitting the ground.
- Grinds and slides: three recordings each (slow, medium, fast), mixed by the speed, for concrete, metal and wood.

The sounds come from the board: they are played from where the board is as the camera sees it, so they move to one side when the camera is beside the rider and fade with distance (`Config.SoundFromBoard`, `SoundNear`, `SoundRolloff`, `SoundEars`). They are still played by the browser layer, not by GTA's own audio engine, so the game's echo and walls do not act on them, and only the rider hears the board, not the players around.

What is the game's and what is a choice: the rolling and wheel recordings are named by the game, so those are certain. Everything else comes out of sound banks whose samples have no names. Which sample is the pop, which the landing and so on was worked out from the shape of the sounds, and which of the game's 41 grind recordings goes with what is a pick too. `/skatesound` lists the picks; `/skatesound grind_metal 12` puts the game's 12th grind on metal rails and plays it (slots: `grind_` / `slide_` + `concrete`, `metal`, `wood`). How loud the sounds are against each other is ours as well.

How loud: `Config.SoundVolume` (0 to 1, a slider position: half way is a quarter of the power) is the server's setting, `/skatevolume 0..100` is your own (kept on your PC), and the board also follows the game's own SFX volume in Settings > Audio (`Config.SoundFollowsGame`). `Config.Sound = false` switches the sounds off. `/skatetest` ends with how many recordings the sound page could load.

### Skate 3's own numbers
`skate3_assets` also carries Skate 3's tuning database, decoded from your copy of the game (`skate3-sp/tools/build_tuning.py`). While it is running the board runs on those numbers instead of the ones in `config.lua`; `tuning.lua` lists every value used and how. None of them are in this resource.

- Pushing: the speed one kick adds and the speed where pushing stops helping, for the difficulty you picked.
- Rolling: nothing slows the board below about 30 km/h while you are using the controls; let go of everything for 3 seconds and it starts to slow down. A manual slows it gently.
- Ground: Skate 3 has five kinds of ground (smooth, rough, slippery, slow, very slow), each with its own slowing-down and its own bite for the brake. GTA's surface under the wheels is sorted onto them: grass, dirt and gravel are slow, sand, mud, snow and long grass very slow (the board stops within a few metres), broken tarmac and cobbles rough. Which GTA material is which kind is this resource's sorting (`GROUND_OF` in `client.lua`).
- Hills: gravity pulls along the slope of the ground the board is on, up to the 7 m/s per second Skate 3 allows.
- Banks and ramps: how steep a face has to be before gravity turns the board down it, how much more of a pop there is off a steep face, the speed a landing on a ramp's curve gives, and how fast the rider comes round to the ramp he is coming down on.
- Pop height: the weakest and the strongest pop for the difficulty (easy always pops the strongest), lower at very high speed.
- Steering and spinning: how the stick and the speed shape a turn, how quickly the board takes a turn up (its steering damping), and how fast the body spins in the air.
- Drops: how far the ground may fall away under the wheels (12 cm) and how short a fall is no jump (0.2 s).
- Grinds: where the trucks are, how fast a grind slows down, how straight a 50-50 and how square a slide has to be, how far a rail pulls you in.
- Bails: the landing speed and the landing angle that throw you off. The landing speed is the speed INTO the ground, so a drop onto a downhill is soft and the board keeps what is left of its speed along the slope (it comes out faster), while the same drop onto the flat is hard.
- Camera: Skate 3's follow camera, with its own distance, height, angle and wide lens for rolling slowly, rolling fast, manuals, air and grinds, on the side your chest faces. `Config.UseSkate3Camera = false` keeps the simple camera.
- Points: Skate 3's score for every trick, grab, grind and manual, its points for grab time, grind length, manual distance and spin, half points for repeating a trick in the same line, and its bonuses (out of a manual, a grind or fakie; into a grind; less for a sketchy landing or a pop from a standstill). A line is banked after 5 seconds of plain rolling.

`Config.Mode` ('easy', 'normal' or 'hardcore', or `/skatemode` in game) picks Skate 3's difficulty set. `Config.UseSkate3Tuning = false` goes back to the numbers in `config.lua`.

What those numbers do here is read from their names and values in the database, not from the game's code, and the board is still moved by this resource's own simple physics, not Skate 3's physics engine. Three readings are worth knowing about, because they are the ones most likely to feel different from the real game:
- The speed a kick adds (`MaxPushDVStart` / `MaxPushDVEnd`) is applied once per kick, times `Config.S3PushScale`. It is 3: taken as it stands, the number gave a push far weaker than the game's (about fourteen kicks to top speed), and three times it matches how far the push clips themselves carry the rider. If pushing feels weaker or stronger than in Skate 3, that is the number to change.
- Pop height is taken from how long the crouch was held (Skate 3 calls it the strength of the crouch and ramps the crouch in over 0.2 s).
- The line multiplier (1.5x, 2x, 3x) is taken from the points behind the line (Skate 3's "momentum meter"), which run down at 100 a second while you just roll.

Stance: Skate 3's clips are authored goofy and the game mirrors them for the other stance. `skate3_assets` contains a mirrored copy (`<clip>_mir`) of every clip the controller plays; a regular rider plays those.

With Skate 3 clips, `BoardYaw`, `FlipAxis`, `RideHeight`, `BoardZ` and the stand/air anims are not used (the board is measured and lined up automatically). Set `UseSkate3Anims = false` to go back to the stock poses, `UseSkate3Flick = false` for the built-in stick reader.

Gestures: G (D-pad left) plays the next gesture from `Config.Gestures` over the riding pose (into, held for `GestureTime`, out). Tricks and grabs cut it short. The config lists every gesture name Skate 3 has.

Board under the feet: the clips were converted on Franklin's skeleton, and other peds (the freemode ones, female even more) have other leg lengths, so their feet land a few cm away from where the board was baked. While you ride, `skate3_assets` measures the real foot bones and moves the rider to take up the difference within about half a second ("skeleton correction"). It is remembered per ped model until the resource restarts.

Checking it in game:
- `/s3check` plays a few clips on you, standing still and while being moved every frame the way the ride moves you, and prints what the game reports. The last line starts with `RESULT:`.
- `/s3debug` shows, among others,
  - `clip ... playing true`: the game is playing the clip the ride asked for.
  - `feet vs deck: x cm sideways, y cm forward, z cm up`: where the real feet are compared to where the board was put. It should stay within a couple of cm while rolling. `[one-foot clip]` means pushing or braking, where only one foot rides the board, so bigger numbers are expected there.
  - `skeleton correction on: x / y / z cm`: what was corrected for your ped. `/s3trim` turns it off and on to compare.
  - `clip restarts N`: how often the ride had to start a clip again because the game dropped it. It should stay 0.

Test commands from `skate3_assets`: `/s3anim <clip>`, `/s3anim lean`, `/s3anim stop`, `/s3list <text>`, `/s3check`, `/s3debug`, `/s3trim`, `/s3boardfix rx ry rz`.

## Tuning (`config.lua`)
- `BoardModels`: the first model that exists is used. `v_res_skateboard` is in the base game; put a custom streamed board at the top to use your own.
- `Mode`, `UseSkate3Tuning`, `UseSkate3Camera`, `S3PushScale`: Skate 3's own numbers (see above). The next few are what is used without them.
- `PushImpulse`, `PushMax`, `Friction`, `BrakeDecel`, `TurnRate`, `Gravity`: how the board rolls. `PopMin`, `PopMax`: how far the weakest and the strongest pop lift the rider with Skate 3 clips; `OllieSpeed` with the stock poses.
- `AnticFullTime`: how long the crouch has to be held for the strongest pop. `MouseFlickScale`: raise it if mouse flicks don't register, lower it if they fire too easily.
- `ManualMin`, `ManualMax`: the right-stick zone that holds a manual.
- `SpinSpeed`, `LandTolerance`, `SketchyLanding`: spinning and how far off line a landing may be.
- `GrindLock`, `GrindLockDist`, `GrindLockSpeed`, `GrindStraight`, `SlideRange`: the grind lock and which grind a landing gives.
- `SwitchAfter`: seconds of rolling fakie before the rider turns round.
- `S3LeanSign`, `TiltSign`: set to `-1.0` if the rider leans out of turns, or the wrong way on slopes.
- `BoardYaw`, `FlipAxis`, `RideHeight`, `BoardZ` (stock poses only): line the board up under the feet.
- `NetworkBoard = false`: use this if your server's entity lockdown blocks objects that clients create.
- `Sound`, `SoundVolume`, `SoundFollowsGame`, `SoundFromBoard`, `SoundNear`, `SoundRolloff`, `SoundEars`: the sounds (see above).
- `ShowSpeed`, `ShowTricks`, `ShowBails`: what is written on the screen. `BailHurts`: whether a bail injures the rider.
- `AutoSpinSpeed`, `AutoSpinTime`: the squaring-up before a landing. `PadToggle`, `PadGesture`: the controller's buttons.
- `SideStickTail`: which way the right stick's sides go in the air (see the grabs table: `true` is how Skate 3's data reads, the tail follows the stick; `false` swaps the sides). `TipGrabLinger`, `TruckPick`, `HippyFullTime`, `RevertMinSpeed`, `TruckStep`, `CoffinDrag`: see the comments there.
- `AirExtendTime`: when the legs reach for the ground before a landing. `NaturalDrop`, `NaturalAirTime`, `SteerDamping`: the drop, short-fall and steering numbers without Skate 3's.
- `Log`: one line in the F8 console (and FiveM's log file) for every landing and every bail, with the numbers behind it (speed into the ground, the slope, the speed before and after, why it was a bail). `GroundDrag`: the kinds of ground without Skate 3's numbers.
