-- Skateboard with Skate 3's controls. The rider is frozen and moved kinematically every frame (ground, walls and
-- rails are found by raycasts) and the board is placed under the feet, so tricks can turn it. Doing our own physics
-- keeps GTA's fall / ragdoll tasks from interrupting the ride; on a bail the rider and the board are handed back to
-- the game's physics.
--
-- Controls follow Skate 3 (controller): left stick steers and spins, right stick is Flick-It (pull down to crouch,
-- flick for the trick), A / X push with the right / left foot, B brakes, triggers grab, Y steps off.
-- With `skate3_assets` running the rider is posed with Skate 3's own clips, the stick is read with Skate 3's own
-- gesture patterns (s3.lua, flick.lua) and the board follows Skate 3's own tuning numbers (tuning.lua); without it a
-- simpler built-in reader, stock GTA poses and the numbers in config.lua are used.

local RAY_FLAGS = 1 | 2 | 16 -- world, vehicles, objects (not peds)
local LOCK_FLAGS = 1 | 16    -- what a jump may be pulled onto: world and objects, not somebody's car
local C = {
    lookX = 1, lookY = 2, lr = 30, ud = 31,
    pushR = 21, pushL = 22, off = 23, grabR = 24, grabL = 25, brake = 45, -- pad: A, X, Y, RT, LT, B
    dark = 44,                                                            -- pad: RB (the dark catch)
    hang = 44, hangKey = 74,                                              -- pad: RB on the ground, keyboard: H (hold on to a car)
    shift = 21, space = 22, ctrl = 36, e = 38, q = 44, r = 45,            -- keyboard: the same control numbers
}
local DISABLE = { 0, 1, 2, 21, 22, 23, 24, 25, 30, 31, 36, 37, 38, 44, 45, 140, 141, 142, 143, 257, 263, 264 }

-- The controls. /skatetest (selftest.lua) rides a scripted routine by handing in a table of controller input
-- ({ normal = { [control] = -1 .. 1 }, pressed = { [control] = true }, just = { [control] = true } }) to read
-- instead of the real pad.
local sim
local function padNormal(c)
    if sim then return sim.normal[c] or 0.0 end
    return GetDisabledControlNormal(0, c)
end
local function padPressed(c)
    if sim then return sim.pressed[c] == true end
    return IsDisabledControlPressed(0, c)
end
local function padJust(c)
    if sim then
        local v = sim.just[c] == true
        sim.just[c] = nil
        return v
    end
    return IsDisabledControlJustPressed(0, c)
end

-- Board motion for the stock fallback (no skate3_assets): degrees the prop turns during the trick.
local STOCK = {
    Ollie = {}, Nollie = {},
    Kickflip = { roll = 360 }, Heelflip = { roll = -360 }, N_Kickflip = { roll = 360 }, N_Heelflip = { roll = -360 },
    PopShuvit = { yaw = 180 }, FSPopShuvit = { yaw = -180 },
    ['360Flip'] = { roll = 360, yaw = 360 }, Laserflip = { roll = -360, yaw = -360 },
}
-- built-in stick reader's names -> trick keys (the gesture names Skate 3 uses)
local BUILTIN = {
    ['Ollie'] = 'Ollie', ['Nollie'] = 'Nollie', ['Kickflip'] = 'Kickflip', ['Heelflip'] = 'Heelflip',
    ['Nollie Kickflip'] = 'N_Kickflip', ['Nollie Heelflip'] = 'N_Heelflip', ['Pop Shove-it'] = 'PopShuvit',
    ['FS Shove-it'] = 'FSPopShuvit', ['360 Flip'] = '360Flip', ['Laser Flip'] = 'Laserflip',
}

-- ride state
local riding = false
local board, boardModel, cam
local pos = vector3(0, 0, 0) -- where the board touches the ground (in the air: the flight path of that point)
local facing = 0.0           -- the way the rider and the nose of the board point, degrees (a GTA heading)
local speed = 0.0            -- along `facing`; negative = rolling backwards (fakie)
local vz = 0.0
local mode = 'ground'        -- ground | air | grind
local switch = false         -- riding switch: the other foot forward than Config.Goofy says
local airTime, groundVz, tilt = 0.0, 0.0, 0.0
local groundN                -- the face of the ground the board is on (its normal), nil until it has touched one
local yawRate = 0.0          -- how fast the board is turning, degrees per second
local spin = 0.0             -- body rotation in the air since takeoff, degrees to the left
local air                    -- the jump in progress: { name, label, tricks = { { label, key, points } }, from... }
local flip, grab, manual, grind -- tables while each is active
local ggrab                  -- a hand on the board on the ground: { kind = 'fs' | 'bs' | 'dbl', label, t }
local coffin                 -- lying on the board: { t }
local onefoot                -- a foot off the board in the air: { kind = 'front' | 'back', foot, t }
local flickHeld = false      -- the stick is still where the last flick left it (Skate 3: more flips while it is)
local uflipAsked = false     -- a second flick has come during a flip: the underflip
local darkAsked = false      -- the dark-catch button was pressed during a flip: catch the board upside down
local ttl = 9.0              -- seconds until the board is down again (in the air)
local hippy                  -- the hippy jump: { phase = 'antic' | 'into' | 'air', t, h, strength, takeoff, hop, vz, down }
local revert                 -- the board being slid round on the ground: { dir (+1 = to the left), ang, key, label }
local pushFront = false      -- the push in progress is the front foot's (a flick now is a no comply)
local pushStartT, wasPushing = -10.0, false -- when that push began; a push was on last frame
local leftSet, leftSetOf     -- the left stick's 180-slide gestures, and the pattern table they were taken from
local leftStick = Flick.reader() -- the left stick's gestures (Skate 3's skaterls.pat: the 180 slides)
local pushCd, rollTime = 0.0, 0.0
local line, lineScore, totalScore = {}, 0, 0
local momentum, counts = 0.0, {} -- points behind the line (sets its multiplier); how often each trick is in it
local message, messageUntil = nil, 0
local stickX, stickY = 0.0, 0.0
local camPos, camHeading, camShot
local ramps = {}
local pending                -- a flick waiting for its takeoff clip: { name, label, strength, fromManual, t }
local slopeDeg, s3pitch, braking = 0.0, 0.0, false
local popHigh = true         -- the pop in progress is a strong one (Skate 3's high version of the trick)
local antic                  -- crouched for a pop: 'ollie' | 'shuv' | 'fsshuv' | 'nollie' | 'nshuv' | 'nfsshuv'
local anticNext, anticT      -- the crouch the stick is asking for now, and for how long it has
local adjust                 -- right stick held in the air: 'nose' | 'tail' down (picks the grind)
local fakieT, switching = 0.0, nil -- seconds rolling fakie on the ground; the stance switch in progress (seconds left)
local landLock = 0.0         -- no tricks for a moment after landing (Skate 3: Landing.xml DisableTricks 0.3)
local idleT = 0.0            -- seconds without any input
local inputT = 0.0           -- seconds since the controls were last touched (Skate 3 lets the board slow down then)
-- how long the stick sat in the crouch before the flick (sets how strong the pop is), for each end of the board
local crouch = { t = 0.0, tail = { held = 0.0, at = -10.0 }, nose = { held = 0.0, at = -10.0 } }
local lock                   -- the rail a jump is drifting onto: { off = metres to the left still to go, z, t }
local kick, kickPhase        -- the push in progress: { left = speed it still has to give, rate }; the push clip's phase
local landingSoon = false    -- in the air and about to touch down (the body squares up now)
local extendSoon = false     -- ... and close enough for the legs to start reaching for the ground
local lastBail               -- why the last bail happened (shown only with Config.ShowBails; /skatetest reads it)
local manualOut = -10.0      -- when the last manual ended (a pop right after it is still a pop out of the manual)
local camSide                -- which side of the rider the camera is on, eased (+1 left .. -1 right)
local lastSide = 0.0         -- which side of its path the rider last moved towards (+ left), to name a grind's side
local clock = 0.0            -- ride time, for the stick history
local skitch                 -- holding on to the back of a car: { veh, off = metres across it, t, hand, high, ... }
local sk = { cd = 0.0, scan = 0.0 } -- seconds until the next hold may start; until cars are looked for again
local SK = {}                       -- helpers kept in a table (this file's main chunk has no local variables to spare)
function SkateboardRiding() return riding end   -- (for engine.lua: the two rides do not run together)

-- ------------------------------------------------------------------ helpers

local function fwd(h)
    local r = math.rad(h)
    return vector3(-math.sin(r), math.cos(r), 0.0)
end

local function lerp(a, b, t) return a + (b - a) * t end
local function clamp(x, lo, hi) return math.max(lo, math.min(hi, x)) end
local function angDiff(a, b) return (a - b + 180.0) % 360.0 - 180.0 end
local function sign(x) return x < 0 and -1.0 or 1.0 end

local function ray(from, to, ignore, flags)
    local h = StartExpensiveSynchronousShapeTestLosProbe(from.x, from.y, from.z, to.x, to.y, to.z,
        flags or RAY_FLAGS, ignore or 0, 7)
    local _, hit, hitPos, normal = GetShapeTestResult(h)
    return hit == 1, hitPos, normal
end

local function probe(p, up, down)
    local hit, hp = ray(p + vector3(0, 0, up), p - vector3(0, 0, down), board)
    return hit and hp.z or nil
end

-- ------------------------------------------------------------------ the face under the board
--
-- Not all ground is level, and a ramp's curve ends standing straight up (see surface.lua). On the ground the board
-- has the face it is on (sk.u, its normal) and the way its nose points along that face (sk.d). `facing` is that
-- direction as a heading, with the face laid flat. sk.up is the way up the rider and the board are drawn with: it
-- comes round to a new face over a few frames; in the air it levels out, or stays with the wall of a ramp.
-- In the air sk.ah is the heading the nose had (in sk.up's frame) when it left the ground, where that is not `facing`
-- (which in the air is the line the board travels along over the ground), and sk.re says the jump left a steep face
-- going up: { n = that face, z = the height it left it at }.

-- The board is on the face `n`: pointing along `d` there, or (no d) along the heading `facing`.
function SK.put(n, d)
    sk.u = n
    if d then
        sk.d = d
        facing = facing + angDiff(Surf.flat(d, n), facing)
    else
        sk.d = Surf.onto(facing, n)
    end
    sk.seen = facing
end

-- Whatever has turned `facing` since the last look (the stick, a revert, a switch of stance) turned the board on
-- its face.
function SK.sync()
    local u = sk.u
    if not u then return SK.put(Surf.UP) end
    if not sk.d or u.z > 0.9999999 then
        sk.d, sk.seen = Surf.onto(facing, u), facing -- (on the level a heading says it all)
    elseif facing ~= sk.seen then
        sk.d, sk.seen = Surf.turn(sk.d, u, facing - sk.seen), facing
    end
end

-- Where a truck stands, `p` being its place on the face `u`: the ground found there, square to the face, unless
-- that is not this ground going on (a drop, a kerb).
function SK.truck(p, u)
    local hit, hp = ray(p + u * Config.StepUp, p - u, board)
    if hit and math.abs(Surf.dot(hp - p, u)) <= Config.TruckStep then return hp end
    return p
end

-- The board leaves the ground with velocity `v` (m/s, as it is in the world): the air's own numbers. In the air
-- `facing` is the line the board travels along over the ground, `speed` its speed along that and `vz` its speed
-- upwards; the nose keeps the heading it had on the face (sk.ah) and the body turns from there.
--
-- Up off a steep face, the top of a quarter pipe above all, what the board has of speed out over the top is taken
-- away and it is given a little drift back: it comes down on the curve it left. Skate 3 bends such a jump for the
-- same end (physics_trajectory: the landing it likes best within 40 degrees of the jump's own line, ConeAngleZ, a
-- transition scoring high among them); that it is done this way is ours.
function SK.fly(v)
    local u, d = sk.u or Surf.UP, sk.d
    sk.re = nil
    if u.z > 0.999999 and v.x * v.x + v.y * v.y > 1e-8 and d and Surf.dot(d, vector3(v.x, v.y, 0.0)) * speed > 0.0 then
        -- (off level ground the board's line and its speed along it are what they were)
        vz, sk.ah = v.z, nil
        return
    end
    if u.z < Config.VertFace and v.z > 0.5 then
        local side = Surf.unit(vector3(u.x, u.y, 0.0)) -- level, away from the face
        local out = -(v.x * side.x + v.y * side.y)
        -- Where it is to come down: 30 cm under where it left, a hand's width in from the face. Where the face is
        -- THERE is looked for: the board goes on along the top of the ramp while it is in the air, and the wall of
        -- a bowl curves away from that line.
        local t = (v.z + math.sqrt(v.z * v.z + 0.6 * Tune.gravity)) / Tune.gravity
        local at = pos + vector3(v.x + side.x * out, v.y + side.y * out, 0.0) * t - vector3(0.0, 0.0, 0.3)
        local hit, hp, n = ray(at + side * 2.0, at - side * 2.0, board)
        local gap = (hit and Surf.dot(n, side) > 0.3) and Surf.dot(hp - at, side) or 0.3 * u.z
        local back = (gap + 0.03) / t
        if math.abs(back) < 1.5 then
            if out > -back then v = v + side * (out + back) end
            sk.re = { n = u, z = pos.z }
        end
    end
    sk.ah = facing
    local h = math.sqrt(v.x * v.x + v.y * v.y)
    if h > 0.001 then
        local th = Surf.heading(v)
        if math.abs(angDiff(th, facing)) <= 90.0 then
            facing, speed = facing + angDiff(th, facing), h
        else
            facing, speed = facing + angDiff(th + 180.0, facing), -h
        end
    else
        speed = 0.0
    end
    vz = v.z
    if sk.ah == facing and (sk.up or u).z > 0.999999 then sk.ah = nil end
end

-- The heading of the board's nose in the air (in sk.up's frame) before the body's own turn.
function SK.noseH() return sk.ah or facing end

-- In the air the rider levels out, as he always did, unless it is the wall of a ramp he is coming down on: up off
-- the top of one he stays turned to it, and on the way down it he comes round to its curve (Skate 3 turns the rider
-- to the ground under the landing: SpeedToAlignToGround_PhysAir). A rider who has come away from the ramp altogether
-- rights himself for the floor.
function SK.alignAir(dt)
    local up = sk.up
    local want, k = Surf.UP, 1.0 - 0.75 ^ (dt * 60.0)
    local re = sk.re
    if re and pos.z > re.z - 0.2 then
        want = re.n -- (still above the lip: the face is not there to be found)
    elseif re or up.z < Config.VertFace then
        local hit, _, n = ray(pos + up * (S3.lift + 0.3), pos - up * 2.0, board)
        if hit and Surf.dot(n, up) > 0.5 and n.z < 0.8 then want = n else sk.re = nil end
    end
    if want == Surf.UP and sk.ah then
        -- (levelling out: the nose comes round to the line the board travels along as the tilt goes. Off a slope the
        -- two are not quite the same thing: see SK.put)
        local off = angDiff(facing, sk.ah)
        sk.ah = math.abs(off) > 0.01 and sk.ah + off * k or nil
    end
    if want.x == up.x and want.y == up.y and want.z == up.z then return end
    if want ~= Surf.UP then k = 1.0 - (1.0 - Tune.alignAir) ^ (dt * 30.0) end
    sk.up = Surf.unit(up + (want - up) * k) or want
    if want == Surf.UP and sk.up.z > 0.999999 then sk.up = Surf.UP end
end

-- The spin at which the board lies along the line it is travelling, nearest the spin it has: what the body squares
-- up to before a landing. On the level that is the nearest half turn; standing off a wall it is the line the board
-- is falling along there.
function SK.square()
    local up = sk.up
    if not (sk.re or up.z < Config.VertFace) then return math.floor(spin / 180.0 + 0.5) * 180.0 end
    local f = fwd(facing)
    local way = Surf.along(vector3(f.x * speed, f.y * speed, vz), up)
    if not way or (speed * speed + vz * vz) < 0.25 then return spin end
    local a = Surf.angle(Surf.onto(SK.noseH() + spin, up), way, up)
    if a > 90.0 then a = a - 180.0 elseif a < -90.0 then a = a + 180.0 end
    return spin + a
end

-- The board coming down while it is not upright (off the wall of a ramp): the face it is turned to, looked for the
-- way its wheels point from where it was to where it will be, and the floor straight below as well. Returns hit,
-- where, the face.
function SK.touch(target)
    local up, lift = sk.up, math.min(S3.lift, 0.08)
    local hit, gp, gn = ray(pos + up * (S3.lift + 0.1), target + up * (lift - 0.05), board)
    if hit and Surf.dot(gn, up) > 0.3 then return true, gp, gn end
    local h = S3.lift * up.z
    hit, gp, gn = ray(vector3(target.x, target.y, pos.z + h + 0.1), target + vector3(0, 0, h - 0.05), board)
    if hit and gn.z > 0.5 then return true, gp, gn end
    return false
end

-- ... and will it be down within `t` seconds?
function SK.soon(t)
    local f = fwd(facing)
    local to = pos + f * (speed * t) + vector3(0, 0, vz * t - 0.5 * Tune.gravity * t * t)
    return (ray(pos + sk.up * (S3.lift + 0.1), to - sk.up * 0.05, board))
end

-- A landing on a face the board is not upright on, or with the board not upright (the curve of a ramp): the nose
-- as it came down (heading `noseH` in the air's frame `up`) laid on the face `n`, and `vt`, what the board has of
-- speed along that face. A board rolls along its own length, forwards or backwards: whichever of the two is the way
-- that speed goes. Returns the way the nose points as it rolls on and how far the board was turned off that line
-- (degrees to the left); sets `speed`. keep = there was no jump to come down from (a hop over a kerb): the nose
-- stays as it is.
function SK.settle(n, up, noseH, vt, keep)
    local nose = Surf.along(Surf.onto(noseH, up), n)
    local v = #vt
    local way = v > 0.5 and vt / v or nil
    nose = nose or way or Surf.onto(facing, n)
    if keep or not way then
        speed = Surf.dot(vt, nose)
        return nose, 0.0
    end
    local back = Surf.dot(nose, way) < 0.0
    local on = back and way * -1.0 or way
    speed = back and -v or v
    return on, Surf.angle(on, nose, n)
end

local function notify(msg)
    BeginTextCommandThefeedPost('STRING')
    AddTextComponentSubstringPlayerName(msg)
    EndTextCommandThefeedPostTicker(false, false)
end

local function text(str, x, y, scale, r, g, b)
    SetTextFont(4)
    SetTextScale(scale, scale)
    SetTextColour(r, g, b, 255)
    SetTextOutline()
    SetTextCentre(true)
    BeginTextCommandDisplayText('STRING')
    AddTextComponentSubstringPlayerName(str)
    EndTextCommandDisplayText(x, y)
end

local function show(msg, seconds)
    message, messageUntil = msg, GetGameTimer() + math.floor(seconds * 1000)
end

-- Sounds: html/sound.js plays Skate 3's own recordings from the sound pack in skate3_assets; this tells it what
-- the board is doing. Without the pack there is no sound.
local soundT, soundOn = 0.0, false

local function sound(name, strength)
    if Config.Sound then SendNUIMessage({ t = 'hit', name = name, v = strength }) end
end

-- What the board is on, for the sound of it: GTA's surface materials (materials.dat) sorted onto the surfaces
-- Skate 3 has rolling recordings of. A material not listed here counts as smooth concrete. (Dusty concrete and
-- plaster as rough, tarmac under ice or snow, the odd metals and woods: as SK8V's materials.rs sorts them.)
local SURFACE_OF = {}
for surface, names in pairs({
    concrete_rough = { 'CONCRETE_POTHOLE', 'CONCRETE_DUSTY', 'PLASTER_SOLID', 'PLASTER_BRITTLE', 'BREEZE_BLOCK', 'ROCK', 'ROCK_MOSSY', 'ROCK_NOINST', 'STONE', 'BRICK',
                       'BRICK_PAVEMENT', 'SANDSTONE_SOLID', 'SANDSTONE_BRITTLE' },
    concrete_aggregate = { 'COBBLESTONE', 'PAVING_SLAB', 'RUMBLE_STRIP', 'GRAVEL_SMALL', 'GRAVEL_LARGE', 'GRAVEL_DEEP',
                           'GRAVEL_TRAIN_TRACK' },
    asphalt_smooth = { 'TARMAC', 'TARMAC_PAINTED', 'ICE_TARMAC', 'SNOW_TARMAC', 'STUNT_RAMP_SURFACE' },
    asphalt_rough = { 'TARMAC_POTHOLE', 'DIRT_TRACK', 'MUD_HARD', 'SAND_COMPACT', 'CLAY_HARD' },
    metal = { 'METAL_SOLID_SMALL', 'METAL_SOLID_MEDIUM', 'METAL_SOLID_LARGE', 'METAL_HOLLOW_SMALL',
              'METAL_HOLLOW_MEDIUM', 'METAL_HOLLOW_LARGE', 'METAL_CHAINLINK_SMALL', 'METAL_CHAINLINK_LARGE',
              'METAL_CORRUGATED_IRON', 'METAL_GRILLE', 'METAL_RAILING', 'METAL_DUCT', 'METAL_GARAGE_DOOR',
              'METAL_MANHOLE', 'METAL_SOLID_ROAD_SURFACE', 'CAR_METAL', 'CAR_ENGINE', 'VFX_METAL_ELECTRIFIED',
              'VFX_METAL_WATER_TOWER', 'VFX_METAL_STEAM', 'VFX_METAL_FLAME', 'PHYS_ELECTRIC_FENCE',
              'PHYS_ELECTRIC_METAL', 'PHYS_BARBED_WIRE' },
    wood = { 'WOOD_SOLID_SMALL', 'WOOD_SOLID_MEDIUM', 'WOOD_SOLID_LARGE', 'WOOD_SOLID_POLISHED', 'WOOD_FLOOR_DUSTY',
             'WOOD_HOLLOW_SMALL', 'WOOD_HOLLOW_MEDIUM', 'WOOD_HOLLOW_LARGE', 'WOOD_CHIPBOARD', 'WOOD_OLD_CREAKY',
             'WOOD_HIGH_DENSITY', 'WOOD_LATTICE', 'WOOD_HIGH_FRICTION', 'LAMINATE', 'TREE_BARK', 'WOODCHIPS',
             'SLATTED_BLINDS', 'VFX_WOOD_BEER_BARREL' },
}) do
    for _, n in ipairs(names) do SURFACE_OF[GetHashKey(n) & 0xFFFFFFFF] = surface end
end
-- ... and onto the kinds of ground Skate 3's friction knows (physics_surfaces). Smooth unless listed.
local GROUND_OF = {}
for kind, names in pairs({
    rough = { 'CONCRETE_POTHOLE', 'TARMAC_POTHOLE', 'COBBLESTONE', 'BRICK', 'BRICK_PAVEMENT', 'PAVING_SLAB',
              'BREEZE_BLOCK', 'ROCK', 'ROCK_MOSSY', 'ROCK_NOINST', 'STONE', 'SANDSTONE_SOLID', 'SANDSTONE_BRITTLE',
              'RUMBLE_STRIP', 'WOOD_OLD_CREAKY', 'METAL_GRILLE', 'METAL_CHAINLINK_SMALL', 'METAL_CHAINLINK_LARGE',
              'METAL_CORRUGATED_IRON' },
    slow = { 'GRASS_SHORT', 'GRASS', 'DIRT_TRACK', 'MUD_HARD', 'SAND_COMPACT', 'SAND_TRACK', 'CLAY_HARD',
             'GRAVEL_SMALL', 'GRAVEL_TRAIN_TRACK', 'WOODCHIPS', 'CARPET_SOLID', 'CARPET_SOLID_DUSTY',
             'CARPET_FLOORBOARD', 'ROOF_FELT', 'TARPAULIN', 'CLOTH', 'RUBBER' },
    veryslow = { 'GRASS_LONG', 'SAND_LOOSE', 'SAND_WET', 'SAND_UNDERWATER', 'SAND_DRY_DEEP', 'SAND_WET_DEEP',
                 'GRAVEL_LARGE', 'GRAVEL_DEEP', 'MUD_POTHOLE', 'MUD_SOFT', 'MUD_UNDERWATER', 'MUD_DEEP', 'MARSH',
                 'MARSH_DEEP', 'SOIL', 'CLAY_SOFT', 'SNOW_LOOSE', 'SNOW_COMPACT', 'SNOW_DEEP', 'SNOW_TARMAC', 'HAY',
                 'BUSHES', 'BUSHES_NOINST', 'TWIGS', 'LEAVES', 'FOAM' },
    slippery = { 'ICE', 'ICE_TARMAC', 'MARBLE', 'CERAMIC', 'WOOD_SOLID_POLISHED', 'LINOLEUM', 'LAMINATE',
                 'GLASS_SHOOT_THROUGH', 'GLASS_BULLETPROOF', 'GLASS_OPAQUE', 'PERSPEX', 'OIL', 'PLASTIC',
                 'PLASTIC_HIGH_DENSITY' },
}) do
    for _, n in ipairs(names) do GROUND_OF[GetHashKey(n) & 0xFFFFFFFF] = kind end
end
local surface = 'concrete_smooth'   -- what the wheels are on, for the sound
local ground = 'smooth'             -- ... and for how it rolls
local surfaceT = 0.0
local surfaceSeen, surfaceSeenT     -- another surface under them: it has to stay there a moment before it is heard

-- The surface under p (looked for 0.3 m either side of its height): which recording it is and what kind of ground
-- it is to roll on. nil with nothing there.
local function surfaceAt(p, flags)
    local h = StartExpensiveSynchronousShapeTestLosProbe(p.x, p.y, p.z + 0.3, p.x, p.y, p.z - 0.3,
        flags or RAY_FLAGS, board or 0, 7)
    local _, hit, _, _, material = GetShapeTestResultIncludingMaterial(h)
    if hit ~= 1 then return nil end
    material = material & 0xFFFFFFFF
    return SURFACE_OF[material] or 'concrete_smooth', GROUND_OF[material] or 'smooth'
end

-- What happened, for looking into a report afterwards (Config.Log).
local function note(fmt, ...)
    if Config.Log then print(('[skateboard] ' .. fmt):format(...)) end
end

-- Where p is as the camera hears it: metres to its right, above it and BEHIND it (in front is negative), which is
-- how the sound page counts. The sounds are played from there.
local function heardAt(p)
    local c, r = GetFinalRenderedCamCoord(), GetFinalRenderedCamRot(2)
    local pitch, yaw = math.rad(r.x), math.rad(r.z)
    local fx, fy, fz = -math.sin(yaw) * math.cos(pitch), math.cos(yaw) * math.cos(pitch), math.sin(pitch)
    local rx, ry = math.cos(yaw), math.sin(yaw)                -- the camera's right (its roll is left out)
    local ux, uy, uz = ry * fz, -rx * fz, rx * fy - ry * fx    -- its up = right x forward
    local dx, dy, dz = p.x - c.x, p.y - c.y, p.z - c.z
    return { dx * rx + dy * ry, dx * ux + dy * uy + dz * uz, -(dx * fx + dy * fy + dz * fz) }
end

-- How loud the board is, 0 .. 1 (a slider position): the rider's own setting (/skatevolume) or the server's, times
-- the game's own SFX volume setting.
local function soundVolume()
    local own = GetResourceKvpInt('skatevolume') -- 1 .. 101, 0 = never set
    local v = own > 0 and (own - 1) / 100.0 or Config.SoundVolume
    if Config.SoundFollowsGame then
        local sfx = GetProfileSetting(300) -- PROFILE_AUDIO_SFX_LEVEL, 0 .. 10
        if sfx >= 0 and sfx <= 10 then v = v * sfx / 10.0 end
    end
    return v
end
local soundVol, soundVolT = nil, 0.0

local function soundWorld()
    if not Config.SoundFromBoard then return false end
    return { near = Config.SoundNear, rolloff = Config.SoundRolloff, model = Config.SoundEars }
end

-- What the sound page says it could load: { loaded, total, rate, state }, once it has answered.
local soundReport
RegisterNUICallback('sound_ready', function(data, cb)
    soundReport = type(data) == 'table' and data or nil
    cb('ok')
end)

-- The sound pack with the rider's own picks in it (/skatesound). nil without a pack.
local SOUND_SLOTS = { 'grind_concrete', 'grind_metal', 'grind_wood', 'slide_concrete', 'slide_metal', 'slide_wood' }

local function soundPack()
    local pack = S3.sounds()
    if not pack or type(pack.sounds) ~= 'table' then return nil end
    local grinds = pack.choices and pack.choices.grind
    if grinds then
        for _, slot in ipairs(SOUND_SLOTS) do
            local n = GetResourceKvpInt('skatesound_' .. slot)
            if n and n >= 1 and grinds[n] then
                pack.sounds[slot] = grinds[n]
                pack.sounds[slot].pick = n
            end
        end
    end
    return pack
end

local function soundStop()
    if soundOn then SendNUIMessage({ t = 'stop' }) end
    soundOn = false
end

local function loadModel(model)
    if not IsModelInCdimage(model) then return false end
    RequestModel(model)
    local deadline = GetGameTimer() + 3000
    while not HasModelLoaded(model) and GetGameTimer() < deadline do Wait(0) end
    return HasModelLoaded(model)
end

local function loadDict(dict)
    if not dict or not DoesAnimDictExist(dict) then return false end
    RequestAnimDict(dict)
    local deadline = GetGameTimer() + 3000
    while not HasAnimDictLoaded(dict) and GetGameTimer() < deadline do Wait(0) end
    return HasAnimDictLoaded(dict)
end

-- The model for a new board: Skate 3's own deck of the rider's choice when skate3_assets has the board (deck.lua;
-- the second result says so: that board gets its trucks and wheels put on), else the first GTA prop of the list that
-- exists. Asked for every new board, not remembered: a remembered model may no longer be in memory.
local function pickBoardModel()
    local deck = Deck.model()
    if deck and loadModel(deck) then return deck, true end
    for _, name in ipairs(Config.BoardModels) do
        local hash = joaat(name)
        if loadModel(hash) then return hash, false end
    end
end

-- The rider plays the mirrored clips: regular stance (Skate 3's clips are authored goofy), or goofy riding switch.
local function mirrored() return (not Config.Goofy) ~= switch end

local targetAdded = false

local function itemRequired()
    return Config.RequireItem and GetResourceState('ox_inventory') == 'started'
end

local function useTarget()
    return Config.UseTarget and GetResourceState('ox_target') == 'started'
end

local function deleteBoard()
    Deck.undress() -- (its trucks and wheels, when it is Skate 3's board)
    if board and DoesEntityExist(board) then
        if targetAdded then
            pcall(function() exports.ox_target:removeLocalEntity(board, { 'skateboard_ride', 'skateboard_pickup' }) end)
        end
        SetEntityAsMissionEntity(board, true, true)
        DeleteObject(board)
    end
    board, targetAdded = nil, false
end

-- Ask the server whether we own a board (the ox_inventory item). The client only asks; the server decides.
local reply
RegisterNetEvent('skateboard:boardReply', function(ok) reply = ok end)

local function ownsBoard()
    if not itemRequired() then return true end
    reply = nil
    TriggerServerEvent('skateboard:requestBoard')
    local deadline = GetGameTimer() + 3000
    while reply == nil and GetGameTimer() < deadline do Wait(0) end
    return reply == true
end

-- ------------------------------------------------------------------ trick lines

-- A trick goes into the line. key = what it is for the points tables (and for counting repeats), points = what
-- it is worth before the line's multiplier, scale = bonuses (out of a manual, into a grind ...).
local function addToLine(label, key, points, scale)
    local n = counts[key] or 0
    counts[key] = n + 1
    local worth = points * Tune.repeatScale(n) * (scale or 1.0)
    line[#line + 1] = label
    lineScore = lineScore + math.floor(worth * Tune.multiplier(momentum) + 0.5)
    momentum = math.min(Tune.momentumCap(), momentum + worth)
    rollTime = 0.0
end

local function cashLine()
    if #line == 0 then return end
    -- Skate 3's tables carry their own multiplier; the stand-in rule without them is points x tricks
    local total = Tune.scoring() and lineScore or lineScore * #line
    totalScore = totalScore + total
    local sum = Tune.scoring() and '' or (lineScore .. ' x' .. #line .. ' = ')
    if Config.ShowTricks then show('~g~' .. table.concat(line, ' + ') .. '~s~\n' .. sum .. '~y~' .. total, 3.0) end
    line, lineScore, momentum, counts = {}, 0, 0.0, {}
end

local function loseLine()
    line, lineScore, momentum, counts = {}, 0, 0.0, {}
end

local function endManual()
    if manual and manual.hold > Config.ManualEngage then manualOut = clock end
    if manual and manual.t > 0.2 then
        local key = manual.nose and 'manual_nose' or 'manual_tail'
        addToLine(manual.label, key, Tune.baseScore(key) + Tune.manualScore(manual.t, manual.dist))
    end
    manual = nil
end

local function endGrind()
    if grind then
        -- (with Skate 3's points the grind's own name in its table: side, grind and the hand on the board)
        local key, label = grind.name, grind.label
        if Tune.scoring() and grind.key then
            key = grind.key .. (grind.grabKey and ('_' .. grind.grabKey) or '')
            if Tune.baseScore(key) == 0 then key = grind.key end
        end
        if grind.grabLabel then label = label .. ' ' .. grind.grabLabel end
        addToLine(label, key, Tune.baseScore(key) + Tune.grindScore(grind.t, grind.dist))
    end
    grind = nil
end

-- What the other buttons made of the grab is over (a foot off the board, both feet off, superman ...): each of
-- those counts under its own name.
local function endGrabVar()
    local g = grab
    if not g then return end
    if g.var and not g.var:find('^tw_') and g.varT > 0.15 and air then
        local key, label = S3.grabName(g.kind, g.var)
        if key then air.tricks[#air.tricks + 1] = { label, key, Tune.baseScore(key) + Tune.grabScore(g.varT) } end
    end
    g.var, g.varT = nil, 0.0
end

-- Let go of the board: the grab counts for the jump if it was held long enough to see, under the name of the tweak
-- it was last held in (an FS grab with the nose pushed down is a nosebone).
local function endGrab()
    if grab then
        endGrabVar()
        if grab.t > 0.15 and air then
            local key, label = 'grab_' .. grab.kind, grab.label
            if S3.active() then key, label = S3.grabName(grab.kind, grab.tweak and ('tw_' .. grab.tweak) or nil) end
            air.tricks[#air.tricks + 1] = { label, key, Tune.baseScore(key) + Tune.grabScore(grab.t) }
        end
    end
    grab = nil
end

-- A grab begins. hand = 'back' | 'front' | 'both'.
local function newGrab(kind, hand)
    local label = Config.GrabNames[kind] or 'Grab'
    if S3.active() then label = select(2, S3.grabName(kind)) or label end
    return { kind = kind, hand = hand, label = label, t = 0.0, varT = 0.0 }
end

-- Grabs the hand stays on whatever the other hand does (Skate 3: their states cannot be interrupted), and of those
-- the ones that need the stick held as well (BoardAdjustUp / Down.xml).
local STICKY = { tail = true, seatbelt = true, crail = true, nose = true, mute = true, stale = true }
local TIP = { tail = true, seatbelt = true, crail = true, nose = true }

-- Where the right stick is held out in the air (Skate 3's BoardAdjust*.xml): 'up' | 'down' | 'left' | 'right', or
-- nil. Up and down are the stick's own. Left and right are the way the NOSE swings: the stick is the foot on the
-- tail, as in Flick-It, so for the clips as authored (goofy) the stick to the right takes the tail right and the nose
-- left. That is read out of the game's data, not stated in it; Config.SideStickTail = false turns the two round.
local function stickZone(kb)
    if kb then return padPressed(C.ctrl) and 'up' or (padPressed(C.shift) and 'down' or nil) end
    if stickX * stickX + stickY * stickY < Config.AdjustMin * Config.AdjustMin then return nil end
    if math.abs(stickY) >= math.abs(stickX) then return stickY > 0 and 'up' or 'down' end
    local noseLeft = (stickX > 0) ~= mirrored()
    if not Config.SideStickTail then noseLeft = not noseLeft end
    return noseLeft and 'left' or 'right'
end

-- The hand comes off the board on the ground: it counts like a grab, by how long it was held.
local function endGroundGrab()
    if ggrab and ggrab.t > 0.15 then
        local key = 'gnd_' .. ggrab.kind .. 'grab'
        addToLine(ggrab.label, key, Tune.baseScore(key) + Tune.grabScore(ggrab.t))
    end
    ggrab = nil
end

-- The foot goes back on the board.
local function endOneFoot()
    if onefoot and onefoot.t > 0.15 and air then
        local key = 'ollie_onefoot_' .. onefoot.kind
        air.tricks[#air.tricks + 1] = { onefoot.kind == 'front' and 'One Foot' or 'Back Foot Off', key,
                                        Tune.baseScore(key) + Tune.grabScore(onefoot.t) }
    end
    onefoot = nil
end

-- Sitting up out of the coffin.
local function endCoffin()
    if coffin and coffin.t > 0.15 then
        local points = Tune.baseScore('coffin') + Tune.grabScore(coffin.t)
        if mode == 'air' and air then
            air.tricks[#air.tricks + 1] = { 'Coffin', 'coffin', points }
        else
            addToLine('Coffin', 'coffin', points)
        end
    end
    coffin = nil
end

-- ------------------------------------------------------------------ Flick-It (built-in reader, no skate3_assets)

local fl = { state = 'idle' }
local function resetFlick(state)
    fl.state, fl.t, fl.center, fl.leave, fl.left, fl.right, fl.sideT = state or 'idle', 0.0, 0.0, nil, false,
        false, nil
end
resetFlick()

-- Returns a trick name and the flick time (fast flicks pop higher) when a flick completes.
local function readFlick(sx, sy, dt, canPop)
    if Config.Goofy ~= switch then sx = -sx end
    local mag = math.sqrt(sx * sx + sy * sy)
    local ang = math.deg(math.atan(sy, sx))

    if fl.state == 'cool' then
        if mag < 0.35 then resetFlick() end
        return
    end
    if fl.state == 'idle' then
        if not canPop then return end
        if mag > 0.65 and ang > -125 and ang < -55 then resetFlick('tail')
        elseif mag > 0.65 and ang > 55 and ang < 125 then resetFlick('nose') end
        return
    end

    fl.t = fl.t + dt
    if mag < 0.3 then
        fl.center = fl.center + dt
        if fl.center > 0.25 then resetFlick() end
        return
    end
    fl.center = 0.0

    local function fire(name)
        local flickTime = fl.leave and (fl.t - fl.leave) or 0.1
        resetFlick('cool')
        return name, flickTime
    end

    if fl.state == 'tail' then
        if not (mag > 0.6 and ang > -125 and ang < -55) and not fl.leave then fl.leave = fl.t end
        if mag > 0.6 then
            if math.abs(ang) >= 150 then
                fl.left, fl.sideT = true, fl.sideT or fl.t
            elseif math.abs(ang) <= 30 then
                fl.right, fl.sideT = true, fl.sideT or fl.t
            elseif ang > 30 and ang < 150 then
                if fl.left and ang > 60 then return fire('360 Flip') end
                if fl.right and ang < 120 then return fire('Laser Flip') end
                if ang >= 110 then return fire('Kickflip') end
                if ang <= 70 then return fire('Heelflip') end
                return fire('Ollie')
            end
            if fl.sideT and fl.t - fl.sideT > 0.15 then return fire(fl.left and 'Pop Shove-it' or 'FS Shove-it') end
        end
    elseif fl.state == 'nose' then
        if not (mag > 0.6 and ang > 55 and ang < 125) and not fl.leave then fl.leave = fl.t end
        if mag > 0.6 and ang < -30 and ang > -150 then
            if ang <= -110 then return fire('Nollie Kickflip') end
            if ang >= -70 then return fire('Nollie Heelflip') end
            return fire('Nollie')
        end
    end
end

-- ------------------------------------------------------------------ Flick-It (Skate 3's patterns)

-- The crouch the stick is asking for (ActionGraphIncludes/onground.xml "Antic"): how far round from straight down
-- the stick is held. Up to 30 degrees: ollie; 30-90 to a side: a shuvit wind-up; the same from straight up for
-- nollies. The side is not mirrored with the rider; the game swaps the wind-up instead.
local function readAntic(px, py)
    local mag = math.sqrt(px * px + py * py)
    if mag < (antic and Config.AnticRelease or Config.AnticEngage) then return nil end
    local a = math.atan(px, py) -- 0 = straight down, positive = towards the right
    local abs = math.abs(a)
    if abs <= 0.52 then return 'ollie' end
    if abs >= 2.62 then return 'nollie' end
    local bs = (px > 0) ~= mirrored() -- authored (goofy): the stick out to the right winds up the BS shuvit
    if abs <= 1.57 then return bs and 'shuv' or 'fsshuv' end
    return bs and 'nshuv' or 'nfsshuv'
end

-- How strong a pop is, 0 .. 1. Skate 3 sets a trick's height from the crouch ("AnticStrength", and its crouch
-- ramps in over 0.2 s): a flick straight through the crouch is the weakest pop, a crouch held that long the
-- strongest. The crouch is timed for each end of the board (tail for ollies, nose for nollies).
local function crouchEnd(a)
    if not a then return nil end
    return (a == 'ollie' or a == 'shuv' or a == 'fsshuv') and 'tail' or 'nose'
end

local function trackCrouch(want, dt)
    local side = crouchEnd(want)
    if side ~= crouch.side then
        if crouch.side then
            local left = crouch[crouch.side] -- the stick has just left that crouch
            left.held, left.at = crouch.t, clock
        end
        crouch.side, crouch.t = side, 0.0
    end
    if side then crouch.t = crouch.t + dt end
end

local function crouchStrength(nose)
    local side = nose and 'nose' or 'tail'
    local t = crouch.side == side and crouch.t or 0.0
    if clock - crouch[side].at <= 0.5 then t = math.max(t, crouch[side].held) end
    return clamp(t / Config.AnticFullTime, 0.0, 1.0)
end

local function resetCrouch()
    crouch.side, crouch.t = nil, 0.0
    crouch.tail.held, crouch.tail.at, crouch.nose.held, crouch.nose.at = 0.0, -10.0, 0.0, -10.0
end

-- The built-in reader has no crouch to time: a quick final stroke is a strong pop.
local function flickStrength(flickTime) return clamp(1.0 - (flickTime or 0.1) * 5.0, 0.0, 1.0) end

-- The crouch follows the stick with a little inertia: a flick sweeps the stick through other zones on its way
-- (out of the crouch, across the centre, up into the nollie zone) and none of those should show before the trick
-- itself starts.
local function setAntic(want, dt)
    if want == antic then
        anticNext, anticT = want, 0.0
        return
    end
    if want ~= anticNext then anticNext, anticT = want, 0.0 end
    anticT = anticT + dt
    if anticT >= (want and Config.AnticDwell or Config.AnticLinger) then antic, anticT = want, 0.0 end
end

local startFlip, pop, requestPop -- defined below

-- A flick that comes during a flip is an underflip when it is one of these gestures (onboardgeneral.xml
-- "Underflips").
local UNDERFLIP = { Nollie = true, Kickflip = true, Heelflip = true, N_Kickflip = true, N_Heelflip = true,
                    L_F_Kickflip = true, L_F_Heelflip = true, L_B_Kickflip = true, L_B_Heelflip = true, Fingerflip = true }
-- Feed this frame's stick to the trick reader. Returns nothing; starts pops and late flips itself.
-- The right stick's gestures while a hand is on the board: Skate 3's finger-flip set, with the late flips that count
-- as finger flips too (T_Grab.xml); for a crail or a seatbelt only the varials and the late shuvits do anything
-- (BoardAdjustUp / Down.xml).
local grabSets, grabSetsOf

local function grabPatterns(pats, kind)
    if grabSetsOf ~= pats then
        local flips, shuvs = {}, {}
        for _, q in ipairs(pats.grab or {}) do
            flips[#flips + 1] = q
            if q.name ~= 'Fingerflip' then shuvs[#shuvs + 1] = q end
        end
        for _, q in ipairs(pats.air or {}) do
            if q.name:find('Shuvit') then shuvs[#shuvs + 1] = q else flips[#flips + 1] = q end
        end
        grabSets, grabSetsOf = { flips = flips, shuvs = shuvs }, pats
    end
    return (kind == 'crail' or kind == 'seatbelt') and grabSets.shuvs or grabSets.flips
end

local function readTricks(dt, kb, darkHeld)
    -- (a hand on the board comes before the crouch: Skate 3's "Grabbing" is ahead of "Antic" on the ground)
    local canPop = mode ~= 'air' and not pending and not switching and landLock <= 0.0 and not ggrab and not hippy
        and not revert
    local pats = S3.active() and S3.patterns() or nil
    if pats then
        local px, py = Flick.toPattern(stickX, stickY)
        local set = pats.ground
        local ax, ay = px, py -- the stick as the crouch reads it
        if mode == 'air' then
            set = pats.air
            if grab and pats.grab and not S3.tricking() then set = grabPatterns(pats, grab.kind) end
        elseif mode == 'grind' and grind.slide then
            -- sideways on the rail the gestures turn with the board (skater90.pat / skaterN90.pat): the crouch is a
            -- pull towards the tail, which is to the left when the rider is turned right and the other way round
            if grind.turn < 0 then
                set, ax, ay = pats.ground90 or pats.ground, py, -px
            else
                set, ax, ay = pats.groundN90 or pats.ground, -py, px
            end
        end
        if canPop and not (manual and manual.hold > Config.ManualEngage) then
            local want = readAntic(ax, ay)
            trackCrouch(want, dt)
            setAntic(want, dt)
        else
            trackCrouch(nil, dt)
            antic, anticNext = nil, nil
        end
        local name = Flick.update(clock, px, py, set, Config.FlickSegTime)
        if name then
            if (pending or (mode == 'air' and S3.tricking())) and UNDERFLIP[name] then
                uflipAsked = true -- a second flick while the board is turning
            elseif mode == 'air' then
                if air and S3.dark() then
                    -- the board is upside down under the feet: a late flip turns it the right way up
                    local label, key = S3.darkOut(name)
                    if label then
                        air.tricks[#air.tricks + 1] = { label, key, Tune.baseScore(key) }
                        sound('flip', 0.7)
                    end
                elseif air and grab then
                    -- a flick with a hand on the board: the board is flipped by hand
                    local label, key, to = S3.fingerflip(name)
                    if label then
                        air.tricks[#air.tricks + 1] = { label, key, Tune.baseScore(key) }
                        sound('flip', 0.7)
                        if to then
                            -- ... and caught in another grab, by the same hand
                            local hand = grab.hand
                            endGrab()
                            grab = newGrab(to, hand)
                        end
                    end
                elseif air and not grab then
                    -- (with the dark-catch button held the board is caught upside down; a foot that is off the
                    -- board goes back on for the flip)
                    endOneFoot()
                    local label, key = S3.lateflip(name, darkHeld)
                    if label then
                        air.tricks[#air.tricks + 1] = { label, key, Tune.baseScore(key) }
                        sound('flip', 0.7)
                    end
                end
            elseif canPop then
                local key, label, nose = S3.trick(name)
                if key then
                    requestPop(key, label, crouchStrength(nose))
                    flickHeld = true -- until the stick comes back from where the flick left it
                end
            end
        end
    else
        antic, anticNext = nil, nil
        local name, flickTime = readFlick(stickX, stickY, dt, canPop)
        if S3.active() and (fl.state == 'tail' or fl.state == 'nose') then
            antic = fl.state == 'tail' and 'ollie' or 'nollie'
        end
        if name and canPop then requestPop(BUILTIN[name], S3.trickLabel(BUILTIN[name]), flickStrength(flickTime)) end
    end
    -- keyboard shortcuts for the basics
    if kb and canPop and not pending then
        local key
        if padJust(C.space) then key = 'Ollie'
        elseif padJust(C.q) then key = 'Kickflip'
        elseif padJust(C.e) then key = 'Heelflip'
        elseif padJust(C.r) then key = 'PopShuvit' end
        if key then requestPop(key, S3.trickLabel(key), 0.5) end
    end
end

startFlip = function(name)
    local t = STOCK[name]
    if flip or not t or not (t.roll or t.yaw) then return end
    flip = { name = name, roll = t.roll or 0, yaw = t.yaw or 0, t = 0.0 }
end

-- Leave the ground (or a manual, or a rail). strength 0 .. 1 = how strong the pop is.
pop = function(name, label, strength, fromManual, plant)
    local fromGrind = mode == 'grind'
    if fromGrind then
        -- off the rail the way the board was travelling, with the body where the grind had it
        local g = grind
        endGrind()
        spin = angDiff(g.facing, g.h)
        facing, speed = g.h, g.speed
    end
    endManual()
    local launch = Config.OllieSpeed * (0.8 + 0.4 * strength)
    if S3.active() then
        -- Skate 3 pops half height off a rail (T_Trick.xml: SetTrickHeight 0.5 from a grind)
        launch = Tune.popSpeed(fromGrind and Config.GrindPopStrength or strength, speed)
    end
    if plant then
        -- off a planted foot (boneless, fastplant, no comply): Skate 3's own jump for it, and the plant costs speed
        launch = Tune.plantJump()
        speed = speed * Tune.plantKeep(speed)
    end
    -- (on a rail the speed is along the rail: the rider stands backwards on it when the body is turned round)
    local backwards = speed < -0.5 or (fromGrind == true and math.abs(spin) > 90.0)
    local prefix = (backwards and 'Fakie ' or '') .. (switch and 'Switch ' or '')
    mode, airTime = 'air', 0.0
    if fromGrind then
        vz, sk.ah, sk.re = launch, nil, nil
    else
        -- off the ground the board flies on the way it was going, uphill or down, with the pop on top of that. The
        -- pop is straight up, and on a steep face there is more of it (Skate 3: JumpYScalarVsGroundNormalY)
        SK.sync()
        local jump, rising = launch * Tune.popSteep(sk.u.z), sk.d.z * speed
        if rising > 0.0 and sk.u.z < 0.9 then
            -- going up a steep face the pop does not come on top of the speed upwards: it adds its height to the
            -- height that speed has (else an ollie at the top of a quarter pipe would be three times any other)
            local steep = clamp((0.9 - sk.u.z) / (0.9 - Config.VertFace), 0.0, 1.0)
            jump = jump + (math.sqrt(rising * rising + jump * jump) - rising - jump) * steep
        end
        SK.fly(sk.d * speed + vector3(0.0, 0.0, jump))
    end
    air = { name = name, label = prefix .. label, tricks = {}, fromGrind = fromGrind, fromManual = fromManual,
            fromFakie = backwards, stationary = math.abs(speed) < Tune.stationarySpeed(), prefix = prefix, plain = label }
    if not fromGrind then spin = 0.0 end
    air.spin0 = spin -- (off a rail the body starts turned as it stood on it: only what the jump adds is a spin)
    if fromGrind and S3.active() then
        -- off a darkslide the jump is the way out of it
        local key, text = S3.slideOut()
        if key then air.name, air.label, air.plain = key, prefix .. text, text end
    end
    adjust, lock = nil, nil
    sound('pop', strength)
    if name ~= 'Ollie' and name ~= 'Nollie' then sound('flip', 0.7) end -- the board whipping round
    startFlip(name)
end

-- A flick. With Skate 3 clips the takeoff clip plays on the ground first, as in Skate 3, then the board leaves.
requestPop = function(name, label, strength)
    antic, anticNext = nil, nil
    flickHeld, uflipAsked, darkAsked = false, false, false
    resetCrouch()
    -- the front foot is going down for a push: with a flick it is planted instead, and the board popped round it
    -- (Skate 3's ground.xml: Push.PushStart -> NoComply)
    if S3.active() and mode == 'ground' and pushFront and clock - pushStartT <= S3.pushStartTime() and speed > -0.5 then
        local t, text = S3.plant('nocomply', speed)
        if t then
            pending = { name = 'nocomply', label = text, strength = 1.0, fromManual = false, t = t, plant = true }
            return
        end
    end
    -- out of a manual there is no crouch to time. Skate 3 still counts the pop as out of the manual for a moment
    -- after the manual has ended (ground.xml: SetManualOutTimer 0.1).
    local fromManual = (manual ~= nil and manual.hold > Config.ManualEngage) or clock - manualOut <= Config.ManualOutTime
    if fromManual then strength = Config.ManualPopStrength end
    if S3.active() then
        -- Skate 3 blends each trick between a low and a high version by its height; we play the nearer one. The
        -- high one also needs the air time to finish in.
        local onRail = mode == 'grind'
        local rise = Tune.popRise(onRail and Config.GrindPopStrength or strength, onRail and grind.speed or speed)
        popHigh = strength >= Config.S3HighPop and rise >= Config.S3HighRise
        pending = { name = name, label = label, strength = strength, fromManual = fromManual,
                    t = S3.pop(name, popHigh, onRail and 'grind' or nil) }
    else
        pop(name, label, strength, fromManual)
    end
end

-- The takeoff clip has played (or the ground ran out under it): leave now.
local function launchPending()
    pop(pending.name, pending.label, pending.strength, pending.fromManual, pending.plant)
    S3.launch(pending.name)
    pending = nil
end

-- ------------------------------------------------------------------ rails and ledges

-- Looks for a rail or ledge edge under p: a top that carries on at this height along one line and is not there
-- to at least one side. Returns the rail heading closest to the travel heading and the angle between them, or
-- nil.
--
-- It feels round p in a circle of half a metre, every 3 degrees: where is there a top at this height? A rail
-- shows as two short arcs opposite each other, a ledge as one long arc. The gap between the arcs is the drop, and
-- the rail runs across it. (Testing a handful of fixed headings instead misses a thin rail that lies between two
-- of them: at half a metre a 5 cm bar is under 6 degrees wide.)
--
-- A rail that slants (the handrail down a flight of stairs) is not at p's height half a metre along it: it is as far
-- above it one way as it is below it the other way, and that is how it is known (RING_SLANT: up to 42 degrees).
-- Ground that only drops to one side, a kerb, has nothing above on the other and is no slant.
local RING_STEP, RING_R, RING_SLANT = 3, 0.5, 0.45
local RING_N = 360 // RING_STEP

local function findRail(p, travel)
    local zs, on, count = {}, {}, 0
    for i = 0, RING_N - 1 do
        zs[i] = probe(p + fwd(i * RING_STEP) * RING_R, RING_SLANT + 0.1, RING_SLANT + 0.1)
    end
    for i = 0, RING_N - 1 do
        local z, o = zs[i], zs[(i + RING_N // 2) % RING_N]
        if z then
            local d = z - p.z
            on[i] = math.abs(d) < 0.15 or (o ~= nil and math.abs(d) <= RING_SLANT and d * (o - p.z) < 0.0 and
                math.abs((z + o) * 0.5 - p.z) < 0.1)
        else
            on[i] = false
        end
        if on[i] then count = count + 1 end
    end
    if count == 0 or count == RING_N then return nil end -- a post, or flat ground
    -- the widest gap: `len` steps from index `first`
    local first, len
    for i = 0, RING_N - 1 do
        if not on[i] and on[(i - 1) % RING_N] then
            local n = 1
            while not on[(i + n) % RING_N] do n = n + 1 end
            if not len or n > len then first, len = i, n end
        end
    end
    if len * RING_STEP < 60 then return nil end -- no real drop to either side
    -- the tops either side of the gap: how many steps of top before it, and after it
    local before, after = 0, 0
    while before < RING_N and on[(first - 1 - before) % RING_N] do before = before + 1 end
    while after < RING_N and on[(first + len + after) % RING_N] do after = after + 1 end
    local narrow = 60 // RING_STEP
    local a1, a2 -- the angles the rail leaves the circle at, before the gap and after it (a2 > a1)
    if before <= narrow then a1 = (first - 1 - (before - 1) * 0.5) * RING_STEP else a1 = (first - 0.5) * RING_STEP end
    if after <= narrow then a2 = (first + len + (after - 1) * 0.5) * RING_STEP else a2 = (first + len - 0.5) * RING_STEP end
    local mid = (a1 + a2) * 0.5 -- the middle of the gap: straight off the rail
    -- a wall there instead of a drop is not a rail
    local out = fwd(mid) * RING_R
    if ray(p + vector3(0, 0, 0.1), p + out + vector3(0, 0, 0.1), board) then return nil end
    local best
    if before + len == RING_N and before <= narrow then
        best = (first + len + (after - 1) * 0.5) * RING_STEP -- one short arc and nothing else: the rail starts here
        if math.abs(angDiff(best, travel)) > 75.0 then return nil end
        return best % 360.0, math.abs(angDiff(best, travel))
    end
    best = mid + 90.0
    local diff = math.abs(angDiff(best, travel))
    if diff > 90.0 then best, diff = best + 180.0, 180.0 - diff end
    if diff > 75.0 then return nil end
    return best % 360.0, diff
end

-- Is there a top at height z under each point of a line across p? Every `step` metres from `from` to `to`
-- (metres to the LEFT of p along `left`). Returns t[0 .. n] = true / false, and n.
local function topAcross(p, left, from, to, step, z)
    local t, n = {}, math.floor((to - from) / step + 0.5)
    for i = 0, n do
        local q = p + left * (from + i * step)
        local hit = ray(vector3(q.x, q.y, z + 0.1), vector3(q.x, q.y, z - 0.1), board, LOCK_FLAGS)
        t[i] = hit
    end
    return t, n
end

-- Where the board should sit on a rail or ledge whose top (height z) is under p + left * off: how far to the LEFT
-- of p. The middle of a rail; just inside the edge of a ledge. Also says what it found there: 'rail', 'ledge',
-- 'flat' (a top with no edge within `half` (0.3 m) to either side) or 'none' (no top under that point at all).
local function seatOn(p, left, off, z, half)
    local step = 0.01
    half = half or 0.3
    local t, n = topAcross(p, left, off - half, off + half, step, z)
    local c = math.floor(half / step + 0.5)
    if not t[c] then return off, 'none' end
    local lo, hi = c, c
    while lo > 0 and t[lo - 1] do lo = lo - 1 end
    while hi < n and t[hi + 1] do hi = hi + 1 end
    local right, leftEnd = off - half + lo * step, off - half + hi * step
    if lo > 0 and hi < n then return (right + leftEnd) * 0.5, 'rail' end -- both ends found: a rail
    if hi < n then return leftEnd - 0.05, 'ledge' end                     -- a ledge that ends to the left
    if lo > 0 then return right + 0.05, 'ledge' end                       -- ... or to the right
    return off, 'flat'
end

-- The board has landed on a rail (heading railH) at p: how far to the LEFT of the direction of travel it still
-- has to go to sit on it properly.
local function railCentre(p, railH)
    return seatOn(p, fwd(railH + 90.0), 0.0, p.z)
end

-- The nearest rail or ledge edge beside p, no further than `reach` to either side: a top that stands at least
-- 0.25 m above what is next to it (what findRail takes for a rail), between `bottom` and `top`. Returns how far
-- to the LEFT of p it is and its height, or nil.
-- The probes stand 6 cm apart, and a handrail is thinner than that: at some distances it stands between two of them
-- and is not seen. `phase` moves the whole row sideways, so that the next look sees what this one missed; `step`
-- sets them closer.
local function edgeBeside(p, left, reach, top, bottom, phase, step)
    step = step or 0.06
    phase = phase or 0.0
    local n = math.floor(reach / step + 0.5)
    local h = {}
    for k = -n - 1, n + 1 do
        local q = p + left * (k * step + phase)
        local hit, hp = ray(vector3(q.x, q.y, top), vector3(q.x, q.y, bottom), board, LOCK_FLAGS)
        h[k] = hit and hp.z or nil
    end
    local function drops(z, other) return other == nil or other < z - 0.25 end
    local best
    for k = -n, n do
        local z = h[k]
        if z and (drops(z, h[k - 1]) or drops(z, h[k + 1]))
            and (not best or math.abs(k * step + phase) < math.abs(best * step + phase)) then
            best = k
        end
    end
    if not best then return nil end
    return best * step + phase, h[best]
end

-- Skate 3 pulls a jump onto a rail or a ledge edge that is within reach (physics_mode.GrindLockDist). Look to both
-- sides of the line of flight for one that runs the board's way. Returns how far to the LEFT of p the board should
-- be to land on it, its height, and how much further left that is for every metre flown (a rail seldom runs
-- exactly the way the board flies); or nil.
local function seekRail(p, travelH, boardZ, phase)
    local f, left = fwd(travelH), fwd(travelH + 90.0)
    local top, bottom = boardZ + 0.05, boardZ - 1.2
    local near, far = p + f * 0.3, p + f * 0.9
    local off, z = edgeBeside(near, left, Tune.grindLockDist, top, bottom, phase)
    if not off then return nil end
    -- it has to run our way: still there, and about as far to the side, a little further on (looked for with the
    -- probes at half the spacing: two rows as coarse as each other can both miss a thin rail that runs at a slant,
    -- time after time)
    local off2, z2 = edgeBeside(far, left, Tune.grindLockDist + 0.3, top, bottom, phase, 0.03)
    if not off2 or math.abs(off2 - off) > 0.3 or math.abs(z2 - z) > 0.3 then return nil end
    local seat, seat2 = seatOn(near, left, off, z), seatOn(far, left, off2, z2, 0.15)
    local slant = (seat2 - seat) / 0.6
    return seat - slant * 0.3, z, slant
end

-- Which grind is this? From how the rider lands on the rail, as in Skate 3 (and on a real board):
--   railH   the way the board travels along the rail
--   body    the way the rider points (facing + spin)
--   adj     the right stick held in the air: 'nose' / 'tail' down, or nil
--   side    which side of the rider's path the rail was on at takeoff: > 0 left, < 0 right, 0 unknown
--   cross   where the rail crosses the board's length, metres ahead of its middle, on the line the jump was on
--           before any pull onto the rail (nil = not known)
--   dark    the board comes down upside down
-- An angled grind is named for the truck that is on the rail and for the way the nose points from it, across the
-- rail to its far side or back to the side the rider came from, as on a real board:
--   front truck, tail up (stick up):    crooked (nose over the far side) / overcrook
--   front truck, tail hanging:          willy / overwilly
--   back truck, nose hanging:           feeble (nose over the far side) / smith
--   back truck, nose up (stick down):   salad (nose over the far side) / plain 5-0
-- With the stick held the truck is the one it puts down. Without, it is the truck nearer the rail on the line of
-- the jump; coming down with the rail under the middle of the board that is the back one (smith, feeble).
-- A nose or tail slide with the board gone over the rail is a blunt slide.
-- Returns the grind table the ride keeps.
local function chooseGrind(railH, body, adj, side, cross, dark)
    local m = mirrored()
    local rel = angDiff(body, railH)               -- the rider's turn against the direction of travel, + = left
    local a = math.abs(rel)
    -- the rail was on the toe side (frontside) or the heel side (backside). Toes point left for the clips as authored.
    local toeSide = (side > 0) ~= m
    if side == 0 then toeSide = false end
    local name, clipSide, turn, fakie = '50-50', 'fs', 0.0, false
    if dark or math.abs(a - 90.0) <= ((adj == 'nose' or adj == 'tail') and Tune.tipSlideRange or Tune.slideRange) then
        -- across the rail: a slide. `forward` = the rider travels chest first.
        local forward = (rel < 0) ~= m
        -- the nose points over the rail to its far side (not knowing the side: say it does)
        local far = side == 0 or forward ~= toeSide
        -- nose over the rail = boardslide, tail over = lipslide: chest first from the heel side or back first from
        -- the toe side is a boardslide. A nose slide has the nose on the rail and the board back on the near side,
        -- a tail slide the tail; with the board over on the far side instead they are the blunt slides.
        if dark then name = 'Darkslide'
        elseif adj == 'nose' then name = far and 'Noseslide' or 'Noseblunt'
        elseif adj == 'tail' then name = (far and side ~= 0) and 'Blunt' or 'Tailslide'
        else name = far and 'Boardslide' or 'Lipslide' end
        local d = S3.GRINDS[name]
        clipSide = forward and d.fwd or (d.fwd == 'fs' and 'bs' or 'fs')
        turn = sign(rel) * 90.0
    else
        fakie = a > 90.0
        local lean = fakie and angDiff(rel, 180.0) or rel -- how far off straight
        -- (standing backwards on the board the toes point the other way: a rail on the left of the path is then
        -- on the heel side)
        if fakie and side ~= 0 then toeSide = not toeSide end
        clipSide = toeSide and 'fs' or 'bs'
        if math.abs(lean) <= Tune.grindStraight then
            name = adj == 'nose' and 'Nosegrind' or (adj == 'tail' and '5-0' or '50-50')
        else
            -- angled (see above)
            local left = (lean > 0) ~= m           -- the nose points left of travel, in the authored clips' terms
            local far = left == (clipSide == 'fs') -- ... which is over the rail when the rail was on that side
            if adj == 'nose' and side == 0 then
                name = 'Crooked'                   -- (the side not known: named by the angle alone)
                clipSide = left and 'fs' or 'bs'
            elseif adj == 'nose' then
                name = far and 'Crooked' or 'Overcrook'
            elseif adj == 'tail' then
                name = far and 'Salad' or '5-0'
            elseif cross ~= nil and cross > Config.TruckPick then
                name = far and 'Willy' or 'Overwilly'
            else
                name = far and 'Feeble' or 'Smith'
            end
            local t = S3.GRINDS[name].turn
            if t then turn = m and -t[clipSide] or t[clipSide] end
        end
        if fakie then turn = turn + 180.0 end
    end
    local d = S3.GRINDS[name]
    local prefix = (clipSide == 'fs' and 'FS ' or 'BS ')
    if side == 0 and not d.slide and not d.turn then prefix = '' end -- straight on, side unknown: just "50-50"
    return {
        name = name, label = prefix .. d.label, side = clipSide, fakie = fakie, slide = d.slide == true, turn = turn,
        key = (side == 0 and d.gen) or (d.key and (clipSide .. '_' .. d.key)) or nil,
        h = railH, facing = railH + turn, speed = 0.0, t = 0.0, dist = 0.0, shift = 0.0,
    }
end

-- ------------------------------------------------------------------ camera

local function travelHeading()
    if mode == 'grind' and grind then return grind.h end
    return speed < -0.5 and facing + 180.0 or facing
end

-- Skate 3's follow camera: a "shot" for the situation (rolling slow / fast, manual, air, grind) says how far behind
-- the rider the camera sits, how far round to the side and how high, which point it circles and how the view is
-- turned off that point. The numbers come from the game's camera_shots table (tuning.lua); which SIDE the camera
-- leans to and which way the view is turned are our reading of them: towards the rider's chest, looking ahead.
local function shotCam(ped, dt, shot, situation)
    local c = camShot
    if not c then
        c = { now = {}, situation = situation }
        camShot = c
    elseif c.situation ~= situation then
        -- another situation: blend over to its shot from where the camera is now, in the shot's transition time
        c.from, c.t, c.situation = {}, 0.0, situation
        for k, v in pairs(c.now) do c.from[k] = v end
    end
    local s = c.now
    if c.from then
        c.t = c.t + dt
        local u = clamp(c.t / math.max(shot.transition or 0.5, 0.01), 0.0, 1.0)
        u = u * u * (3.0 - 2.0 * u) -- eases in and out
        for k, v in pairs(shot) do s[k] = (c.from[k] or v) + (v - (c.from[k] or v)) * u end
        if u >= 1.0 then c.from = nil end
    else
        for k, v in pairs(shot) do s[k] = v end
    end
    -- the camera swings round behind the way the rider goes, with the shot's lag
    local h = travelHeading()
    local lag = clamp(Tune.smoothTime(s.smoothYaw), 0.05, 1.0)
    camHeading = camHeading and (camHeading + angDiff(h, camHeading) * (1.0 - math.exp(-dt / lag))) or h

    -- the point the camera circles: so far above the board, the rider's middle, or between the two
    local wb, wc = s.weightBoard or 1.0, s.weightCOM or 0.0
    local ref = pos + vector3(0, 0, s.boardOffset or 0.0)
    if wc > 0.0 then ref = (ref * wb + GetEntityCoords(ped) * wc) * (1.0 / (wb + wc)) end
    -- the clips as authored have the chest to the LEFT of the way the rider points; rolling backwards that is the
    -- right of the way the board goes. The camera moves over when it changes, it doesn't jump.
    local chestLeft = (not mirrored()) ~= (mode ~= 'grind' and speed < -0.5)
    camSide = camSide or (chestLeft and 1.0 or -1.0)
    camSide = camSide + clamp((chestLeft and 1.0 or -1.0) - camSide, -2.5 * dt, 2.5 * dt)
    local chest = camSide
    local bearing = camHeading + 180.0 - chest * (s.side or 0.0)
    local elev = math.rad(s.elevation or 0.0)
    local dist = s.distance or 2.0
    local want = ref + fwd(bearing) * (dist * math.cos(elev)) + vector3(0, 0, dist * math.sin(elev))
    local hit, hp = ray(ref, want, board)
    if hit then want = hp + (ref - hp) * 0.15 end
    camPos = want

    if not cam then
        cam = CreateCam('DEFAULT_SCRIPTED_CAMERA', true)
        RenderScriptCams(true, true, 400, true, false)
    end
    SetCamFov(cam, Config.S3CamFov or Tune.fov(s.lens or 12.0))
    SetCamCoord(cam, camPos.x, camPos.y, camPos.z)
    -- look at the point, then turn the view by the shot's yaw (towards the way the rider is going) and pitch
    local to = ref - camPos
    local flat = math.sqrt(to.x * to.x + to.y * to.y)
    local yaw = math.deg(math.atan(-to.x, to.y)) + chest * (s.yaw or 0.0)
    local pitch = math.deg(math.atan(to.z, math.max(flat, 0.01))) + (s.pitch or 0.0)
    SetCamRot(cam, pitch, 0.0, yaw, 2)
end

local function updateCam(ped, dt)
    if not Config.SkateCam then return end
    local inManual = manual ~= nil and manual.hold > Config.ManualEngage
    local situation = (mode == 'air' and 'air') or (mode == 'grind' and 'grind') or (skitch and 'skitch') or
        (inManual and 'manual') or 'ground'
    local v = (mode == 'grind' and grind) and grind.speed or speed
    local big = mode == 'air' and airTime > Config.CamBigAir
    local shot = Tune.shot(situation, v, big)
    if shot then return shotCam(ped, dt, shot, big and 'big air' or situation) end

    local target = GetEntityCoords(ped)
    local h = travelHeading()
    camHeading = camHeading and (camHeading + angDiff(h, camHeading) * (1.0 - math.exp(-dt * Config.CamTurn))) or h
    local f = fwd(camHeading)
    local side = fwd(camHeading - 90.0) * Config.CamSide
    local want = target - f * Config.CamDist + side + vector3(0, 0, Config.CamHeight - Config.RideHeight * 0.5)
    local hit, hp = ray(target, want, board)
    if hit then want = hp + (target - hp) * 0.15 end
    camPos = camPos and lerp(camPos, want, 1.0 - math.exp(-dt * Config.CamFollow)) or want
    if not cam then
        cam = CreateCam('DEFAULT_SCRIPTED_CAMERA', true)
        SetCamFov(cam, Config.CamFov)
        RenderScriptCams(true, true, 400, true, false)
    end
    SetCamCoord(cam, camPos.x, camPos.y, camPos.z)
    local look = target + f * Config.CamLead - vector3(0, 0, Config.CamLookDown)
    PointCamAtCoord(cam, look.x, look.y, look.z)
end

local function releaseCam()
    if cam then
        RenderScriptCams(false, true, 400, true, false)
        DestroyCam(cam, false)
    end
    cam, camPos, camHeading, camShot, camSide = nil, nil, nil, nil, nil
end

-- ------------------------------------------------------------------ skitching (holding on to the back of a car)
--
-- Skate 3's skitching, as far as its data says how (ground.xml "EnterSkitching" / "Skitching",
-- physics_state_skitching): the hold button near the back of a car takes hold of it, the car takes the rider
-- along, the left stick moves the rider along the back of it, letting go of the button lets go of the car. The
-- game holds the rider to the car with springs and puts the hands on it with IK; here the board is kept a hand's
-- reach behind the car's back end, where the hold clips have the hands.

-- The car's box as its model has it: the two corners, the middle of its width and half its width.
function SK.box(veh)
    local lo, hi = GetModelDimensions(GetEntityModel(veh))
    return lo, hi, (lo.x + hi.x) * 0.5, (hi.x - lo.x) * 0.5
end

-- How far ahead of the back end of its box the car's body really is, `off` across it and at the height z: a ray
-- at the car from behind. nil when the car has nothing at that height.
function SK.back(veh, lo, off, z)
    local from = GetOffsetFromEntityInWorldCoords(veh, off, lo.y - 1.0, 0.0)
    local to = GetOffsetFromEntityInWorldCoords(veh, off, lo.y + 1.0, 0.0)
    local hit, hp = ray(vector3(from.x, from.y, z), vector3(to.x, to.y, z), board, 2)
    if not hit then return nil end
    return math.sqrt((hp.x - from.x) ^ 2 + (hp.y - from.y) ^ 2) - 1.0
end

-- Take hold of the car whose back end is within reach ahead, if there is one.
function SK.grab()
    local T = Tune.skitch
    local f = fwd(facing)
    local best, bestD
    for _, veh in ipairs(GetGamePool('CVehicle')) do
        if DoesEntityExist(veh) and not Config.SkitchNoClass[GetVehicleClass(veh)]
            and #(GetEntityCoords(veh) - pos) < 15.0 then
            local lo, hi, mid, half = SK.box(veh)
            local l = GetOffsetFromEntityGivenWorldCoords(veh, pos.x, pos.y, pos.z)
            local behind, across = lo.y - l.y, math.abs(l.x - mid) - half
            local vv = GetEntityVelocity(veh)
            local closing = speed - (vv.x * f.x + vv.y * f.y)
            if behind > -0.2 and behind < T.reach and across < T.side and math.abs(l.z - lo.z) < 0.6
                and math.abs(angDiff(GetEntityHeading(veh), facing)) < T.angle and math.abs(closing) < T.maxClose
                and (not best or behind < bestD) then
                best, bestD = { veh = veh, lo = lo, mid = mid, half = half, x = l.x, closing = closing }, behind
            end
        end
    end
    if not best then return false end
    local k = best
    local most = math.max(k.half - T.edge, 0.0)
    k.off = clamp(k.x, k.mid - most, k.mid + most)
    -- the low hold where the car has something down at bumper height that is not set back under the rest of it;
    -- the high one otherwise (a boot lid, a tailgate, the back of a van)
    local low = SK.back(k.veh, k.lo, k.off, pos.z + Config.SkitchHandsLow)
    local high = SK.back(k.veh, k.lo, k.off, pos.z + Config.SkitchHandsHigh)
    if low and (not high or low <= high + 0.15) then
        k.high, k.inset = false, low
    elseif high then
        k.high, k.inset = true, high
    else
        k.high, k.inset = false, 0.0
    end
    -- how the hands get there (Skate 3 has a quick and a slow reach, and a pull on the arms when the car is going
    -- faster or slower than the rider: its AbsorbContactSpeedMapping starts at 2.8 m/s)
    local gap = math.max(bestD + k.inset - Config.SkitchHandsAhead, 0.0)
    local c = math.abs(k.closing)
    k.fast = gap / math.max(c, 0.5) < 0.4
    k.absorb = c > 2.8 and (c > 8.5 and 'fast' or 'slow') or nil
    k.t = 0.0
    if manual then endManual() end
    if ggrab then endGroundGrab() end
    skitch = k
    note('skitch: holding on (%s hold, %.1f m/s between car and board)', k.high and 'high' or 'low', k.closing)
    return true
end

-- One frame of holding on. held = the hold button; steer / throttle = the left stick. Returns false when the hold
-- has ended (the ride goes on from the car's speed).
function SK.hold(dt, steer, throttle, held)
    local k, T = skitch, Tune.skitch
    local veh = k.veh
    if not DoesEntityExist(veh) then
        skitch, sk.cd = nil, T.again
        return false
    end
    local vv, vh = GetEntityVelocity(veh), GetEntityHeading(veh)
    local vf = fwd(vh)
    local along = vv.x * vf.x + vv.y * vf.y
    k.t = k.t + dt
    local function letGo(push, why)
        skitch, sk.cd = nil, T.again
        speed, yawRate = along + (push or 0.0), 0.0
        note('skitch: let go after %.1f s at %.1f m/s (%s)', k.t, speed, why)
        return false
    end
    if pending then return letGo(0.0, 'popped') end
    if not held and k.t >= T.minTime then
        -- (Skate 3: ExitPushForwardSpeedDelta / ExitPushBackSpeedDelta; that the left stick picks is our reading)
        return letGo(throttle > 0.5 and T.exitFwd or (throttle < -0.5 and T.exitBack or 0.0), 'button')
    end
    if along < -1.0 then return letGo(0.0, 'the car is backing up') end

    -- along the back of the car, hand over hand; at either end one hand is past it and the other holds
    local most = math.max(k.half - T.edge, 0.0)
    local move = (math.abs(steer) > 0.3 and k.t > 0.3) and steer * T.shimmy or 0.0
    local before = k.off
    k.off = clamp(k.off + move * dt, k.mid - most, k.mid + most)
    local past = math.abs(k.off - k.mid) > most - T.hand
    k.hand = past and (k.off > k.mid and 'left' or 'right') or nil
    k.shimmy = (k.off ~= before and not k.hand) and move / T.shimmy or nil

    -- carried along with the car, and drawn to its place behind it
    local a = GetOffsetFromEntityInWorldCoords(veh, k.off, k.lo.y + k.inset - Config.SkitchHandsAhead, 0.0)
    local px, py = pos.x + vv.x * dt, pos.y + vv.y * dt
    local e = 1.0 - math.exp(-dt * 8.0)
    px, py = px + (a.x - px) * e, py + (a.y - py) * e
    local gap = math.sqrt((a.x - px) ^ 2 + (a.y - py) ^ 2)
    if gap > T.exitDist + (k.t < T.minTime and T.reach or 0.0) then return letGo(0.0, 'the car got away') end

    -- the ground under the board (the car itself is not ground)
    local p = vector3(px, py, pos.z)
    local hit, gp, gn = ray(p + vector3(0, 0, Config.StepUp), p - vector3(0, 0, T.drop + 0.2), board, LOCK_FLAGS)
    if not hit or pos.z - gp.z > T.drop then return letGo(0.0, 'the ground fell away') end
    local step = math.max(math.abs(along) * dt * 1.75, 0.01)
    groundVz = lerp(groundVz, clamp(gp.z - pos.z, -step, step) / dt, 0.5)
    pos, groundN = gp, gn
    facing = facing + angDiff(vh, facing) * (1.0 - math.exp(-dt * 6.0))
    speed, yawRate = along, 0.0
    -- (the road under the car: the board lies on it as on any ground)
    local n = gn.z > 0.5 and gn or Surf.UP
    SK.put(n)
    sk.up = Surf.unit(sk.up + (n - sk.up) * 0.25) or n
    return true
end

-- ------------------------------------------------------------------ helmets

-- The helmet is a prop of the head slot (0), as hats are; the hat that was on comes back when it is taken off.
local helmet = { on = false }

function helmet.choice()
    local d, t = Config.Helmet.drawable, Config.Helmet.texture
    if GetResourceKvpInt('helmet_set') == 1 then d, t = GetResourceKvpInt('helmet_drawable'), GetResourceKvpInt('helmet_texture') end
    return d, t
end

function helmet.takeOff(ped)
    if helmet.game then RemovePedHelmet(ped, true) end
    ClearPedProp(ped, 0)
    if helmet.hat and helmet.hat >= 0 then SetPedPropIndex(ped, 0, helmet.hat, math.max(helmet.hatTex or 0, 0), true) end
    SetPedCanLosePropsOnDamage(ped, true, 0)
    helmet.on, helmet.game = false, false
end

function helmet.putOn(ped)
    if not helmet.on then helmet.hat, helmet.hatTex = GetPedPropIndex(ped, 0), GetPedPropTextureIndex(ped, 0) end
    local d, t = helmet.choice()
    if helmet.game then RemovePedHelmet(ped, true) end
    if d >= 0 and d < GetNumberOfPedPropDrawableVariations(ped, 0) then
        SetPedPropIndex(ped, 0, d, t, true)
        helmet.game = false
    else
        ClearPedProp(ped, 0)
        GivePedHelmet(ped, true, 4096, -1) -- (4096: the ped's regular helmet)
        helmet.game = true
    end
    if Config.Helmet.stayOn then SetPedCanLosePropsOnDamage(ped, false, 0) end
    helmet.on, helmet.ped = true, ped
end

function helmet.toggle()
    if not Config.Helmet.enabled then return end
    local ped = PlayerPedId()
    if helmet.on and helmet.ped == ped then
        helmet.takeOff(ped)
        notify('Helmet off.')
    else
        helmet.on = false -- (another ped since: there is no hat of this one to give back)
        helmet.putOn(ped)
        notify('Helmet on.')
    end
end

local helmetReply
RegisterNetEvent('skateboard:helmetReply', function(ok) helmetReply = ok end)

local function ownsHelmet()
    if not itemRequired() then return true end
    helmetReply = nil
    TriggerServerEvent('skateboard:requestHelmet')
    local deadline = GetGameTimer() + 3000
    while helmetReply == nil and GetGameTimer() < deadline do Wait(0) end
    return helmetReply == true
end

-- /skatehelmet: on / off.  /skatehelmet <number> [texture]: that prop of the head slot, remembered.
-- /skatehelmet next | prev: step through the head props.  /skatehelmet default: the one from config.lua again.
RegisterCommand('skatehelmet', function(_, args)
    CreateThread(function()
        if not Config.Helmet.enabled then return end
        if not ownsHelmet() then
            notify('~r~You need a helmet.~s~ Get one into your inventory first.')
            return
        end
        local a = args[1] and args[1]:lower() or nil
        if not a then return helmet.toggle() end
        local ped = PlayerPedId()
        local count = GetNumberOfPedPropDrawableVariations(ped, 0)
        local d, t = helmet.choice()
        if a == 'default' then
            SetResourceKvpInt('helmet_set', 0)
        else
            if a == 'next' or a == 'prev' then
                if count < 1 then return notify('This character has no head props.') end
                d = (math.max(d, -1) + (a == 'next' and 1 or -1)) % count
                t = 0
            else
                d, t = math.floor(tonumber(a) or -1), math.max(math.floor(tonumber(args[2]) or 0), 0)
                if d < 0 or d >= count then return notify(('Head props go from 0 to %d on this character.'):format(count - 1)) end
            end
            SetResourceKvpInt('helmet_set', 1)
            SetResourceKvpInt('helmet_drawable', d)
            SetResourceKvpInt('helmet_texture', t)
        end
        if helmet.ped ~= ped then helmet.on = false end
        helmet.putOn(ped)
        d, t = helmet.choice()
        notify(d >= 0 and ('Helmet: head prop %d, texture %d.'):format(d, t) or 'Helmet: the game\'s own for this character.')
    end)
end, false)

-- ox_inventory: items.lua -> client = { export = 'skateboard.useHelmet' } (ox_inventory has checked the item)
exports('useHelmet', function() helmet.toggle() end)

-- ------------------------------------------------------------------ getting on and off

local addBoardTarget -- defined below, once getOn and pickUp exist
local tick           -- the ride itself, defined further down
local stepOff, walkTick, putAway -- Skate 3's off-board mode, defined further down
local off           -- ... and its state while the rider is off the board that way (see there)

local gettingOn = false -- getOn waits (for the server, a model, the clips): a second key press must not start another

-- from = { pos, facing, speed }: out of Skate 3's off-board mode, the jump onto the board has just played: the board
-- is under the feet and the rider is already being posed, so nothing is made or cleared, and the ride starts rolling.
-- May this ped be on a board now? Not in a car, dead or down, cuffed, being thrown about, stunned, in the water or
-- falling. A server's own rule goes in Config.CanRide (config.lua).
function SK.fit(ped)
    if IsPedInAnyVehicle(ped, false) or IsEntityDead(ped) or IsPedFatallyInjured(ped) or IsPedCuffed(ped) or
        IsPedRagdoll(ped) or IsPedBeingStunned(ped, 0) or IsPedSwimming(ped) or IsPedFalling(ped) then
        return false
    end
    if GetResourceState('qbx_medical') == 'started' then
        local ok, down = pcall(function() return exports.qbx_medical:IsDead() or exports.qbx_medical:IsLaststand() end)
        if ok and down then return false end
    end
    local st = LocalPlayer and LocalPlayer.state
    if st and (st.isDead or st.dead or st.isCuffed or st.isHandcuffed) then return false end
    if Config.CanRide and Config.CanRide(ped) == false then return false end
    return true
end

-- (for engine.lua: the two questions asked before anyone gets on a board, with the same words when the answer is no)
function SkateboardMayRide()
    local ped = PlayerPedId()
    if not SK.fit(ped) then
        if not IsPedInAnyVehicle(ped, false) then notify("You can't get on a board right now.") end
        return false
    end
    if not ownsBoard() then
        notify('~r~You need a skateboard.~s~ Get one into your inventory first.')
        return false
    end
    return true
end

local function mount(from)
    local ped = PlayerPedId()
    if not SK.fit(ped) then
        if not IsPedInAnyVehicle(ped, false) then notify("You can't get on a board right now.") end
        return
    end
    -- /skatestance while riding changes the stance from here on
    if sk.stance ~= nil then Config.Goofy, sk.stance = sk.stance, nil end
    local here = GetEntityCoords(ped)

    -- far from the board: it is called for (the one lying in the world goes, another is under the feet), unless
    -- config.lua says a rider walks to their board
    if not from and board and DoesEntityExist(board) and Config.CallBoard == false then
        local far = #(GetEntityCoords(board) - here)
        if far > 3.0 then return notify(('Your board is %.0f m away.'):format(far)) end
    end
    if not from and board and (not DoesEntityExist(board) or #(GetEntityCoords(board) - here) > 3.0) then deleteBoard() end
    if not from and not board then
        if not ownsBoard() then
            notify('~r~You need a skateboard.~s~ Get one into your inventory first.')
            return
        end
        local model, skate3 = pickBoardModel()
        if model then
            board = CreateObject(model, here.x, here.y, here.z - 1.0, Config.NetworkBoard, true, false)
            SetModelAsNoLongerNeeded(model)
            SetEntityLodDist(board, Config.BoardLodDist) -- (a prop's own is 15 m: a rider 20 m off would have no board)
            if skate3 then Deck.dress(board) end
            addBoardTarget(board)
        else
            notify('~y~No skateboard model found.~s~ Add one to Config.BoardModels. Riding without a board.')
        end
    end
    if board then
        DetachEntity(board, true, false)
        SetEntityCollision(board, false, false)
    end

    local hit, gp = ray(here + vector3(0, 0, 0.5), here - vector3(0, 0, 3.0), board)
    pos = hit and gp or (here - vector3(0, 0, 1.0))
    facing = GetEntityHeading(ped)
    speed, vz, mode, airTime, groundVz, tilt, spin = 0.0, 0.0, 'ground', 0.0, 0.0, 0.0, 0.0
    groundN, yawRate = nil, 0.0
    sk.u, sk.d, sk.seen, sk.up, sk.ah, sk.re = Surf.UP, nil, nil, Surf.UP, nil, nil
    flip, grab, manual, grind, air, ggrab, coffin, onefoot = nil, nil, nil, nil, nil, nil, nil, nil
    flickHeld, uflipAsked, darkAsked, ttl = false, false, false, 9.0
    hippy, revert, pushFront = nil, nil, false
    skitch, sk.cd, sk.scan, sk.rayZ = nil, 0.0, 0.0, nil
    Flick.reset(leftStick)
    loseLine()
    switch, fakieT, switching, landLock, idleT, lastSide, clock = false, 0.0, nil, 0.0, 0.0, 0.0, 0.0
    stickX, stickY = 0.0, 0.0
    pending, slopeDeg, s3pitch, braking, antic, adjust, pushCd = nil, 0.0, 0.0, false, nil, nil, 0.0
    anticNext, anticT, inputT, lock, kick, kickPhase, manualOut = nil, 0.0, 0.0, nil, nil, nil, -10.0
    resetCrouch()
    resetFlick()
    Flick.reset()

    if S3.available() and not S3.ready() then
        -- just joined: the clip dictionaries are still streaming in
        notify('Loading the skate animations...')
        local deadline = GetGameTimer() + 10000
        while not S3.ready() and GetGameTimer() < deadline do Wait(100) end
    end
    if from then
        pos, facing, speed = from.pos, from.facing, from.speed
    else
        ClearPedTasksImmediately(ped)
    end
    FreezeEntityPosition(ped, true)
    if S3.available() and S3.start(ped, board, mirrored(), from ~= nil) then
        Tune.apply(S3.tuning()) -- Skate 3's own numbers, when the asset build has them
    else
        Tune.reset()
        loadDict(Config.StandDict)
        loadDict(Config.AirDict)
    end
    riding = true
    sk.rider = ped -- (the ride is on this ped: see the top of tick)
    lastBail = nil
    if Config.Sound then
        local pack = S3.active() and soundPack() or nil
        soundReport = nil
        soundVol, soundVolT = soundVolume(), 0.0
        SendNUIMessage({ t = 'config', volume = soundVol, base = pack and pack.base or nil,
                         sounds = pack and pack.sounds or nil, world = soundWorld() })
        surface, ground, surfaceT, surfaceSeen = 'concrete_smooth', 'smooth', 0.0, nil
    end
    tick(clamp(GetFrameTime(), 0.001, 0.05)) -- pose the rider now; the ride loop may be asleep for a moment yet
end

local function getOn()
    if riding or gettingOn or off then return end
    if Engine and Engine.active() then return end   -- (Skate 3's engine has the rider: engine.lua)
    gettingOn = true
    local ok, err = pcall(mount)
    gettingOn = false
    if not ok then error(err, 0) end
end
function SkateboardGetOn() getOn() end   -- (for engine.lua: this ride, when the engine cannot take the rider)

-- ------------------------------------------------------------------ the board after a bail

-- A bail leaves the board in the world: a thing that tumbles on, comes to rest and lies there until the rider goes
-- back to it (or calls for it with the get-on key). The game's own physics has it, and that is where a board was
-- lost: let go of inside the wall it was ridden into it is thrown through the wall or out of the world, and a
-- board that goes through the ground is not seen again. So it is let go of clear of the ground and of what was hit,
-- thrown the way it was going (back off a wall), and watched until it lies still. One that goes on down through the
-- ground, is thrown out of sight or is taken out of the world is put back on the ground where the rider fell, to
-- stay. What became of it goes in the log (Config.Log).

-- the board, on the ground at `home`, there to stay
function SK.putBack(b, home, why)
    SetEntityVelocity(b, 0.0, 0.0, 0.0)
    FreezeEntityPosition(b, true)
    SetEntityCoordsNoOffset(b, home.x, home.y, home.z + 0.05, false, false, false)
    SetEntityRotation(b, 0.0, 0.0, facing, 2, true)
    PlaceObjectOnGroundProperly(b)
    note('board after the bail: %s; it is back on the ground where you fell', why)
end

-- a board in place of one the game took out of the world
function SK.lay(home)
    local model, skate3 = pickBoardModel()
    if not model then return end
    Deck.undress()
    board, targetAdded = CreateObject(model, home.x, home.y, home.z, Config.NetworkBoard, true, false), false
    SetModelAsNoLongerNeeded(model)
    SetEntityLodDist(board, Config.BoardLodDist)
    SetEntityHeading(board, facing)
    PlaceObjectOnGroundProperly(board)
    FreezeEntityPosition(board, true)
    if skate3 then Deck.dress(board) end
    addBoardTarget(board)
    note('board after the bail: it was taken out of the world; another lies where you fell')
end

function SK.watch(b, home)
    sk.thrown = (sk.thrown or 0) + 1
    local mine = sk.thrown
    CreateThread(function()
        local still, start = 0, GetEntityCoords(b)
        for _ = 1, 120 do
            Wait(100)
            -- (ridden again, picked up, in the hand, or thrown again: not this watch's any more)
            if riding or gettingOn or board ~= b or sk.thrown ~= mine or (off and off.holding) then return end
            if not DoesEntityExist(b) then
                board = nil
                return SK.lay(home)
            end
            local p = GetEntityCoords(b)
            local under = ray(vector3(p.x, p.y, p.z + 0.3), vector3(p.x, p.y, p.z - 300.0), b)
            if p.z < home.z - 1.0 and not under then return SK.putBack(b, home, 'it went through the ground') end
            if #(p - home) > 80.0 then return SK.putBack(b, home, 'it was thrown out of sight') end
            still = GetEntitySpeed(b) > 0.15 and 0 or still + 100
            if still >= 1000 then
                if #(p - start) < 0.03 then
                    -- (the physics never took it: it hangs where it was let go of)
                    PlaceObjectOnGroundProperly(b)
                    return note('board after the bail: it did not move; set down where it was')
                end
                return note('board after the bail: lying %.1f m from where you fell', #(p - home))
            end
        end
    end)
end

-- vel = the ride's velocity along the ground (m/s); hitWall = the bail is a wall's (or anything else in the way)
function SK.throwBoard(vel, hitWall)
    local b = board
    if not (b and DoesEntityExist(b)) then return end
    local v = #vel
    local dir = v > 0.1 and vel / v or vector3(0.0, 0.0, 0.0)
    local hit, gp = ray(pos + vector3(0, 0, 0.5), pos - vector3(0, 0, 80.0), b)
    local home = hit and gp or pos
    local from = pos + vector3(0, 0, 0.25)
    if hitWall then from = from - dir * 0.6 end
    SetEntityCoordsNoOffset(b, from.x, from.y, from.z, false, false, false)
    FreezeEntityPosition(b, false)
    SetEntityCollision(b, true, true)
    SetEntityDynamic(b, true)
    ActivatePhysics(b)
    local out = hitWall and dir * -math.min(v * 0.3, 2.5) or vel * 0.7
    SetEntityVelocity(b, out.x, out.y, hitWall and 1.5 or 3.0)
    SK.watch(b, home)
end

-- Off the board. bailReason = a fall (the line is lost); soft = no fall with it: the rider steps off (Skate 3's
-- run-out).
-- gone = the game has given the player another ped (a new model, a respawn somewhere else): nothing of the ride is on
-- that one and it is not ours to move. The ride just ends; the board stays where it was.
local function getOff(bailReason, soft, gone)
    if bailReason then
        note('bail: %s (%s; %.1f m/s, falling at %.1f m/s, turned %d degrees from the line; on %s ground)', bailReason,
            tostring(mode), speed, math.max(0.0, -vz), math.floor(math.abs(spin) + 0.5), ground)
    end
    riding = false
    pending, switching, skitch = nil, nil, nil
    soundStop()
    if bailReason and not soft then sound('bail', 1.0) end
    S3.stop()
    releaseCam()
    if gone then
        if board and DoesEntityExist(board) then
            DetachEntity(board, true, true)
            FreezeEntityPosition(board, false)
            SetEntityCollision(board, true, true)
            PlaceObjectOnGroundProperly(board)
        end
        loseLine()
        flip, grab, manual, grind, air, ggrab, coffin, onefoot, mode = nil, nil, nil, nil, nil, nil, nil, nil, 'ground'
        hippy, revert = nil, nil
        return
    end
    local ped = PlayerPedId()
    local dir, v = fwd(facing), speed
    if mode == 'grind' and grind then dir, v = fwd(grind.h), grind.speed end
    local f = dir * v
    if mode == 'ground' and sk.d and sk.u and sk.u.z < 0.9999999 then f = sk.d * speed end -- (up or down a ramp)
    FreezeEntityPosition(ped, false)
    ClearPedTasks(ped)
    SetEntityRotation(ped, 0.0, 0.0, GetEntityHeading(ped), 2, true)

    if board and DoesEntityExist(board) then
        DetachEntity(board, true, true)
        SetEntityCollision(board, true, true)
    end

    if bailReason and not soft then
        if not Config.BailHurts then
            -- the tumble itself must not cost health: no collision damage until the rider is back up, and
            -- anything that got through is given back
            local before = GetEntityHealth(ped)
            SetEntityProofs(ped, false, false, false, true, false, false, false, false)
            CreateThread(function()
                local stop = GetGameTimer() + 4500
                while GetGameTimer() < stop do
                    Wait(100)
                    local p = PlayerPedId()
                    if not IsEntityDead(p) and GetEntityHealth(p) < before then SetEntityHealth(p, before) end
                end
                local p = PlayerPedId()
                SetEntityProofs(p, false, false, false, false, false, false, false, false)
                ClearPedBloodDamage(p)
            end)
        end
        SetPedToRagdoll(ped, 2500, 3000, 0, false, false, false)
        SetEntityVelocity(ped, f.x, f.y, math.max(vz, 2.0))
        if board then SK.throwBoard(f, bailReason == 'Hit a wall' or bailReason == 'Slammed') end
        if Config.ShowBails then
            show('~r~BAILED~s~  ' .. bailReason .. ((Config.ShowTricks and #line > 0) and '\n~c~line lost' or ''), 2.5)
        end
        lastBail = bailReason
        loseLine()
    else
        if bailReason then
            if Config.ShowBails then show('~y~' .. bailReason .. ((Config.ShowTricks and #line > 0) and '\n~c~line lost' or ''), 2.5) end
            lastBail = bailReason
            loseLine()
        else
            cashLine()
        end
        -- (stepping off on the curve of a ramp: clear of it, not half inside it)
        local clear = (sk.up and sk.up.z < Config.VertFace) and sk.up * 0.6 or vector3(0.0, 0.0, 0.0)
        SetEntityCoordsNoOffset(ped, pos.x + clear.x, pos.y + clear.y, pos.z + 1.0, false, false, false)
        if board then
            local side = fwd(facing - 90.0)
            SetEntityCoords(board, pos.x + side.x * 0.6, pos.y + side.y * 0.6, pos.z + 0.1, false, false, false, false)
            SetEntityHeading(board, facing)
            PlaceObjectOnGroundProperly(board)
        end
    end
    flip, grab, manual, grind, air, ggrab, coffin, onefoot, mode = nil, nil, nil, nil, nil, nil, nil, nil, 'ground'
    hippy, revert = nil, nil
end

-- Pick your board up off the ground (it goes back to being just the item in your inventory).
local function pickUp()
    if off then return putAway(true) end
    if riding or not board then return end
    local ped = PlayerPedId()
    if DoesEntityExist(board) and #(GetEntityCoords(board) - GetEntityCoords(ped)) > Config.InteractDistance + 1.0 then
        notify('Your skateboard is too far away.')
        return
    end
    if loadDict('pickup_object') then
        TaskPlayAnim(ped, 'pickup_object', 'pickup_low', 8.0, -8.0, 900, 48, 0.0, false, false, false)
        Wait(450)
    end
    deleteBoard()
    notify('Skateboard picked up.')
end

addBoardTarget = function(entity)
    if not entity or not useTarget() then return end
    local ok = pcall(function()
        exports.ox_target:addLocalEntity(entity, {
            { name = 'skateboard_ride', icon = 'fa-solid fa-person-skating', label = 'Ride skateboard',
              distance = Config.InteractDistance, canInteract = function() return not riding and not off end,
              onSelect = function() CreateThread(getOn) end },
            { name = 'skateboard_pickup', icon = 'fa-solid fa-hand', label = 'Pick up skateboard',
              distance = Config.InteractDistance, canInteract = function() return not riding end,
              onSelect = function() CreateThread(pickUp) end },
        })
    end)
    targetAdded = ok
end

-- The rider's parts have changed (deck.lua): a board lying on the ground is built again where it lies, as the new one;
-- one being ridden stays as it is until the rider next gets on.
Deck.changed = function()
    if riding or gettingOn or not board or not DoesEntityExist(board) then return end
    CreateThread(function()
        local at, heading = GetEntityCoords(board), GetEntityHeading(board)
        deleteBoard()
        local model, skate3 = pickBoardModel()
        if not model then return end
        board = CreateObject(model, at.x, at.y, at.z, Config.NetworkBoard, true, false)
        SetModelAsNoLongerNeeded(model)
        SetEntityLodDist(board, Config.BoardLodDist)
        SetEntityHeading(board, heading)
        PlaceObjectOnGroundProperly(board)
        if skate3 then Deck.dress(board) end
        addBoardTarget(board)
    end)
end

-- The get on / off key. Riding: off the board the way Skate 3 does it (the board in the hand) when that is there,
-- else a plain step off. Off the board with it in the hand: the board is put away. Otherwise: onto the board.
local function toggle()
    CreateThread(function()
        -- (Skate 3's own engine rides when it is there and switched on: engine.lua)
        if Engine and Engine.rides(riding or off ~= nil) then return Engine.toggle() end
        if riding then
            if stepOff() == nil then getOff() end
        elseif off then
            putAway(true)
        else
            getOn()
        end
    end)
end

RegisterCommand('skateboard', toggle, false)
RegisterKeyMapping('skateboard', 'Get on / off skateboard', 'keyboard', Config.ToggleKey)

-- Gestures (Skate 3 clips only, see Config.Gestures); rebindable like the toggle keys
local function gesture()
    if riding then S3.gesture() end
end
RegisterCommand('skateboard_gesture', gesture, false)
RegisterKeyMapping('skateboard_gesture', 'Skateboard gesture', 'keyboard', Config.GestureKey)

-- The controller's buttons for the two. FiveM's key bindings are for keys: a controller button was turned down in
-- the game ("Invalid I/O parameter pairing: <pad_digitalbutton, LRIGHT_INDEX>", in capitals and in lower case) and
-- did nothing. So the D-pad is read here, the way the game's own scripts read it, and only while a controller is
-- in use: on the keyboard the same controls are the D and A keys.
CreateThread(function()
    while true do
        if IsUsingKeyboard(2) or IsPauseMenuActive() then
            Wait(300)
        else
            Wait(0)
            local function pressed(c)
                return c and c ~= 0 and (IsControlJustPressed(2, c) or IsDisabledControlJustPressed(2, c))
            end
            if pressed(Config.PadToggle) then
                toggle()
            elseif riding and pressed(Config.PadGesture) then
                gesture()
            end
        end
    end
end)

RegisterCommand('skatecam', function()
    Config.SkateCam = not Config.SkateCam
    if not Config.SkateCam then releaseCam() end
    notify('Skate cam ' .. (Config.SkateCam and 'on' or 'off'))
end, false)

-- /skatestance: regular <-> goofy (which foot is forward). Applies the next time you get on.
RegisterCommand('skatestance', function()
    local goofy = Config.Goofy
    if sk.stance ~= nil then goofy = sk.stance end
    goofy = not goofy
    if riding or off or gettingOn then
        sk.stance = goofy -- (the ride in progress keeps the stance it started with)
    else
        Config.Goofy, sk.stance = goofy, nil
    end
    notify('Stance: ' .. (goofy and 'goofy (right foot forward)' or 'regular (left foot forward)') ..
        ((riding or off) and '. Step off and on again to change.' or ''))
end, false)

-- /skatemode easy | normal | hardcore: Skate 3's three difficulty settings (pop height, push strength, how far a
-- rail pulls you in). Only with Skate 3's tuning from skate3_assets. Applies the next time you get on.
RegisterCommand('skatemode', function(_, args)
    local want = (args[1] or ''):lower()
    if want == 'easy' or want == 'normal' or want == 'hardcore' then
        Config.Mode = want
        notify('Skate mode: ' .. want .. (riding and '. Step off and on again to change.' or ''))
    else
        notify('Skate mode is ' .. Config.Mode .. '. /skatemode easy, normal or hardcore')
    end
end, false)

-- /skatevolume          how loud your board is
-- /skatevolume 30       set it (0 .. 100); kept on this PC. The server's setting is Config.SoundVolume.
RegisterCommand('skatevolume', function(_, args)
    local n = tonumber(args[1])
    if n then
        n = math.floor(clamp(n, 0, 100) + 0.5)
        SetResourceKvpInt('skatevolume', n + 1)
        soundVol = soundVolume()
        SendNUIMessage({ t = 'config', volume = soundVol })
    end
    local own = GetResourceKvpInt('skatevolume')
    notify(('Skateboard volume: %d of 100%s'):format(math.floor((own > 0 and (own - 1) / 100.0 or Config.SoundVolume) * 100 + 0.5),
        n and '' or '.  /skatevolume 0 .. 100 changes it'))
end, false)

-- /skatesound                    which of the game's grind recordings is heard on what
-- /skatesound grind_metal        hear the one picked for trucks on a metal rail
-- /skatesound grind_metal 12     pick the game's grind number 12 for it instead, and hear it
-- The sound pack holds every grind recording of the game (41 of them, three speeds each) without saying which is
-- for what: the picks it comes with were made by looking at the sounds, not read from the game. The slots are
-- grind_ / slide_ (trucks on it / board across it) + concrete, metal, wood. A pick is kept on this PC.
RegisterCommand('skatesound', function(_, args)
    local pack = soundPack()
    local grinds = pack and pack.choices and pack.choices.grind
    if not grinds then return notify('No Skate 3 sound pack: the sounds come with skate3_assets') end
    local slot, n = (args[1] or ''):lower(), tonumber(args[2])
    local known = false
    for _, s in ipairs(SOUND_SLOTS) do known = known or s == slot end
    if not known then
        for _, s in ipairs(SOUND_SLOTS) do
            print(('[skateboard] %s = grind %d of %d'):format(s, pack.sounds[s] and pack.sounds[s].pick or 0, #grinds))
        end
        return notify('/skatesound <' .. table.concat(SOUND_SLOTS, ' | ') .. '> [1 .. ' .. #grinds .. ']  (F8 lists the picks)')
    end
    if n then
        n = math.floor(clamp(n, 1, #grinds))
        SetResourceKvpInt('skatesound_' .. slot, n)
        pack.sounds[slot] = grinds[n]
        pack.sounds[slot].pick = n
    end
    local picked = pack.sounds[slot]
    if not picked then return notify('The sound pack has no ' .. slot) end
    SendNUIMessage({ t = 'pick', base = pack.base, volume = soundVolume(), name = slot, sound = picked,
                     preview = true, v = 6.0, seconds = 3.0 })
    notify(('%s: grind %d of %d'):format(slot, picked.pick or 0, #grinds))
end, false)

-- Put one of Config.Ramps on the ground at p. Returns the prop, or nil when its model is not in the game.
local function spawnRamp(name, p, heading)
    local model = joaat(Config.Ramps[name] or name)
    if not loadModel(model) then return nil end
    local ramp = CreateObject(model, p.x, p.y, p.z, Config.NetworkBoard, true, false)
    SetEntityHeading(ramp, heading)
    PlaceObjectOnGroundProperly(ramp)
    FreezeEntityPosition(ramp, true)
    SetModelAsNoLongerNeeded(model)
    ramps[#ramps + 1] = ramp
    return ramp
end

RegisterCommand('skateramp', function(_, args)
    if not Dev.may() then return notify(Dev.why) end
    local name = args[1] or 'kicker'
    if name == 'clear' then
        for _, r in ipairs(ramps) do
            if DoesEntityExist(r) then SetEntityAsMissionEntity(r, true, true) DeleteObject(r) end
        end
        ramps = {}
        return
    end
    local modelName = Config.Ramps[name]
    if not modelName then
        local names = {}
        for k in pairs(Config.Ramps) do names[#names + 1] = k end
        table.sort(names)
        notify('Ramps: ' .. table.concat(names, ', ') .. ', clear')
        return
    end
    local ped = PlayerPedId()
    local h = GetEntityHeading(ped)
    local p = GetEntityCoords(ped) + fwd(h) * 8.0
    if not spawnRamp(name, p, h + 180.0) then notify('Ramp model ' .. modelName .. ' not found.') end
end, false)

TriggerEvent('chat:addSuggestion', '/skateramp', 'Spawn a skate ramp in front of you',
    { { name = 'type', help = 'kicker, flat, funbox, halfpipe, quarter, rail, spine or clear' } })
TriggerEvent('chat:addSuggestion', '/skatecam', 'Toggle the Skate 3 follow camera')
TriggerEvent('chat:addSuggestion', '/skatestance', 'Switch between regular and goofy stance')
TriggerEvent('chat:addSuggestion', '/skatemode', 'Skate 3 difficulty: easy, normal or hardcore',
    { { name = 'mode', help = 'easy, normal or hardcore' } })

-- ------------------------------------------------------------------ landing

local function land(groundPos, normal)
    local landedVz = vz
    -- How the board meets the ground. Its speed INTO the surface is what can break the rider; the rest of its
    -- speed runs on along the surface, as much of it as lies the way the board points. So a drop onto a downhill
    -- is soft and fast, the same drop onto the flat is hard, and onto an uphill it is harder still and slow.
    --
    -- steep = a face no board is upright on, or a board that is not upright as it comes down: the curve of a ramp.
    -- There a compass heading says too little, and the landing is worked out on the face itself (SK.settle).
    local up, noseH = sk.up or Surf.UP, SK.noseH() + spin
    local steep = normal ~= nil and (up.z < Config.VertFace or normal.z < 0.5)
    local n = (normal and (steep or normal.z > 0.2)) and normal or vector3(0.0, 0.0, 1.0)
    local dir = fwd(facing)
    local vx, vy = dir.x * speed, dir.y * speed
    local into = math.max(0.0, -(vx * n.x + vy * n.y + landedVz * n.z))
    local vt = vector3(vx + into * n.x, vy + into * n.y, landedVz + into * n.z) -- what runs on along the face
    local rise = steep and 0.0 or -(dir.x * n.x + dir.y * n.y) / n.z -- the surface's rise per metre the way the board points
    local before = speed
    if steep then
        speed = (vt.x * dir.x + vt.y * dir.y < 0.0) and -#vt or #vt -- (which way round it rolls on: settled below)
        rise = #vt > 0.01 and vt.z / math.max(math.sqrt(vt.x * vt.x + vt.y * vt.y), 0.01) or 0.0
    else
        speed = ((vx + into * n.x) * dir.x + (vy + into * n.y) * dir.y + (landedVz + into * n.z) * rise)
            / math.sqrt(1.0 + rise * rise)
    end
    pos, mode, vz, groundVz, groundN, yawRate = groundPos, 'ground', 0.0, 0.0, n, 0.0
    sk.rayZ, sk.ah, sk.re = nil, nil, nil
    local held = grab and grab.kind or nil -- a hand still on the board
    local heldHand = grab and grab.hand or nil
    local lying = coffin ~= nil            -- the rider is lying on it: it just comes down and rolls on
    endGrab()
    endOneFoot()
    local jump = air or { tricks = {} }
    local pulled = lock and lock.pulled or 0.0 -- how far the rail has pulled the board across (to the left)
    -- what the flip came to: more than one turn (the flick was held), an underflip, a dark catch
    local info = jump.info
    if jump.name and info and (info.n > 1 or info.under or info.dark) then
        local COUNT = { [2] = 'Double ', [3] = 'Triple ', [4] = 'Quad ' }
        jump.name = Tune.scoreName(jump.name) .. (info.n > 1 and tostring(info.n) or '') ..
            (info.under and '_underflip' or (info.dark and '_darkcatch' or ''))
        jump.label = (jump.prefix or '') .. (COUNT[info.n] or '') .. (jump.plain or jump.label) ..
            (info.under and ' Underflip' or (info.dark and ' Dark Catch' or ''))
    end
    flickHeld, uflipAsked, darkAsked = false, false, false
    air, fakieT, lock = nil, 0.0, nil
    -- off a kerb and down again in a moment: no jump, so nothing to land (Skate 3: NaturalAirTime). A hand that
    -- was on the board before the kerb stays there.
    local natural = not jump.name and #jump.tricks == 0 and (not held or jump.groundGrab) and airTime < Tune.naturalAirTime
    if not natural then
        note('landed: %.1f m/s into the ground (falling at %.1f, slope %d degrees), rolling %.1f -> %.1f m/s', into,
            -landedVz, math.floor(math.deg(math.atan(rise)) + 0.5), before, speed)
    end

    if into > Tune.hardLanding then return getOff('Too high') end
    sound('land', clamp(into / 8.0, 0.0, 1.0))
    if S3.active() then
        if not S3.flipDone() then return getOff('Under-flipped') end
    elseif flip and flip.t < Config.FlipTime * 0.85 then
        return getOff('Under-flipped')
    end

    -- what the jump is worth: more out of a manual, a grind or fakie, next to nothing from a standstill
    local scale = 1.0
    if jump.name then
        scale = (jump.fromFakie and Tune.bonus('fromFakie') or 1.0) * (jump.fromManual and Tune.bonus('fromManual') or 1.0)
            * (jump.fromGrind and Tune.bonus('fromGrind') or 1.0) * (jump.stationary and Tune.bonus('fromStationary') or 1.0)
    end

    -- a rail or a ledge under the board starts a grind
    local dark = S3.active() and S3.dark()
    if math.abs(speed) > Config.GrindMinSpeed and not lying and not steep then
        local railH = findRail(pos, speed < 0 and facing + 180.0 or facing)
        if railH then
            local shift, what = railCentre(pos, railH) -- still to move across onto the middle of the rail
            -- where the rail crosses the board's length, on the line the jump had before the rail pulled it over
            local sinRel = math.sin(math.rad(angDiff(facing + spin, railH)))
            local cross = math.abs(sinRel) > 0.2 and (shift + pulled) / sinRel or nil
            local g = chooseGrind(railH, facing + spin, adjust, lastSide, cross, dark)
            g.speed = math.abs(speed) * (g.slide and 0.9 or 1.0)
            g.shift, g.ledge = shift, what == 'ledge'
            scale = scale * Tune.bonus('toGrind')
            if jump.name then addToLine(jump.label, jump.name, Tune.baseScore(jump.name), scale) end
            for _, t in ipairs(jump.tricks) do addToLine(t[1], t[2], t[3], scale) end
            -- what it is made of, for the sound of it: metal, wood, or (anything else) concrete
            local made = surfaceAt(pos, LOCK_FLAGS)
            g.rail = (made == 'metal' or made == 'wood') and made or 'concrete'
            g.followT, g.followD = 0.0, 0.0
            grind, mode, spin, flip, adjust = g, 'grind', 0.0, nil, nil
            sound(g.rail == 'metal' and 'lock' or 'land', g.rail == 'metal' and 0.5 or 0.3)
            return
        end
    end

    -- down on the grip tape with no rail under it: nothing to ride. Skate 3's rider steps off it (OnGroundDark:
    -- the run-out)
    if dark then return getOff('Landed on the grip tape', true) end

    -- the board has to come down pointing along the way it rolls: forwards or backwards
    local halfTurns = math.floor(spin / 180.0 + 0.5)
    local off = spin - halfTurns * 180.0
    -- (slid off the end of a rail, no pop: the board swings round into its line as it comes down; there was no
    -- jump to turn it in, and Skate 3 helps the board out of a grind the same way)
    local slidOff = jump.fromGrind and not jump.name
    if natural then
        -- off a kerb while carving: the board went on turning as it does on the ground. There was no jump to land
        -- sideways from, and nothing to play
        if steep then
            SK.put(n, (SK.settle(n, up, noseH, vt, true)))
        else
            facing = facing + spin
            local f = fwd(facing)
            SK.put(n, n.z <= 0.9999999 and Surf.lift(f.x, f.y, n) or nil)
        end
        spin, flip, adjust = 0.0, nil, nil
        return
    end
    local on -- (a steep landing) the way the nose points as the board rolls on
    if steep then on, off = SK.settle(n, up, noseH, vt) end
    if math.abs(off) > Tune.landTolerance and not slidOff then return getOff('Landed sideways') end
    if steep then
        SK.put(n, on)
    else
        facing = facing + halfTurns * 180.0
        if halfTurns % 2 ~= 0 then speed = -speed end
        local f = fwd(facing)
        SK.put(n, n.z <= 0.9999999 and Surf.lift(f.x, f.y, n) or nil)
    end
    -- (coming down on the curve of a ramp gives the board a little speed: Skate 3's LandingSpeedScalarVsGroundNormalY)
    speed = speed * Tune.landBoost(n.z)

    -- the half turns the jump itself made: a rider who came off a rail backwards, as they stood on it, has spun
    -- nothing, and a quarter turn out of a slide is no 180
    local made = spin - (jump.spin0 or 0.0)
    local madeTurns = math.floor(math.abs(made) / 180.0 + 0.4999) * (made < 0 and -1 or 1)
    -- frontside = the chest turns towards the way you travel first: clockwise for the clips as authored (goofy)
    local m = mirrored()
    local fs = (madeTurns < 0) ~= m
    local hard = into > -Config.HeavyLanding
    local sketchy = math.abs(off) > Config.SketchyLanding
    if lying then
        -- (the coffin goes on along the ground: nothing to play)
    elseif held then
        S3.land(hard, 'grab', heldHand == 'both' and 'dbl' or (heldHand == 'back' and 'fs' or 'bs'))
    elseif sketchy then
        S3.land(hard, 'sketchy', ((off < 0) ~= m) and 'fs' or 'bs')
    elseif madeTurns ~= 0 then
        S3.land(hard, 'nice', fs and 'fs' or 'bs')
    else
        S3.land(hard)
    end
    if not lying then landLock = Config.LandLock end
    if sketchy then scale = scale * Tune.bonus('toSketchy') end

    local turns = math.abs(madeTurns)
    local spinPart = turns ~= 0 and ((fs and 'FS ' or 'BS ') .. tostring(turns * 180)) or nil
    if jump.name then
        addToLine((spinPart and (spinPart .. ' ') or '') .. jump.label, jump.name,
            Tune.baseScore(jump.name) + Tune.spinScore(turns * 180.0), scale)
    elseif spinPart then
        addToLine(spinPart, 'spin', Tune.spinScore(turns * 180.0), scale)
    end
    for _, t in ipairs(jump.tricks) do addToLine(t[1], t[2], t[3], scale) end
    spin, flip, adjust = 0.0, nil, nil
end

-- ------------------------------------------------------------------ the ride

-- ------------------------------------------------------------------ off the board, as in Skate 3
--
-- Skate 3's off-board mode with its own clips and rules (offboard.xml, mount.xml, dismount.xml; the clips are the
-- OffBoard bank's, played through skate3_assets): the rider stands, walks, runs and sprints with the board in the hand,
-- and gets back on by throwing it down and jumping onto it. As on the board, the rider is moved by this script: the
-- distance comes from the clips' own root motion, so the feet do not slide; the ground and walls are found with rays.
--   left stick   which way (seen from the camera) and how fast: part of the way = walk, past half = run (Skate 3's
--                OB_SteerMagnitude 0.5)
--   A (Shift)    sprint ("Press A to sprint", Skate 3's own tutorial)
--   Y (F)        back onto the board
-- off = { state = 'stand' | 'into' | 'move' | 'stop' | 'mount' | 'air', gait, holding (the board is in the hand),
--         heading, v (m/s), vz, clip, t, len, wantT }

-- (its helpers live in a table: this file's main chunk has no local variables to spare)
local OB = {}

function OB.play(clip, blend, loop)
    off.clip, off.t = clip, 0.0
    off.len = S3.offPlay(clip, blend, loop)
end

-- Skate 3 has a clip for each quarter of a stride to stop or to mount out of: which one the cycle is in now.
function OB.quarter()
    return (math.floor(S3.offPhase() * 4.0 + 0.5) % 4) * 25
end

-- now = the gait in progress: it is kept until the stick is clearly past the line between a walk and a run (a
-- stick held about half way over flicked between the two with every tremble of the thumb, and each change starts
-- the stride again).
function OB.gait(mag, sprint, now)
    if mag <= 0.01 then return nil end
    local line = 0.5
    if now == 'walk' then line = 0.6 elseif now == 'run' or now == 'sprint' then line = 0.4 end
    if mag > line then return sprint and 'sprint' or 'run' end
    return 'walk'
end

-- Leave Skate 3's off-board mode. away = the board goes back into the inventory when it is in the hand (otherwise
-- it stays where it lies).
putAway = function(away, gone)
    if not off then return end
    local holding = off.holding
    off = nil
    S3.stop()
    releaseCam()
    if not gone then -- (gone: see getOff)
        local ped = PlayerPedId()
        FreezeEntityPosition(ped, false)
        ClearPedTasks(ped)
        SetEntityRotation(ped, 0.0, 0.0, GetEntityHeading(ped), 2, true)
        SetEntityCoordsNoOffset(ped, pos.x, pos.y, pos.z + 1.0, false, false, false)
    end
    mode = 'ground'
    if board and DoesEntityExist(board) then
        if holding and away ~= false then
            deleteBoard()
        else
            FreezeEntityPosition(board, false)
            SetEntityCollision(board, true, true)
            if holding then PlaceObjectOnGroundProperly(board) end
        end
    end
end

-- Off the board out of a ride (Y). true = done; false = not now (Skate 3 does not let go of the board in the last
-- 0.3 s before a landing); nil = this mode is not there (the caller steps off the old way).
stepOff = function()
    if not (Config.OffBoard.enabled and S3.active()) then return nil end
    if mode == 'air' and ttl <= 0.3 then return false end
    local v = (mode == 'grind' and grind) and grind.speed or speed
    local h = travelHeading()
    local inAir, fall, hand = mode == 'air', vz, grab and grab.kind or nil
    riding = false
    pending, switching, skitch = nil, nil, nil
    soundStop()
    cashLine()
    flip, grab, manual, grind, air, ggrab, coffin, onefoot = nil, nil, nil, nil, nil, nil, nil, nil
    hippy, revert = nil, nil
    facing, speed, spin = h, math.abs(v), 0.0
    off = { holding = true, heading = h, v = math.abs(v), vz = 0.0, wantT = 0.0 }
    if inAir then
        -- in the air: with a hand on the board it comes along in that hand; otherwise it is kicked away
        local clip = hand and S3.offClip('airGrab', true, hand) or nil
        if clip then
            OB.play(clip, 0.1, false)
        else
            OB.play(S3.offClip('kickout'), 0.1, false)
            off.holding = false
            if board and DoesEntityExist(board) then
                local f = fwd(h)
                FreezeEntityPosition(board, false)
                SetEntityCollision(board, true, true)
                SetEntityDynamic(board, true)
                ActivatePhysics(board)
                SetEntityVelocity(board, f.x * off.v, f.y * off.v, fall + 1.5)
                local under, gp = ray(pos + vector3(0, 0, 0.5), pos - vector3(0, 0, 80.0), board)
                SK.watch(board, under and gp or pos)
            end
        end
        off.state, off.vz, mode = 'air', fall, 'air'
    else
        mode, vz = 'ground', 0.0
        if off.v < 1.0 then
            OB.play(S3.offClip('dismount', true, 'stand'), 0.2, false)
            off.state = 'stop'
        else
            OB.play(S3.offClip('dismount', true, off.v < 8.0 and 'run' or 'fast'), 0.1, false)
            off.state, off.gait = 'into', 'run'
        end
    end
    note('off the board (%s, %.1f m/s)', off.state, off.v)
    return true
end

-- Back onto the board: Skate 3's mount for what the rider is doing (out of a stand, or out of a stride of a walk, a
-- run or a sprint). A board that is not in the hand is fetched first, as Skate 3 does.
function OB.mount()
    if not off.holding then
        if not board or not DoesEntityExist(board) then
            local model, skate3 = pickBoardModel()
            if not model then return end
            board = CreateObject(model, pos.x, pos.y, pos.z, Config.NetworkBoard, true, false)
            SetModelAsNoLongerNeeded(model)
            SetEntityLodDist(board, Config.BoardLodDist)
            if skate3 then Deck.dress(board) end
        end
        SetEntityCollision(board, false, false)
        FreezeEntityPosition(board, true)
        off.holding = true
    end
    local moving = off.state == 'move' and off.gait or nil
    OB.play(S3.offClip('mount', true, moving, moving and OB.quarter() or nil), 0.1, false)
    off.state = 'mount'
end

walkTick = function(dt)
    local ped = PlayerPedId()
    if ped ~= sk.rider then return putAway(false, true) end
    if IsEntityDead(ped) or IsPedInAnyVehicle(ped, false) or IsPedCuffed(ped) then return putAway(false) end
    for _, c in ipairs(DISABLE) do DisableControlAction(0, c, true) end
    local o = off
    local sx, sy = padNormal(C.lr), -padNormal(C.ud)
    local mag = math.min(1.0, math.sqrt(sx * sx + sy * sy))
    local sprint = padPressed(C.pushR)
    o.t = o.t + dt

    if padJust(C.off) and o.state ~= 'mount' and o.state ~= 'air' then OB.mount() end

    local f = fwd(o.heading)
    if o.state == 'air' then
        -- falling: the speed it had, gravity, until the feet find the ground
        o.vz = o.vz - Tune.gravity * dt
        local target = pos + f * (o.v * dt) + vector3(0, 0, o.vz * dt)
        local hit, gp = ray(pos + vector3(0, 0, 0.3), target - vector3(0, 0, 0.05), o.holding and board or 0, LOCK_FLAGS)
        if hit and o.vz <= 0.0 then
            pos = gp
            local into = -o.vz
            if into > Tune.hardLanding then
                mode, speed, vz, facing, off = 'ground', o.v, o.vz, o.heading, nil
                return getOff('Landed too hard')
            end
            local size = into > Config.OffBoard.bigFall and 'big' or 'sml'
            if o.v < 1.0 then
                OB.play(S3.offClip('land', o.holding, 'stand', size), 0.1, false)
                o.state = 'stop'
            else
                OB.play(S3.offClip('land', o.holding, 'run', size), 0.1, false)
                o.state, o.gait = 'into', 'run'
            end
            o.vz, mode = 0.0, 'ground'
        else
            pos = target
        end
    else
        -- which way: the stick, seen from the camera. Standing still the rider turns on the spot to it when setting
        -- off; moving, as fast as Skate 3 lets a skater turn at that speed.
        if mag > 0.01 and o.state ~= 'mount' then
            local want = (camHeading or o.heading) - math.deg(math.atan(sx, sy))
            local rate = Tune.offTurn and Tune.graph(Tune.offTurn, o.v) or Config.OffBoard.turnRate
            o.heading = o.heading + clamp(angDiff(want, o.heading), -rate * dt, rate * dt)
            f = fwd(o.heading)
        end

        if o.state == 'stand' then
            -- (Skate 3: the stick has to be off centre for 0.06 s before the skater sets off)
            o.wantT = mag > 0.01 and o.wantT + dt or 0.0
            if o.wantT > 0.06 then
                o.gait = OB.gait(mag, sprint)
                OB.play(S3.offClip('start', o.holding, o.gait), 0.1, false)
                o.state, o.wantT = 'into', 0.0
            end
        elseif o.state == 'into' then
            -- a start, a step off the board or a landing that ends in a stride
            if o.t >= o.len - 0.1 then
                local g = OB.gait(mag, sprint)
                if g then
                    o.gait = g
                    OB.play(S3.offClip('cycle', o.holding, g), 0.1, true)
                    o.state = 'move'
                else
                    OB.play(S3.offClip('stop', o.holding, o.gait == 'sprint' and 'sprint' or (o.gait or 'run'), 0), 0.1, false)
                    o.state = 'stop'
                end
            end
        elseif o.state == 'move' then
            local g = OB.gait(mag, sprint, o.gait)
            if not g then
                OB.play(S3.offClip('stop', o.holding, o.gait, OB.quarter()), 0.1, false)
                o.state = 'stop'
            elseif g ~= o.gait then
                o.gait = g
                OB.play(S3.offClip('cycle', o.holding, g), 0.2, true)
            end
        elseif o.state == 'stop' then
            if o.t >= o.len then
                OB.play(S3.offClip('stand', o.holding), 0.2, true)
                o.state, o.wantT = 'stand', 0.0
            elseif mag > 0.2 and o.t >= o.len - 0.5 then
                -- (IntoStand -> OutOfStand: the stick is over again near the end of the stop)
                o.gait = OB.gait(mag, sprint)
                OB.play(S3.offClip('start', o.holding, o.gait), 0.1, false)
                o.state = 'into'
            end
        elseif o.state == 'mount' then
            if o.t >= o.len then
                -- on the board: the ride takes over where the jump ended, at the speed it had
                local at, h, v = pos, o.heading, o.v
                off = nil
                return mount({ pos = at, facing = h, speed = v })
            end
        end

        -- the clip's own root motion moves the rider; a wall stops it; the ground is followed up and down a step,
        -- and past a drop the rider falls
        local dist = S3.offTravel()
        if dist ~= 0.0 then
            local target = pos + f * dist
            local blocked, _, n = ray(pos + vector3(0, 0, 0.6), target + vector3(0, 0, 0.6) + f * 0.3, board, LOCK_FLAGS)
            if blocked and n.z < 0.35 then target = pos end
            local hit, gp = ray(target + vector3(0, 0, Config.OffBoard.stepUp), target - vector3(0, 0, Config.OffBoard.drop),
                o.holding and board or 0, LOCK_FLAGS)
            if hit then
                pos = gp
            elseif o.state ~= 'mount' then
                pos, o.state, o.vz, mode = target, 'air', 0.0, 'air'
            end
        end
        o.v = lerp(o.v, dist / dt, 0.2)
    end

    if not off then return end
    facing, speed = o.heading, o.v
    S3.offDrive(pos.x, pos.y, pos.z, o.heading, o.holding)
    updateCam(ped, dt)
end

tick = function(dt)
    local ped = PlayerPedId()
    if ped ~= sk.rider then return getOff(nil, nil, true) end
    if IsEntityDead(ped) or IsPedInAnyVehicle(ped, false) or IsPedCuffed(ped) then return getOff() end
    if board and not DoesEntityExist(board) then board = nil end
    clock = clock + dt

    for _, c in ipairs(DISABLE) do DisableControlAction(0, c, true) end
    local kb = not sim and IsUsingKeyboard(0)
    local steer = padNormal(C.lr)
    local throttle = -padNormal(C.ud)

    if padJust(C.off) then
        -- Y: off the board. Skate 3's way when it is there (nil = it is not: the plain step off)
        local did = stepOff()
        if did == nil then return getOff() end
        if did then return end
    end

    -- right stick, or a spring-loaded virtual stick driven by the mouse
    if kb then
        local k = math.exp(-dt * Config.MouseReturn)
        stickX = stickX * k + padNormal(C.lookX) * Config.MouseFlickScale
        stickY = stickY * k - padNormal(C.lookY) * Config.MouseFlickScale
        local m = math.sqrt(stickX * stickX + stickY * stickY)
        if m > 1.0 then stickX, stickY = stickX / m, stickY / m end
    else
        stickX, stickY = padNormal(C.lookX), -padNormal(C.lookY)
    end

    -- buttons. Pushing: A = right foot, X = left foot on a controller (as in Skate 3), W on the keyboard.
    local pushFoot
    if kb then
        if throttle > 0.5 then pushFoot = mirrored() and 'right' or 'left' end -- the back foot
    elseif padPressed(C.pushR) then pushFoot = 'right'
    elseif padPressed(C.pushL) then pushFoot = 'left' end
    -- both push buttons together are no push: the crouch for a hippy jump (or, with both hands on the board, the coffin)
    local bothPush = not kb and padPressed(C.pushR) and padPressed(C.pushL)
    if bothPush then pushFoot = nil end
    local brakeHeld = (kb and throttle < -0.5) or (not kb and padPressed(C.brake))
    local grabR, grabL = padPressed(C.grabR), padPressed(C.grabL)

    local stickMag = math.sqrt(stickX * stickX + stickY * stickY)
    if stickMag < 0.5 then flickHeld = false end
    local footJust, justFoot -- a push button has just been pressed; which foot's
    -- The dark catch has its own button: the right bumper (Skate 3's trick book: "right bumper + flick", and the
    -- right bumper again to let the board go). Pressed while the board is turning it asks for the catch. On the
    -- keyboard it is Space, which is the back foot's button there too.
    local darkJust, darkHeld
    if kb then
        footJust = (mode == 'air' or pending ~= nil or ggrab ~= nil) and padJust(C.space)
        justFoot = footJust and (mirrored() and 'right' or 'left') or nil -- (the back foot)
        darkJust, darkHeld = footJust, padPressed(C.space)
    else
        local a, b = padJust(C.pushR), padJust(C.pushL)
        footJust = a or b
        justFoot = a and 'right' or (b and 'left' or nil)
        darkJust, darkHeld = padJust(C.dark), padPressed(C.dark)
    end
    if darkJust and S3.active() then
        if pending or (mode == 'air' and S3.tricking()) then
            darkAsked = true
        elseif mode == 'air' and S3.dark() then
            S3.darkOut(nil) -- pressed again with the board upside down: the quick way out, back the right way up
        end
    end
    local touched = pushFoot or brakeHeld or grabR or grabL or math.abs(steer) > 0.2 or stickMag > 0.2
    inputT = touched and 0.0 or inputT + dt
    if touched or math.abs(speed) > 0.5 or mode ~= 'ground' then
        idleT = 0.0
    else
        idleT = idleT + dt
    end
    landLock = math.max(0.0, landLock - dt)
    pushCd = math.max(0.0, pushCd - dt)

    -- the coffin: the rider lies on the board, from lying back to sitting up again
    if S3.active() and S3.inCoffin() then
        coffin = coffin or { t = 0.0 }
        coffin.t = coffin.t + dt
    elseif coffin then
        endCoffin()
    end

    readTricks(dt, kb, darkHeld)
    if not riding then return end
    do
        local pats = S3.active() and S3.patterns() or nil
        if pats and pats.left and leftSetOf ~= pats then
            -- (the set's other gestures, the body flips, are not built: left in, a sweep through the bottom of the
            -- stick would be taken for the start of one)
            leftSet, leftSetOf = {}, pats
            for _, q in ipairs(pats.left) do
                if q.name == 'SlideFs180' or q.name == 'SlideBs180' then leftSet[#leftSet + 1] = q end
            end
        end
        local name = pats and pats.left and Flick.update(clock, steer, -throttle, leftSet, Config.FlickSegTime, leftStick)
        if name and (name == 'SlideFs180' or name == 'SlideBs180') and mode == 'ground' and not revert and not hippy
            and not ggrab and not pending and not switching and not manual and math.abs(speed) > Config.RevertMinSpeed then
            -- Skate 3's SlideFs180 is the stick swept right > down > left: the board goes round with it, clockwise.
            -- For the clips as authored that is the frontside way; a mirrored rider's is called backside.
            local clockwise = name == 'SlideFs180'
            local side = (clockwise ~= mirrored()) and 'fs' or 'bs'
            S3.revert(side)
            revert = { dir = clockwise and -1.0 or 1.0, ang = 0.0, key = side .. 'revert',
                       label = side == 'fs' and 'FS Revert' or 'BS Revert' }
        end
    end
    if pending then
        -- the takeoff clip is playing; leave the ground when it ends
        pending.t = pending.t - dt
        if pending.t <= 0.0 then launchPending() end
    end

    local f = fwd(facing)
    braking = false
    local pushing = false

    -- ground grabs (onground.xml "Grabbing"): a trigger held while rolling puts that hand on the board, the same
    -- hand as in the air. It comes before the crouch, the push and the brake: none of those while it is held.
    -- Skate 3 clips only.
    local gg
    if S3.active() and (grabR or grabL) and not pending and not switching then
        if grabR and grabL then
            gg = 'dbl'
        else
            gg = ((grabL and not mirrored()) or (grabR and mirrored())) and 'fs' or 'bs'
        end
    end

    if hippy and (mode ~= 'ground' or not S3.active()) then hippy = nil end
    if revert and mode ~= 'ground' then revert = nil end

    -- skitching: the hold button (right bumper; H on the keyboard) near the back of a car takes hold of it, and
    -- while it is held the car has the board (see skitchHold)
    sk.cd = math.max(0.0, sk.cd - dt)
    local hang = Tune.skitch.enabled and padPressed(kb and C.hangKey or C.hang)
    if skitch and (mode ~= 'ground' or not SK.hold(dt, steer, throttle, hang)) then skitch = nil end
    if not skitch and hang and mode == 'ground' and sk.cd <= 0.0 and not pending and not switching and not hippy
        and not revert and not coffin and speed > -0.5 then
        sk.scan = sk.scan - dt
        if sk.scan <= 0.0 then
            sk.scan = 0.1
            SK.grab()
        end
    end

    if skitch then
        gg, f = nil, fwd(facing) -- (no hand for the board, no push, no brake: both hands are the car's)
    elseif mode == 'ground' then
        -- a foot planted out of a ground grab (Skate 3's "PushTrick"): the front foot's push button is a boneless,
        -- the back foot's a fastplant; frontside or backside by the hand on the board
        if ggrab and ggrab.kind ~= 'dbl' and justFoot and S3.active() and not pending and not switching and not coffin
            and speed > -0.5 then
            local front = (justFoot == 'right') ~= mirrored() -- (the clips as authored have the right foot in front)
            local name = ggrab.kind .. (front and 'boneless' or 'fastplant')
            local t, text = S3.plant(name, speed)
            if t then
                pending = { name = name, label = text, strength = 1.0, fromManual = false, t = t, plant = true }
                gg = nil
            end
        end

        -- the hippy jump (T_HippyJump.xml): both push buttons held = the crouch; let go, and the rider jumps while
        -- the board rolls on underneath. How long the crouch was held is how high.
        if hippy then
            local h = hippy
            gg = nil
            if h.phase == 'antic' then
                h.t = h.t + dt
                if not bothPush then
                    h.phase, h.t2 = 'into', 0.0
                    h.strength = clamp(h.t / Config.HippyFullTime, 0.0, 1.0)
                    h.h, h.takeoff = S3.hippy(h.t)
                end
            elseif h.phase == 'into' then
                h.t2 = h.t2 + dt
                if h.t2 >= h.takeoff then
                    h.phase, h.hop, h.vz = 'air', 0.0, math.sqrt(2.0 * Tune.gravity * Tune.hippyRise(h.strength))
                end
            else
                h.hop = h.hop + h.vz * dt - 0.5 * Tune.gravity * dt * dt
                h.vz = h.vz - Tune.gravity * dt
                -- the legs go out for the board when it is a quarter second away, as for any landing
                local te = Config.AirExtendTime
                h.down = h.vz < 0.0 and h.hop < -h.vz * te + 0.5 * Tune.gravity * te * te
                if h.hop <= 0.0 and h.vz < 0.0 then
                    hippy = nil
                    S3.land(false)
                    landLock = Config.LandLock
                    sound('land', 0.3)
                    addToLine('Hippy Jump', 'hippyjump', Tune.baseScore('hippyjump'))
                end
            end
        elseif bothPush and S3.active() and not gg and not ggrab and not pending and not switching and not revert
            and landLock <= 0.0 then
            if manual then endManual() end
            hippy = { phase = 'antic', t = 0.0 }
        end

        if gg then
            if not ggrab or ggrab.kind ~= gg then
                endGroundGrab()
                ggrab = { kind = gg, label = Config.GroundGrabNames[gg] or 'Ground Grab', t = 0.0 }
            end
            if not coffin then ggrab.t = ggrab.t + dt end
        elseif ggrab then
            endGroundGrab()
        end

        -- manuals: half-tilt the stick and hold (Shift / Ctrl on keyboard)
        local wantManual, nose
        if kb then
            wantManual = padPressed(C.shift) or padPressed(C.ctrl)
            nose = padPressed(C.ctrl)
        else
            local ay = math.abs(stickY)
            wantManual = math.abs(stickX) < Config.ManualSide and ay > Config.ManualMin and ay < Config.ManualMax
            nose = stickY > 0
        end
        if wantManual and not pending and not switching and not ggrab and not hippy and not revert
            and math.abs(speed) > Tune.manualMinSpeed then
            if not manual or manual.nose ~= nose then
                endManual()
                manual = { label = nose and 'Nose Manual' or 'Manual', nose = nose, t = 0.0, hold = 0.0, dist = 0.0 }
            end
            manual.hold = manual.hold + dt
            if manual.hold > Config.ManualEngage then
                manual.t, manual.dist = manual.t + dt, manual.dist + math.abs(speed) * dt
            end
        elseif manual then
            endManual()
        end
        local inManual = manual ~= nil and manual.hold > Config.ManualEngage

        -- the stick asks for a rate of turn; the board comes to it (Skate 3's steering Damping), it is not a switch
        -- (the board rolls on straight under a rider who has jumped off it, and through a revert)
        local turn = ((hippy and hippy.phase == 'air') or revert) and 0.0 or steer
        yawRate = yawRate + (Tune.turnRate(turn, speed) - yawRate) * (1.0 - Tune.steerKeep ^ (dt * 30.0))
        facing = facing - yawRate * dt
        f = fwd(facing)

        -- a revert (revert.xml): the board slides round half a turn while it rolls on the way it was going, at the
        -- rate Skate 3 turns it; it ends rolling backwards
        if revert then
            local r = revert
            r.ang = r.ang + Tune.revertRate(r.ang) * dt
            if r.ang >= 180.0 then
                facing, speed, spin, revert = facing + 180.0, -speed, 0.0, nil
                f = fwd(facing)
                addToLine(r.label, r.key, Tune.baseScore(r.key))
            else
                spin = r.dir * r.ang
            end
        end

        -- rolling fakie for a moment: turn round on the board and ride switch (ground.xml "Switch")
        local fakie = speed < -0.5
        if switching then
            switching = switching - dt
            if switching <= 0.0 then
                switching, switch, fakieT = nil, not switch, 0.0
                facing, speed = facing + 180.0, -speed
                f = fwd(facing)
                S3.setMirrored(mirrored())
            end
        elseif fakie and not inManual and not pending and not antic and not ggrab and not hippy and not revert then
            fakieT = fakieT + dt
            if fakieT > Config.SwitchAfter or pushFoot then
                switching = S3.active() and S3.switchStance(pushFoot ~= nil and pushFoot ~= false) or 0.0 -- the stock poses have no clip for it
            end
        else
            fakieT = 0.0
        end

        if S3.active() then
            -- Skate 3's push cycle: every kick gives its speed while the foot is on the ground, however briefly the
            -- button was pressed
            local phase = S3.pushPhase()
            if phase == 'contact' and kickPhase ~= 'contact' then
                local gain = Tune.pushGain(speed)
                kick = { left = gain, rate = gain / math.max(S3.pushContactTime(), 0.05) }
                sound('push', 0.5)
            end
            kickPhase = phase
            if kick then
                local give = 0.0
                if phase == 'contact' then
                    give = math.min(kick.left, kick.rate * dt)
                elseif phase == 'recover' or phase == 'out' then
                    give = kick.left -- the foot is off the ground: the last of it
                end
                kick.left = (phase == 'contact') and kick.left - give or 0.0
                -- (also when the board is creeping backwards, too slowly to count as fakie: the kick stops it and
                -- sends it forward)
                if speed < Tune.pushMax then speed = math.min(Tune.pushMax, speed + give) end
                if kick.left <= 0.0 then kick = nil end
            end
        end

        if not inManual then
            if pushFoot and not pending and not switching and not antic and not fakie and not brakeHeld and not ggrab
                and not hippy and not revert then
                pushing = true
                if not wasPushing then
                    -- (as authored the right foot is in front)
                    pushStartT, pushFront = clock, pushFoot == (mirrored() and 'left' or 'right')
                end
                if not S3.active() and pushCd <= 0.0 and speed < Tune.pushMax then
                    speed = math.min(Tune.pushMax, math.max(speed, 0.0) + Tune.pushGain(speed))
                    pushCd = Config.PushCooldown
                    sound('push', 0.5)
                end
            end
            if brakeHeld and not pending and not ggrab and not hippy then
                braking = true
                local brake = Config.BrakeDecel * Tune.brakeScale(ground) * dt
                speed = speed > 0 and math.max(0.0, speed - brake) or math.min(0.0, speed + brake)
            end
            -- a line lasts while tricks keep coming; plain rolling lets its momentum run down, then banks it
            rollTime = rollTime + dt
            momentum = math.max(0.0, momentum - Tune.momentumDrain() * dt)
            if rollTime > Tune.lineSeconds then cashLine() end
        end

        -- what the wheels are on: looked at ten times a second. How it rolls changes at once; the sound of it only
        -- when the new ground has been there for 0.3 s (a drain cover or a painted line crossed at speed is not a
        -- change of ground)
        surfaceT = surfaceT - dt
        if surfaceT <= 0.0 then
            surfaceT = 0.1
            local heard, kind = surfaceAt(pos)
            if heard then
                ground = kind
                if heard == surface then
                    surfaceSeen = nil
                elseif heard ~= surfaceSeen then
                    surfaceSeen, surfaceSeenT = heard, 0.0
                else
                    surfaceSeenT = surfaceSeenT + 0.1
                    if surfaceSeenT >= 0.3 then surface, surfaceSeen = heard, nil end
                end
            end
        end

        -- The face the board is on, and gravity along it. Along the board's length it speeds the board up or slows
        -- it down (lets you roll back down a ramp). Across it, it bends the board's path down the hill, as it does to
        -- anything that rolls where it points: ridden across a bank or round the wall of a bowl the line curves down
        -- and comes round to the fall line. `speed` is the board's speed along the face, so on a slope only part of
        -- it is level travel.
        SK.sync()
        local u, d = sk.u, sk.d
        local turned = false
        if u.z < 1.0 then
            local steep = math.sqrt(math.max(1.0 - u.z * u.z, 0.0)) -- the sine of the slope
            local pull = vector3(u.x * u.z, u.y * u.z, u.z * u.z - 1.0) *
                math.min(Tune.gravity, Tune.slopeAcc / math.max(steep, 0.001))
            speed = speed + Surf.dot(pull, d) * dt
            -- (how much of the pull across the board turns it: Skate 3's HeadingAdjustVsSlope, nothing on ground that
            -- is all but level. Slower than Config.CarveMinSpeed the board comes round as if it rolled that fast.)
            local across = Surf.dot(pull, Surf.cross(u, d)) * Tune.carve(steep)
            if math.abs(across) > 0.001 then
                local v = math.max(math.abs(speed), Config.CarveMinSpeed) * sign(speed)
                d, turned = Surf.turn(d, u, math.deg(across / v) * dt), true
            end
        end
        -- (the stock pose leans into a manual)
        tilt = lerp(tilt, (inManual and (manual.nose and -12.0 or 12.0) or 0.0) * Config.TiltSign, 0.25)

        local drag = math.min(math.abs(speed), Tune.friction(speed, inputT, inManual, ground) * dt)
        speed = clamp(speed - (speed > 0 and drag or -drag), -Tune.maxSpeed, Tune.maxSpeed)
        if coffin then
            -- lying on the board costs speed (Skate 3: CoffinAcceleration)
            local lose = math.min(math.abs(speed), Tune.coffinDrag * dt)
            speed = speed - (speed > 0 and lose or -lose)
        end

        local step = speed * dt
        local target = pos + d * step
        if math.abs(speed) > 0.05 then
            -- something in the way: a face that stands up out of this one like a wall. (The next piece of a ramp's
            -- curve does not: what counts is how it stands to the face the board is on, not to the level.)
            local dir = speed > 0 and d or d * -1.0
            local hit, _, n = ray(pos + u * 0.35, target + u * 0.35 + dir * 0.35, board)
            if hit and Surf.dot(n, u) < 0.35 then
                if math.abs(speed) > Config.WallBailSpeed then return getOff('Slammed') end
                speed, target, step = 0.0, pos, 0.0
            end
        end

        -- which way the rider is drifting across their path (names the side of the next grind)
        -- (the stick turns the board the same way round whichever end leads, so the path bends the same way too)
        if math.abs(steer) > 0.2 and math.abs(speed) > 1.0 then lastSide = -steer end

        -- The ground under the next step, looked for square to the face the board is on. It may fall away a little
        -- and still be followed (Skate 3: NaturalAirMaxDist, 12 cm), and ground that is lower only by what its own
        -- slope makes of this step is followed too. Anything else lower than that is a step down, and the board is
        -- in the air: off a kerb it falls, it is not put down.
        local len = math.abs(step)
        local hit, gp, gn = ray(target + u * Config.StepUp, target - u * (Tune.naturalDrop + len * 1.75), board)
        if hit and Surf.dot(gn, u) < 0.35 and Surf.dot(gn, d) * speed < 0.0 then
            hit, gp, gn, speed = true, pos, u, 0.0 -- (the foot of something that stands like a wall: no further)
        end
        if hit then
            local drop = Surf.dot(target - gp, u)
            if drop > Tune.naturalDrop then
                local down = Surf.dot(gn, d) * sign(speed) / math.max(Surf.dot(gn, u), 0.3) -- that face's fall per metre our way
                if drop > math.max(0.0, down) * len * 1.5 + 0.03 then hit = false end
            end
            -- ... and where the ground bends away under a board fast enough to clear it by more than that drop (the
            -- lip of a ramp, the top of a quarter pipe, the brow of a bank), the board flies on as well
            local away = Surf.dot(gn, d) * speed
            if hit and away > 0.0 and away * away / (2.0 * Tune.gravity * math.max(gn.z, 0.2)) > Tune.naturalDrop then
                hit = false
            end
        end
        if hit then
            if gn.x ~= u.x or gn.y ~= u.y or gn.z ~= u.z then
                -- onto the next face: the nose keeps its angle to the crease between the two
                d, turned = Surf.along(Surf.carry(d, u, gn), gn) or d, true
            end
            groundVz = d.z * speed -- (how fast the ground is taking the board up or down)
            pos, groundN = gp, gn
            if turned then SK.put(gn, d) else sk.u = gn end
            -- the look of it: the board lies on its two trucks. Where a truck's place is not this ground going on
            -- (the drop past the end of a ledge, the top of a kerb too high to roll up) the board lies as the face
            -- under it does: it does not dip its nose before it has left the ledge.
            local front, back = SK.truck(pos + d * 0.6, gn), SK.truck(pos - d * 0.6, gn)
            local want = Surf.along(gn, Surf.unit(front - back) or d) or gn
            sk.up = Surf.unit(sk.up + (want - sk.up) * 0.25) or want
        else
            -- rolled off a ledge or over a lip: the board flies on the way it was going, up or down
            if turned then SK.put(u, d) end
            -- (up off the top of a ramp it leaves from where it stands on the curve: from a step further on, out over
            -- the deck, it would not come down on the curve again)
            if not (u.z < Config.VertFace and d.z * speed > 0.5) then pos = target end
            switching = nil
            if pending then
                launchPending() -- the flick was already in: pop off the lip
            else
                endManual()
                SK.fly(d * speed)
                mode, airTime, air, spin, adjust = 'air', 0.0, { tricks = {}, groundGrab = ggrab ~= nil }, 0.0, nil
                lock = nil
            end
        end
    elseif mode == 'grind' then
        slopeDeg = 0.0
        if sk.up.z < 1.0 then sk.up = sk.up.z > 0.999999 and Surf.UP or Surf.unit(sk.up + (Surf.UP - sk.up) * 0.25) end
        local g = grind
        local rf = fwd(g.h)
        g.t = g.t + dt
        -- the left stick leans the rider on the rail (GrindBalanceX); nothing to fall off from, as in Skate 3
        g.balance = lerp(g.balance or 0.0, steer, 1.0 - math.exp(-dt * 6.0))
        g.low = antic ~= nil
        -- a trigger puts that hand on the board (grinding.xml): the back hand, the front one, or both
        do
            local m = mirrored()
            local backHeld, frontHeld = (grabL and not m) or (grabR and m), (grabR and not m) or (grabL and m)
            g.grab = (backHeld and frontHeld) and 'dbl' or (backHeld and 'fs' or (frontHeld and 'bs' or nil))
            if S3.active() then
                local key, label = S3.grindGrabbed()
                if key then g.grabKey, g.grabLabel = key, label end
            end
        end

        local zAhead = probe(pos + rf * 0.5, 0.3, 0.3)
        if zAhead then g.speed = g.speed - Tune.gravity * (zAhead - pos.z) / 0.5 * dt end
        g.speed = g.speed - Tune.grindFriction(g.t, g.slide) * dt
        local target = pos + rf * (g.speed * dt)
        -- stay on it: ten times a second, where is the middle of the rail (the edge of the ledge) from here? Go
        -- across to it, and turn the line of travel by what it was out, so a rail that bends is followed too.
        g.followT, g.followD = (g.followT or 0.0) + dt, (g.followD or 0.0) + math.abs(g.speed) * dt
        if g.followT >= 0.1 and g.followD > 0.05 then
            local off, found = railCentre(pos, g.h)
            -- flat ground with no edge near (the ledge ran out into a pavement): twice running and the grind is over
            g.flat = found == 'flat' and (g.flat or 0) + 1 or 0
            if math.abs(off) > 0.005 and math.abs(off) < 0.25 then
                if g.settled then -- (not while it is still coming across from where it landed)
                    local turn = clamp(math.deg(math.atan(off, g.followD)) * 0.5, -6.0, 6.0)
                    g.h, g.facing = g.h + turn, g.facing + turn
                    rf = fwd(g.h)
                    target = pos + rf * (g.speed * dt)
                end
                g.shift = off
            end
            g.settled = math.abs(off) < 0.03
            g.followT, g.followD = 0.0, 0.0
        end
        -- slide across onto the middle of the rail
        if g.shift ~= 0.0 then
            local move = clamp(g.shift, -Tune.lockSpeed * dt, Tune.lockSpeed * dt)
            target, g.shift = target + fwd(g.h + 90.0) * move, g.shift - move
        end
        local z = probe(target, 0.3, 0.35)
        -- how far the top may rise or fall in this step and still be the same rail: a handrail down a flight of
        -- stairs (35 degrees or so), not the drop off the end of a kerb
        local stepZ = math.abs(g.speed) * dt * 0.75 + 0.03
        if (not z or math.abs(z - pos.z) > stepZ) and g.speed >= Config.GrindMinSpeed * 0.5 then
            -- nothing under the middle of the board any more. The end of the rail, or has it turned? Look for its
            -- top a hand's width to either side, and if it is there go with it.
            local left = fwd(g.h + 90.0)
            local t, n = topAcross(target, left, -0.15, 0.15, 0.01, pos.z)
            local best
            for i = 0, n do
                if t[i] and (not best or math.abs(i - n * 0.5) < math.abs(best - n * 0.5)) then best = i end
            end
            if best then
                local off = seatOn(target, left, -0.15 + best * 0.01, pos.z)
                local turn = clamp(math.deg(math.atan(off, math.max(g.followD or 0.0, 0.2))), -6.0, 6.0)
                g.h, g.facing = g.h + turn, g.facing + turn
                target = target + left * off
                g.shift, g.followT, g.followD, g.settled = 0.0, 0.0, 0.0, false
                z = probe(target, 0.3, 0.35)
            end
        end
        if g.speed < Config.GrindMinSpeed * 0.5 or not z or math.abs(z - pos.z) > stepZ or (g.flat or 0) >= 2 then
            -- off the end of the rail (or out of speed): the board keeps its line, the body turns back with it
            pos = target
            if pending then
                launchPending() -- the flick was already in: pop off the end
            else
                endGrind()
                spin = angDiff(g.facing, g.h)
                facing, speed = g.h, math.max(g.speed, 0.0)
                sk.ah, sk.re = nil, nil
                mode, vz, airTime, air, adjust, lock = 'air', 0.0, 0.0, { tricks = {}, fromGrind = true, spin0 = spin }, nil, nil
            end
        else
            g.dist = g.dist + math.abs(g.speed) * dt
            pos = vector3(target.x, target.y, z)
        end
        tilt = lerp(tilt, 0.0, 0.2)
    end

    wasPushing = pushing
    if mode ~= 'ground' and ggrab then endGroundGrab() end

    if mode == 'air' then
        f = fwd(facing) -- popping off a rail just changed it
        airTime = airTime + dt
        tilt = lerp(tilt, 0.0, 0.1)
        -- left stick spins the body; stick right = clockwise
        if not (air and air.name) and airTime < Tune.naturalAirTime then
            -- rolled off an edge a moment ago, no jump: the board goes on round at the rate it was turning (down
            -- again this soon, nothing happened: see land)
            spin = spin - yawRate * dt
        elseif math.abs(steer) > 0.15 then
            spin = spin - Tune.spinRate(steer, airTime) * dt
        elseif (air and air.fromGrind) or (landingSoon and not (lock and lock.off)) then
            -- stick let go: coming off a slide, or just before the board lands on the ground, the body squares up
            -- with the board's line by itself (Skate 3's auto body spin). Not on the way onto a rail: there the
            -- angle is the rider's choice of grind.
            local want = SK.square()
            local step = Tune.autoSpin * dt
            spin = math.abs(want - spin) <= step and want or spin + sign(want - spin) * step
        end

        -- how long until the board is down (Skate 3's TimeToLand): by the fall to the ground under it
        do
            local hit, gp = ray(pos + vector3(0, 0, 0.2), pos - vector3(0, 0, 60.0), board)
            local h = hit and math.max(pos.z - gp.z, 0.0) or 60.0
            -- (up off the top of a ramp it is the curve it left that the board comes down on, a little under the lip)
            if sk.re and sk.up.z < Config.VertFace then h = math.min(h, math.max(pos.z - sk.re.z + 0.3, 0.0)) end
            ttl = (vz + math.sqrt(vz * vz + 2.0 * Tune.gravity * h)) / Tune.gravity
            SK.alignAir(dt)
        end
        if S3.active() then
            local info = S3.flipInfo()
            if air and info then air.info = info end
        end

        -- board adjust: the right stick held up / down in the air drops the nose / tail (picks the grind and, with
        -- a trigger, the grab). Ctrl / Shift on the keyboard.
        local tricking = S3.active() and S3.tricking()
        local zone = stickZone(kb)
        adjust = zone == 'up' and 'nose' or (zone == 'down' and 'tail' or nil)

        -- Grabs: hold the triggers (mouse buttons on keyboard). Skate 3 (air.xml, T_Grab.xml, BoardAdjust*.xml,
        -- StaleMuteGrab.xml): the left trigger is the back hand of the clips as authored, the right one when the
        -- rider is mirrored. Which grab is settled when the hand goes on, by where the stick is held THEN:
        --   back hand:   FS grab;  stick up (nose down) tail grab;  down crail;      to the FS-shifty side stalefish
        --   front hand:  BS grab;  stick up seatbelt;               down nose grab;  to the FS-shifty side mute
        --   both hands:  double grab
        -- The stick moved afterwards tweaks the grab it is. A tail / nose / crail / seatbelt grab needs the stick
        -- only to begin: after that the trigger holds it (BoardAdjustUp.xml "TailGrab": the stick is a precondition,
        -- the trigger is wanted always). Those and stale / mute stay whatever the other hand does.
        local m = mirrored()
        local backHeld, frontHeld = (grabL and not m) or (grabR and m), (grabR and not m) or (grabL and m)
        local dark = S3.active() and S3.dark()
        if grab then
            local g, on = grab, nil
            if STICKY[g.kind] then
                on = (g.hand == 'back' and backHeld) or (g.hand == 'front' and frontHeld)
            else
                on = g.hand == ((backHeld and frontHeld) and 'both' or (backHeld and 'back' or (frontHeld and 'front' or nil)))
            end
            if not on or tricking or dark then endGrab() end
        end
        if not grab and (backHeld or frontHeld) and not tricking and not dark then
            local hand = (backHeld and frontHeld) and 'both' or (backHeld and 'back' or 'front')
            local kind
            if hand == 'both' then
                kind = 'dbl'
            elseif zone == 'up' then
                kind = hand == 'back' and 'tail' or 'seatbelt'
            elseif zone == 'down' then
                kind = hand == 'back' and 'crail' or 'nose'
            elseif zone == 'right' and S3.active() then
                kind = hand == 'back' and 'stale' or 'mute'
            else
                kind = hand == 'back' and 'fs' or 'bs'
            end
            grab = newGrab(kind, hand)
        end
        if grab then
            -- what the other buttons make of it (Skate 3 clips): the other hand on a nose grab = rocket air; the
            -- brake button = the feet off (superman on a double grab, no-foot / christ air on a FS / BS grab, airwalk
            -- on a tail or nose grab, where both push buttons do it too); one push button = that foot off; the stick
            -- = a tweak. (The action graph calls it "Dismount", which is not the button that gets off the board: the
            -- trick book has the brake's button for these, and Y for getting off.)
            local g, var = grab, nil
            if S3.active() and not coffin then
                local off = brakeHeld
                local pr, pl = (not kb) and padPressed(C.pushR), padPressed(C.pushL)
                -- (on a FS / BS grab the foot comes off on a new press of its button, T_Grab.xml "NewOneFoot"; on a
                -- tail or nose grab the button held is enough, BoardAdjustUp / Down.xml)
                if not (pr or pl) then g.footArmed = false elseif justFoot then g.footArmed = true end
                if g.kind == 'nose' and backHeld and frontHeld then
                    var = 'rocket'
                elseif off and S3.grabHas(g.kind, 'super') then
                    var = 'super'
                elseif off and S3.grabHas(g.kind, 'nofoot') then
                    var = 'nofoot'
                elseif (off or (pr and pl)) and S3.grabHas(g.kind, 'airwalk') then
                    var = 'airwalk'
                elseif pr ~= pl and (TIP[g.kind] or g.footArmed) then
                    -- (the clips as authored have the right foot in front)
                    local v = (((pr and true or false) ~= m)) and 'foot_front' or 'foot_back'
                    if S3.grabHas(g.kind, v) then var = v end
                end
                if not var and zone and S3.grabHas(g.kind, 'tw_' .. zone) then var = 'tw_' .. zone end
            end
            if var ~= g.var then
                endGrabVar()
                g.var = var
            end
            if var and not var:find('^tw_') then
                g.varT = g.varT + dt
            elseif not coffin then
                g.t = g.t + dt
                if var then
                    g.varT = g.varT + dt
                    if g.varT > 0.15 then g.tweak = var:sub(4) end
                end
            end
        end

        -- a foot off the board (air.xml "OneFootOllie"): the push button of that foot pressed in the air and held
        -- (a button still held from a push on the ground does not do it: "NewOneFoot" wants a new press), with
        -- nothing else going on and half a second of air left when it starts. Space on the keyboard (the back foot).
        local foot
        if S3.active() and air and not tricking and not grab and not coffin and not S3.dark() then
            if kb then
                foot = padPressed(C.space) and (mirrored() and 'right' or 'left') or nil
            else
                foot = padPressed(C.pushR) and 'right' or (padPressed(C.pushL) and 'left' or nil)
            end
        end
        if onefoot and onefoot.foot ~= foot then endOneFoot() end
        if foot and justFoot == foot and not onefoot and ttl > 0.5 then
            -- the clips as authored (goofy) have the right foot in front
            onefoot = { foot = foot, kind = ((foot == 'right') ~= mirrored()) and 'front' or 'back', t = 0.0 }
        end
        if onefoot then onefoot.t = onefoot.t + dt end

        -- the exact arc for this frame, so a pop reaches the same height at any frame rate
        local rise = vz * dt - 0.5 * Tune.gravity * dt * dt
        vz = vz - Tune.gravity * dt
        local target = pos + f * (speed * dt) + vector3(0, 0, rise)

        -- a rail or a ledge edge beside the line of flight: drift onto it, as Skate 3's grind lock does
        if Tune.grindLockDist > 0.0 and math.abs(speed) > Config.GrindMinSpeed then
            local travelH = speed < 0 and facing + 180.0 or facing
            local boardZ = target.z + S3.lift
            if not lock or clock - lock.t >= 0.15 then
                -- (each look has its row of probes a third of their spacing further over, and a rail that one look
                -- does not see is kept for the next two: see edgeBeside)
                local n = lock and lock.n or 0
                local off, z, slant = seekRail(target, travelH, boardZ, (n % 3) * 0.02)
                -- (a rail that slants away faster than the pull can go is not one to be pulled along: the board
                -- comes down where its own line takes it, on the rail or not)
                if off and math.abs(slant * speed) > Tune.lockSpeed then off = nil end
                if off and not (lock and lock.off) and math.abs(off) > 0.05 then lastSide = sign(off) end
                local pulled = lock and lock.pulled or 0.0
                if off then
                    lock = { off = off, z = z, slant = slant, t = clock, n = n + 1, miss = 0, pulled = pulled }
                elseif lock and lock.off and lock.miss < 2 then
                    lock.t, lock.n, lock.miss = clock, n + 1, lock.miss + 1
                else
                    lock = { t = clock, n = n + 1, pulled = pulled }
                end
            end
            if lock.off then
                -- Timed to arrive as the board comes down to it. Where the rail does not run quite the way the
                -- board flies it is the place the rail will be THEN that the board is taken to, and between two
                -- looks the rail is followed by its slant (otherwise the board is pulled onto the rail early and
                -- carried on past it, to come down beside it).
                local fall = math.max(boardZ - lock.z, 0.0)
                local left = (vz + math.sqrt(vz * vz + 2.0 * Tune.gravity * fall)) / Tune.gravity
                local drift = lock.slant * math.abs(speed) -- metres a second the rail goes off to the left
                local move = clamp((lock.off + drift * left) * dt / math.max(left, dt), -Tune.lockSpeed * dt,
                    Tune.lockSpeed * dt)
                target = target + fwd(travelH + 90.0) * move
                lock.off, lock.pulled = lock.off + drift * dt - move, lock.pulled + move
            end
        end

        -- a wall in the way, at the height the board and the feet really are (tucked up above the flight path)
        -- (not upright: the rider stands off the wall of a ramp, and everything is looked for from there. That wall
        -- is not one to hit: it is landed on)
        local tipped = sk.up.z < Config.VertFace
        local dir = speed >= 0 and f or f * -1.0
        local up = tipped and sk.up * (S3.lift + 0.35) or vector3(0, 0, S3.lift + 0.35)
        local hit, _, n = ray(pos + up, target + up + dir * 0.3, board)
        if hit and n.z < 0.35 and not (tipped and Surf.dot(n, sk.up) >= 0.7) then return getOff('Hit a wall') end

        slopeDeg = 0.0
        landingSoon, extendSoon = false, false
        if vz > 0.0 then sk.rayZ = nil end
        if vz <= 0.0 and tipped then
            local landHit, gp, gn = SK.touch(target)
            if landHit then
                land(gp, gn)
                if not riding then return end
            else
                pos = target
                landingSoon = SK.soon(Config.AutoSpinTime)
                extendSoon = Config.AirExtendTime > 0.0 and SK.soon(Config.AirExtendTime)
            end
        elseif vz <= 0.0 then
            -- with Skate 3 clips the feet (and the board) are tucked up above the flight path by S3.lift
            -- (looked for from the lowest point the last frame looked at: the legs reaching for the ground lower the
            -- board between two frames, and no height may go unlooked at)
            local top = pos.z + S3.lift + 0.1
            if sk.rayZ and sk.rayZ > top then top = sk.rayZ end
            local landHit, gp, gn = ray(vector3(target.x, target.y, top), target + vector3(0, 0, S3.lift - 0.05), board)
            sk.rayZ = target.z + S3.lift - 0.05
            -- A board is a hand wide. A rail the lock has brought it to within that of is under the board as it
            -- comes down, even when it is not under the very middle of it: the board goes on it.
            if not landHit and lock and lock.off and math.abs(lock.off) <= Config.GrindCatch then
                local over = fwd((speed < 0 and facing + 180.0 or facing) + 90.0) * lock.off
                local hit2, gp2, gn2 = ray(vector3(target.x + over.x, target.y + over.y, top),
                    target + over + vector3(0, 0, S3.lift - 0.05), board, LOCK_FLAGS)
                if hit2 and gn2.z > 0.7 then
                    landHit, gp, gn = true, gp2, gn2
                    lock.pulled, lock.off = lock.pulled + lock.off, 0.0
                end
            end
            if landHit then
                land(gp, gn)
                if not riding then return end
            else
                pos = target
                -- is the ground close enough to be landed on within Config.AutoSpinTime?
                local t = Config.AutoSpinTime
                local reach = -vz * t + 0.5 * Tune.gravity * t * t
                landingSoon = ray(vector3(pos.x, pos.y, pos.z + S3.lift + 0.1), pos + vector3(0, 0, S3.lift - reach), board)
                -- ... and will the board be down within Config.AirExtendTime once the legs are out? Then they start
                -- reaching for the ground now (Skate 3's ControlAirLegExtension), and the tuck is gone by touchdown.
                local te = Config.AirExtendTime
                if te > 0.0 then
                    local fall = -vz * te + 0.5 * Tune.gravity * te * te
                    extendSoon = ray(vector3(pos.x, pos.y, pos.z + S3.lift + 0.1), pos - vector3(0, 0, fall), board)
                end
            end
        else
            -- still going up. The ground ahead may go up faster (a jump at the foot of a bank), or the top of a ledge
            -- be a little above the wheels: the board is then on it, not through it
            local upHit, gp, gn
            if tipped then
                upHit, gp, gn = ray(target + sk.up * (S3.lift + 0.3), target + sk.up * (S3.lift + 0.02), board)
                upHit = upHit and Surf.dot(gn, sk.up) > 0.7
            else
                upHit, gp, gn = ray(vector3(target.x, target.y, pos.z + S3.lift + 0.3),
                    target + vector3(0, 0, S3.lift + 0.02), board)
                upHit = upHit and gn.z > 0.7
            end
            if upHit and airTime > 0.05 then
                land(gp, gn)
                if not riding then return end
            else
                pos = target
            end
        end
        if airTime > 6.0 then return getOff('Lost in the air') end
    end

    if flip then
        flip.t = math.min(Config.FlipTime, flip.t + dt)
    end

    -- place the rider and the board
    local inManual = manual ~= nil and manual.hold > Config.ManualEngage
    if S3.active() then
        -- skate3_assets poses the rider with Skate 3's clips and keeps the feet and the board together
        -- (the heading is the nose's on the face the board is on, or is turned to in the air: see SK.put)
        local heading = (mode == 'air' and SK.noseH() or facing) + spin
        if mode == 'grind' then heading = grind.facing end
        S3.update(dt, {
            mode = mode, speed = speed, steer = steer, braking = braking, fakie = speed < -0.5,
            pushing = pushing, pushKind = (math.abs(speed) > Config.S3FastPush and 'fast' or 'slow') ..
                ((pushFoot == (mirrored() and 'left' or 'right')) and '_mongo' or ''),
            idle = idleT > Config.IdleStandAfter,
            antic = antic, manual = inManual and (manual.nose and 'nose' or 'tail') or nil,
            grab = grab and grab.kind or nil, gvar = grab and grab.var or nil, grind = grind, truck = Tune.truck,
            ggrab = mode == 'ground' and gg or nil,
            skitch = skitch and { hand = skitch.hand, high = skitch.high, shimmy = skitch.shimmy, fast = skitch.fast,
                                  absorb = skitch.absorb } or nil,
            onefoot = (mode == 'air' and onefoot) and onefoot.kind or nil,
            -- the flip in the air: the flick still held (more flips), time left to fall, a second flick (underflip),
            -- a push button pressed (dark catch)
            hold = flickHeld, timeToLand = ttl, uflip = uflipAsked, dcatch = darkAsked,
            -- the hippy jump: the crouch, the jump by its height, the legs out to land; and how high the rider is
            hippy = hippy and (hippy.phase == 'antic' and 'antic' or (hippy.down and 'down' or hippy.h)) or nil,
            hop = (hippy and hippy.phase == 'air') and hippy.hop or nil,
            -- the coffin: both push buttons as well, out of the double grab (coffin.xml), on the ground or in the
            -- air; then for as long as all four are held
            coffin = grabR and grabL and padPressed(C.pushR) and padPressed(C.pushL) and (coffin ~= nil or
                (mode == 'ground' and ggrab ~= nil and ggrab.kind == 'dbl') or (mode == 'air' and grab ~= nil and
                grab.kind == 'dbl')),
            -- off the ground crouched on the board or lying on it: the rider stays that low
            low = mode == 'air' and (coffin ~= nil or (air ~= nil and air.groundGrab == true)),
            landing = mode == 'air' and extendSoon,
            -- a moment off the ground (off a kerb) is no jump: the rider rides on as before
            natural = mode == 'air' and air ~= nil and not air.name and not air.fromGrind and airTime < Tune.naturalAirTime,
            x = pos.x, y = pos.y, z = pos.z, pitch = 0.0, heading = heading,
            ux = sk.up.x, uy = sk.up.y, uz = sk.up.z,
        })
    end
    if not S3.active() then
        local sideways = 90.0 * ((Config.Goofy ~= switch) and -1 or 1) -- the stock pose stands across the board
        local pedHeading = (mode == 'grind' and grind.facing or (mode == 'air' and SK.noseH() or facing) + spin) + sideways
        local up = sk.up
        if up.z > 0.999999 then
            SetEntityCoordsNoOffset(ped, pos.x, pos.y, pos.z + Config.BoardZ + Config.RideHeight, true, true, false)
            SetEntityRotation(ped, 0.0, tilt, pedHeading, 2, true)
        else
            -- on a bank or the curve of a ramp: the rider stands square to it
            local at = pos + up * (Config.BoardZ + Config.RideHeight)
            SetEntityCoordsNoOffset(ped, at.x, at.y, at.z, true, true, false)
            local qx, qy, qz, qw = Surf.quat(up, pedHeading, tilt)
            SetEntityQuaternion(ped, qx, qy, qz, qw)
        end

        local dict, anim = Config.StandDict, Config.StandAnim
        if mode == 'air' and Config.AirDict then dict, anim = Config.AirDict, Config.AirAnim end
        if dict and HasAnimDictLoaded(dict) and not IsEntityPlayingAnim(ped, dict, anim, 3) then
            TaskPlayAnim(ped, dict, anim, 8.0, -8.0, -1, 1, 0.0, false, false, false)
        end
    end

    if board and not S3.active() then
        local roll, yaw, lift = 0.0, Config.BoardYaw, 0.0
        if flip then
            local p = flip.t / Config.FlipTime
            roll, yaw, lift = flip.roll * p, yaw + flip.yaw * p, math.sin(math.pi * p) * 0.2
        end
        if grab then roll, lift = roll + 20.0, lift + 0.25 end
        local rx, ry = 0.0, 0.0
        if Config.FlipAxis == 'x' then rx = roll else ry = roll end
        AttachEntityToEntity(board, ped, GetPedBoneIndex(ped, 0), 0.0, 0.0, -Config.RideHeight + lift,
            rx, ry, yaw, false, false, false, false, 2, true)
    end

    updateCam(ped, dt)

    -- sound: what is rolling and what is scraping, and where the board is from the camera, 20 times a second
    soundT = soundT - dt
    if Config.Sound and soundT <= 0.0 then
        soundT, soundOn = math.max(soundT + 0.05, 0.0), true
        local scrape = (mode == 'grind' and grind) and math.max(math.abs(grind.speed), 0.5) or 0.0
        -- the volume: the game's SFX setting may have been changed in the pause menu
        soundVolT = soundVolT - 0.05
        if soundVolT <= 0.0 then
            soundVolT = 1.0
            local v = soundVolume()
            if v ~= soundVol then
                soundVol = v
                SendNUIMessage({ t = 'config', volume = v })
            end
        end
        local free = math.max(math.abs(speed), 1.0) -- wheels spinning with nothing under them
        SendNUIMessage({
            t = 'state', roll = mode == 'ground' and math.abs(speed) or 0.0, quiet = inManual, surface = surface,
            grind = (grind and not grind.slide) and scrape or 0.0, slide = (grind and grind.slide) and scrape or 0.0,
            rail = grind and grind.rail or nil,
            air = mode == 'air' and free or 0.0, manual = (mode == 'ground' and inManual) and free or 0.0,
            at = Config.SoundFromBoard and heardAt((board and DoesEntityExist(board)) and GetEntityCoords(board) or pos) or nil,
        })
    end

    -- HUD
    if Config.ShowSpeed then
        local v = (mode == 'grind' and grind) and grind.speed or speed
        text(string.format('%d km/h', math.floor(math.abs(v) * 3.6 + 0.5)), 0.5, 0.92, 0.45, 255, 255, 255)
    end
    if not Config.ShowTricks then return end
    text('Score ' .. totalScore, 0.5, 0.95, 0.35, 200, 200, 200)
    local now = {}
    for i = 1, #line do now[i] = line[i] end
    if mode == 'air' and air then
        for _, t in ipairs(air.tricks) do now[#now + 1] = t[1] end
        if grab and grab.t > 0.15 then now[#now + 1] = grab.label end
        if air.name then
            local spinNow = math.floor(math.abs(spin) / 180.0 + 0.5) * 180
            now[#now + 1] = (spinNow > 0 and (spinNow .. ' ') or '') .. air.label
        end
    elseif mode == 'grind' and grind then
        now[#now + 1] = grind.label
    elseif inManual then
        now[#now + 1] = manual.label
    elseif coffin then
        now[#now + 1] = 'Coffin'
    elseif ggrab and ggrab.t > 0.15 then
        now[#now + 1] = ggrab.label
    end
    if #now > 0 then
        text(table.concat(now, ' + '), 0.5, 0.14, 0.5, 255, 220, 80)
        if lineScore > 0 then
            local mult = Tune.multiplier(momentum)
            local tail = Tune.scoring() and (mult > 1.0 and ('  x' .. mult) or '') or (' x' .. math.max(#line, 1))
            text(lineScore .. tail, 0.5, 0.18, 0.45, 255, 255, 255)
        end
    end
end

CreateThread(function()
    local hintShown = false
    while true do
        if riding then
            if not hintShown then
                notify('~b~Skate~s~  Right stick (or the mouse): pull down then flick up = ollie, up-left kickflip, ' ..
                    'up-right heelflip (regular stance). A / X (or W) push, B (or S) brake, left stick carves and spins, ' ..
                    'half-tilt the right stick (Shift / Ctrl) to manual, triggers (mouse buttons) grab, ' ..
                    'hold RB (H) behind a car to hang on to it, ' ..
                    (S3.active() and (Config.GestureKey .. ' gesture, ') or '') ..
                    'Y / F or ' .. Config.ToggleKey .. ' to step off.')
                hintShown = true
            end
            tick(clamp(GetFrameTime(), 0.001, 0.05)) -- (a frame may report no time at all: nothing divides by it)
        elseif off then
            walkTick(clamp(GetFrameTime(), 0.001, 0.05))
        end

        -- standing next to your board without ox_target: E to ride, G to pick it up
        local near = false
        if not riding and not off and board and DoesEntityExist(board) and not targetAdded then
            if #(GetEntityCoords(board) - GetEntityCoords(PlayerPedId())) <= Config.InteractDistance then
                near = true
                BeginTextCommandDisplayHelp('STRING')
                AddTextComponentSubstringPlayerName('~INPUT_CONTEXT~ Ride skateboard   ~INPUT_DETONATE~ Pick up')
                EndTextCommandDisplayHelp(0, false, false, -1)
                if IsControlJustPressed(0, 51) then CreateThread(getOn)
                elseif IsControlJustPressed(0, 47) then CreateThread(pickUp) end
            end
        end

        local showing = message and GetGameTimer() < messageUntil
        if showing then text(message, 0.5, 0.25, 0.6, 255, 255, 255) end
        Wait((riding or off or showing or near) and 0 or 250)
    end
end)

-- For selftest.lua (/skatetest): scripted controller input, and the ride's state from outside.
SkateTest = {
    getOn = getOn, getOff = getOff, spawnRamp = spawnRamp,
    -- sounds switched on?, is there a sound pack?, what the sound page loaded of it
    sound = function() return Config.Sound, S3.active() and S3.sounds() ~= nil, soundReport end,
    input = function(t) sim = t end,
    state = function()
        return {
            riding = riding, mode = mode, speed = speed, facing = facing, x = pos.x, y = pos.y, z = pos.z, vz = vz,
            spin = spin, switch = switch, switching = switching ~= nil, line = table.concat(line, ' + '),
            lineScore = lineScore, total = totalScore, message = lastBail, antic = antic, pending = pending ~= nil,
            manual = manual and manual.label or nil, grab = grab and grab.kind or nil, air = air and air.label or nil,
            ggrab = ggrab and ggrab.kind or nil, coffin = coffin ~= nil, clip = S3.clip, gvar = grab and grab.var or nil,
            hippy = hippy and hippy.phase or nil, revert = revert ~= nil,
            skitch = skitch ~= nil, helmet = helmet.on, off = off and off.state or nil,
            onefoot = onefoot and onefoot.kind or nil, dark = S3.active() and S3.dark() or false,
            grind = grind and grind.label or nil, grindSpeed = grind and grind.speed or nil, board = board,
            grindDist = grind and grind.dist or nil, rail = grind and grind.rail or nil, surface = surface,
            ground = ground,
            mirrored = mirrored(), popHigh = popHigh, tuned = Tune.skate3, lock = lock and lock.off or nil,
            inputT = inputT, cam = cam,
        }
    end,
    -- put the rider somewhere else on the ground, rolling: a test starts each trick from a known speed and line
    place = function(x, y, z, heading, v)
        if not riding or mode ~= 'ground' then return false end
        pos, facing, speed = vector3(x, y, z), heading, v
        sk.u, sk.d = Surf.UP, nil
        return true
    end,
    clearRamps = function()
        for _, r in ipairs(ramps) do
            if DoesEntityExist(r) then SetEntityAsMissionEntity(r, true, true) DeleteObject(r) end
        end
        ramps = {}
    end,
}

-- ox_inventory: items.lua -> client = { export = 'skateboard.useBoard' }
-- Using the item drops your board and puts you on it; using it while riding steps off and picks it up.
exports('useBoard', function()
    CreateThread(function()
        if Engine and Engine.rides(riding or off ~= nil) then return Engine.toggle() end
        if riding then
            getOff()
            pickUp()
        elseif off then
            putAway(true)
        else
            getOn()
        end
    end)
end)

AddEventHandler('onResourceStop', function(res)
    if res ~= GetCurrentResourceName() then return end
    if riding then getOff() end
    if off then putAway(false) end
    releaseCam()
    deleteBoard()
    for _, r in ipairs(ramps) do
        if DoesEntityExist(r) then SetEntityAsMissionEntity(r, true, true) DeleteObject(r) end
    end
end)
