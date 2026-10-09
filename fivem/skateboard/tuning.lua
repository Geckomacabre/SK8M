-- How the board behaves, in one place ("Tune"): speeds, pop heights, turning, spinning, friction, grinds, bails,
-- camera and points. The numbers start out as the ones in config.lua. When `skate3_assets` is running and was built
-- with Skate 3's own tuning database (skate3-sp/tools/build_tuning.py, decoded from your copy of the game), those
-- numbers replace them. None of Skate 3's numbers are in this file: it only knows which of them it can use, and how.
--
-- What comes from Skate 3 when it is there (class.attribute in its database), and how it is used here. The names
-- are the game's; what each one does is read from its name and its values, not from the game's code:
--   physics.WorldGravity                          gravity
--   physics_push.MaxPushableSpeed                 pushing adds no speed above this
--   physics_mode.MaxPushDVStart / MaxPushDVEnd    speed one push adds, at a standstill / at the top pushing speed
--   physics_mode.JumpMinHeight / JumpMaxHeight    how high the weakest / strongest pop takes the rider's middle,
--   physics_jump.AbsoluteMinHeight                 measured from this height (= no air at all)
--   physics_jump.MaxHeightVsSpeed                 pops get lower at very high speed
--   physics_surfaces.smooth.FrictionVsSpeedNew    how fast the board slows down by itself (nothing below 8 m/s) ...
--   physics_friction.FrictionVsSpeed_NoInput       ... plus this once the controls have been let go for NoInputTime,
--   physics_friction.FrictionVsSpeed_Manual        ... or this in a manual
--   physics_steering.SteeringVsInput / VsSpeed    how the stick and the speed shape the turn (the turn rate itself is
--                                                  Config.TurnRate: the game gets it from its truck simulation)
--   physics_bodyspin.PropBodySpinVsTime           how fast the body spins in the air, by time since takeoff
--   physics_mode.MaxAutoBodySpinSpeed             how fast the body squares up by itself just before it lands
--   physics_grinds.DeckCenterToTruck              where the trucks are,
--   physics_grinds.FrictionCoefficient / VsTime    how fast a grind slows down,
--   physics_grinds_air.AngleRange*                 how straight a 50-50 and how square a slide has to be,
--   physics_mode.GrindLockDist                     how far away a rail still pulls the board in
--   physics_wipeout.Wipeout_AirMaxSpeedIntoGround, Wipeout_GroundMaxAngularDeckError
--                                                 landing speed and landing angle that bail
--   camera_shots.*                                the follow camera: distance, height, angle, lens for each situation
--   physics_speed_conservation.CoffinAcceleration  what lying on the board costs in speed,
--   physics_state_skitching.*                     holding on to a car: how near its back has to be (GrabbableBox*),
--                                                  how long a hold lasts at least and how soon the next may start,
--                                                  the sling forward / the drop back on letting go (ExitPush*),
--                                                  when the hands lose it (ExitDist, NaturalAirMaxDist), the hands
--   anim_skitching.ShimmySpeedMax                 how fast the rider moves along the back of the car
--   physics_biped.TurnVsSpeed                     off the board: how fast the rider can turn, by speed
--   physics_heading.HeadingAdjustVsSlope          on a bank or the wall of a bowl: how much of gravity's pull across
--                                                  the board turns it down the hill, by how steep the face is
--   physics_jump.JumpYScalarVsGroundNormalY       a pop off a steep face goes higher (the jump is straight up there)
--   physics_airstates.SpeedToAlignToGround_PhysAir how fast the rider comes round, in the air, to the ground under
--                                                  the landing,
--   physics_airstates.LandingSpeedScalarVsGroundNormalY  the speed a landing on the curve of a ramp gives
--   scoring_trick.BaseScore, scoring2_*           points
-- physics_mode has an easy, a normal and a hardcore set: Config.Mode picks one.

Tune = {}

-- Value of a graph { x = {...}, y = {...} } at x: straight lines between the points, flat outside them.
function Tune.graph(g, x)
    local xs, ys = g.x, g.y
    local n = #xs
    if x <= xs[1] then return ys[1] end
    for i = 2, n do
        if x <= xs[i] then
            local x0, x1 = xs[i - 1], xs[i]
            if x1 <= x0 then return ys[i] end
            return ys[i - 1] + (ys[i] - ys[i - 1]) * (x - x0) / (x1 - x0)
        end
    end
    return ys[n]
end

local function clamp(x, lo, hi) return math.max(lo, math.min(hi, x)) end

local s3 -- Skate 3's tuning table while it is in use
local mode -- its set for Config.Mode

-- Back to the numbers in config.lua.
function Tune.reset()
    s3, mode = nil, nil
    Tune.skate3 = false
    Tune.gravity = Config.Gravity
    Tune.pushMax = Config.PushMax
    Tune.maxSpeed = Config.MaxSpeed
    Tune.hardLanding = -Config.HardLanding     -- m/s into the ground that bails
    Tune.landTolerance = Config.LandTolerance  -- degrees off line that bail
    Tune.grindStraight = Config.GrindStraight  -- degrees off the rail that still lock on as a straight grind
    Tune.slideRange = Config.SlideRange        -- degrees either side of square across the rail that count as a slide
    Tune.tipSlideRange = Config.SlideRange     -- ... for a nose or tail slide
    Tune.grindLockDist = Config.GrindLock and Config.GrindLockDist or 0.0
    Tune.lockSpeed = Config.GrindLockSpeed     -- m/s the board is pulled sideways towards a rail
    Tune.truck = 0.26                          -- deck centre to each truck, metres
    Tune.manualMinSpeed = 1.0
    Tune.lineSeconds = Config.LineCashTime
    Tune.autoSpin = Config.AutoSpinSpeed       -- degrees per second
    Tune.slopeAcc = Config.Gravity             -- the most a slope speeds the board up or slows it down, m/s per second
    Tune.naturalDrop = Config.NaturalDrop      -- metres the ground may fall away under the wheels and still be followed
    Tune.naturalAirTime = Config.NaturalAirTime -- seconds off the ground that are no jump (no landing to play)
    Tune.steerKeep = Config.SteerDamping       -- how much of the turning the board keeps every 1/30 s (0 = none: instant)
    Tune.coffinDrag = Config.CoffinDrag        -- m/s the board loses every second while the rider lies on it
    Tune.offTurn = nil                         -- off the board: degrees per second by speed (Skate 3's own, when there)
    Tune.alignAir = Config.AirAlign            -- in the air: how much of the way to the landing's ground, every 1/30 s
    Tune.skitch = {}                           -- holding on to the back of a car (see Config.Skitch)
    for k, v in pairs(Config.Skitch) do Tune.skitch[k] = v end
end

-- Use Skate 3's numbers (the table skate3_assets exports). Returns false, leaving config.lua's, when it has none.
function Tune.apply(t)
    Tune.reset()
    if type(t) ~= 'table' or not Config.UseSkate3Tuning then return false end
    local m = t.modes and (t.modes[Config.Mode] or t.modes.normal)
    if not (m and t.push and t.jump and t.friction and t.steering and t.bodyspin and t.grind and t.wipeout) then return false end
    s3, mode = t, m
    Tune.skate3 = true
    Tune.gravity = t.gravity or Tune.gravity
    Tune.pushMax = t.push.maxSpeed
    if t.friction.surface then Tune.maxSpeed = t.friction.surface.x[#t.friction.surface.x] end -- where its speeds end
    Tune.hardLanding = t.wipeout.airMaxSpeedIntoGround
    Tune.landTolerance = math.deg(t.wipeout.groundMaxAngularDeckError)
    Tune.grindStraight = t.grind.angleRange5050
    Tune.slideRange = t.grind.angleRangeBoardSlide
    Tune.tipSlideRange = t.grind.angleRangeTipSlide or Tune.slideRange
    Tune.grindLockDist = Config.GrindLock and m.grindLockDist or 0.0
    Tune.truck = t.grind.deckCenterToTruck
    if m.maxAutoBodySpinSpeed then Tune.autoSpin = math.deg(m.maxAutoBodySpinSpeed) end
    if t.slope and t.slope.maxGravityAcceleration then Tune.slopeAcc = t.slope.maxGravityAcceleration end
    if t.slope and t.slope.coffinAcceleration then Tune.coffinDrag = math.abs(t.slope.coffinAcceleration) end
    if t.air then
        Tune.naturalDrop = t.air.naturalAirMaxDist or Tune.naturalDrop
        Tune.naturalAirTime = t.air.naturalAirTime or Tune.naturalAirTime
    end
    if t.steering.damping then Tune.steerKeep = t.steering.damping end
    if type(t.transition) == 'table' and type(t.transition.alignToGround) == 'number' then
        Tune.alignAir = clamp(t.transition.alignToGround, 0.01, 1.0)
    end
    if type(t.offboard) == 'table' and type(t.offboard.turnVsSpeed) == 'table' then Tune.offTurn = t.offboard.turnVsSpeed end
    if type(t.skitch) == 'table' then
        for k, v in pairs(t.skitch) do
            if type(v) == 'number' and type(Tune.skitch[k]) == 'number' then Tune.skitch[k] = v end
        end
    end
    if t.scoring then
        Tune.manualMinSpeed = t.scoring.manualMinSpeed
        Tune.lineSeconds = t.scoring.lineSeconds
    end
    return true
end

-- Speed one push adds, rolling at `speed`.
function Tune.pushGain(speed)
    if not s3 then return Config.PushImpulse end
    local dv = mode.pushDVStart + (mode.pushDVEnd - mode.pushDVStart) * clamp(math.abs(speed) / Tune.pushMax, 0.0, 1.0)
    return dv * Config.S3PushScale
end

-- How fast the board slows down by itself (m/s per second). noInput = seconds since the controls were last
-- touched; inManual = balancing on two wheels; ground = the kind of ground under the wheels ('smooth', 'rough',
-- 'slippery', 'slow', 'veryslow': Skate 3's physics_surfaces).
function Tune.friction(speed, noInput, inManual, ground)
    if not s3 then return Config.Friction * (Config.GroundDrag[ground or 'smooth'] or 1.0) end
    local v, f = math.abs(speed), s3.friction
    local graph = (f.surfaces and f.surfaces[ground or 'smooth']) or f.surface
    local a = graph and Tune.graph(graph, v) or 0.0
    if inManual and f.manual then
        a = a + Tune.graph(f.manual, v)
    elseif (noInput or 0.0) >= (f.noInputTime or 0.0) then
        a = a + Tune.graph(f.noInput, v)
    end
    return a
end

-- Banks and ramps. `steep` = the sine of the slope of the face the board is on, `nz` = how upright that face's
-- normal is (1 = level ground, 0 = a wall).
-- How much of gravity's pull across the board turns it down the hill: nothing on ground that is all but level.
function Tune.carve(steep)
    local t = s3 and s3.transition
    if t and t.carveVsSlope then return Tune.graph(t.carveVsSlope, steep) end
    return clamp((steep - Config.CarveFrom) / (Config.CarveFull - Config.CarveFrom), 0.0, 1.0)
end

-- A pop is straight up. How much more of it there is off a steep face.
function Tune.popSteep(nz)
    local t = s3 and s3.transition
    if t and t.jumpVsNormal then return Tune.graph(t.jumpVsNormal, clamp(nz, 0.0, 1.0)) end
    return 1.0
end

-- What a landing on a face that steep makes of the board's speed (the curve of a ramp gives a little).
function Tune.landBoost(nz)
    local t = s3 and s3.transition
    if t and t.landingVsNormal then return Tune.graph(t.landingVsNormal, clamp(nz, 0.0, 1.0)) end
    return 1.0
end

-- A foot plant off the ground (boneless, fastplant, no comply): the speed the jump leaves the ground with, and what
-- is left of the rolling speed.
function Tune.plantJump()
    local b = s3 and s3.boneless
    if b then return Tune.graph(b.jumpSpeedVsNormal, 1.0) end
    return Config.OllieSpeed * 0.8
end

function Tune.plantKeep(speed)
    local b = s3 and s3.boneless
    if b then return Tune.graph(b.planarVsSpeed, math.abs(speed)) end
    return 0.85
end

-- The hippy jump: how high the rider goes, metres, for a crouch of strength 0 .. 1.
function Tune.hippyRise(strength)
    local h = s3 and s3.hippy
    if h then return h.minHeight + (h.maxHeight - h.minHeight) * clamp(strength, 0.0, 1.0) - h.floor end
    return 0.4 + 0.3 * clamp(strength, 0.0, 1.0)
end

-- A revert: how fast the board turns, degrees per second, when it is `deg` degrees round.
function Tune.revertRate(deg)
    local r = s3 and s3.revert
    if r then return math.deg(Tune.graph(r.rotSpeedVsAngle, math.rad(deg))) end
    return 300.0
end

-- How much harder (or softer) the brake bites on that kind of ground.
function Tune.brakeScale(ground)
    local b = s3 and s3.friction.braking
    return b and b[ground or 'smooth'] or 1.0
end

-- Turn rate in degrees per second for a stick deflection (-1 left .. 1 right; positive = turning right).
function Tune.turnRate(steer, speed)
    local v = math.abs(speed)
    if not s3 then return steer * Config.TurnRate / (1.0 + v * Config.TurnSpeedFalloff) end
    local st = s3.steering
    local input = Tune.graph(st.vsInput, math.abs(steer)) / Tune.graph(st.vsInput, 1.0)
    local rate = Config.TurnRate * input * Tune.graph(st.vsSpeed, v / st.vsSpeedMaxSpeed)
    return steer < 0 and -rate or rate
end

-- Body spin in the air, degrees per second, `airTime` seconds after takeoff.
function Tune.spinRate(steer, airTime)
    if not s3 then return steer * Config.SpinSpeed end
    local rate = math.min(s3.bodyspin.maxSpinSpeed, math.deg(Tune.graph(s3.bodyspin.vsTime, airTime)))
    return steer * rate
end

-- How far a pop of `strength` (0 weakest .. 1 strongest) lifts the rider, metres, at ground speed `speed`.
function Tune.popRise(strength, speed)
    strength = clamp(strength, 0.0, 1.0)
    if not s3 then return Config.PopMin + (Config.PopMax - Config.PopMin) * strength end
    local j = s3.jump
    local x = clamp(math.abs(speed) / j.speedResponseMaxSpeed, 0.0, 1.0)
    local hi = math.max(j.absoluteMinHeight, mode.jumpMaxHeight * Tune.graph(j.maxHeightVsSpeed, x))
    local lo = math.min(hi, math.max(j.absoluteMinHeight, mode.jumpMinHeight * Tune.graph(j.minHeightVsSpeed, x)))
    -- never less than the trick clips need to finish before the board is back on the ground
    return math.max(Config.PopFloor, lo + (hi - lo) * strength - j.absoluteMinHeight)
end

-- Upward speed that reaches that rise.
function Tune.popSpeed(strength, speed)
    return math.sqrt(2.0 * Tune.gravity * Tune.popRise(strength, speed))
end

-- How fast a grind slows down (m/s per second), `t` seconds in.
function Tune.grindFriction(t, slide)
    if not s3 then return Config.GrindFriction * (slide and Config.SlideFrictionScale or 1.0) end
    return s3.grind.frictionCoefficient * Tune.gravity * Tune.graph(s3.grind.frictionVsTime, t)
end

-- ------------------------------------------------------------------ camera

-- The follow camera for a situation, or nil to use the simple camera from config.lua. Skate 3 has a "shot" for each
-- situation: a distance, a compass heading round the rider (180 = straight behind), an elevation angle, the point
-- it circles (so far above the board, or the rider's middle) and how the view is turned away from that point.
--   situation: 'ground' | 'manual' | 'air' | 'grind';  speed m/s;  big = a big air
-- Returns a table of numbers: distance, side (degrees round from straight behind, towards the rider's chest),
-- elevation, boardOffset, weightBoard, weightCOM, yaw, pitch, lens, smoothYaw, smoothDirection, transition.
function Tune.shot(situation, speed, big)
    local shots = s3 and Config.UseSkate3Camera and s3.camera and s3.camera.shots
    if not shots then return nil end
    local function side(s)
        local out = {}
        for k, v in pairs(s) do out[k] = v end
        -- negative headings are on the side the camera is mirrored to for the rider's stance: the chest side
        out.side = (s.heading < 0 and 1.0 or -1.0) * (180.0 - math.abs(s.heading))
        out.heading = nil
        return out
    end
    local function mix(a, b, w)
        if not (a and b) then return (a or b) and side(a or b) or nil end
        a, b = side(a), side(b)
        for k, v in pairs(a) do a[k] = v + ((b[k] or v) - v) * w end
        return a
    end
    local fast = clamp((math.abs(speed) - Config.CamSlowSpeed) / (Config.CamFastSpeed - Config.CamSlowSpeed), 0.0, 1.0)
    if situation == 'skitch' and shots.skitching then
        return mix(shots.skitching, nil, 0.0)
    elseif situation == 'air' then
        return mix(big and shots.air_big or shots.air_small, nil, 0.0)
    elseif situation == 'grind' then
        return mix(shots.grind_flat_slow, shots.grind_flat_fast, fast)
    elseif situation == 'manual' then
        return mix(shots.close_manual, shots.far_manual, fast)
    end
    return mix(shots.chase_flat_slow, shots.chase_flat_fast, fast)
end

-- Field of view (vertical, degrees) of a lens length in millimetres on a 35 mm frame cropped to 16:9.
function Tune.fov(lens)
    return math.deg(2.0 * math.atan(10.125 / lens))
end

-- Seconds for a "smoothing" value (taken as what is kept of the old value each 30 Hz tick) to close most of a gap.
function Tune.smoothTime(s)
    if not s or s <= 0.0 then return 0.0 end
    if s >= 0.999 then return 30.0 end
    return -1.0 / (30.0 * math.log(s))
end

-- ------------------------------------------------------------------ points

-- our trick keys -> the names in Skate 3's scoring table
local SCORE_NAME = {
    Ollie = 'ollie', Nollie = 'nollie', Kickflip = 'kickflip', Heelflip = 'heelflip', PopShuvit = 'popshuvit',
    FSPopShuvit = 'fspopshuvit', VarialKickflip = 'varialkickflip', VarialHeelflip = 'varialheelflip',
    Hardflip = 'hardflip', InwardHeelflip = 'inwardheelflip', ['360PopShuvit'] = '360popshuvit',
    FS360PopShuvit = 'fs360popshuvit', ['360Flip'] = '360flip', Laserflip = 'laserflip',
    ['360Hardflip'] = '360hardflip', ['360InwardHeelflip'] = '360inwardheelflip',
    N_Kickflip = 'n_kickflip', N_Heelflip = 'n_heelflip', N_PopShuvit = 'n_popshuvit',
    N_FSPopShuvit = 'n_fspopshuvit', N_VarialKickflip = 'n_varialkickflip', N_VarialHeelflip = 'n_varialheelflip',
    N_Hardflip = 'n_hardflip', N_InwardHeelflip = 'n_inwardheelflip', N_360PopShuvit = 'n_360popshuvit',
    N_FS360PopShuvit = 'n_fs360popshuvit', N_360Flip = 'n_360flip', N_Laserflip = 'n_laserflip',
    N_360Hardflip = 'n_360hardflip', N_360InwardHeelflip = 'n_360inwardheelflip',
    L_F_Kickflip = 'latekickflip', L_F_Heelflip = 'lateheelflip', L_B_Kickflip = 'latebackfootkickflip',
    L_B_Heelflip = 'latebackfootheelflip', L_FS_Shuvit = 'latefsshuv', L_BS_Shuvit = 'latebsshuv',
    grab_fs = 'fsgrab', grab_bs = 'bsgrab', grab_dbl = 'dblgrab', grab_tail = 'tailgrab', grab_nose = 'nosegrab',
    grab_crail = 'crailgrab', grab_seatbelt = 'seatbeltgrab',
    ['50-50'] = 'fs_50_50', ['5-0'] = 'bs_5_o', Nosegrind = 'bs_nosegrind', Crooked = 'fs_crook', Smith = 'fs_smith',
    Feeble = 'fs_feeble', Boardslide = 'fs_board', Lipslide = 'fs_lip', Noseslide = 'fs_noseslide',
    Tailslide = 'fs_tailslide', manual_tail = 'tailmanual', manual_nose = 'nosemanual',
}
-- our trick keys -> the group they fall back on in Config.TrickScores
local GENERIC = {
    ['50-50'] = 'grind', ['5-0'] = 'grind', Nosegrind = 'grind', Crooked = 'grind', Smith = 'grind', Feeble = 'grind',
    Boardslide = 'grind', Lipslide = 'grind', Noseslide = 'grind', Tailslide = 'grind',
}

-- The name a trick has in Skate 3's scoring table ('Kickflip' -> 'kickflip'): its variants are built on it
-- ('kickflip2_underflip').
function Tune.scoreName(key) return SCORE_NAME[key] or key end

-- Skate 3's points tables while they are in use.
function Tune.scoring() return s3 and s3.scoring or nil end

-- Base points of a trick (our key: a trick, 'grab_<kind>', a grind name, 'manual_tail' / 'manual_nose', 'spin').
function Tune.baseScore(key)
    local sc = Tune.scoring()
    if sc then
        return sc.base[SCORE_NAME[key] or key] or 0 -- (newer keys are the table's own names)
    end
    local scores = Config.TrickScores
    if scores[key] then return scores[key] end
    local group = GENERIC[key] or (key:sub(1, 2) == 'L_' and 'late') or key:match('^(%a+)_')
    if group == 'manual' or key == 'spin' then return 0 end -- these score by time and by turn alone
    return scores[group or 'default'] or scores.default
end

-- Points for holding a grab `t` seconds, grinding `dist` metres, holding a manual `dist` metres, spinning `deg`.
function Tune.grabScore(t)
    local sc = Tune.scoring()
    if sc then return Tune.graph(sc.airGrabTime, t) end
    return math.floor(t * Config.TrickScores.grabPerSecond)
end

function Tune.grindScore(t, dist)
    local sc = Tune.scoring()
    if sc then return Tune.graph(sc.grindLength, dist) end
    return math.floor(t * Config.TrickScores.grindPerSecond)
end

function Tune.manualScore(t, dist)
    local sc = Tune.scoring()
    if sc then return Tune.graph(sc.manualDist, dist) end
    return math.floor(t * Config.TrickScores.manualPerSecond)
end

function Tune.spinScore(deg)
    local sc = Tune.scoring()
    if sc then return Tune.graph(sc.airPlayerSpin, math.abs(deg)) end
    return math.floor(math.abs(deg) / 180.0 + 0.5) * Config.TrickScores.spin180
end

-- What a trick is worth the n-th time it comes up in one line (n = 0 the first time).
function Tune.repeatScale(n)
    local sc = Tune.scoring()
    if sc then return Tune.graph(sc.duplicatePenalty, n) end
    return 1.0
end

-- Bonus for how a jump started or ended: 'fromFakie', 'fromManual', 'fromGrind', 'fromStationary', 'toGrind',
-- 'toSketchy'.
function Tune.bonus(name)
    local sc = Tune.scoring()
    return sc and sc[name] or 1.0
end

-- A jump from slower than this counts as from a standstill.
function Tune.stationarySpeed()
    local sc = Tune.scoring()
    return sc and sc.stationarySpeed or 0.0
end

-- The line's multiplier follows the points behind it ("momentum"): they build with each trick, up to a cap, and
-- run down while just rolling.
function Tune.multiplier(momentum)
    local sc = Tune.scoring()
    local m = 1.0
    if sc then
        for _, step in ipairs(sc.momentum) do
            if momentum >= step[1] then m = step[2] end
        end
    end
    return m
end

function Tune.momentumCap()
    local sc = Tune.scoring()
    return sc and sc.momentumMaxPoints or math.huge
end

function Tune.momentumDrain()
    local sc = Tune.scoring()
    return sc and sc.momentumPointsPerSecond or 0.0
end

Tune.reset()
