-- Skate 3's own engine, hosted by this resource.
--
-- The engine is the Rust rewrite of Skate 3's skating that SK8V runs, built as WebAssembly (fivem/engine in the
-- repository) and put into skate3_assets with the data of the player's own disc. It runs in this resource's page
-- (html/engine/): this file hands it the pad every frame, as an Xbox pad reports it, and puts the board, the rider
-- and the camera where it says. Nothing of this resource's own physics or trick logic runs meanwhile.
--
-- FIRST STEP, behind a test command: /sk8engine starts it where you stand, /sk8engine again (or off) ends it.
--   * the ground is a flat floor at the height you start at (GTA's own ground is not given to the engine yet):
--     use it somewhere flat and open,
--   * the rider is shown in the riding stance only (which clips the engine plays is not read out yet),
--   * the board is seen by you alone.
-- Skate 3's space is metres with y up: Skate (x, y, z) = GTA (x, -z, y) from the place it was started at.

Engine = {}

local DECK_ABOVE_ROOT = 0.0122   -- the top of the deck above the engine's board root (as in the converter)
local ROOT_ABOVE_GROUND = 0.087  -- the engine's board root above the wheels' contact when the board stands
local BUTTON = { [222] = 0x8000, [223] = 0x1000, [224] = 0x4000, [225] = 0x2000, [226] = 0x0100, [227] = 0x0200,
                 [230] = 0x0040, [231] = 0x0080, [232] = 0x0001, [233] = 0x0002, [234] = 0x0004, [235] = 0x0008,
                 [236] = 0x0020 }   -- GTA's script pad inputs -> XInput's button bits (Y A X B, bumpers, sticks, D-pad, back)
local KEEP = { 245, 249, 199, 200, 322 }   -- chat, push to talk, pause: left to the game

local on = false
local origin, startHeading      -- GTA place and heading the engine's (0, 0, 0) and heading 0 stand for
local board, boardGeom, dressed
local cam
local pose, poseAt              -- the engine's last answer and when it came (game timer, ms)
local poses, firstPose = 0, nil
local riderHeading

local function say(text)
    print(('[skateboard] engine: %s'):format(text))
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

-- The pad as XInput reports it. On the keyboard: W pushes, S brakes, A / D steer, the arrow keys are the right stick.
local function readPad()
    local buttons = 0
    for control, bit in pairs(BUTTON) do
        if IsDisabledControlPressed(0, control) then buttons = buttons | bit end
    end
    local function axis(control) return math.floor(GetDisabledControlNormal(0, control) * 32767.0 + 0.5) end
    local pad = { t = 'eng', op = 'pad', buttons = buttons,
                  lt = math.floor(GetDisabledControlNormal(0, 228) * 255.0 + 0.5),
                  rt = math.floor(GetDisabledControlNormal(0, 229) * 255.0 + 0.5),
                  lx = axis(218), ly = -axis(219), rx = axis(220), ry = -axis(221) }
    if IsUsingKeyboard(0) then
        local function key(control) return IsDisabledControlPressed(0, control) and 1 or 0 end
        pad.buttons = (key(32) == 1 and 0x1000 or 0) | (key(33) == 1 and 0x2000 or 0)
        pad.lt, pad.rt = 0, 0
        pad.lx, pad.ly = (key(35) - key(34)) * 24000, 0
        pad.rx, pad.ry = (key(175) - key(174)) * 32767, (key(172) - key(173)) * 32767
    end
    return pad
end

-- Put the board, the rider and the camera where the engine's last answer has them.
local function show(ped)
    local r, v, c = pose.r, pose.v, pose.c
    -- (the answer is a tick or two old when it is drawn: carried on by the board's speed for that long)
    local age = math.min(math.max((GetGameTimer() - poseAt) / 1000.0, 0.0), 0.05)
    local px, py, pz = gta(r[13] + v[1] * age, r[14] + v[2] * age, r[15] + v[3] * age)
    px, py, pz = origin.x + px, origin.y + py, origin.z + pz
    local rx, ry, rz = gta(r[1], r[2], r[3])       -- the board's right,
    local ux, uy, uz = gta(r[5], r[6], r[7])       -- up,
    local nx, ny, nz = gta(r[9], r[10], r[11])     -- and nose
    local drop = ROOT_ABOVE_GROUND + boardGeom.bottom
    SetEntityCoordsNoOffset(board, px - ux * drop, py - uy * drop, pz - uz * drop, false, false, false)
    if boardGeom.longX then
        SetEntityQuaternion(board, quaternion(nx, ny, nz, rx, ry, rz, ux, uy, uz))
    else
        SetEntityQuaternion(board, quaternion(-rx, -ry, -rz, nx, ny, nz, ux, uy, uz))
    end
    -- the rider: over the board, upright, facing the way the board goes
    local vx, vy = gta(v[1], v[2], v[3])
    if vx * vx + vy * vy > 0.64 then riderHeading = heading(vx, vy) end
    SetEntityCoordsNoOffset(ped, px + ux * DECK_ABOVE_ROOT, py + uy * DECK_ABOVE_ROOT,
        pz + uz * DECK_ABOVE_ROOT + Config.RideHeight, true, false, false)
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
end

function Engine.stop(why)
    if not on then return end
    on = false
    SendNUIMessage({ t = 'eng', op = 'stop' })
    local ped = PlayerPedId()
    if cam then
        RenderScriptCams(false, false, 0, true, false)
        DestroyCam(cam, false)
        cam = nil
    end
    if board and DoesEntityExist(board) then
        if dressed then Deck.undress() end
        DeleteEntity(board)
    end
    board = nil
    ClearPedTasks(ped)
    FreezeEntityPosition(ped, false)
    SetEntityCollision(ped, true, true)
    say(('stopped%s; %d answers from the engine'):format(why and (' (' .. why .. ')') or '', poses))
end

function Engine.active() return on end
function Engine.board() return board end

function Engine.start()
    if on then return end
    if SkateboardRiding() then
        say('get off the board first')
        return
    end
    local ok, base = pcall(function() return exports.skate3_assets:EngineBase() end)
    if not ok or not base then
        say('skate3_assets has no engine in it (build it with the engine staged, see fivem/engine)')
        return
    end
    local ped = PlayerPedId()
    local at = GetEntityCoords(ped)
    local found, ground = GetGroundZFor_3dCoord(at.x, at.y, at.z + 0.5, false)
    origin = vector3(at.x, at.y, found and ground or at.z - 1.0)
    startHeading = GetEntityHeading(ped)
    riderHeading = startHeading
    board, boardGeom, dressed = makeBoard(origin)
    if not board then
        say('no board model could be loaded')
        return
    end
    on, pose, poses, firstPose = true, nil, 0, nil
    FreezeEntityPosition(ped, true)
    SetEntityCollision(ped, false, false)
    stance(ped)
    -- (the engine faces Skate +z at heading 0, which is GTA south: half a turn from GTA's heading 0)
    SendNUIMessage({ t = 'eng', op = 'start', base = base, heading = math.rad(startHeading + 180.0) })
    say(('starting at %.1f %.1f %.1f, heading %.0f; the first time takes about ten seconds'):format(
        origin.x, origin.y, origin.z, startHeading))
    CreateThread(function()
        while on do
            DisableAllControlActions(0)
            for _, control in ipairs(KEEP) do EnableControlAction(0, control, true) end
            if PlayerPedId() ~= ped or IsEntityDead(ped) then
                Engine.stop('the player changed')
                break
            end
            SendNUIMessage(readPad())
            if pose then show(ped) end
            Wait(0)
        end
    end)
end

RegisterNUICallback('eng', function(data, cb)
    cb('ok')
    if data.k == 'pose' then
        if not on then return end
        pose, poseAt = data, GetGameTimer()
        poses = poses + 1
        if not firstPose then
            firstPose = poseAt
            say(('riding: %s'):format(tostring(data.s)))
        end
    elseif data.k == 'ready' then
        say(('loaded in %d ms, %d bones, one tick = %.4f s'):format(data.ms or 0, data.bones or 0, data.period or 0.0))
    elseif data.k == 'log' then
        say(tostring(data.m))
    elseif data.k == 'error' then
        say('FAILED: ' .. tostring(data.m))
        Engine.stop('the engine failed')
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
    if not on then return say('not running') end
    if not pose then return say('running, no answer from the engine yet') end
    local seconds = math.max((GetGameTimer() - firstPose) / 1000.0, 0.001)
    say(('%s; board %.2f %.2f %.2f (Skate space), speed %.2f m/s; %d answers, %.0f a second'):format(
        tostring(pose.s), pose.r[13], pose.r[14], pose.r[15],
        math.sqrt(pose.v[1] ^ 2 + pose.v[2] ^ 2 + pose.v[3] ^ 2), poses, poses / seconds))
end, false)

AddEventHandler('onResourceStop', function(name)
    if name == GetCurrentResourceName() then Engine.stop('the resource stopped') end
end)
