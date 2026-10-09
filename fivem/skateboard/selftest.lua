-- /skatetest: a scripted ride that checks the board in the real game.
--
-- It gets on the board and works through pushing, rolling, braking, an ollie, a kickflip, a shuvit, a manual, a
-- grab, a 180 into switch and a grind on a rail it spawns; with Skate 3's clips also a ground grab and the coffin, a
-- boneless, a hippy jump, a revert, a held flick, a dark catch and a tweaked grab. The ride is fed scripted controller input (the values a
-- pad would give), and for every step it prints what the GAME reports: is the clip really playing, how far are the
-- ped's real foot bones from where the board was put, did the trick land. Every line starts with [skatetest] and
-- the last one starts with RESULT. They are in the F8 console and in FiveM's log file.
--
--   /skatetest          runs where you stand: it looks all round you for 30 m of flat, clear ground (60 m is
--                       better) and rides that way
--   /skatetest runway   takes you to the airport runway first and brings you back afterwards
--
-- With the stock poses (no skate3_assets) the steps still run; the clip and foot checks are skipped.

local T = SkateTest
local PAD = { lookX = 1, lookY = 2, lr = 30, ud = 31, pushR = 21, pushL = 22, off = 23, grabR = 24, grabL = 25, brake = 45,
              dark = 44 }
local RUNWAY = { x = -1336.0, y = -3044.0, z = 13.95, h = 330.0 } -- Los Santos International
local LENGTH = 60.0  -- metres of flat ground it looks for ahead of the start line ...
local SHORTEST = 30.0 -- ... and the least it can work with

local running = false
local input
local origin    -- the start line: { x, y, z, h, length = metres of flat ground ahead }
local st        -- what was seen during the current step
local tally

local function say(fmt, ...) print(('[skatetest] ' .. fmt):format(...)) end

local function check(name, ok, fmt, ...)
    tally[ok and 'ok' or 'bad'] = tally[ok and 'ok' or 'bad'] + 1
    say('%s %s: ' .. (fmt or ''), ok and 'OK ' or 'BAD', name, ...)
    return ok
end

local function ahead(h, d)
    local r = math.rad(h)
    return vector3(-math.sin(r) * d, math.cos(r) * d, 0.0)
end

local function rayDown(p, up, down)
    local h = StartExpensiveSynchronousShapeTestLosProbe(p.x, p.y, p.z + up, p.x, p.y, p.z - down, 1 | 16, 0, 7)
    local _, hit, hp = GetShapeTestResult(h)
    return hit == 1 and hp.z or nil
end

-- Where the follow camera is, as the rider would say it: metres behind, to the right and above the board, and how
-- far its view is turned off the way the board is going (degrees, + = to the left).
local function camView()
    local s = T.state()
    if not s.cam or not DoesCamExist(s.cam) then return nil end
    local c, r = GetCamCoord(s.cam), GetCamRot(s.cam, 2)
    local h = s.speed < -0.5 and s.facing + 180.0 or s.facing
    local f = ahead(h, 1.0)
    local dx, dy = c.x - s.x, c.y - s.y
    return { behind = -(dx * f.x + dy * f.y), right = dx * f.y - dy * f.x, up = c.z - s.z,
             look = (r.z - h + 180.0) % 360.0 - 180.0, pitch = r.x, fov = GetCamFov(s.cam) }
end

local function camText()
    local v = camView()
    if not v then return 'no follow camera' end
    return ('camera %.1f m behind, %.1f m to the %s, %.1f m up, looking %.0f degrees %s and %.0f down, lens %.0f')
        :format(v.behind, math.abs(v.right), v.right >= 0 and 'right' or 'left', v.up, math.abs(v.look),
            v.look >= 0 and 'left' or 'right', -v.pitch, v.fov)
end

-- ------------------------------------------------------------------ input

local function stick(x, y) input.normal[PAD.lookX], input.normal[PAD.lookY] = x, y end -- right stick: x right, y DOWN
local function steer(x) input.normal[PAD.lr] = x end
local function leftStick(x, y) input.normal[PAD.lr], input.normal[PAD.ud] = x, y end -- x right, y DOWN
local function press(control) input.just[control] = true end
-- (a button that goes down reports "just pressed" for a frame, as a real one does)
local function hold(control, on)
    if on and not input.pressed[control] then input.just[control] = true end
    input.pressed[control] = on or nil
end

-- ------------------------------------------------------------------ watching the ride

local function reset()
    st = { n = 0, probed = 0, playing = 0, measured = 0, feet = 0.0, feetOnce = 0.0, feetBlend = 0.0, recent = {},
           clips = {}, air = 0, peak = 0.0, minUp = 1.0, replays = 0, ground = origin and origin.z or 0.0,
           camOff = 0.0, camNear = 99.0, camFar = 0.0 }
end

local function watch()
    local s, p = T.state(), S3.probe()
    st.n, st.s = st.n + 1, s
    if p then
        st.probed = st.probed + 1
        if p.playing then st.playing = st.playing + 1 end
        if p.clip and p.clip ~= st.clip then
            st.clip = p.clip
            st.clips[#st.clips + 1] = p.clip
        end
        if p.feet and not p.oneFoot then
            -- how far the real feet are from where the board was put: with a clip fully in, and while one clip
            -- fades into the next (the game blends the body, the board follows its own cross-fade)
            local d = math.sqrt(p.feet[1] ^ 2 + p.feet[2] ^ 2 + p.feet[3] ^ 2)
            if p.blending then
                st.recent = {}
                if d > st.feetBlend then st.feetBlend, st.feetBlendClip = d, p.clip end
            else
                -- "off" means off for three frames running; a single frame (the game starts a clip one frame
                -- after it is asked to) is kept apart
                local r = st.recent
                r[#r + 1] = d
                if #r > 3 then table.remove(r, 1) end
                if #r == 3 then
                    local lasting = math.min(r[1], r[2], r[3])
                    if lasting > st.feet then st.feet, st.feetClip = lasting, p.clip end
                end
                st.feetOnce = math.max(st.feetOnce, d)
            end
            st.measured = st.measured + 1
        end
        st.replays0 = st.replays0 or p.replays
        st.replays = p.replays - st.replays0
    end
    if s.mode == 'air' then
        st.air = st.air + 1
        st.peak = math.max(st.peak, s.z - st.ground)
        st.label = s.air or st.label
        st.maxSpin = math.max(st.maxSpin or 0.0, math.abs(s.spin))
    end
    if s.grind then
        st.grind, st.grindFrames = s.grind, (st.grindFrames or 0) + 1
        st.grindDist, st.rail = math.max(st.grindDist or 0.0, s.grindDist or 0.0), s.rail
    end
    st.manual, st.grab, st.antic = s.manual or st.manual, s.grab or st.grab, s.antic or st.antic
    if s.board and DoesEntityExist(s.board) then
        local _, _, up = GetEntityMatrix(s.board)
        st.minUp = math.min(st.minUp, up.z)
    end
    local v = camView()
    if v then
        -- how far round from straight behind the camera gets, and how near and far
        st.camOff = math.max(st.camOff, math.abs(math.deg(math.atan(v.right, v.behind))))
        local d = math.sqrt(v.behind ^ 2 + v.right ^ 2)
        st.camNear, st.camFar = math.min(st.camNear, d), math.max(st.camFar, d)
    end
end

local function camSeen()
    if st.camFar == 0.0 then return 'no follow camera' end
    return ('camera %.1f to %.1f m away, at most %.0f degrees round from straight behind'):format(st.camNear, st.camFar, st.camOff)
end

local function seconds(t, each)
    local stop = GetGameTimer() + math.floor(t * 1000)
    while GetGameTimer() < stop do
        Wait(0)
        if each then each() end
    end
end

-- Back on the ground and calm for a moment (or t seconds have passed). False when the rider came off.
local function settle(t)
    local stop, calm = GetGameTimer() + math.floor((t or 6.0) * 1000), 0.0
    while GetGameTimer() < stop do
        Wait(0)
        watch()
        local s = st.s
        if not s.riding then return false end
        calm = (s.mode == 'ground' and not s.pending and not s.switching) and calm + GetFrameTime() or 0.0
        if calm > 0.7 then return true end
    end
    return false
end

-- What the game said about the clips during the step.
local function seen()
    if st.probed == 0 then return 'stock poses' end
    return ('clip playing %d%% of %d frames; feet off the board by at most %.1f cm%s, %.1f cm for a single frame, '
        .. '%.1f cm while clips fade over%s; restarts %d'):format(math.floor(100.0 * st.playing / st.probed + 0.5),
        st.probed, st.feet * 100.0, st.feetClip and (' (' .. st.feetClip .. ')') or '', st.feetOnce * 100.0,
        st.feetBlend * 100.0, st.feetBlendClip and (' (' .. st.feetBlendClip .. ')') or '', st.replays)
end

-- The clip kept playing, the feet stayed with the board and nothing had to be restarted.
local function healthy(minPlaying)
    if st.probed == 0 then return true end
    return st.playing >= st.probed * (minPlaying or 0.9) and st.feet < 0.06 and st.replays == 0
end

local function clipList(max)
    local out = {}
    for i = 1, math.min(#st.clips, max or 8) do out[i] = st.clips[i] end
    return table.concat(out, ' > ') .. (#st.clips > (max or 8) and ' ...' or '')
end

local function played(part)
    for _, c in ipairs(st.clips) do
        if c:find(part, 1, true) then return true end
    end
    return false
end

-- Back to the start line, rolling at v. Gets back on first if the last step threw the rider off.
local function restart(v)
    if not T.state().riding then
        T.getOn()
        seconds(1.0)
    end
    for _ = 1, 3 do
        if T.place(origin.x, origin.y, origin.z, origin.h, v or 0.0) then break end
        seconds(0.5)
    end
    steer(0.0)
    stick(0.0, 0.0)
    seconds(0.6)
    return T.state().riding
end

-- Hold the stick at the first point of a gesture, then flick through the rest.
local function flick(path, crouch)
    stick(path[1][1], path[1][2])
    Wait(0) -- at least one frame at the start of the gesture
    watch()
    seconds(crouch or 0.3, watch)
    for i = 2, #path do
        local a, b = path[i - 1], path[i]
        for k = 1, 3 do
            stick(a[1] + (b[1] - a[1]) * k / 3, a[2] + (b[2] - a[2]) * k / 3)
            Wait(0)
            watch()
        end
    end
    local last = path[#path]
    if path.rest then seconds(path.rest, watch) end
    for _, k in ipairs({ 0.7, 0.4, 0.1, 0.0 }) do
        stick(last[1] * k, last[2] * k)
        Wait(0)
        watch()
    end
end

-- The stick path that gives THIS rider a trick (Skate 3's own gesture patterns; the built-in reader's otherwise).
local BUILTIN_PATH = {
    Ollie = { { 0.0, 1.0 }, { 0.0, -1.0 } }, Kickflip = { { 0.0, 1.0 }, { -0.72, -0.69 } },
    PopShuvit = { { 0.0, 1.0 }, { -1.0, 0.0 }, rest = 0.25 }, -- the built-in reader wants the stick held at the side
}
local function pathFor(trick)
    local pats = S3.active() and S3.patterns()
    if pats then
        for _, p in ipairs(pats.ground) do
            local c = p.coords
            if S3.trick(p.name) == trick and c and #c >= 2 and math.sqrt(c[1][1] ^ 2 + c[1][2] ^ 2) >= 0.9 then
                local path = {}
                for i, xy in ipairs(c) do path[i] = { xy[1], xy[2] } end
                return path
            end
        end
    end
    local path = BUILTIN_PATH[trick]
    if path and (Config.Goofy ~= T.state().switch) then -- the built-in reader mirrors the stick for the other stance
        path = { { -path[1][1], path[1][2] }, { -path[2][1], path[2][2] }, rest = path.rest }
    end
    return path
end

-- ------------------------------------------------------------------ the steps

local function stepGetOn()
    T.getOn()
    seconds(1.0)
    local s = T.state()
    if not check('get on', s.riding, 'riding %s, Skate 3 clips %s, Skate 3 numbers %s (mode %s), board %s',
        tostring(s.riding), tostring(S3.active()), tostring(s.tuned), Config.Mode, tostring(s.board ~= nil)) then
        return false
    end
    origin.x, origin.y, origin.z, origin.h = s.x, s.y, s.z, s.facing
    reset()
    seconds(2.0, watch)
    check('standing on the board', healthy(0.95) and IsEntityPositionFrozen(PlayerPedId()),
        '%s; %s; board upright %.2f; %s', clipList(3), seen(), st.minUp, camText())
    return true
end

local function stepPush()
    restart(0.0)
    reset()
    hold(PAD.pushR, true)
    seconds(4.2, watch)
    hold(PAD.pushR, false)
    local v = T.state().speed
    seconds(1.5, watch)
    local kicks = 0
    for _, c in ipairs(st.clips) do
        if c:find('_cyc1', 1, true) then kicks = kicks + 1 end
    end
    local want = S3.active() and Tune.pushGain(0.0) * kicks or v
    check('push (A held 4 s)', v > 0.5 and (st.probed == 0 or (kicks >= 3 and math.abs(v - want) < Tune.pushGain(0.0) * 1.2))
        and healthy(0.8), '%.2f m/s after %d kicks (a kick adds %.2f); %s; %s', v, kicks, Tune.pushGain(0.0), clipList(6), seen())
end

local function stepRoll()
    restart(6.0)
    reset()
    local h0 = T.state().facing
    steer(0.4)
    seconds(1.5, watch)
    steer(-0.4)
    seconds(1.5, watch)
    steer(0.0)
    local s = T.state()
    local lost = 6.0 - s.speed
    check('roll and carve', s.riding and s.mode == 'ground' and healthy(0.9) and (not s.tuned or math.abs(lost) < 0.05),
        'speed %.2f -> %.2f m/s, heading %.0f degrees from where it started; %s; %s; %s', 6.0, s.speed,
        math.abs(s.facing - h0), clipList(5), seen(), camSeen())
    -- the camera on a straight line, slow and fast
    for _, v in ipairs({ 2.0, 8.0 }) do
        restart(v)
        seconds(1.5)
        say('     rolling straight at %.0f m/s: %s', v, camText())
    end
end

local function stepBrake()
    restart(5.0)
    reset()
    hold(PAD.brake, true)
    local t0 = GetGameTimer()
    while GetGameTimer() - t0 < 4000 and math.abs(T.state().speed) > 0.1 do
        Wait(0)
        watch()
    end
    local took = (GetGameTimer() - t0) / 1000.0
    seconds(1.2, watch)
    hold(PAD.brake, false)
    seconds(1.2, watch)
    check('brake (B held)', math.abs(T.state().speed) < 0.1 and took < 3.0 and (st.probed == 0 or played('brake')) and healthy(0.8),
        'stopped from 5 m/s in %.1f s; %s; %s', took, clipList(6), seen())
end

-- One trick from a rolling start. Returns the step's observations.
local function trick(name, crouch)
    restart(6.0)
    reset()
    local path = pathFor(name)
    if not path then
        check(name, false, 'no stick path for it')
        return nil
    end
    flick(path, crouch)
    local landed = settle(6.0)
    st.landed = landed
    return st
end

local function stepOllie()
    local o = trick('Ollie', 0.35)
    if not o then return end
    local want = S3.active() and Tune.popRise(1.0, 6.0) or nil
    local s = T.state()
    check('ollie (held crouch)', o.landed and o.air > 8 and o.label ~= nil and o.label:find('Ollie', 1, true) ~= nil
        and (not want or math.abs(o.peak - want) < 0.08) and healthy(0.7) and o.minUp > 0.3,
        "'%s', rose %.2f m%s, %d frames in the air, line '%s'; %s; %s; %s", tostring(o.label), o.peak,
        want and (' (%.2f expected)'):format(want) or '', o.air, s.line, clipList(7), seen(), camSeen())
    o = trick('Ollie', 0.0)
    if not o then return end
    want = S3.active() and Tune.popRise(0.0, 6.0) or nil
    check('ollie (flick straight through)', o.landed and o.air > 5 and o.peak > 0.15 and (not want or o.peak < want + 0.2)
        and healthy(0.7),
        'rose %.2f m%s, %d frames in the air; %s; %s', o.peak, want and (' (%.2f is the weakest pop)'):format(want) or '',
        o.air, clipList(7), seen())
end

local function stepFlip(name, label, flips)
    local o = trick(name, 0.35)
    if not o then return end
    local s = T.state()
    local turned = flips and o.minUp < -0.5 or (not flips)
    check(label, o.landed and o.label == label and s.line:find(label, 1, true) ~= nil and (st.probed == 0 or turned) and healthy(0.7),
        "'%s', landed %s (%s), board upside down at some point: %s (up %.2f), line '%s'; %s; %s", tostring(o.label),
        tostring(o.landed), tostring(s.message or 'no message'), tostring(o.minUp < -0.5), o.minUp, s.line, clipList(7), seen())
end

local function stepManual()
    restart(6.0)
    reset()
    stick(0.0, 0.4)
    seconds(2.0, watch)
    local tilt = st.minUp
    local label = st.manual
    stick(0.0, 0.0)
    settle(3.0)
    check('manual (stick half way down)', label == 'Manual' and (st.probed == 0 or (played('m_idle') and tilt < 0.995)) and healthy(0.9),
        "'%s', board tipped to up %.3f, line '%s'; %s; %s", tostring(label), tilt, T.state().line, clipList(5), seen())
end

local function stepGrab()
    restart(6.0)
    reset()
    flick(pathFor('Ollie'), 0.35)
    local t0 = GetGameTimer()
    while GetGameTimer() - t0 < 2000 and T.state().mode ~= 'air' do
        Wait(0)
        watch()
    end
    seconds(0.2, watch)
    hold(PAD.grabR, true)
    seconds(0.3, watch)
    hold(PAD.grabR, false)
    local got = st.grab
    local landed = settle(6.0)
    check('grab (RT in the air)', landed and got ~= nil and (st.probed == 0 or played('gr_')) and healthy(0.7),
        "grab '%s', landed %s, line '%s'; %s; %s", tostring(got), tostring(landed), T.state().line, clipList(8), seen())
end

-- ---- the tricks that need Skate 3's clips: one step for each family (they are not run on the stock poses)

local function lineHas(text) return (T.state().line or ''):find(text, 1, true) ~= nil end

local function stepCoffin()
    restart(5.0)
    reset()
    hold(PAD.grabR, true)
    seconds(1.2, watch)
    local hand = T.state().ggrab
    hold(PAD.grabL, true)
    seconds(0.8, watch)
    hold(PAD.pushR, true)
    hold(PAD.pushL, true)
    seconds(1.8, watch)
    local lying = T.state().coffin
    local v = T.state().speed
    for _, c in ipairs({ PAD.pushR, PAD.pushL, PAD.grabR, PAD.grabL }) do hold(c, false) end
    local up = settle(4.0)
    seconds(1.2, watch)
    check('ground grab, both hands, coffin (RT; + LT; + A + X)', hand ~= nil and lying and up and played('gr_ground_n_coffin')
        and lineHas('Coffin'), "hand on the board '%s', lying on it %s (rolling %.1f m/s), up again %s, line '%s'; %s; %s",
        tostring(hand), tostring(lying), v, tostring(up), T.state().line, clipList(9), seen())
end

local function stepBoneless()
    restart(5.0)
    reset()
    hold(PAD.grabR, true)
    seconds(1.0, watch)
    press(PAD.pushR)
    seconds(0.5, watch)
    hold(PAD.grabR, false)
    local landed = settle(6.0)
    local want = Tune.plantJump() ^ 2 / (2.0 * Tune.gravity)
    check('foot plant (one hand on the board, then A)', landed and (lineHas('Boneless') or lineHas('Fastplant'))
        and (played('boneless_') or played('fastplant_')) and math.abs(st.peak - want) < 0.08,
        "landed %s, rose %.2f m (%.2f expected), line '%s'; %s; %s", tostring(landed), st.peak, want, T.state().line,
        clipList(9), seen())
end

local function stepHippy()
    restart(5.0)
    reset()
    hold(PAD.pushR, true)
    hold(PAD.pushL, true)
    seconds(0.8, watch)
    local crouch = T.state().hippy
    hold(PAD.pushR, false)
    hold(PAD.pushL, false)
    local top, t0 = 0.0, GetGameTimer()
    while GetGameTimer() - t0 < 4000 and T.state().hippy do
        Wait(0)
        watch()
        top = math.max(top, S3.lift or 0.0)
    end
    local on = settle(4.0)
    check('hippy jump (A + X held, then let go)', crouch == 'antic' and on and lineHas('Hippy Jump') and played('t_hippyjump')
        and top > 0.3, "crouch '%s', feet %.2f m above the board at most, back on it %s, line '%s'; %s; %s", tostring(crouch),
        top, tostring(on), T.state().line, clipList(8), seen())
end

local function stepRevert()
    restart(5.0)
    reset()
    local pats = S3.patterns()
    local c
    for _, q in ipairs(pats and pats.left or {}) do
        if q.name == 'SlideFs180' then c = q.coords break end
    end
    if not c then return check('revert', false, 'no left-stick gestures in this skate3_assets build') end
    leftStick(c[1][1], c[1][2])
    seconds(0.07, watch)
    for i = 2, #c do
        for k = 1, 4 do
            leftStick(c[i - 1][1] + (c[i][1] - c[i - 1][1]) * k / 4, c[i - 1][2] + (c[i][2] - c[i - 1][2]) * k / 4)
            Wait(0)
            watch()
        end
    end
    for _, k in ipairs({ 0.7, 0.4, 0.1, 0.0 }) do
        leftStick(c[#c][1] * k, c[#c][2] * k)
        Wait(0)
        watch()
    end
    seconds(1.0, watch)
    local v = T.state().speed
    check('revert (left stick swept through the bottom half)', v < -2.0 and lineHas('Revert') and played('r_turn_180slide'),
        "rolling %.1f m/s (backwards is negative), line '%s'; %s; %s", v, T.state().line, clipList(6), seen())
    settle(4.0)
end

local function stepHeldFlick()
    restart(6.0)
    reset()
    local path = pathFor('Kickflip')
    if not path then return check('held flick', false, 'no stick path for a kickflip') end
    path.rest = 1.2 -- the stick stays where the flick ended
    flick(path, 0.35)
    local landed = settle(6.0)
    check('double kickflip (the flick held, strongest pop)', landed and lineHas('Double Kickflip') and played('_cyc1'),
        "landed %s (%s), line '%s'; %s; %s", tostring(landed), tostring(T.state().message or 'no message'), T.state().line,
        clipList(8), seen())
end

local function stepDarkCatch()
    restart(6.0)
    reset()
    local path = pathFor('Kickflip')
    if not path then return check('dark catch', false, 'no stick path for a kickflip') end
    flick(path, 0.35)
    press(PAD.dark)
    local dark, t0 = false, GetGameTimer()
    while GetGameTimer() - t0 < 3000 and T.state().riding do
        Wait(0)
        watch()
        dark = dark or T.state().dark
    end
    local s = T.state()
    -- (on the flat there is no time to flick it back over: it comes down on the grip tape and the rider steps off)
    check('dark catch (kickflip, then the right bumper)', dark and played('dcatch') and not s.riding and s.message == 'Landed on the grip tape',
        "caught upside down %s, then: riding %s, '%s'; %s; %s", tostring(dark), tostring(s.riding), tostring(s.message),
        clipList(8), seen())
end

local function stepTweak()
    restart(6.0)
    reset()
    flick(pathFor('Ollie'), 0.35)
    local t0 = GetGameTimer()
    while GetGameTimer() - t0 < 2000 and T.state().mode ~= 'air' do
        Wait(0)
        watch()
    end
    seconds(0.1, watch)
    hold(PAD.grabR, true)
    seconds(0.22, watch)
    stick(0.0, -1.0) -- up: the grab in hand is tweaked, it does not turn into a tail grab
    seconds(0.25, watch)
    local kind, var = T.state().grab, T.state().gvar
    stick(0.0, 0.0)
    hold(PAD.grabR, false)
    local landed = settle(6.0)
    check('grab, then the stick up (a tweak)', landed and (kind == 'fs' or kind == 'bs') and var == 'tw_up'
        and (played('gr_nbone') or played('gr_melon')) and (lineHas('Nosebone') or lineHas('Melon')),
        "grab '%s' with '%s', landed %s, line '%s'; %s; %s", tostring(kind), tostring(var), tostring(landed), T.state().line,
        clipList(9), seen())
end

local function stepSwitch()
    restart(6.0)
    reset()
    flick(pathFor('Ollie'), 0.35)
    local t0 = GetGameTimer()
    while GetGameTimer() - t0 < 3000 do
        Wait(0)
        watch()
        local s = st.s
        if s.mode == 'air' then
            steer(math.abs(s.spin) < 172.0 and 1.0 or 0.0)
        elseif st.air > 0 then
            break
        end
    end
    steer(0.0)
    local s = T.state()
    local fakie = s.riding and s.speed < -1.0
    local line = s.line
    local t1 = GetGameTimer()
    while GetGameTimer() - t1 < 4000 and not T.state().switch do
        Wait(0)
        watch()
    end
    seconds(1.0, watch)
    s = T.state()
    check('180, fakie, then switch', fakie and s.riding and s.switch and s.speed > 1.0 and healthy(0.7)
        and (st.probed == 0 or played('r_switch_ride')), "spun %.0f degrees, landed fakie %s ('%s'), riding switch %s at %.1f m/s; %s; %s",
        st.maxSpin or 0.0, tostring(fakie), line, tostring(s.switch), s.speed, clipList(9), seen())
    -- back to the normal stance for the next steps
    T.getOff()
    seconds(0.5)
    T.getOn()
    seconds(1.0)
end

local function stepGrind()
    restart(0.0)
    local h = origin.h
    local at = vector3(origin.x, origin.y, origin.z) + ahead(h, math.min(42.0, origin.length - 9.0))
    local rail = T.spawnRamp('rail', at, h)
    if not rail then
        check('grind', false, 'the rail model (%s) is not in the game', tostring(Config.Ramps.rail))
        return
    end
    local lo, hi = GetModelDimensions(GetEntityModel(rail))
    local long = hi.y - lo.y
    if hi.x - lo.x > long then -- the model is long on its x axis: turn it along the run
        long = hi.x - lo.x
        SetEntityHeading(rail, h + 90.0)
    end
    seconds(0.5)
    local centre = GetEntityCoords(rail)
    local top = centre.z + hi.z
    local dist = function()
        local s = T.state()
        local dx, dy = centre.x - s.x, centre.y - s.y
        local f = ahead(h, 1.0)
        return dx * f.x + dy * f.y, dx * f.y - dy * f.x -- along the run, and to the right of it
    end
    say('     rail: %.1f m long, top %.2f m above the ground, %.1f m ahead', long, top - origin.z, select(1, dist()))
    reset()
    T.place(origin.x, origin.y, origin.z, h, 6.0)
    -- roll up at 6 m/s; the flick has to finish with the middle of the rail about 5.5 m ahead
    local t0 = GetGameTimer()
    while GetGameTimer() - t0 < 12000 do
        Wait(0)
        watch()
        local s = st.s
        local d = dist()
        if not s.riding or d < 5.5 + 6.0 * 0.45 then break end
        if s.mode == 'ground' then T.place(s.x, s.y, s.z, h, 6.0) end
    end
    flick(pathFor('Ollie'), 0.35)
    local t1 = GetGameTimer()
    local side = 0.0
    while GetGameTimer() - t1 < 8000 do
        Wait(0)
        watch()
        local s = st.s
        if not s.riding then break end
        if s.mode == 'grind' then
            local _, off = dist()
            side = math.max(side, math.abs(off))
        elseif s.mode == 'ground' and (st.air > 0) and not s.pending then
            break
        end
    end
    local name, frames = st.grind, st.grindFrames or 0
    local landed = settle(5.0)
    hold(PAD.brake, true) -- there may be little room behind the rail
    seconds(1.5, watch)
    hold(PAD.brake, false)
    -- it has to stay on for a good part of the rail (the landing uses up some of it)
    local far = st.grindDist or 0.0
    check('grind (ollie onto a rail)', name ~= nil and far >= math.min(1.5, long * 0.4) and landed and side < 0.15 and healthy(0.7)
        and (st.probed == 0 or played('g_')), "'%s' for %.1f m (%d frames) on a rail heard as %s, %.0f cm off the rail's line at most, rolled away %s (%s), line '%s'; %s; %s",
        tostring(name), far, frames, tostring(st.rail), side * 100.0, tostring(landed), tostring(T.state().message or 'no message'), T.state().line,
        clipList(9), seen())
    T.clearRamps()
end

-- Nobody can hear the page that plays the sounds, so it says what it loaded (it has had the whole ride to do it).
local function stepSound()
    local on, pack, rep = T.sound()
    if not on then return say('     sound: switched off (Config.Sound)') end
    if not pack then return say('     sound: there is no Skate 3 sound pack in skate3_assets, so the board is silent') end
    local stop = GetGameTimer() + 8000
    while not rep and GetGameTimer() < stop do
        Wait(100)
        on, pack, rep = T.sound()
    end
    local s = T.state()
    check('sound', rep ~= nil and rep.total > 0 and rep.loaded == rep.total and rep.state == 'running',
        "%s; the wheels were last heard on '%s'",
        rep and ('%d of %d recordings loaded, audio %s at %d Hz, played from %s'):format(rep.loaded, rep.total,
            tostring(rep.state), math.floor(rep.rate or 0), rep.world == 'screen' and 'the screen (Config.SoundFromBoard is off)'
                or ('the board (' .. tostring(rep.world) .. ')')) or 'the sound page did not answer', tostring(s.surface))
end

local function stepGetOff()
    stepSound()
    T.getOff()
    seconds(1.0)
    local ped = PlayerPedId()
    check('step off', not T.state().riding and not IsEntityPositionFrozen(ped), 'riding %s, ped frozen %s',
        tostring(T.state().riding), tostring(IsEntityPositionFrozen(ped)))
end

-- ------------------------------------------------------------------ the run

-- How many metres of flat, clear ground lie ahead of p (up to LENGTH), and why it ends where it does.
local function flatAhead(p, h)
    local length, why = LENGTH, 'flat and clear'
    local a, b = p + vector3(0, 0, 0.6), p + ahead(h, LENGTH) + vector3(0, 0, 0.6)
    local ray = StartExpensiveSynchronousShapeTestLosProbe(a.x, a.y, a.z, b.x, b.y, b.z, 1 | 2 | 16, PlayerPedId(), 7)
    local _, hit, hp = GetShapeTestResult(ray)
    if hit == 1 then
        length = math.sqrt((hp.x - p.x) ^ 2 + (hp.y - p.y) ^ 2) - 2.0
        why = 'something is in the way'
    end
    for d = 0.0, length, 2.5 do
        local q = p + ahead(h, d)
        local z
        for _ = 1, 20 do -- the ground further off may still be loading
            z = rayDown(vector3(q.x, q.y, p.z), 2.0, 2.0)
            if z then break end
            Wait(100)
        end
        if not z or math.abs(z - p.z) > 0.2 then
            length, why = d - 2.5, z and ('the ground is %.2f m off level there'):format(z - p.z) or 'the ground ends there'
            break
        end
    end
    return length, why
end

local function goTo(x, y, z, h)
    local ped = PlayerPedId()
    RequestCollisionAtCoord(x, y, z)
    SetEntityCoords(ped, x, y, z, false, false, false, false)
    SetEntityHeading(ped, h)
    local stop = GetGameTimer() + 8000
    while not HasCollisionLoadedAroundEntity(ped) and GetGameTimer() < stop do Wait(50) end
    Wait(500)
end

local home -- where the player stood before the test took them to the runway

local function run(where)
    local ped = PlayerPedId()
    local back = GetEntityCoords(ped)
    local backH = GetEntityHeading(ped)
    local moved = false
    tally = { ok = 0, bad = 0 }
    say('start: game build %d, ped model %d, skate3_assets %s, clips ready %s', GetGameBuildNumber(), GetEntityModel(ped),
        tostring(S3.available()), tostring(S3.ready()))
    if T.state().riding then
        T.getOff()
        seconds(1.0)
    end
    if where == 'runway' then
        home = { x = back.x, y = back.y, z = back.z, h = backH }
        goTo(RUNWAY.x, RUNWAY.y, RUNWAY.z, RUNWAY.h)
        moved = true
    end
    local p, h = GetEntityCoords(ped), GetEntityHeading(ped)
    local ground = rayDown(p, 0.5, 3.0)
    local length, why = 0.0, 'no ground under you'
    if ground then
        -- the way the rider faces first, then every 15 degrees round: the longest flat run wins
        local from, h0 = vector3(p.x, p.y, ground), h
        for turn = 0.0, 180.0, 15.0 do
            for _, side in ipairs(turn == 0.0 and { 1.0 } or { 1.0, -1.0 }) do
                local l, w = flatAhead(from, h0 + turn * side)
                if l > length then length, why, h = l, w, h0 + turn * side end
            end
            if length >= 45.0 then break end
        end
        h = (h + 360.0) % 360.0
        SetEntityHeading(ped, h)
    end
    if check('place', length >= SHORTEST, '%.1f, %.1f, %.1f heading %.0f: %.0f m of flat ground ahead (%s)%s', p.x, p.y, p.z, h,
        length, why, length >= SHORTEST and '' or ': it needs 30 m, turn to face open ground and run it again') then
        origin = { x = p.x, y = p.y, z = ground, h = h, length = length }
        input = { normal = {}, pressed = {}, just = {} }
        T.input(input)
        if stepGetOn() then
            local steps = { stepPush, stepRoll, stepBrake, stepOllie,
                            function() stepFlip('Kickflip', 'Kickflip', true) end,
                            function() stepFlip('PopShuvit', 'Pop Shuvit', false) end,
                            stepManual, stepGrab }
            if S3.active() then
                for _, extra in ipairs({ stepTweak, stepHeldFlick, stepDarkCatch, stepCoffin, stepBoneless, stepHippy }) do
                    steps[#steps + 1] = extra
                end
            end
            steps[#steps + 1] = stepSwitch
            steps[#steps + 1] = stepGrind
            if S3.active() then steps[#steps + 1] = stepRevert end -- (last: it leaves the rider rolling backwards)
            for _, step in ipairs(steps) do
                local ok, err = pcall(step)
                if not ok then check('step', false, 'script error: %s', tostring(err)) end
                input.normal, input.pressed, input.just = {}, {}, {}
                T.input(input)
            end
        end
        stepGetOff()
    end
    T.input(nil)
    T.clearRamps()
    if moved then goTo(back.x, back.y, back.z, backH) end
    home = nil
    say('RESULT: %d OK, %d BAD%s', tally.ok, tally.bad, tally.bad == 0 and ' - everything this test looks at works in the game' or '')
end

RegisterCommand('skatetest', function(_, args)
    if running then return end
    if not Dev.may() then return say('%s', Dev.why) end
    running = true
    CreateThread(function()
        local ok, err = pcall(run, args[1])
        if not ok then
            T.input(nil)
            say('RESULT: stopped by a script error: %s', tostring(err))
            -- nothing of the test is left behind: off the board, its ramps gone, the player back where they stood
            pcall(function()
                if T.state().riding then T.getOff() end
                T.clearRamps()
                if home then goTo(home.x, home.y, home.z, home.h) end
            end)
            home = nil
        end
        running = false
    end)
end, false)

TriggerEvent('chat:addSuggestion', '/skatetest', 'Scripted test ride (results in the F8 console)',
    { { name = 'where', help = 'empty = where you stand, facing 30 m of flat ground; runway = at the airport' } })
