-- Skate 3's own engine: the player's side.
--
-- The engine is the Rust rewrite of Skate 3's skating that SK8V runs, built as WebAssembly (fivem/engine in the
-- repository). FiveM's in-game browser has WebAssembly switched off, so the engine runs on the SERVER
-- (engine_server.js), one rider a player, with the data of the server owner's own disc; that data never comes
-- here. This file sends the server the pad, sample by sample as an Xbox pad reports it, and the ground round the
-- board, and puts the board, the rider and the camera where the server's answers say. Nothing of this resource's
-- own physics or trick logic runs meanwhile.
--
-- With Config.Engine on and a server that has the engine, getting on the board (the item, F6, D-pad right) starts
-- it and the same again ends it. /sk8engine does the same by hand, /sk8enginestate says what it is doing.
--   * the ground is the map itself where the server has it baked (GTA's own collision with the grind rails
--     found in it: kerbs are kerbs, ledges and handrails grind). Where it has not, or where this game finds the
--     ground somewhere else than the baked map has it (a map the server adds), it is what rays find under a grid
--     round the board, half a metre apart: slopes and ramps are there, a kerb is a ramp, nothing grinds,
--   * props, vehicles and people are not in either: the board goes through them,
--   * the rider plays the ONE clip that has most of the engine's pose, at the engine's time in it, and is stood
--     where that clip has the board under the feet. The engine's own pose is a blend of several clips with the
--     feet and hands placed on top; a script cannot set a ped's bones, so that exact pose cannot be shown,
--   * the board is seen by you alone,
--   * what you do reaches the engine a few hundredths of a second later, plus your ping.
-- Skate 3's space is metres with y up: Skate (x, y, z) = GTA (x, -z, y) from the place it was started at.

Engine = {}

local DECK_ABOVE_ROOT = 0.0122   -- the top of the deck above the engine's board root (as in the converter)
local ROOT_ABOVE_GROUND = 0.087  -- the engine's board root above the wheels' contact when the board stands
-- GTA's script pad inputs -> XInput's button bits: A X B, bumpers, sticks, D-pad up / down / left, back. Y (Skate
-- 3's "get off and walk") and D-pad right (this resource's get on / off) are not handed over.
local BUTTON = { [223] = 0x1000, [224] = 0x4000, [225] = 0x2000, [226] = 0x0100, [227] = 0x0200,
                 [230] = 0x0040, [231] = 0x0080, [232] = 0x0001, [233] = 0x0002, [234] = 0x0004, [236] = 0x0020 }
local KEEP = { 245, 249, 199, 200, 322 }   -- chat, push to talk, pause: left to the game
local TICK = 1.0 / 60.0                    -- the engine's tick: the pad is sampled once for each
local PADS_A_MESSAGE = 2                   -- samples sent together (30 messages a second while the pad moves)

-- The ground: heights on a grid fixed in the world, found by rays and kept; the window round the board is sent
-- to the engine when it has moved on and is complete.
local CELL, SAMPLES, STEP = 0.5, 41, 4     -- metres between samples, samples across the window, cells a window moves by
local HALF = (SAMPLES - 1) // 2
local RAYS_A_FRAME = 120
local GROUND_FLAGS = 1 | 16                -- the map and objects (not vehicles, not peds)
local NO_GROUND = -1000.0                  -- sent for a sample with nothing under it

local have, haveWhy             -- does the server have the engine? (nil until it has answered), and if not, why
local toldAt = -100000          -- when the player was last told which ride they are on
local on = false
local origin, startHeading      -- GTA place and heading the engine's (0, 0, 0) and heading 0 stand for
local board, boardGeom, dressed
local cam
local pose, poseAt              -- the engine's last answer and when it came (game timer, ms)
local poses, firstPose = 0, nil
local riderHeading
local heights, heightAt         -- cell -> ground height there (false = none), and the height it was looked for from
local sent                      -- the window the engine has: { x, y, at }
local grounds = 0
local samples, owed, lastSent   -- pad samples waiting to go, time not yet sampled, the last sample that went
local anim                      -- the clip the ped plays: { clip, dict, length }, and the clips there were none of
local baked                     -- is the rider on the server's baked map? (false: on the ground the rays find)
local checkedAt, wrongSince     -- when the baked map was last held against the game's ground, and since when it is off

local function say(text)
    print(('[skateboard] engine: %s'):format(text))
end

-- A line above the map, so that nobody has to guess which ride they are on.
local function tell(text)
    BeginTextCommandThefeedPost('STRING')
    AddTextComponentSubstringPlayerName(text)
    EndTextCommandThefeedPostTicker(false, false)
end

-- A Skate-space direction as a GTA one.
local function gta(x, y, z) return x, -z, y end

-- Rotation with the given axes (GTA vectors, square to each other) as a quaternion x, y, z, w.
local function quaternion(xx, xy, xz, yx, yy, yz, zx, zy, zz)
    local trace = xx + yy + zz
    if trace > 0.0 then
        local s = math.sqrt(trace + 1.0) * 2.0
        return (yz - zy) / s, (zx - xz) / s, (xy - yx) / s, 0.25 * s
    elseif xx > yy and xx > zz then
        local s = math.sqrt(1.0 + xx - yy - zz) * 2.0
        return 0.25 * s, (yx + xy) / s, (zx + xz) / s, (yz - zy) / s
    elseif yy > zz then
        local s = math.sqrt(1.0 + yy - xx - zz) * 2.0
        return (yx + xy) / s, 0.25 * s, (zy + yz) / s, (zx - xz) / s
    end
    local s = math.sqrt(1.0 + zz - xx - yy) * 2.0
    return (zx + xz) / s, (zy + yz) / s, 0.25 * s, (xy - yx) / s
end

local function heading(x, y)
    local h = math.deg(math.atan(-x, y))
    return h < 0.0 and h + 360.0 or h
end

local function loadModel(model)
    if not IsModelInCdimage(model) then return false end
    RequestModel(model)
    local deadline = GetGameTimer() + 3000
    while not HasModelLoaded(model) and GetGameTimer() < deadline do Wait(0) end
    return HasModelLoaded(model)
end

-- The board: Skate 3's own (with its trucks and wheels) when skate3_assets has it, else the first GTA prop there is.
local function makeBoard(at)
    local model, skate3 = Deck.model(), true
    if not (model and loadModel(model)) then
        model, skate3 = nil, false
        for _, name in ipairs(Config.BoardModels) do
            local hash = joaat(name)
            if loadModel(hash) then model = hash break end
        end
    end
    if not model then return nil end
    local object = CreateObject(model, at.x, at.y, at.z, false, true, false)
    SetEntityCollision(object, false, false)
    FreezeEntityPosition(object, true)
    if skate3 then Deck.dress(object) end
    local lo, hi = GetModelDimensions(model)
    SetModelAsNoLongerNeeded(model)
    return object, { longX = (hi.x - lo.x) > (hi.y - lo.y), bottom = lo.z }, skate3
end

-- The riding stance, held (the clips the engine plays are not read out yet).
local function stance(ped)
    local clip = 'r_idle_hcom_000' .. (Config.Goofy and '' or '_mir')
    local ok, dict = pcall(function() return exports.skate3_assets:ClipDict(clip) end)
    if not ok or not dict then return end
    RequestAnimDict(dict)
    local deadline = GetGameTimer() + 3000
    while not HasAnimDictLoaded(dict) and GetGameTimer() < deadline do Wait(0) end
    if HasAnimDictLoaded(dict) then TaskPlayAnim(ped, dict, clip, 8.0, -8.0, -1, 1, 0.0, false, false, false) end
end

-- The pad as XInput reports it: buttons, left trigger, right trigger, left stick x, y, right stick x, y. On the
-- keyboard: W pushes, S brakes, A / D steer, the arrow keys are the right stick.
local function readPad()
    if IsUsingKeyboard(0) then
        local function key(control) return IsDisabledControlPressed(0, control) and 1 or 0 end
        return (key(32) == 1 and 0x1000 or 0) | (key(33) == 1 and 0x2000 or 0), 0, 0,
            (key(35) - key(34)) * 24000, 0, (key(175) - key(174)) * 32767, (key(172) - key(173)) * 32767
    end
    local buttons = 0
    for control, bit in pairs(BUTTON) do
        if IsDisabledControlPressed(0, control) then buttons = buttons | bit end
    end
    local function axis(control) return math.floor(GetDisabledControlNormal(0, control) * 32767.0 + 0.5) end
    return buttons, math.floor(GetDisabledControlNormal(0, 228) * 255.0 + 0.5),
        math.floor(GetDisabledControlNormal(0, 229) * 255.0 + 0.5), axis(218), -axis(219), axis(220), -axis(221)
end

-- Sample the pad once for every tick of the engine that has gone by (whatever the frame rate) and send the
-- samples a few at a time. While nothing on the pad changes nothing is sent: the server keeps the last sample.
local function sendPad(dt)
    owed = math.min(owed + dt, 0.1)
    while owed >= TICK do
        owed = owed - TICK
        local n = #samples
        samples[n + 1], samples[n + 2], samples[n + 3], samples[n + 4], samples[n + 5], samples[n + 6], samples[n + 7] = readPad()
    end
    if #samples < 7 * PADS_A_MESSAGE then return end
    local same = true
    for i = 1, #samples do
        if samples[i] ~= lastSent[(i - 1) % 7 + 1] then same = false break end
    end
    if not same then
        TriggerServerEvent('skateboard:engPads', samples)
        for i = 1, 7 do lastSent[i] = samples[#samples - 7 + i] end
    end
    samples = {}
end

-- The ground under one sample of the grid, looked for from the board's height: first from a little over it (so a
-- floor is found under a ceiling), then, with nothing there, from well above (so a hill ahead is found).
local function groundAt(x, y, z, ped)
    for _, above in ipairs({ 1.5, 8.0 }) do
        local ray = StartExpensiveSynchronousShapeTestLosProbe(x, y, z + above, x, y, z - 10.0, GROUND_FLAGS, ped, 7)
        local _, hit, at = GetShapeTestResult(ray)
        if hit == 1 and at.z < z + above - 0.02 then return at.z end
    end
    return false
end

-- Look for the ground round the board (some rays a frame) and hand the engine the window of it the board is in
-- when that window has moved on. px, py, pz = the board in GTA; vx, vy = its speed over the ground.
local function ground(ped, px, py, pz, vx, vy)
    local speed = math.sqrt(vx * vx + vy * vy)
    local lead = speed > 0.5 and math.min(speed * 0.6, 6.0) / speed or 0.0   -- (the window is a little ahead of the board)
    local cx = math.floor((px + vx * lead) / CELL / STEP + 0.5) * STEP
    local cy = math.floor((py + vy * lead) / CELL / STEP + 0.5) * STEP
    local rays, unknown, changed = 0, 0, false
    for j = -HALF, HALF do
        for i = -HALF, HALF do
            local key = (cx + i + 0x80000) * 0x100000 + (cy + j + 0x80000)
            local from = heightAt[key]
            if from == nil or math.abs(from - pz) > 1.5 then   -- (not looked at, or looked at from another level)
                if rays < RAYS_A_FRAME then
                    rays = rays + 1
                    local was = heights[key]
                    local now = groundAt((cx + i) * CELL, (cy + j) * CELL, pz, ped)
                    heights[key], heightAt[key] = now, pz
                    if from ~= nil and now ~= was then changed = true end
                else
                    unknown = unknown + 1
                end
            end
        end
    end
    local now = GetGameTimer()
    local moved = not sent or sent.x ~= cx or sent.y ~= cy
    if unknown > 0 or not (moved or (changed and now - sent.at > 200)) then return end
    -- rows from north to south (Skate z = -GTA y), samples from west to east, heights from where the engine began
    local h, n = {}, 0
    for j = HALF, -HALF, -1 do
        for i = -HALF, HALF do
            local z = heights[(cx + i + 0x80000) * 0x100000 + (cy + j + 0x80000)]
            n = n + 1
            h[n] = z and math.floor((z - origin.z) * 1000.0 + 0.5) / 1000.0 or NO_GROUND
        end
    end
    TriggerServerEvent('skateboard:engGround', SAMPLES, CELL, (cx - HALF) * CELL - origin.x,
        -((cy + HALF) * CELL - origin.y), NO_GROUND, h)
    sent = { x = cx, y = cy, at = now }
    grounds = grounds + 1
end

-- The rider's clip: the one the engine plays most of, held at the engine's time in it (the clip does not run by
-- itself: its time is set every frame). Returns the clip's board against the ped at that time (see the Sample
-- export of skate3_assets), or nil when the clip is not among the converted ones.
local function animate(ped, age)
    local clip = pose.clip
    if type(clip) ~= 'string' or clip == '' then clip = nil end
    if clip and pose.mirrored then clip = clip .. '_mir' end
    if clip and clip ~= anim.clip and not anim.none[clip] then
        local ok, dict = pcall(function() return exports.skate3_assets:ClipDict(clip) end)
        if not (ok and dict) then
            anim.none[clip] = true
            say('no converted clip ' .. clip .. ' (the last one stays)')
        elseif HasAnimDictLoaded(dict) then
            anim.clip, anim.dict, anim.lost = clip, dict, nil
            anim.length = math.max(exports.skate3_assets:ClipLength(clip) or 0.0, 0.01)
            anim.phase = math.min(math.max(pose.t / anim.length, 0.0), 0.99)
            TaskPlayAnim(ped, dict, clip, 6.0, -6.0, -1, 2, anim.phase, false, false, false)
            anim.clips = anim.clips + 1
        else
            RequestAnimDict(dict)   -- (the last clip stays until it is there)
        end
    end
    if not anim.dict then return nil end
    if anim.clip == clip then anim.phase = math.min(math.max((pose.t + age) / anim.length, 0.0), 0.999) end
    if IsEntityPlayingAnim(ped, anim.dict, anim.clip, 3) then
        anim.lost = nil
        SetEntityAnimSpeed(ped, anim.dict, anim.clip, 0.0)
        SetEntityAnimCurrentTime(ped, anim.dict, anim.clip, anim.phase)
    else
        -- (a new task takes a frame or two to start; after longer than that the game has dropped it: once more)
        local now = GetGameTimer()
        anim.lost = anim.lost or now
        if now - anim.lost > 200 then
            TaskPlayAnim(ped, anim.dict, anim.clip, 8.0, -8.0, -1, 2, math.min(anim.phase, 0.99), false, false, false)
            anim.lost, anim.replays = nil, anim.replays + 1
        end
    end
    -- (a skate3_assets from before this resource has no Sample: the rider is then stood over the board as before)
    local ok, qx, qy, qz, qw, ax, ay, az = pcall(function() return exports.skate3_assets:Sample(anim.clip, anim.phase) end)
    if ok and qx then return qx, qy, qz, qw, ax, ay, az end
    if not anim.old then
        anim.old = true
        say('skate3_assets cannot say where a clip has the board (an older build is running: ensure skate3_assets)')
    end
    return nil
end

-- On the baked map: is the game's ground where the engine has the board? One ray under the board four times a
-- second, at the map alone (the baked map has no props either). Rolling, the board's root is ROOT_ABOVE_GROUND over
-- the ground; in the air only a board well under the ground is wrong. Off for more than half a second (a map this
-- server adds, a place only Online changes): the server is told, and the ground is the rays' from here on.
local function agree(ped, px, py, pz)
    local now = GetGameTimer()
    if now - checkedAt < 250 then return end
    checkedAt = now
    local ray = StartExpensiveSynchronousShapeTestLosProbe(px, py, pz + 1.5, px, py, pz - 8.0, 1, ped, 7)
    local _, hit, at = GetShapeTestResult(ray)
    local gap = hit == 1 and (pz - ROOT_ABOVE_GROUND - at.z) or nil
    local off = gap ~= nil and (gap < -1.0 or (pose.s == 'PhysicsGround' and math.abs(gap) > 0.4))
    if not off then
        wrongSince = nil
        return
    end
    wrongSince = wrongSince or now
    if now - wrongSince < 600 then return end
    baked, sent = false, nil
    local nx, ny = gta(pose.r[9], pose.r[10], pose.r[11])
    say(('the baked map is %.2f m off this game\'s ground at %.1f %.1f %.1f: the ground is what rays find from here on'):format(
        gap, px, py, at.z))
    TriggerServerEvent('skateboard:engRays', px - origin.x, at.z - origin.z, -(py - origin.y),
        math.rad(heading(nx, ny) + 180.0), gap)
end

-- Put the board, the rider and the camera where the engine's last answer has them.
local function show(ped)
    local r, v, c = pose.r, pose.v, pose.c
    -- (the answer is a tick or two old when it is drawn: carried on by the board's speed for that long; and for up to
    -- 0.15 s when none comes, which is the server handing the engine a new piece of the baked map)
    local age = math.min(math.max((GetGameTimer() - poseAt) / 1000.0, 0.0), 0.15)
    local px, py, pz = gta(r[13] + v[1] * age, r[14] + v[2] * age, r[15] + v[3] * age)
    px, py, pz = origin.x + px, origin.y + py, origin.z + pz
    local rx, ry, rz = gta(r[1], r[2], r[3])       -- the board's left (Skate's x),
    local ux, uy, uz = gta(r[5], r[6], r[7])       -- up,
    local nx, ny, nz = gta(r[9], r[10], r[11])     -- and nose
    local drop = ROOT_ABOVE_GROUND + boardGeom.bottom
    SetEntityCoordsNoOffset(board, px - ux * drop, py - uy * drop, pz - uz * drop, false, false, false)
    if boardGeom.longX then
        SetEntityQuaternion(board, quaternion(nx, ny, nz, rx, ry, rz, ux, uy, uz))
    else
        SetEntityQuaternion(board, quaternion(-rx, -ry, -rz, nx, ny, nz, ux, uy, uz))
    end
    -- the rider: playing the engine's clip, upright, turned and stood so that the clip's board is the engine's
    -- (in the clip the board's tail end is tx, ty from the ped and the deck's middle is ax, ay, az from it)
    local vx, vy = gta(v[1], v[2], v[3])
    local dx, dy, dz = px + ux * DECK_ABOVE_ROOT, py + uy * DECK_ABOVE_ROOT, pz + uz * DECK_ABOVE_ROOT
    local qx, qy, qz, qw, ax, ay, az = animate(ped, age)
    if qx then
        local tx, ty = 2.0 * (qx * qy - qw * qz), 1.0 - 2.0 * (qx * qx + qz * qz)   -- (the clip's board's +y)
        if tx * tx + ty * ty > 0.09 and nx * nx + ny * ny > 0.09 then
            riderHeading = (heading(-nx, -ny) - heading(tx, ty)) % 360.0
        end
        local h = math.rad(riderHeading)
        local ch, sh = math.cos(h), math.sin(h)
        -- (keepTasks, keepIK, no warp: without keepTasks the game drops the clip every time the ped is moved)
        SetEntityCoordsNoOffset(ped, dx - (ax * ch - ay * sh), dy - (ax * sh + ay * ch), dz - az, true, true, false)
    else
        -- (no clip for it: over the board, facing the way it goes)
        if vx * vx + vy * vy > 0.64 then riderHeading = heading(vx, vy) end
        SetEntityCoordsNoOffset(ped, dx, dy, dz + Config.RideHeight, true, true, false)
    end
    SetEntityHeading(ped, riderHeading)
    -- the camera: the engine's own
    if c[13] > 1.0 then
        local cx, cy, cz = gta(c[1] + v[1] * age, c[2] + v[2] * age, c[3] + v[3] * age)
        local fx, fy, fz = gta(c[10], c[11], c[12])
        if not cam then
            cam = CreateCam('DEFAULT_SCRIPTED_CAMERA', true)
            RenderScriptCams(true, false, 0, true, false)
        end
        SetCamCoord(cam, origin.x + cx, origin.y + cy, origin.z + cz)
        SetCamRot(cam, math.deg(math.asin(math.max(-1.0, math.min(1.0, fz)))), 0.0, heading(fx, fy), 2)
        SetCamFov(cam, c[13])
    end
    return px, py, pz, vx, vy
end

function Engine.stop(why)
    if not on then return end
    on = false
    TriggerServerEvent('skateboard:engStop')
    local ped = PlayerPedId()
    if cam then
        RenderScriptCams(false, false, 0, true, false)
        DestroyCam(cam, false)
        cam = nil
    end
    local at = board and DoesEntityExist(board) and GetEntityCoords(board) or nil
    if board and DoesEntityExist(board) then
        if dressed then Deck.undress() end
        DeleteEntity(board)
    end
    board = nil
    ClearPedTasks(ped)
    FreezeEntityPosition(ped, false)
    SetEntityCollision(ped, true, true)
    -- (set down where the board was, on the ground there, not left in the air over it)
    if at then SetEntityCoordsNoOffset(ped, at.x, at.y, at.z + 1.0, false, false, false) end
    say(('stopped%s; %d answers from the engine, the ground handed over %d times'):format(
        why and (' (' .. why .. ')') or '', poses, grounds))
end

function Engine.active() return on end
function Engine.board() return board end

function Engine.start()
    if on then return end
    if SkateboardRiding() then
        say('get off the board first')
        return
    end
    if not have then
        say('this server has no engine (skate3_assets built with it, and the skateboard resource started after it)')
        return
    end
    local ped = PlayerPedId()
    local at = GetEntityCoords(ped)
    local found, floor = GetGroundZFor_3dCoord(at.x, at.y, at.z + 0.5, false)
    origin = vector3(at.x, at.y, found and floor or at.z - 1.0)
    startHeading = GetEntityHeading(ped)
    riderHeading = startHeading
    board, boardGeom, dressed = makeBoard(origin)
    if not board then
        say('no board model could be loaded')
        return
    end
    on, pose, poses, firstPose = true, nil, 0, nil
    heights, heightAt, sent, grounds = {}, {}, nil, 0
    samples, owed, lastSent = {}, 0.0, { 0, 0, 0, 0, 0, 0, 0 }
    anim = { none = {}, clips = 0, replays = 0 }
    baked, checkedAt, wrongSince = false, 0, nil
    FreezeEntityPosition(ped, true)
    SetEntityCollision(ped, false, false)
    stance(ped)   -- (until the engine's first answer says which clip)
    -- (the engine faces Skate +z at heading 0, which is GTA south: half a turn from GTA's heading 0)
    TriggerServerEvent('skateboard:engStart', math.rad(startHeading + 180.0), origin.x, origin.y, origin.z)
    say(('starting at %.1f %.1f %.1f, heading %.0f'):format(origin.x, origin.y, origin.z, startHeading))
    CreateThread(function()
        local last = GetGameTimer()
        while on do
            DisableAllControlActions(0)
            for _, control in ipairs(KEEP) do EnableControlAction(0, control, true) end
            if PlayerPedId() ~= ped or IsEntityDead(ped) then
                Engine.stop('the player changed')
                break
            end
            local now = GetGameTimer()
            sendPad((now - last) / 1000.0)
            last = now
            if pose then
                local px, py, pz, vx, vy = show(ped)
                if pz < origin.z - 300.0 then
                    Engine.stop('the board fell out of the world')
                    break
                end
                if baked then agree(ped, px, py, pz) else ground(ped, px, py, pz, vx, vy) end
            else
                ground(ped, origin.x, origin.y, origin.z + ROOT_ABOVE_GROUND, 0.0, 0.0)
            end
            Wait(0)
        end
    end)
end

-- Does getting on / off the board mean the engine? busy = the resource's own ride has the rider.
function Engine.rides(busy)
    if on then return true end
    if Config.Engine == false or busy then return false end
    if have == true then return true end
    -- (switched on, and the server has no engine: said once a minute, on the screen and in the console)
    if GetGameTimer() - toldAt > 60000 then
        toldAt = GetGameTimer()
        local why = have == nil and 'the server has not answered yet' or (haveWhy ~= '' and haveWhy or 'the server has none')
        say('not used, this is the old ride: ' .. why)
        tell('~y~Skate 3 engine: OFF~s~ (old ride). ' .. why)
    end
    return false
end

function Engine.toggle()
    if on then
        Engine.stop()
    elseif SkateboardMayRide() then
        Engine.start()
    end
end

RegisterNetEvent('skateboard:engHave', function(yes, why)
    have, haveWhy = yes == true, tostring(why or '')
end)

RegisterNetEvent('skateboard:engReady', function(period, ms, onMap)
    baked = onMap == true
    say(('the server\'s engine has you: ready in %d ms, one tick = %.4f s, on %s'):format(ms or 0, period or 0.0,
        baked and 'the baked map' or 'the ground this game finds with rays'))
end)

RegisterNetEvent('skateboard:engPose', function(n, state, r, v, c, clip, time, mirrored)
    if not on or type(r) ~= 'table' or type(v) ~= 'table' or type(c) ~= 'table' then return end
    pose, poseAt = { n = n, s = state, r = r, v = v, c = c, clip = clip, t = tonumber(time) or 0.0,
                     mirrored = mirrored == true }, GetGameTimer()
    poses = poses + 1
    if not firstPose then
        firstPose = poseAt
        say(('riding: %s'):format(tostring(state)))
        tell('~g~Skate 3 engine: ON~s~')
    end
end)

RegisterNetEvent('skateboard:engError', function(text)
    if not on then return end
    local riding = firstPose ~= nil
    say('FAILED: ' .. tostring(text))
    Engine.stop('the engine failed')
    tell('~r~Skate 3 engine failed~s~: ' .. tostring(text) .. (riding and '' or '. Old ride instead.'))
    -- (every rider of the engine taken, or it would not start: the resource's own ride instead)
    if not riding then SkateboardGetOn() end
end)

-- (asked now and then: the server's resource may be started again while this one runs)
CreateThread(function()
    while true do
        TriggerServerEvent('skateboard:engAsk')
        Wait(have == nil and 5000 or 60000)
    end
end)

RegisterCommand('sk8engine', function(_, args)
    if not Dev.may() then
        say(Dev.why)
        return
    end
    if on or args[1] == 'off' then Engine.stop() else CreateThread(Engine.start) end
end, false)

-- Where the engine has the board and what the rider does, for looking into a report afterwards.
RegisterCommand('sk8enginestate', function()
    if not on then return say(have and 'not running; the server has the engine' or 'not running; the server has no engine') end
    if not pose then return say('running, no answer from the engine yet') end
    local seconds = math.max((GetGameTimer() - firstPose) / 1000.0, 0.001)
    say(('%s on %s, clip %s at %.2f s; board %.2f %.2f %.2f (Skate space), speed %.2f m/s; %d answers, %.0f a second; ground handed over %d times; %d clips started, %d of them twice'):format(
        tostring(pose.s), baked and 'the baked map' or 'the rays\' ground', tostring(pose.clip), pose.t or 0.0, pose.r[13], pose.r[14], pose.r[15],
        math.sqrt(pose.v[1] ^ 2 + pose.v[2] ^ 2 + pose.v[3] ^ 2), poses, poses / seconds, grounds,
        anim.clips, anim.replays))
end, false)

AddEventHandler('onResourceStop', function(name)
    if name == GetCurrentResourceName() then Engine.stop('the resource stopped') end
end)
