Config = {}

-- Board prop. The first model that exists in the game files is used, so you can put a custom
-- streamed skateboard model at the top of this list. v_res_skateboard is in the base game (int_residential.rpf):
-- a 0.9 m deck, long axis on x, origin at the bottom of the wheels.
Config.BoardModels  = { 'v_res_skateboard' }
Config.BoardYaw     = 90.0   -- board rotation relative to the rider (the rider stands sideways)
Config.FlipAxis     = 'x'    -- the attach axis that runs along the board ('x' or 'y'); flips roll around it
Config.BoardZ       = 0.08   -- deck height above the ground
Config.NetworkBoard = true   -- false if your server's entity lockdown blocks client-created objects
-- After a bail the board lies in the world where it came to rest. The get-on key far from it calls for it (that
-- board goes, another is under your feet); false = no calling: walk to it (E / the target on it), or pick it up.
Config.CallBoard    = true
Config.BoardLodDist = 120    -- metres from which the board is still drawn (a prop's own is 15)
-- Skate 3's own engine. On a server whose skate3_assets was built with it (fivem/engine in the repository, from
-- the owner's own copy of the game), getting on the board starts the engine: the game's real physics, tricks and
-- camera, on the ground rays find round the board. The engine runs on the server (engine_server.js), for as many
-- riders at a time as `set skateboard_engine_riders N` in server.cfg says (one by default); a player it has no
-- room for gets this resource's own ride. false = this resource's own ride for everybody, as before. See
-- engine.lua for what the engine's ride does not have yet (the rider's animations, grinds, others seeing it).
Config.Engine = true
-- Skate 3's own board. While skate3_assets is running and was built with it (skate3-sp/tools/build_board.py, from your
-- own copy of the game), the board is Skate 3's: its deck, trucks and wheels, each one of Skate 3's own, chosen at a
-- skate shop or with /skatedeck, /skatetruck, /skatewheel (no argument = what is on; next / prev; or a part's id).
-- Otherwise the prop above is the board.
-- At a skate shop the shopkeeper opens Skate 3's own board section as a page: decks, trucks and wheels with the game's
-- thumbnails, names, brands and prices; bought parts are yours for good and can be swapped at will.
Config.Decks = {
    enabled  = true,
    free     = false,    -- true = every part is everybody's. false = parts are bought with `currency` for Skate 3's own
                         -- prices (with ox_inventory; without it everything is free anyway), and the commands only
                         -- switch among the parts you own
    currency = 'money',  -- the ox_inventory item parts are paid with
    anywhere = false,    -- true = /skatedeck opens the board page anywhere, not only at a skate shop
}

-- Rider pose. Leave AirDict nil to keep the stand pose in the air.
Config.StandDict, Config.StandAnim = 'mini@strip_club@idles@bouncer@base', 'base'
Config.AirDict,   Config.AirAnim   = nil, nil
Config.RideHeight = 1.0      -- ped root height above the deck
Config.TiltSign   = 1.0      -- flip to -1.0 if the rider leans the wrong way on slopes and in manuals
Config.Goofy      = false    -- false = regular (left foot forward), true = goofy. /skatestance switches it in game.

-- Physics (metres, seconds)
Config.PushImpulse  = 2.2    -- speed added by one push
Config.PushCooldown = 0.55
Config.PushMax      = 9.0    -- pushing stops adding speed above this
Config.MaxSpeed     = 24.0
Config.BrakeDecel   = 7.0
Config.Friction     = 0.35
Config.Gravity      = 9.81
Config.TurnRate     = 120.0  -- degrees per second at low speed
Config.TurnSpeedFalloff = 0.04 -- the faster you roll, the wider the turn: rate / (1 + speed * this)
Config.OllieSpeed   = 5.5    -- upward launch speed of an average flick
Config.StepUp       = 0.6    -- tallest ledge you roll up onto without ollieing
-- Skate 3's numbers when its tuning is there (physics_airstates NaturalAirMaxDist / NaturalAirTime, physics_steering
-- Damping); these otherwise:
Config.NaturalDrop    = 0.12 -- metres the ground may drop away under the wheels and still be followed. More is a fall
Config.NaturalAirTime = 0.2  -- a fall shorter than this is no jump: no landing is played for it
Config.SteerDamping   = 0.7  -- how much of its turning the board keeps every 1/30 s: the stick is not a switch
Config.CoffinDrag     = 0.5  -- m/s the board loses every second while the rider lies on it (the coffin)
Config.TruckStep      = 0.25 -- how far off the slope under the board a truck's ground may be and still tilt it
-- Banks, quarter pipes, bowls. The board rides whatever face is under it, up to straight up, and gravity pulls it along
-- that face: along the board it speeds it up or slows it down, across the board it turns it down the hill.
Config.CarveMinSpeed  = 1.5  -- slower than this the board is turned down the hill as if it rolled this fast (m/s)
Config.CarveFrom      = 0.05 -- without Skate 3's numbers: the slope (its sine) where that turning begins ...
Config.CarveFull      = 0.29 -- ... and where it is all there (below CarveFrom a street's camber does not steer the board)
Config.VertFace       = 0.64 -- a face steeper than this (how upright its normal is: 0.64 = 50 degrees) is the top of a
                             -- ramp: a jump up off it comes down on the ramp again, not out over the deck
Config.AirAlign       = 0.1  -- without Skate 3's numbers: how much of the way the rider comes round, every 1/30 s in the
                             -- air, to the ground the board will land on
-- Without Skate 3's numbers: how much more the kinds of ground slow the board than smooth ground does
Config.GroundDrag   = { smooth = 1.0, slippery = 1.0, rough = 2.0, slow = 18.0, veryslow = 60.0 }
-- One line in the F8 console (and FiveM's log) for every bail and landing: what it was and the numbers behind it.
-- For looking into "that bail was not fair" afterwards.
Config.Log          = true
-- Who may use the test tools (/skatetest, /skateramp, skate3_assets' /s3... commands): they move the player, make
-- ramps and drive the controls. 'admin' = players with the ace "skateboard.dev" (or "group.admin"):
--   add_ace group.admin skateboard.dev allow
-- true = everyone (your own private server), false = nobody.
Config.TestCommands = 'admin'
-- Your server's own rule for who may get on a board right now, on top of the ride's own (not in a car, dead, cuffed,
-- ragdolled, swimming or falling; with qbx_medical: not dead or in last stand). Return false to refuse.
-- Config.CanRide = function(ped) return not LocalPlayer.state.inJail end
Config.CanRide = nil
Config.WallBailSpeed = 6.0   -- hitting a wall faster than this throws you off
Config.HardLanding  = -15.0  -- falling faster than this on landing is a bail
Config.BailHurts    = false  -- false = a bail is a tumble, not an injury (no health lost, no blood)
Config.HeavyLanding = -7.0   -- falling faster than this plays the heavy landing
Config.LandLock     = 0.3    -- seconds after a landing before the next trick can start (Skate 3: DisableTricks 0.3)

-- Flick-It (right stick, or the mouse on keyboard)
Config.MouseFlickScale = 6.0 -- how far a mouse movement pushes the virtual stick
Config.MouseReturn     = 7.0 -- how fast the virtual stick springs back to centre
Config.FlipTime        = 0.45
Config.SpinSpeed       = 540.0 -- degrees per second while holding left/right in the air
Config.LandTolerance   = 40.0  -- how far off a 180 you can land a spin
Config.SketchyLanding  = 15.0  -- further off than this (but inside the tolerance) is a sketchy landing
Config.AutoSpinSpeed   = 360.0 -- degrees per second the body squares up with the board's line just before it lands,
                               -- when the spin stick is let go (Skate 3's own: fast on easy / normal, hardly any on hardcore)
-- Seconds before the board comes down that the rider's legs start reaching for the ground (Skate 3 clips). They
-- used to stay tucked: the rider hit the ground in a ball, sank into it and then stood up. 0 = that again.
Config.AirExtendTime  = 0.25
Config.AutoSpinTime    = 0.25  -- seconds before touchdown that this starts

-- Manuals: hold the right stick part of the way down (manual) or up (nose manual). Like Skate 3 there is no
-- balance meter: it lasts as long as you hold the stick there and keep rolling.
Config.ManualMin    = 0.22   -- stick travel where the manual zone starts ...
Config.ManualMax    = 0.58   -- ... and ends (further is the crouch for a pop)
Config.ManualSide   = 0.35   -- how far sideways the stick may be
Config.ManualEngage = 0.2    -- seconds in the zone before the manual starts (Skate 3: ManualEngageTime > 0.2)
Config.ManualOutTime = 0.1   -- seconds after a manual that a pop still counts as out of it (Skate 3: ManualOutTimer 0.1)
Config.ManualPopStrength = 0.5 -- how strong a pop out of a manual is, 0 .. 1 (there is no crouch to time)

-- Grinds. Which grind you get depends on how you land on the rail: straight = 50-50, turned across it = a slide,
-- in between = smith / feeble; holding the right stick down / up in the air drops the tail / nose first
-- (5-0, nosegrind, crooked, tailslide, noseslide). The left stick leans the rider; you ride it out or pop off.
Config.GrindMinSpeed = 2.0   -- slower than this you don't lock on (and drop off at half of it)
Config.GrindFriction = 1.0
Config.SlideFrictionScale = 1.6 -- the wood slides slower than the trucks grind
Config.GrindStraight = 25.0  -- degrees off the rail that still lock on as a straight grind (50-50, 5-0, nosegrind)
Config.SlideRange   = 30.0   -- degrees either side of square across the rail that lock on as a slide
Config.GrindPopStrength = 0.5 -- how strong a pop off a rail is, 0 .. 1 (Skate 3: half the trick height)
-- Coming down next to a rail or a ledge edge that runs your way, the board drifts onto it, as in Skate 3.
Config.GrindLock      = true
Config.GrindLockDist  = 0.5  -- metres to the side a rail may be (with Skate 3's tuning: its own reach for Config.Mode)
Config.GrindLockSpeed = 3.0  -- metres per second the board drifts towards it, at most
Config.GrindCatch     = 0.10 -- metres off the middle of the board a rail may be under it at touchdown and still be
                             -- landed on (half the width of a board; ours, not a number of Skate 3's)
Config.AdjustMin    = 0.5    -- stick travel (in the air) that counts as holding the nose / tail down, or to a side
-- In the air the right stick to a side turns the board under the feet (a shifty) and, held before a trigger, picks
-- the stalefish / mute. true = the TAIL goes the stick's way (the stick is the foot on the tail, as in Flick-It):
-- how Skate 3's data reads. false = the nose goes the stick's way.
Config.SideStickTail = true
-- Landing on a rail at an angle with the board level: how far ahead of the board's middle the rail has to cross it
-- for the FRONT truck to be the one on the rail (a willy / overwilly); otherwise the back one (smith / feeble).
Config.TruckPick     = 0.13
-- The hippy jump (both push buttons held, then let go): the crouch that gives the highest jump, seconds (Skate 3's
-- crouch reaches its held pose after 0.49 s). A revert (the left stick swept through a half circle) needs this much
-- speed, m/s.
Config.HippyFullTime  = 0.49
Config.RevertMinSpeed = 1.0
Config.LineCashTime = 1.0    -- seconds of plain rolling before a trick line is cashed in

-- Off the board, as in Skate 3 (its own clips, so only with skate3_assets). Y / F gets you off the board with it in
-- your hand: you stand, walk (left stick part of the way), run (all the way) and sprint (hold A; Shift on the keyboard)
-- as Skate 3's skater does, and Y / F again throws the board down and jumps onto it, out of a stand, a walk, a run or
-- a sprint. In the air (more than 0.3 s from landing) Y kicks the board away and you come down on your feet, or
-- with a hand on the board it comes with you. The get on / off key (F6, D-pad right) or using the board item puts the
-- board away and gives you back to the game. false = the old way: you step off and the board stays on the ground.
Config.OffBoard = {
    enabled  = true,
    turnRate = 360.0,  -- degrees per second you can turn, when Skate 3's own numbers are not there
    stepUp   = 0.5,    -- metres you walk up without a jump (a kerb, a stair)
    drop     = 0.6,    -- metres the ground may fall away under a step before it is a fall
    bigFall  = 5.0,    -- m/s into the ground from which the big landing plays (ours, not a number of Skate 3's)
}

-- Riding fakie (rolling backwards) for this long, the rider turns round on the board and rides switch, as in
-- Skate 3; pushing does it at once.
Config.SwitchAfter  = 0.6
Config.IdleStandAfter = 10.0 -- seconds without input before the rider puts a foot down (Skate 3: NoInputBrake)

-- Skitching: roll up behind a car and hold the right bumper (Q on the keyboard) to take hold of the back of it; the
-- car pulls you along. The left stick moves you along the back of the car, hand over hand; at either end you hang
-- on with one hand. Let go of the button to let go of the car: with the left stick pushed forward you sling
-- yourself past it, pulled back you drop behind. Popping a trick lets go as well.
-- These numbers are used when Skate 3's own are not there (physics_state_skitching in its tuning database).
Config.Skitch = {
    enabled  = true,
    reach    = 1.3,   -- metres ahead of the board the back of a car may be and still be grabbed ...
    side     = 0.5,   -- ... and how far past either end of it you may be
    angle    = 60.0,  -- degrees off the car's own heading you may be rolling (ours, not a number of Skate 3's)
    maxClose = 15.0,  -- m/s between you and the car at which there is no catching it
    minTime  = 0.5,   -- seconds a hold lasts at least
    again    = 0.5,   -- seconds after letting go before the next hold
    exitFwd  = 2.5,   -- m/s the sling forward gives, and ...
    exitBack = -2.0,  -- ... what dropping back takes
    exitDist = 0.8,   -- metres the car may get away from your hands before they lose it
    drop     = 0.3,   -- metres the ground may fall away under the wheels before you lose the car
    shimmy   = 0.85,  -- m/s along the back of the car, at most
    edge     = 0.1,   -- metres from the end of the car where the last hand stops
    hand     = 0.15,  -- metres from the middle of the body to each hand
}
-- Where the hands are in Skate 3's hold clips, measured from the clips (metres): ahead of the middle of the deck,
-- and above the ground for the low hold (down at a bumper) and the high one (at a boot lid or a tailgate). The
-- rider is put this far behind whichever of the two the back of the car has, so that the hands are on it.
Config.SkitchHandsAhead = 0.67
Config.SkitchHandsLow   = 0.55
Config.SkitchHandsHigh  = 0.87
-- Vehicle classes nobody hangs on to: motorcycles, cycles, boats, helicopters, planes, trains.
Config.SkitchNoClass = { [8] = true, [13] = true, [14] = true, [15] = true, [16] = true, [21] = true }

-- Helmets. With ox_inventory running, a helmet is an item ('skate_helmet'): using it puts it on, using it again
-- takes it off, and the hat you had on comes back. Without ox_inventory, /skatehelmet does the same for anyone.
-- The helmet is one of the game's own head props. drawable = -1 is the helmet the game itself gives your
-- character (GTA's motorcycle helmet for that ped); any other number is that prop of the head slot, which for an
-- online character is the "hats" list of the clothing menu (the numbers depend on the server's clothing packs).
-- /skatehelmet <number> [texture] picks one for yourself in the game (remembered), /skatehelmet next and
-- /skatehelmet prev step through the list to find one.
Config.Helmet = {
    enabled  = true,
    item     = 'skate_helmet',
    drawable = -1,
    texture  = 0,
    stayOn   = true,  -- a bail does not knock it off
}

-- The skate shop: a shopkeeper who sells the skate items (through ox_inventory's own shop window, for its money)
-- and lets you try helmets on. An admin puts one down where they stand with /skateshop place, takes the nearest
-- away with /skateshop remove, and /skateshop list shows them; the server remembers them. `locations` are shops
-- that are always there: { x, y, z, h } (z as the game reports your position, h = the way the shopkeeper faces).
Config.Shop = {
    enabled   = true,
    id        = 'skateshop',
    name      = 'Skate Shop',
    ped       = 'a_m_y_skater_01',
    scenario  = 'WORLD_HUMAN_STAND_IMPATIENT',
    blip      = { sprite = 52, colour = 5, scale = 0.8 },  -- false = no blip on the map
    items     = {                                           -- what it sells (ox_inventory item names) and for how much
        { name = 'skateboard', price = 150 },
        { name = 'skate_helmet', price = 75 },
    },
    locations = {},
}

-- Points. These are placeholders, not Skate 3's scoring: with Skate 3's own points tables (see Config.UseSkate3Tuning)
-- they are not used.
Config.TrickScores = {
    default = 50, late = 150, grab = 100, grabPerSecond = 300, grind = 100, grindPerSecond = 150,
    manualPerSecond = 120, spin180 = 150,
    Ollie = 100, Nollie = 150, Kickflip = 250, Heelflip = 250, PopShuvit = 200, FSPopShuvit = 200,
    VarialKickflip = 350, VarialHeelflip = 350, Hardflip = 400, InwardHeelflip = 400, ['360PopShuvit'] = 300,
    FS360PopShuvit = 300, ['360Flip'] = 450, Laserflip = 450, ['360Hardflip'] = 500, ['360InwardHeelflip'] = 500,
    N_Kickflip = 300, N_Heelflip = 300, N_PopShuvit = 250, N_FSPopShuvit = 250, N_VarialKickflip = 400,
    N_VarialHeelflip = 400, N_Hardflip = 450, N_InwardHeelflip = 450, N_360PopShuvit = 350, N_FS360PopShuvit = 350,
    N_360Flip = 500, N_Laserflip = 500, N_360Hardflip = 550, N_360InwardHeelflip = 550,
}
-- Names of the grabs. The hands are named for a regular rider; the mapping follows the rider's stance.
-- (With Skate 3's clips the names are Skate 3's own, tweaks and all: an FS grab with the nose pushed down is a
-- nosebone, a BS grab with it down a melon ...)
Config.GrabNames = { fs = 'FS Grab', bs = 'BS Grab', dbl = 'Double Grab', tail = 'Tail Grab', crail = 'Crail',
                     nose = 'Nose Grab', seatbelt = 'Seatbelt' }
-- ... and of the grabs on the ground (a trigger held while rolling; Skate 3 clips only)
Config.GroundGrabNames = { fs = 'FS Ground Grab', bs = 'BS Ground Grab', dbl = 'Double Ground Grab' }

-- Skate 3 follow cam (the mouse is the flick stick, so the camera follows the board)
Config.SkateCam   = true
Config.CamDist    = 3.2      -- metres behind the rider
Config.CamHeight  = 0.9      -- metres above the board
Config.CamSide    = 0.0      -- metres to the right of the line of travel
Config.CamFov     = 72.0
Config.CamTurn    = 4.0      -- how quickly the camera swings round behind a turn
Config.CamFollow  = 10.0     -- how tightly it follows
Config.CamLead    = 1.5      -- metres ahead of the rider the camera looks at
Config.CamLookDown = 0.3     -- metres below the rider's middle it looks at
-- What is written on the screen while you ride. Skate 3 itself shows none of it in free skate; the points are
-- still counted either way.
Config.ShowSpeed  = false    -- km/h
Config.ShowTricks = false    -- the names of the tricks in the line, the line's points and the score
Config.ShowBails  = false    -- why a bail happened ("Landed sideways" ...)
Config.CamSlowSpeed = 2.0    -- m/s where the camera starts to move from its slow-rolling place to the fast one ...
Config.CamFastSpeed = 8.0    -- ... and where it has arrived
Config.CamBigAir  = 1.3      -- seconds in the air from which the camera pulls back for a big air (a full ollie on the
                             -- flat is in the air for about 0.9)

-- Sounds: wheels rolling, the pop, the landing, grinding, the push, the bail. This resource has no sound files
-- of its own and makes none up: the sounds are Skate 3's, played from the sound pack in skate3_assets (converted
-- from your own copy of the game). Without that pack the board is silent.
Config.Sound       = true
Config.SoundVolume = 0.5     -- 0 .. 1, a slider position (half way is a quarter of the power). /skatevolume changes
                             -- it for yourself, in the game
Config.SoundFollowsGame = true -- the board also follows the game's own SFX volume setting (Settings > Audio)
-- The sounds come from the board: they are heard from where the board is as the camera sees it (to one side when
-- the camera is beside the rider, fainter from far off). false = plain sound, the same in both ears.
Config.SoundFromBoard = true
Config.SoundNear      = 3.5        -- metres from the camera within which the board is at full loudness
Config.SoundRolloff   = 1.0        -- how fast it falls away beyond that (0 = not at all)
Config.SoundEars      = 'HRTF'     -- 'HRTF': direction as two ears hear it. 'equalpower': plain left / right

-- Ramps for /skateramp <name>
Config.Ramps = {
    kicker   = 'prop_skate_kickers',
    flat     = 'prop_skate_flatramp',
    funbox   = 'prop_skate_funbox',
    halfpipe = 'prop_skate_halfpipe',
    quarter  = 'prop_skate_quartpipe',
    rail     = 'prop_skate_rail',
    spine    = 'prop_skate_spiner',
}

-- ox_inventory: while ox_inventory is running you need a 'skateboard' item to skate (the server checks it).
-- Using the item (or pressing the toggle key) drops your board and puts you on it. The item stays in your
-- inventory - it is your board - so it can't be lost or duplicated. Without ox_inventory anyone can skate.
Config.RequireItem      = true
Config.ItemName         = 'skateboard'
-- ox_target "Ride" / "Pick up" options on your board while ox_target is running; otherwise stand next to it
-- and press E to ride or G to pick it up.
Config.UseTarget        = true
Config.InteractDistance = 2.0

-- Real Skate 3 animations. Only used while the local-only `skate3_assets` resource (built from your own copy
-- of Skate 3 with skate3-sp/tools) is running; otherwise the stock GTA poses above are used.
Config.UseSkate3Anims = true
-- Skate 3's own tuning numbers (speeds, pop heights, friction, steering and spin curves, grind and bail limits, the
-- camera, points), when skate3_assets was built with them (it is, by skate3-sp/tools/build_fivem_assets.py). They are
-- read from your copy of the game and are not in this resource; see tuning.lua for which are used and how.
Config.UseSkate3Tuning = true
Config.UseSkate3Camera = true -- Skate 3's follow camera (distance, height, angle and lens for each situation)
Config.Mode           = 'normal' -- Skate 3's difficulty: 'easy', 'normal' or 'hardcore' (/skatemode in game)
-- Multiplies the speed a push adds. Skate 3's database gives 0.6 m/s per kick on normal; taken as it stands the
-- board crawls (seen in game: 2 km/h a kick) while the push animation is a full kick. Its own push clips travel at
-- about 2 m/s after the first kick, and 3 times the number matches that: about six kicks to top pushing speed.
-- 1.0 = the database number as it stands.
Config.S3PushScale    = 3.0
Config.UseSkate3Flick = true  -- read the stick with Skate 3's own Flick-It patterns (30 tricks + late flips); false =
                              -- the simpler built-in reader (10 tricks)
Config.FlickSegTime   = 0.34  -- seconds allowed between two points of a gesture
Config.AnticEngage    = 0.9   -- stick travel that starts the crouch (Skate 3: AnticMag > 0.9) ...
Config.AnticRelease   = 0.5   -- ... and where it lets go again
Config.AnticDwell     = 0.05  -- seconds the stick has to sit in a crouch zone before the crouch shows
Config.AnticLinger    = 0.12  -- seconds the crouch holds after the stick leaves (a flick fires within this)
Config.AnticFullTime  = 0.2   -- seconds in the crouch for the strongest pop (Skate 3 ramps its crouch in over 0.2 s);
                              -- a flick straight through the crouch is the weakest
Config.S3FastPush     = 5.0   -- m/s from which the high-speed push clips play
-- How far a pop lifts the rider (the tuck adds about 0.4 m of board height). Used with Skate 3's clips when its own
-- tuning is not there; with it, these come from the game (PopFloor stays: the least a pop may be, because Skate 3's
-- trick clips need that long in the air to finish).
Config.PopMin         = 0.35  -- metres, the weakest pop
Config.PopMax         = 0.66  -- metres, the strongest
Config.PopFloor       = 0.34
Config.S3HighPop      = 0.5   -- pop strength (0 .. 1) from which a trick plays Skate 3's high version of its clips ...
Config.S3HighRise     = 0.41  -- ... as long as the pop lifts the rider this far (metres): the high clips take longer
Config.S3LeanSign     = 1.0   -- flip to -1.0 if the rider leans out of turns instead of into them

-- Gestures (Skate 3 clips, so only with skate3_assets): G or D-pad left while riding plays the next one from this
-- list, layered over the riding pose; tricks and grabs cut it short. All the names Skate 3 has:
-- airguitar airplane bicepflex boxing bruce_lee checktime dble_gun devil dunno fingerwag fliptable fonz_eh freedom
-- fu_fist getaway getouttahere handcuffs highpump lowpump peace point_sky prewind raiseroof shaka shrug snap
-- soularch spock surfsup swinghigh swinglow thmb_dwn throwarms wave wings yardsale
Config.Gestures    = { 'shaka', 'peace', 'point_sky', 'raiseroof', 'airguitar', 'surfsup', 'bicepflex', 'highpump',
                       'wave', 'devil' }
Config.GestureTime = 1.2      -- seconds the gesture is held between its in and out clips
Config.GestureKey  = 'G'
Config.PadGesture  = 234      -- controller: D-pad left (the game's control number, INPUT_SCRIPT_PAD_LEFT; 0 = none)

Config.ToggleKey = 'F6'            -- players can rebind it in Settings > Key Bindings > FiveM
Config.PadToggle = 235             -- controller: D-pad right (the game's control number, INPUT_SCRIPT_PAD_RIGHT; 0 = none)
