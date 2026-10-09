-- Skate 3 clip player: plays converted clips on a ped ("rider") and keeps the ped and a board prop together.
--
-- How Skate 3 poses the skater: the board is a physics object and the feet stay on it. The clips move the BODY
-- relative to the feet (a crouch lowers the root, a lean shifts it sideways, a tuck pulls the feet up), and
-- only say how the board is ROTATED. So for every frame the converter bakes two things per clip ("track"):
-- the board rotation and the point under the feet where the deck has to be ("anchor"), both relative to the ped.
--   on the ground: the anchor is put on the ground contact point, so the body moves and the feet stay planted
--   in the air:    the ped root flies and the board follows the feet
-- The clips only rotate bones, so leg lengths come from the ped playing them. The anchors were baked on
-- player_one; a freemode ped (a female one even more) puts its feet a few cm elsewhere. While riding, the real
-- foot bones are measured with the converter's formula and the difference is taken up slowly ("trim").
--
-- Exports
--   StartRide(ped, board) -> id      board: an existing prop, true to spawn one, false/nil for none
--   StopRide(id, keepBoard)
--   Play(id, clip, opts) -> bool     opts: loop, blend (seconds), scrub (bool), phase (0..1), rate
--   SetPhase(id, phase)              move a scrub clip (pose-space clips such as r_lean_hcom)
--   PlayUpper(id, clip, loop) / StopUpper(id)   arm gestures layered over whatever the body is doing
--                                    (a clip that doesn't loop holds its last frame until the next one)
--   Drive(id, x, y, z, heading, pitch, grounded, contactS, contactH, low, hop, carry, ux, uy, uz) -> lift
--         (ux, uy, uz: the way up for the rider and the board, when that is not straight up: the face of a bank or
--          of a ramp's curve. heading and pitch are then as they would be with that face laid flat.)
--        x, y, z = ground contact point (in the air: the flight path of that point); lift = how far the feet
--        are tucked above it, so the caller lands when z + lift reaches the ground
--        contactS, contactH (grinds): the contact point is not under the middle of the deck but contactS metres
--        towards the nose, and the deck top is contactH above it (a truck on a rail, the nose on a ledge)
--        low (in the air): the rider left the ground crouched on the board or lying on it and stays that low
--        hop (metres): the rider has jumped off the board, which rolls on along the ground (the hippy jump): the
--        rider's flight path is that far above it; lift = how far the feet are above the deck
--   HasClip(clip), ClipDict(clip), ClipLength(clip) -> seconds
--   MatchFrame(source, target) -> seconds into `source` where its board lies as at the start of `target`
--   FlickPatterns() -> Skate 3's Flick-It gesture patterns ({ ground = {...}, air = {...} })
--   Ready() -> true once every clip dictionary is loaded
--
-- The ped is frozen and moved every frame with SetEntityCoordsNoOffset(..., keepTasks = true, keepIK = true,
-- doWarp = false). keepTasks MUST be true: with false the game clears the ped's tasks on every call, which stops
-- the clip 60 times a second (the rider then just stands there). /s3check tests exactly this in game.

local Board = {
    models = { 'v_res_skateboard' }, -- in the base game; used when StartRide is asked to spawn a board
    -- extra model-space correction on top of the automatic one (degrees x, y, z; metres)
    fixRot = vector3(0.0, 0.0, 0.0),
    fixPos = vector3(0.0, 0.0, 0.0),
    autoTrim = true, -- follow the real foot bones (see the top of this file); /s3trim toggles it
}
local DECK_HEIGHT = 0.09     -- deck top above the ground, used when the model's size can't be read
local KICK_RISE = 0.03       -- how far the nose/tail tips rise above the flat of the deck
local HALF_WHEELBASE = 0.26  -- deck centre to each truck (from the Skate 3 skeleton)
local FOOT = { R = { 52301, 20781 }, L = { 14201, 2108 } } -- ankle, toe bone tags
-- the converter's sole offsets: how far the toe / ankle bones sit above the sole of a flat foot
local TOE_ABOVE_SOLE, ANKLE_ABOVE_SOLE = 0.042, 0.0925
local TRIM_TIME = 0.4        -- seconds to take up most of a difference between the baked and the real feet
local TRIM_MAX = 0.20        -- metres; a bigger difference is a pose that isn't showing yet, not a skeleton
local REPLAY_AFTER = 0.2     -- seconds a clip may be "not playing" before it is started again (a new task needs
                             -- a frame or two to show up; anything longer means the game dropped it)
-- clips where one foot leaves the board: their anchor follows that foot only (same list as the converter)
local ONE_FOOT = { '^r_push', '^r_crpush', '^r_brake', '^r_stand_idle', '^r_stand_from', '^mongo_push', '^pro_.*_push_' }
local debugOn = false

-- ------------------------------------------------------------------ maths (quaternions are {x, y, z, w})

local function qmul(a, b)
    return {
        a[4] * b[1] + a[1] * b[4] + a[2] * b[3] - a[3] * b[2],
        a[4] * b[2] - a[1] * b[3] + a[2] * b[4] + a[3] * b[1],
        a[4] * b[3] + a[1] * b[2] - a[2] * b[1] + a[3] * b[4],
        a[4] * b[4] - a[1] * b[1] - a[2] * b[2] - a[3] * b[3],
    }
end

local function qconj(q) return { -q[1], -q[2], -q[3], q[4] } end

local function qrot(q, v) -- rotate vector3 v by quaternion q
    local x, y, z, w = q[1], q[2], q[3], q[4]
    local tx = 2 * (y * v.z - z * v.y)
    local ty = 2 * (z * v.x - x * v.z)
    local tz = 2 * (x * v.y - y * v.x)
    return vector3(v.x + w * tx + (y * tz - z * ty), v.y + w * ty + (z * tx - x * tz), v.z + w * tz + (x * ty - y * tx))
end

local function qnlerp(a, b, t)
    local s = (a[1] * b[1] + a[2] * b[2] + a[3] * b[3] + a[4] * b[4]) < 0 and -1 or 1
    local q = {}
    for i = 1, 4 do q[i] = a[i] + (b[i] * s - a[i]) * t end
    local l = math.sqrt(q[1] ^ 2 + q[2] ^ 2 + q[3] ^ 2 + q[4] ^ 2)
    for i = 1, 4 do q[i] = q[i] / l end
    return q
end

local function qaxis(x, y, z, deg)
    local h = math.rad(deg) * 0.5
    return { x * math.sin(h), y * math.sin(h), z * math.sin(h), math.cos(h) }
end

local function qeuler(r) -- degrees, applied x then y then z
    return qmul(qaxis(0, 0, 1, r.z), qmul(qaxis(0, 1, 0, r.y), qaxis(1, 0, 0, r.x)))
end

-- entity rotation from heading and pitch (nose up positive), the same as SetEntityRotation(pitch, 0, heading, 2)
local function qheading(heading, pitch)
    return qmul(qaxis(0, 0, 1, heading), qaxis(1, 0, 0, pitch))
end

-- the shortest turn that takes straight up to the unit vector u
local function qarc(u)
    local x, y, w = -u.y, u.x, 1.0 + u.z
    local l = math.sqrt(x * x + y * y + w * w)
    if l < 1e-6 then return { 1.0, 0.0, 0.0, 0.0 } end -- (upside down)
    return { x / l, y / l, 0.0, w / l }
end

local UP = vector3(0.0, 0.0, 1.0)
local function vdot(a, b) return a.x * b.x + a.y * b.y + a.z * b.z end

local function vlerp(a, b, t) return a + (b - a) * t end
local function clamp(x, lo, hi) return math.max(lo, math.min(hi, x)) end

-- The angles (degrees: x, y, z) the game's natives want for a rotation, in their usual order (2: the turn about y is
-- made first, then the one about x, then the one about z; SetEntityRotation(pitch, roll, heading, 2) is the same).
local function qangles(q)
    local x, y, z, w = q[1], q[2], q[3], q[4]
    local rx = math.asin(clamp(2.0 * (y * z + w * x), -1.0, 1.0))
    local ry = math.atan(-2.0 * (x * z - w * y), 1.0 - 2.0 * (x * x + y * y))
    local rz = math.atan(-2.0 * (x * y - w * z), 1.0 - 2.0 * (x * x + z * z))
    return math.deg(rx), math.deg(ry), math.deg(rz)
end

-- ------------------------------------------------------------------ clips

function ClipDict(clip) return Skate3ClipDict[clip:lower()] end
function HasClip(clip) return ClipDict(clip) ~= nil end

local function trackOf(clip)
    local dict = ClipDict(clip)
    return dict and SkateBoardTracks[dict .. '/' .. clip:lower()], dict
end

function ClipLength(clip)
    local track = trackOf(clip)
    if not track then return 0.0 end
    return math.max(#track.frames - 1, 1) / track.fps
end

-- Where in clip `source` the board lies as it does in the first frame of clip `target`: seconds from the start of
-- `source` (nil without both tracks). Skate 3 leaves a flip for its underflip or its dark catch at a frame tagged
-- in the clip; the tags are not in the data that can be read, but the clip the game goes to was made to carry on
-- from exactly that frame, so the frame can be found.
local matched = {}
function MatchFrame(source, target)
    local k = source .. '>' .. target
    if matched[k] == nil then
        local a, b = trackOf(source), trackOf(target)
        local best, at = nil, false
        if a and b and b.frames[1] then
            local w = b.frames[1]
            for i, f in ipairs(a.frames) do
                local dot = math.abs(f[1] * w[1] + f[2] * w[2] + f[3] * w[3] + f[4] * w[4])
                local off = math.deg(2.0 * math.acos(math.min(1.0, dot)))                     -- degrees between the boards
                    + 100.0 * math.sqrt((f[5] - w[5]) ^ 2 + (f[6] - w[6]) ^ 2 + (f[7] - w[7]) ^ 2) -- and centimetres
                if not best or off < best then best, at = off, (i - 1) / a.fps end
            end
        end
        matched[k] = at
    end
    return matched[k] or nil
end

-- When in a clip the feet are furthest under the hips (the legs at their longest): seconds from its start.
function DeepestFrame(clip)
    local track = trackOf(clip)
    if not track then return nil end
    local best, at = nil, 0.0
    for i, f in ipairs(track.frames) do
        if not best or f[7] < best then best, at = f[7], (i - 1) / track.fps end
    end
    return at
end

-- Board rotation and feet anchor (both relative to the ped) at a phase (0..1) of a clip.
local function sample(track, phase)
    local frames = track.frames
    local n = #frames
    if phase ~= phase then phase = 0.0 end -- NaN guard: math.floor(NaN) throws
    phase = clamp(phase, 0.0, 1.0)
    local f = phase * (n - 1) + 1
    local i = math.max(1, math.min(math.floor(f), n - 1))
    local a, b = frames[i], frames[math.min(i + 1, n)]
    local t = f - i
    local q = qnlerp({ a[1], a[2], a[3], a[4] }, { b[1], b[2], b[3], b[4] }, t)
    local anchor = vector3(a[5] + (b[5] - a[5]) * t, a[6] + (b[6] - a[6]) * t, a[7] + (b[7] - a[7]) * t)
    -- an off-board clip (the rider walks, the board is in the hand): its anchor is the ground under the rider, and it
    -- also has where the deck is and how far the rider has gone forward since the clip began
    if a[11] and b[11] then
        return q, anchor, vector3(a[8] + (b[8] - a[8]) * t, a[9] + (b[9] - a[9]) * t, a[10] + (b[10] - a[10]) * t),
            a[11] + (b[11] - a[11]) * t
    end
    return q, anchor
end

local idle = SkateBoardTracks['skate3@r/r_idle_hcom_000']
-- the riding pose: board level, feet this far under the ped origin
local REST_Q, REST_A = { 0.0, 0.0, 0.0, 1.0 }, vector3(0.0, 0.0, -1.12)
if idle then REST_Q, REST_A = sample(idle, 0.0) end
local ROOT_AIR = -REST_A.z -- ped origin above the deck while flying

local function dictReady(dict, wait)
    if HasAnimDictLoaded(dict) then return true end
    if not DoesAnimDictExist(dict) then return false end
    RequestAnimDict(dict)
    if not wait then return false end
    local deadline = GetGameTimer() + 5000
    while not HasAnimDictLoaded(dict) and GetGameTimer() < deadline do Wait(0) end
    return HasAnimDictLoaded(dict)
end

-- Keep every dictionary loaded, so Play never has to wait for one in the middle of a ride.
local allDicts = {}
do
    local seen = {}
    for _, dict in pairs(Skate3ClipDict) do
        if not seen[dict] then
            seen[dict] = true
            allDicts[#allDicts + 1] = dict
        end
    end
    table.sort(allDicts)
end
CreateThread(function()
    for _, dict in ipairs(allDicts) do dictReady(dict, true) end
end)

-- True once every dictionary is in memory (asks again for any that is not). A ride that starts before that would
-- silently skip clips.
function Ready()
    local ready = true
    for _, dict in ipairs(allDicts) do
        if not HasAnimDictLoaded(dict) then
            RequestAnimDict(dict)
            ready = false
        end
    end
    return ready
end

-- ------------------------------------------------------------------ board prop

local geomCache = {}
-- Skate 3's own board models (decks.lua, when the asset build has them): their tips rise by Skate 3's own amount,
-- not by the GTA prop's.
local S3_BOARD = {}
if Skate3Decks then
    for _, d in ipairs(Skate3Decks.stock or {}) do S3_BOARD[joaat(d.model)] = true end
    for _, m in ipairs(Skate3Decks.custom and Skate3Decks.custom.slots or {}) do S3_BOARD[joaat(m)] = true end
end
local NO_BOARD = { yaw = 0.0, centre = vector3(0.0, 0.0, 0.0), deckHeight = DECK_HEIGHT }

-- How the prop is built: which way it is long, where its deck top is, how high the deck rides.
local function boardGeom(model)
    if geomCache[model] then return geomCache[model] end
    local mn, mx = GetModelDimensions(model)
    local g = { yaw = 0.0, centre = vector3(0.0, 0.0, 0.0), deckHeight = DECK_HEIGHT }
    local sx, sy, sz = mx.x - mn.x, mx.y - mn.y, mx.z - mn.z
    if sx > 0.05 and sy > 0.05 and sz > 0.01 then
        if sx > sy then g.yaw = 90.0 end -- the tracks expect the long axis on y
        local top = mx.z - (S3_BOARD[model] and Skate3Decks.kick or KICK_RISE)
        g.centre = vector3((mn.x + mx.x) * 0.5, (mn.y + mx.y) * 0.5, top)
        g.deckHeight = clamp(top - mn.z, 0.05, 0.18)
    end
    geomCache[model] = g
    return g
end

local function spawnBoard(ped)
    for _, name in ipairs(Board.models) do
        local h = joaat(name)
        if IsModelInCdimage(h) then
            RequestModel(h)
            local deadline = GetGameTimer() + 3000
            while not HasModelLoaded(h) and GetGameTimer() < deadline do Wait(0) end
            if HasModelLoaded(h) then
                local p = GetEntityCoords(ped)
                local board = CreateObject(h, p.x, p.y, p.z - 0.9, true, true, false)
                SetModelAsNoLongerNeeded(h)
                return board, name
            end
        end
    end
end

-- ------------------------------------------------------------------ riders

local riders, nextId = {}, 1
local trimCache = {} -- ped model -> trim, so the next ride on the same ped starts already corrected

local function setLegIk(ped, on)
    SetPedCanLegIk(ped, on)
    SetPedLegIkMode(ped, on and 2 or 0)
end

function StartRide(ped, board)
    local own, modelName = false, nil
    if board == true then
        board, modelName = spawnBoard(ped)
        own = board ~= nil
    end
    if not board or not DoesEntityExist(board) then board = nil end
    local p = GetEntityCoords(ped)
    local ok, gz = GetGroundZFor_3dCoord(p.x, p.y, p.z + 1.0, false)
    local r = {
        ped = ped, board = board, own = own, model = modelName,
        geom = board and boardGeom(GetEntityModel(board)) or NO_BOARD,
        x = p.x, y = p.y, z = ok and gz or (p.z - 1.0), heading = GetEntityHeading(ped), pitch = 0.0,
        grounded = true, driven = false, rootH = ROOT_AIR, lift = 0.0,
        fromQ = REST_Q, fromA = REST_A, blendT = 1.0, blendDur = 0.0,
        pedModel = GetEntityModel(ped), trimFrames = 0, replays = 0,
    }
    r.trim = trimCache[r.pedModel] or vector3(0.0, 0.0, 0.0)
    if board then
        DetachEntity(board, true, false)
        SetEntityCollision(board, false, false)
        FreezeEntityPosition(board, true) -- we place it every frame; physics must not move it
    end
    setLegIk(ped, false) -- GTA's foot planting would drag the feet off the board
    local id = nextId
    nextId = nextId + 1
    riders[id] = r
    return id
end

function StopRide(id, keepBoard)
    local r = riders[id]
    if not r then return end
    riders[id] = nil
    if r.trimFrames > 30 then trimCache[r.pedModel] = r.trim end
    if DoesEntityExist(r.ped) then
        if r.cur then StopAnimTask(r.ped, r.cur.dict, r.cur.clip, -4.0) end
        if r.upper then StopAnimTask(r.ped, r.upper.dict, r.upper.clip, -4.0) end
        setLegIk(r.ped, true)
    end
    if r.board and DoesEntityExist(r.board) then
        if r.held then DetachEntity(r.board, false, false) end
        if r.own and not keepBoard then
            SetEntityAsMissionEntity(r.board, true, true)
            DeleteObject(r.board)
        else
            FreezeEntityPosition(r.board, false)
        end
    end
end

-- Where a clip should be by our own clock (0..1).
local function clockPhase(c)
    if c.scrub then return c.phase end
    if c.loop then return (c.t / c.len) % 1.0 end
    return math.min(1.0, c.t / c.len)
end

-- The phase the body is showing. The game's own playback time comes first, so the board stays with the body
-- even if a scrub (SetEntityAnimCurrentTime) didn't take.
local function phaseOf(r)
    local c = r.cur
    if IsEntityPlayingAnim(r.ped, c.dict, c.clip, 3) then
        local p = GetEntityAnimCurrentTime(r.ped, c.dict, c.clip)
        if p == p then return p end
    end
    return clockPhase(c)
end

-- Board rotation and feet anchor right now, cross-faded from whatever was showing when the clip started.
local function pose(r)
    local q, a, b = REST_Q, REST_A, nil
    if r.cur and r.cur.track then q, a, b = sample(r.cur.track, phaseOf(r)) end
    if r.blendDur > 0.0 and r.blendT < r.blendDur then
        local w = r.blendT / r.blendDur
        w = w * w * (3.0 - 2.0 * w)
        q, a = qnlerp(r.fromQ, q, w), vlerp(r.fromA, a, w)
        if b and r.fromB then b = vlerp(r.fromB, b, w) end
    end
    return q, a, b
end

function Play(id, clip, opts, wait)
    local r = riders[id]
    if not r then return false end
    opts = opts or {}
    clip = clip:lower()
    local track, dict = trackOf(clip)
    if not dict or not dictReady(dict, wait) then return false end
    r.fromQ, r.fromA, r.fromB = pose(r)
    r.blendT, r.blendDur = 0.0, opts.blend or 0.15
    r.before = r.cur and r.cur.track or nil
    local flags = (opts.loop and not opts.scrub) and 1 or 2 -- 2 = hold the last frame
    local speed = r.blendDur > 0.0 and math.min(1.0 / r.blendDur, 1000.0) or 1000.0
    TaskPlayAnim(r.ped, dict, clip, speed, -speed, -1, flags, 0.0, false, false, false)
    r.cur = { dict = dict, clip = clip, track = track, len = math.max(ClipLength(clip), 0.01), loop = opts.loop,
              scrub = opts.scrub, phase = opts.phase or 0.5, rate = opts.rate, t = 0.0, applied = false,
              flags = flags, lost = 0.0 }
    return true
end

function SetPhase(id, phase)
    local r = riders[id]
    if r and r.cur then r.cur.phase = clamp(phase, 0.0, 1.0) end
end

function PlayUpper(id, clip, loop, wait)
    local r = riders[id]
    if not r then return false end
    clip = clip:lower()
    local dict = ClipDict(clip)
    if not dict or not dictReady(dict, wait) then return false end
    -- 16 = upper body only, 32 = on top of the current task; 1 = loop, 2 = hold the last frame
    TaskPlayAnim(r.ped, dict, clip, 4.0, -4.0, -1, 48 + (loop and 1 or 2), 0.0, false, false, false)
    r.upper = { dict = dict, clip = clip }
    return true
end

function StopUpper(id)
    local r = riders[id]
    if r and r.upper then
        StopAnimTask(r.ped, r.upper.dict, r.upper.clip, -4.0)
        r.upper = nil
    end
end

-- Where the deck would have to be according to the ped's real foot bones: the converter's formula (under the
-- ball of each foot, at the sole), averaged over both feet.
local function measuredAnchor(ped)
    local sum = vector3(0.0, 0.0, 0.0)
    for _, tags in pairs(FOOT) do
        local ankle = GetPedBoneCoords(ped, tags[1], 0.0, 0.0, 0.0)
        local toe = GetPedBoneCoords(ped, tags[2], 0.0, 0.0, 0.0)
        sum = sum + vector3(toe.x * 0.7 + ankle.x * 0.3, toe.y * 0.7 + ankle.y * 0.3,
            math.min(toe.z - TOE_ABOVE_SOLE, ankle.z - ANKLE_ABOVE_SOLE))
    end
    return sum * 0.5
end

local function oneFoot(clip)
    for _, p in ipairs(ONE_FOOT) do
        if clip:find(p) then return true end
    end
    return false
end

-- How far the real feet are from the baked anchor a (ped space). The bones still show the pose the game worked
-- out for this frame's phase, on the ped where the last frame put it, so this runs before the ped is moved.
local function feetOffset(r, a)
    if not r.pedPos then return nil end
    return qrot(qconj(r.pedQ), measuredAnchor(r.ped) - r.pedPos) - a
end

-- Take up the difference between the baked anchors and this ped's real feet: slowly, and only while a clip with
-- both feet on the board is fully blended in and playing.
local function updateTrim(r, d, dt)
    local c = r.cur
    if not (d and c and c.track and dt > 0.0) or r.blendT < r.blendDur or oneFoot(c.clip) then return end
    if #d > TRIM_MAX + 0.05 or not IsEntityPlayingAnim(r.ped, c.dict, c.clip, 3) then return end
    local t = r.trim + (d - r.trim) * (1.0 - math.exp(-dt / TRIM_TIME))
    local len = #t
    if len > TRIM_MAX then t = t * (TRIM_MAX / len) end
    r.trim, r.trimFrames = t, r.trimFrames + 1
end

-- The board in the hand. Off the board the rider carries it, and Skate 3 keeps it in the hand through every turn,
-- start and stop. A board put where a track says is only in the hand while one clip plays alone: in every blend
-- from one clip to the next the game mixes the two arm poses its own way and the board went its own (seen in the
-- game: the board at the chest with the hand at the hip). So while a clip has the board in the hand (its track
-- says so: hand = true) the board is fixed to the hand bone, the way the game fixes anything a ped holds, and the
-- game keeps it there itself, for every player who sees it.
local HAND = { R = 57005, L = 18905 } -- SKEL_R_Hand (the clips as authored), SKEL_L_Hand (their mirrored copies)
local GRIP_BLEND = 0.2                -- seconds to bring the board from where a dismount leaves it to the grip

-- the board's own place in the hand bone's frame, for the deck's top at p turned by q there
local function gripOffset(r, p, q)
    local mq = qmul(q, qmul(qeuler(Board.fixRot), qaxis(0, 0, 1, r.geom.yaw)))
    return p - qrot(mq, r.geom.centre + Board.fixPos), mq
end

local function hold(r, side, dt)
    local g = SkateBoardGrip[side]
    local first = r.held ~= side
    if first then
        -- (out of a dismount the board is in the hand a little off the grip: grip1 says where)
        local f = r.before and r.before.grip1
        r.held, r.gripFrom, r.gripT = side, f, f and 0.0 or GRIP_BLEND
    elseif r.gripT >= GRIP_BLEND then
        return
    end
    local p, q = vector3(g[1], g[2], g[3]), { g[4], g[5], g[6], g[7] }
    local f = r.gripFrom
    if f and r.gripT < GRIP_BLEND then
        local w = r.gripT / GRIP_BLEND
        p, q = vlerp(vector3(f[1], f[2], f[3]), p, w), qnlerp({ f[4], f[5], f[6], f[7] }, q, w)
    end
    r.gripT = r.gripT + math.max(dt, 0.001)
    local mp, mq = gripOffset(r, p, q)
    local rx, ry, rz = qangles(mq)
    -- (the arguments after the angles are the ones the game's own scripts give for a thing in a ped's hand)
    AttachEntityToEntity(r.board, r.ped, GetPedBoneIndex(r.ped, HAND[side]), mp.x, mp.y, mp.z, rx, ry, rz, true, true,
        false, false, 2, true)
end

-- Out of the hand again (onto the ground for a mount, or the board is let go of). What the tracks go on from is
-- where the board really is, not where the last clip's track would have had it.
local function letGo(r)
    r.held, r.gripFrom, r.gripT = nil, nil, nil
    if not (r.board and DoesEntityExist(r.board)) then return end
    local p = GetEntityCoords(r.board)
    local x, y, z, w = GetEntityQuaternion(r.board)
    DetachEntity(r.board, false, false)
    if r.pedQ and r.pedPos and w then
        local wq = { x, y, z, w }
        local m = qmul(qeuler(Board.fixRot), qaxis(0, 0, 1, r.geom.yaw))
        r.fromQ = qmul(qmul(qconj(r.pedQ), wq), qconj(m))
        r.fromB = qrot(qconj(r.pedQ), p + qrot(wq, r.geom.centre + Board.fixPos) - r.pedPos)
    end
end

-- Put the ped and the board where the current pose says.
local function place(r, dt)
    local t = r.carry and not r.boardFree and r.cur and r.cur.track
    local side = t and t.hand and SkateBoardGrip and (r.cur.clip:sub(-4) == '_mir' and 'L' or 'R') or nil
    if side and not (SkateBoardGrip[side] and r.board and DoesEntityExist(r.board)) then side = nil end
    if r.held and r.held ~= side then letGo(r) end
    local q, a, b = pose(r)
    local carry = r.carry and b ~= nil
    if (Board.autoTrim or debugOn) and not carry then
        r.feetD = feetOffset(r, a)
        if Board.autoTrim then updateTrim(r, r.feetD, dt) end
    end
    if Board.autoTrim and not carry then a = a + r.trim end
    local hq = qheading(r.heading, r.pitch)
    -- U = the way up: straight up, or the face of a bank or a ramp the board is on (or is turned to in the air).
    -- Everything "above" the board below is above it along U.
    local U = (not carry and r.up) or UP
    if U ~= UP then hq = qmul(qarc(U), hq) end
    local P = vector3(r.x, r.y, r.z)
    local ra = qrot(hq, a)
    local deck = r.geom.deckHeight
    local pedPos, deckPoint
    if carry then
        -- off the board: x, y, z is the ground under the rider, and the board is where the clip has it (in the hand,
        -- or on its way down to the ground in a mount)
        pedPos = vector3(r.x, r.y, r.z) - ra
        deckPoint = pedPos + qrot(hq, b)
        r.rootH, r.lift = pedPos.z - r.z - deck, 0.0
    elseif r.hop then
        -- the hippy jump: the rider is in the air above the board, which stays on the ground and rolls on
        r.rootH = r.rootH + (ROOT_AIR - r.rootH) * (1.0 - math.exp(-dt / 0.15))
        if U == UP then
            deckPoint = vector3(r.x, r.y, r.z + deck)
            pedPos = vector3(r.x - ra.x, r.y - ra.y, r.z + deck + r.hop + r.rootH)
            r.lift = math.max(0.0, pedPos.z + ra.z - deckPoint.z) -- (how far the feet are above the deck)
        else
            deckPoint = P + U * deck
            pedPos = P - (ra - U * vdot(ra, U)) + U * (deck + r.hop + r.rootH)
            r.lift = math.max(0.0, vdot(pedPos + ra - deckPoint, U))
        end
        q = REST_Q
    elseif r.grounded and r.contactS then
        -- grinding: x, y, z is where a truck (or the nose / tail) sits on the rail, contactS along the board
        -- towards the nose from the middle of the deck, with the deck top contactH above it
        local bq = qmul(hq, q)
        local nose = qrot(bq, vector3(0.0, -1.0, 0.0)) -- the tracks' +y is the TAIL end of the board
        local up = qrot(bq, vector3(0.0, 0.0, 1.0))
        deckPoint = vector3(r.x, r.y, r.z) - nose * r.contactS + up * (r.contactH or 0.0)
        pedPos = deckPoint - ra
        r.rootH, r.lift = pedPos.z - r.z - deck, 0.0
    elseif r.grounded then
        -- a tilted board (manual, pop) pivots on its low truck, which lifts the middle of the deck
        local tip = HALF_WHEELBASE * math.abs(qrot(q, vector3(0.0, 1.0, 0.0)).z)
        if U == UP then
            deckPoint = vector3(r.x, r.y, r.z + deck + tip)
            pedPos = deckPoint - ra
            r.rootH, r.lift = pedPos.z - r.z - deck, 0.0
        else
            deckPoint = P + U * (deck + tip)
            pedPos = deckPoint - ra
            r.rootH, r.lift = vdot(pedPos - P, U) - deck, 0.0
        end
    else
        -- In the air the hips ride at their standing height above the flight path, so a pose with the legs pulled
        -- up lifts the board. Not for a rider who left the ground crouched down on the board or lying on it
        -- (`low`): nothing has pushed them up, so the hips stay as far above the board as the pose has them and the
        -- board stays where it was against the path.
        local raU = U == UP and ra.z or vdot(ra, U) -- (how far the pose has the deck above the hips)
        local target = ROOT_AIR
        if r.low then target = -raU + (r.lowLift or 0.0) end
        r.rootH = r.rootH + (target - r.rootH) * (1.0 - math.exp(-dt / 0.15))
        if r.low then r.rootH = math.max(r.rootH, -raU) end -- (never the board under the path)
        if U == UP then
            pedPos = vector3(r.x - ra.x, r.y - ra.y, r.z + deck + r.rootH)
            deckPoint = pedPos + ra
            r.lift = math.max(0.0, deckPoint.z - deck - r.z)
        else
            pedPos = P - (ra - U * raU) + U * (deck + r.rootH)
            deckPoint = pedPos + ra
            r.lift = math.max(0.0, vdot(deckPoint - P, U) - deck)
        end
    end
    -- keepTasks = true, keepIK = true, doWarp = false. With keepTasks = false the game drops the ped's tasks on
    -- every call, i.e. the clip stops playing as soon as the ride starts moving the ped.
    SetEntityCoordsNoOffset(r.ped, pedPos.x, pedPos.y, pedPos.z, true, true, false)
    SetEntityQuaternion(r.ped, hq[1], hq[2], hq[3], hq[4])
    r.pedPos, r.pedQ = pedPos, hq

    if side then
        hold(r, side, dt)
    elseif r.board and DoesEntityExist(r.board) and not (carry and r.boardFree) then
        local wq = qmul(qmul(hq, q), qmul(qeuler(Board.fixRot), qaxis(0, 0, 1, r.geom.yaw)))
        local under = deckPoint
        if not r.grounded and not carry then
            -- a flipping board gets some room under the feet instead of cutting through them
            local up = qrot(wq, vector3(0.0, 0.0, 1.0))
            under = deckPoint - U * ((1.0 - clamp(vdot(up, U), -1.0, 1.0)) * 0.06)
        end
        local pos = under - qrot(wq, r.geom.centre + Board.fixPos)
        SetEntityCoordsNoOffset(r.board, pos.x, pos.y, pos.z, false, false, false)
        SetEntityQuaternion(r.board, wq[1], wq[2], wq[3], wq[4])
    end
    r.deckPoint = deckPoint
end

-- How far the clip that is playing has carried the rider forward since this was last asked (metres): the root motion
-- of Skate 3's off-board clips, which the controller moves the rider by. 0 for clips without it.
function Travel(id)
    local r = riders[id]
    local c = r and r.cur
    if not (c and c.track and c.track.frames[1][11]) then return 0.0 end
    local _, _, _, d = sample(c.track, phaseOf(r))
    local moved = d - (c.travelAt or 0.0)
    local total = c.track.frames[#c.track.frames][11]
    if c.loop and moved < -0.5 * total then moved = moved + total end -- (the cycle has come round)
    c.travelAt = d
    return moved
end

-- The phase (0 .. 1) of the clip that is playing.
function Phase(id)
    local r = riders[id]
    return (r and r.cur) and phaseOf(r) or 0.0
end

function Drive(id, x, y, z, heading, pitch, grounded, contactS, contactH, low, hop, carry, ux, uy, uz)
    local r = riders[id]
    if not r then return 0.0 end
    -- carry: off the board (see place). 'free' = and the board is not in the hand: it lies where it fell, leave it be
    r.carry, r.boardFree = carry == true or carry == 'free', carry == 'free'
    -- `low` begins: the board keeps the height above the flight path it has now (none, straight off the ground)
    if low and not r.low then r.lowLift = r.grounded and 0.0 or (r.lift or 0.0) end
    r.low = low == true
    r.x, r.y, r.z, r.heading, r.pitch, r.grounded, r.driven = x, y, z, heading, pitch or 0.0, grounded, true
    -- (all but straight up is straight up: the level ground of every other ride)
    r.up = (uz and uz < 0.999999) and vector3(ux, uy, uz) or nil
    r.contactS, r.contactH = contactS, contactH
    r.hop = hop or nil
    place(r, GetFrameTime())
    return r.lift
end

local function debugText(lines)
    for i, s in ipairs(lines) do
        SetTextFont(4)
        SetTextScale(0.35, 0.35)
        SetTextColour(255, 255, 255, 255)
        SetTextOutline()
        BeginTextCommandDisplayText('STRING')
        AddTextComponentSubstringPlayerName(s)
        EndTextCommandDisplayText(0.01, 0.30 + i * 0.025)
    end
end

local function showDebug(r)
    local c = r.cur
    local t = Board.autoTrim and r.trim or vector3(0.0, 0.0, 0.0)
    local feet = 'feet vs deck: not measured yet'
    if r.feetD then
        local e = r.feetD - t -- where the feet are relative to where the board was put
        feet = ('feet vs deck: %.0f cm sideways, %.0f cm forward, %.0f cm up (should stay near 0)%s'):format(
            e.x * 100.0, e.y * 100.0, e.z * 100.0, (c and oneFoot(c.clip)) and '  [one-foot clip]' or '')
    end
    debugText({
        c and ('clip %s/%s  phase %.2f  playing %s'):format(c.dict, c.clip, phaseOf(r),
            tostring(IsEntityPlayingAnim(r.ped, c.dict, c.clip, 3))) or 'no clip',
        ('board model %s  long axis fix %.0f  deck %.0f cm above ground'):format(tostring(r.model or r.board),
            r.geom.yaw, r.geom.deckHeight * 100.0),
        ('%s  lift %.2f m  ped origin %.2f m above the deck'):format(r.grounded and 'on the ground' or 'in the air',
            r.lift, r.rootH),
        feet,
        ('skeleton correction %s: %.0f / %.0f / %.0f cm'):format(Board.autoTrim and 'on' or 'OFF', t.x * 100.0,
            t.y * 100.0, t.z * 100.0),
        ('clip restarts %d (should stay 0)'):format(r.replays),
    })
end

local reported = {}

local function update(r, dt)
    r.blendT = r.blendT + dt
    local c = r.cur
    if c then
        c.t = c.t + dt * (c.rate or 1.0)
        local playing = IsEntityPlayingAnim(r.ped, c.dict, c.clip, 3)
        if playing then
            c.lost = 0.0
            if c.seek then
                -- restarted below: put it where it should be by now
                SetEntityAnimCurrentTime(r.ped, c.dict, c.clip, clamp(clockPhase(c), 0.0, 0.999))
                c.seek = nil
            end
        else
            c.lost = c.lost + dt
            if c.lost > REPLAY_AFTER then
                -- the game dropped the clip (something cleared the ped's tasks) or never started it: play it
                -- again from where it should be by now. /s3debug shows how often this happens (should stay 0).
                if not HasAnimDictLoaded(c.dict) then RequestAnimDict(c.dict) end
                TaskPlayAnim(r.ped, c.dict, c.clip, 8.0, -8.0, -1, c.flags, clamp(clockPhase(c), 0.0, 0.99), false,
                    false, false)
                c.lost, c.seek, c.applied = 0.0, true, false
                r.replays = r.replays + 1
            end
        end
        if c.scrub and playing then
            SetEntityAnimSpeed(r.ped, c.dict, c.clip, 0.0)
            SetEntityAnimCurrentTime(r.ped, c.dict, c.clip, clamp(c.phase, 0.0, 0.999))
        elseif c.rate and playing and not c.applied then
            SetEntityAnimSpeed(r.ped, c.dict, c.clip, c.rate)
            c.applied = true
        end
        if r.demo and c.scrub then c.phase = 0.5 + 0.5 * math.sin(GetGameTimer() / 700.0) end
    end
    if not r.driven then place(r, dt) end
    if debugOn then showDebug(r) end
end

CreateThread(function()
    while true do
        local busy = false
        local dt = GetFrameTime()
        for id, r in pairs(riders) do
            if not DoesEntityExist(r.ped) then
                riders[id] = nil
            else
                busy = true
                local ok, err = pcall(update, r, dt) -- one bad frame must not stop the board for good
                if not ok and not reported[err] then
                    reported[err] = true
                    print(('^1[skate3_assets] rider update failed: %s^7'):format(err))
                end
            end
        end
        Wait(busy and 0 or 250)
    end
end)

exports('StartRide', StartRide)
exports('StopRide', StopRide)
exports('Play', function(id, clip, opts) return Play(id, clip, opts, false) end)
exports('SetPhase', SetPhase)
exports('PlayUpper', function(id, clip, loop) return PlayUpper(id, clip, loop, false) end)
exports('StopUpper', StopUpper)
exports('Drive', Drive)
exports('Travel', Travel)
exports('Phase', Phase)
exports('HasClip', HasClip)
exports('ClipDict', ClipDict)
exports('ClipLength', ClipLength)
exports('MatchFrame', MatchFrame)
exports('DeepestFrame', DeepestFrame)
exports('FlickPatterns', function() return Skate3FlickPatterns end)
exports('Decks', function() return Skate3Decks end)   -- Skate 3's own decks, trucks and wheels (decks.lua), nil without them
exports('Tuning', function() return Skate3Tuning end) -- Skate 3's own tuning numbers (tuning.lua), nil without them
exports('Sounds', function() return Skate3Sounds end) -- Skate 3's own sounds (sounds.lua + sounds/*.ogg), nil without them
exports('Ready', Ready)
exports('Replays', function(id) return riders[id] and riders[id].replays or 0 end)
-- What /s3debug shows, as numbers: the clip the game is playing and where the ped's real foot bones are against
-- where the board was put. For the self test in `skateboard` (/skatetest).
exports('Probe', function(id)
    local r = riders[id]
    if not r then return nil end
    local c = r.cur
    local t = Board.autoTrim and r.trim or vector3(0.0, 0.0, 0.0)
    local e = r.feetD and (r.feetD - t) or nil
    return {
        clip = c and c.clip or nil, dict = c and c.dict or nil,
        playing = c ~= nil and IsEntityPlayingAnim(r.ped, c.dict, c.clip, 3) or false,
        phase = c and phaseOf(r) or nil, oneFoot = c ~= nil and oneFoot(c.clip) or false,
        feet = e and { e.x, e.y, e.z } or nil, trim = { t.x, t.y, t.z },
        blending = r.blendT < r.blendDur, -- cross-fading from the clip before: the feet are between two poses
        replays = r.replays, lift = r.lift, rootH = r.rootH, grounded = r.grounded == true,
    }
end)
exports('SetBoardFix', function(rot, pos) Board.fixRot = rot or Board.fixRot; Board.fixPos = pos or Board.fixPos end)

AddEventHandler('onResourceStop', function(res)
    if res ~= GetCurrentResourceName() then return end
    local ids = {}
    for id in pairs(riders) do ids[#ids + 1] = id end
    for _, id in ipairs(ids) do StopRide(id, false) end
end)

-- ------------------------------------------------------------------ test commands
-- /s3anim <clip> [once]   play a Skate 3 clip on yourself with a board under your feet
-- /s3anim lean            the riding lean blend, swept left and right
-- /s3anim stop            stop and remove the test board
-- /s3list <text>          list clip names containing text
-- /s3debug                show clip / board / feet info on screen
-- /s3trim                 turn the skeleton correction (following the real foot bones) off and on again
-- /s3boardfix rx ry rz [px py pz]   extra rotation/offset for the board prop if it sits wrong

local test

local function say(msg) TriggerEvent('chat:addMessage', { args = { 'skate3', msg } }) end

-- clips that happen off the ground: shown hovering so the tuck is visible
local function isAirClip(clip)
    return clip:find('_a$') ~= nil or clip:find('^ia_') ~= nil or clip:find('^gr_') ~= nil
        or clip:find('^t_') ~= nil or clip:find('^f_') ~= nil
end

-- The commands below are tools for whoever set the server up. With the skateboard resource running, it says who may
-- use them (its Config.TestCommands); on their own they are open.
local function devOK()
    if GetResourceState('skateboard') ~= 'started' then return true end
    local ok, may = pcall(function() return exports.skateboard:devAllowed() end)
    if ok and may == false then
        print('[skate3] this command is for the server\'s admins')
        return false
    end
    return true
end

RegisterCommand('s3anim', function(_, args)
    if not devOK() then return end
    local ped = PlayerPedId()
    if test then StopRide(test, false); test = nil end
    local clip = (args[1] or 'stop'):lower()
    if clip == 'stop' then
        FreezeEntityPosition(ped, false)
        return
    end
    local demo = clip == 'lean'
    if demo then clip = 'r_lean_hcom' end
    if not HasClip(clip) then
        say('unknown clip ' .. clip .. ' (try /s3list ollie)')
        return
    end
    FreezeEntityPosition(ped, true)
    test = StartRide(ped, true)
    local r = riders[test]
    r.demo = demo
    if isAirClip(clip) then r.grounded, r.z = false, r.z + 0.6 end
    local loop = args[2] ~= 'once'
    if clip:find('^b_gstr_') then
        -- gesture clips only move the arms: layer them over the riding pose
        Play(test, 'r_idle_ride_n_0_cyc', { loop = true }, true)
        PlayUpper(test, clip, loop and clip:find('_cyc$') ~= nil, true)
    else
        Play(test, clip, { loop = loop, scrub = demo }, true)
    end
end, false)

RegisterCommand('s3list', function(_, args)
    if not devOK() then return end
    local needle = (args[1] or ''):lower()
    local found = {}
    for clip in pairs(Skate3ClipDict) do
        if clip:find(needle, 1, true) then found[#found + 1] = clip end
    end
    table.sort(found)
    for i = 1, math.min(#found, 25) do say(found[i]) end
    say(#found .. ' clips match')
end, false)

RegisterCommand('s3debug', function()
    if not devOK() then return end
    debugOn = not debugOn
end, false)

-- /s3check: can the game play the converted clips at all? Runs a few plays on yourself and prints what happened,
-- next to a vanilla GTA clip played the same way. Results go to chat and the F8 console.
RegisterCommand('s3check', function()
    if not devOK() then return end
    CreateThread(function()
        local ped = PlayerPedId()
        if test then StopRide(test, false); test = nil end
        local out = {}
        local function log(s)
            out[#out + 1] = s
            print('[s3check] ' .. s)
            say(s)
        end
        local function load(dict)
            local exists = DoesAnimDictExist(dict)
            RequestAnimDict(dict)
            local deadline = GetGameTimer() + 5000
            while not HasAnimDictLoaded(dict) and GetGameTimer() < deadline do Wait(0) end
            return exists, HasAnimDictLoaded(dict)
        end
        local function try(label, dict, clip, frozen, flags)
            ClearPedTasksImmediately(ped)
            FreezeEntityPosition(ped, frozen)
            TaskPlayAnim(ped, dict, clip, 8.0, -8.0, -1, flags, 0.0, false, false, false)
            Wait(600)
            local playing = IsEntityPlayingAnim(ped, dict, clip, 3)
            local t = playing and GetEntityAnimCurrentTime(ped, dict, clip) or -1.0
            log(('%s: playing %s, time %.2f'):format(label, tostring(playing), t))
            StopAnimTask(ped, dict, clip, -8.0)
            Wait(200)
        end
        log(('game build %s, ped model %s'):format(tostring(GetGameBuildNumber and GetGameBuildNumber() or '?'),
            tostring(GetEntityModel(ped))))
        local vd, vc = 'mini@strip_club@idles@bouncer@base', 'base'
        local e1, l1 = load(vd)
        log(('vanilla dict exists %s loaded %s, clip length %.2f s'):format(tostring(e1), tostring(l1),
            GetAnimDuration(vd, vc)))
        for _, clip in ipairs({ 'r_idle_hcom_000', 'r_lean_hcom', 'ollie_high_g' }) do
            local dict = ClipDict(clip)
            local e, l = load(dict)
            log(('%s/%s: dict exists %s loaded %s, game clip length %.2f s (converter says %.2f s)'):format(dict, clip,
                tostring(e), tostring(l), GetAnimDuration(dict, clip), ClipLength(clip)))
        end
        try('vanilla, not frozen, loop', vd, vc, false, 1)
        try('vanilla, frozen, loop', vd, vc, true, 1)
        try('skate3 idle, not frozen, loop', 'skate3@r', 'r_idle_hcom_000', false, 1)
        try('skate3 idle, frozen, loop', 'skate3@r', 'r_idle_hcom_000', true, 1)
        try('skate3 idle, frozen, hold', 'skate3@r', 'r_idle_hcom_000', true, 2)
        -- The ride moves the frozen ped every frame. Does the clip survive that? keepTasks = false is the old bug
        -- (expected: NOT playing), keepTasks = true is what the ride does now (expected: playing).
        local function tryMoving(label, keep)
            ClearPedTasksImmediately(ped)
            FreezeEntityPosition(ped, true)
            TaskPlayAnim(ped, 'skate3@r', 'r_idle_hcom_000', 8.0, -8.0, -1, 1, 0.0, false, false, false)
            local p = GetEntityCoords(ped)
            local deadline = GetGameTimer() + 800
            while GetGameTimer() < deadline do
                SetEntityCoordsNoOffset(ped, p.x, p.y, p.z, keep, keep, false)
                Wait(0)
            end
            local playing = IsEntityPlayingAnim(ped, 'skate3@r', 'r_idle_hcom_000', 3)
            log(('%s: playing %s'):format(label, tostring(playing)))
            StopAnimTask(ped, 'skate3@r', 'r_idle_hcom_000', -8.0)
            Wait(200)
            return playing
        end
        local old = tryMoving('moved every frame, keepTasks false (the old bug)', false)
        local new = tryMoving('moved every frame, keepTasks true (the ride)', true)
        log(('RESULT: %s'):format(new and (old and 'ride OK (clip survives being moved; it survived even without keepTasks)'
            or 'ride OK (clip survives being moved; without keepTasks it stops, as expected)')
            or 'PROBLEM - the clip stops when the ped is moved (report this line)'))
        FreezeEntityPosition(ped, false)
        ClearPedTasks(ped)
        log('done - screenshot the chat or copy the [s3check] lines from F8')
    end)
end, false)

RegisterCommand('s3trim', function()
    if not devOK() then return end
    Board.autoTrim = not Board.autoTrim
    say('skeleton correction ' .. (Board.autoTrim and 'on' or 'off'))
end, false)

RegisterCommand('s3boardfix', function(_, args)
    if not devOK() then return end
    local n = function(i) return tonumber(args[i]) or 0.0 end
    Board.fixRot = vector3(n(1), n(2), n(3))
    Board.fixPos = vector3(n(4), n(5), n(6))
    say(('board fix rot %.0f %.0f %.0f  pos %.2f %.2f %.2f'):format(
        Board.fixRot.x, Board.fixRot.y, Board.fixRot.z, Board.fixPos.x, Board.fixPos.y, Board.fixPos.z))
end, false)
