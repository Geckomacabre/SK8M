-- Which board the rider has. With skate3_assets running and built with Skate 3's own board (decks.lua there), the
-- board is Skate 3's: a deck object, which is "the board" the ride moves, with a trucks object and a wheels object
-- attached to it. Every Skate 3 deck, trucks and wheels is its own model, so what a board looks like is simply the
-- models of its three objects, and the game itself shows them to every other player. Without that data the board
-- is the single GTA prop from Config.BoardModels, as before.
--
-- The SERVER keeps each player's parts (deck_server.lua); this file asks it, remembers the answer and builds the board.
-- None of Skate 3's names or prices are in this file: they come from skate3_assets at run time.

Deck = {}

local KINDS = { 'deck', 'truck', 'wheel' }
local LIST = { deck = 'stock', truck = 'trucks', wheel = 'wheels' }   -- where each kind is in the Decks table
local data            -- Skate 3's parts (the Decks export of skate3_assets), false when there are none
local state           -- what the server last said: { owned = { deck = {...}, ... }, design = { deck, truck, wheel }, money }
local parts = {}      -- the trucks and wheels objects on my board
local page = { open = false, waiting = {} }   -- the shop's page: is it up; callbacks waiting for the server's answer

local function say(msg)
    BeginTextCommandThefeedPost('STRING')
    AddTextComponentSubstringPlayerName(msg)
    EndTextCommandThefeedPostTicker(false, false)
end

-- Skate 3's parts, read once per start of skate3_assets.
local function catalogue()
    if data == nil then
        data = false
        if Config.Decks.enabled and GetResourceState('skate3_assets') == 'started' then
            local ok, t = pcall(function() return exports.skate3_assets:Decks() end)
            if ok and type(t) == 'table' and type(t.stock) == 'table' and #t.stock > 0 then
                t.byId = { deck = {}, truck = {}, wheel = {} }
                for _, kind in ipairs(KINDS) do
                    for i, p in ipairs(t[LIST[kind]] or {}) do
                        p.index = i
                        t.byId[kind][p.id] = p
                    end
                end
                data = t
            end
        end
    end
    return data or nil
end

-- The part of one kind my board has: the server's word, else the board nobody has designed yet.
local function current(kind)
    local d = catalogue()
    if not d then return nil end
    local id = state and state.design and state.design[kind]
    return d.byId[kind][id] or d.byId[kind][d.default[kind]] or d[LIST[kind]][1]
end

function Deck.available() return catalogue() ~= nil end

-- The model of the deck object for a new board (a hash), or nil when the GTA prop is to be used.
function Deck.model()
    local p = current('deck')
    return p and joaat(p.model) or nil
end

local function loadModel(model)
    if not IsModelInCdimage(model) then return false end
    RequestModel(model)
    local deadline = GetGameTimer() + 3000
    while not HasModelLoaded(model) and GetGameTimer() < deadline do Wait(0) end
    return HasModelLoaded(model)
end

-- Take the trucks and wheels off (they are deleted: they are nothing without their deck).
function Deck.undress()
    for _, e in ipairs(parts) do
        if DoesEntityExist(e) then
            SetEntityAsMissionEntity(e, true, true)
            DeleteObject(e)
        end
    end
    parts = {}
end

-- Put my trucks and wheels on a Skate 3 deck: two more objects at the deck's own origin, attached to it without
-- offset (the three models share one frame), with no collision of their own (the deck's stands for the whole board).
function Deck.dress(board)
    Deck.undress()
    if not catalogue() or not board or not DoesEntityExist(board) then return end
    local at = GetEntityCoords(board)
    for _, kind in ipairs({ 'truck', 'wheel' }) do
        local p = current(kind)
        local model = p and joaat(p.model)
        if model and loadModel(model) then
            local e = CreateObject(model, at.x, at.y, at.z, Config.NetworkBoard, true, false)
            SetModelAsNoLongerNeeded(model)
            SetEntityCollision(e, false, false)
            AttachEntityToEntity(e, board, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, false, false, false, false, 2, true)
            SetEntityLodDist(e, Config.BoardLodDist)
            parts[#parts + 1] = e
        end
    end
end

-- For /skatetest and the tests: the objects on the board.
function Deck.parts() return parts end

-- What the board is, in words (and for the tests).
function Deck.describe()
    local out = {}
    for _, kind in ipairs(KINDS) do
        local p = current(kind)
        out[kind] = p and p.id or false
    end
    return out
end

-- ------------------------------------------------------------------ the server's word

RegisterNetEvent('skateboard:deckState', function(s, err, code)
    if type(s) ~= 'table' then return end
    local before = Deck.describe()
    state = s
    -- the page asked: it gets the answer (and shows what went wrong itself); otherwise it is told what is new
    local answer = table.remove(page.waiting, 1)
    if answer then
        answer(err, code)
    else
        if err then say('~r~' .. tostring(err)) end
        if page.open then SendNUIMessage({ t = 'designer_state', state = state }) end
    end
    local now = Deck.describe()
    for _, kind in ipairs(KINDS) do
        if before[kind] ~= now[kind] then
            -- (client.lua sets this: a board lying on the ground is rebuilt at once, a ridden one at the next mount)
            if Deck.changed then Deck.changed() end
            break
        end
    end
end)

local function ask()
    data = nil -- (skate3_assets may have been rebuilt)
    if catalogue() then TriggerServerEvent('skateboard:deckState') end
end

CreateThread(ask)
AddEventHandler('onClientResourceStart', function(res)
    if res == 'skate3_assets' then ask() end
end)

-- ------------------------------------------------------------------ choosing without the shop's page

-- ------------------------------------------------------------------ the shop's page (html/designer.*)

-- Open Skate 3's board section as a page over the game: browse decks, trucks and wheels, buy them, put them on.
function Deck.open()
    if page.open then return end
    if not catalogue() then return say('Skate 3\'s board parts are not installed on this server.') end
    page.open, page.waiting = true, {}
    SetNuiFocus(true, true)
    SendNUIMessage({ t = 'designer', open = true, resource = GetCurrentResourceName(),
                     assets = 'https://cfx-nui-skate3_assets/', state = state or { owned = {}, design = {}, money = false } })
    TriggerServerEvent('skateboard:deckState') -- (the money may have changed since it was last asked)
    CreateThread(function()
        -- the page has the keyboard and the mouse; a controller would still walk the player about
        while page.open do
            DisableAllControlActions(0)
            Wait(0)
        end
    end)
end

function Deck.close()
    if not page.open then return end
    page.open, page.waiting = false, {}
    SetNuiFocus(false, false)
    SendNUIMessage({ t = 'designer', open = false })
end

RegisterNUICallback('designer_close', function(_, cb)
    Deck.close()
    cb({ ok = true, error = false })
end)

-- A part picked in the page: the server buys it if need be and puts it on; the page gets the server's answer.
RegisterNUICallback('designer_pick', function(data, cb)
    if type(data) ~= 'table' or type(data.kind) ~= 'string' or type(data.id) ~= 'string' then
        return cb({ ok = false, error = 'That is not a part.', code = 'unknown', state = state })
    end
    local done = false
    local function answer(err, code)
        if done then return end
        done = true
        cb({ ok = not err, error = err or false, code = code or false, state = state })
    end
    page.waiting[#page.waiting + 1] = answer
    TriggerServerEvent('skateboard:deckPick', data.kind, data.id, true)
    CreateThread(function()
        Wait(5000)
        if not done then
            for i, w in ipairs(page.waiting) do
                if w == answer then table.remove(page.waiting, i) break end
            end
            answer('The shop did not answer.', 'timeout')
        end
    end)
end)

AddEventHandler('onResourceStop', function(res)
    if res == GetCurrentResourceName() and page.open then SetNuiFocus(false, false) end
end)

-- /skatedeck, /skatetruck, /skatewheel:  no argument = what is on the board (at a skate shop /skatedeck opens the
-- shop's page instead);  next / prev = the next of my parts;  <id> = that part. Buying is the skate shop's business:
-- these only switch among the parts I own.
local function choose(kind, arg)
    local d = catalogue()
    if not d then return say('Skate 3\'s board parts are not installed on this server.') end
    local cur = current(kind)
    if not arg and kind == 'deck' and (Config.Decks.anywhere or SkateShopNear()) then return Deck.open() end
    if not arg then return say(('%s: %s (%s)'):format(kind, cur.name, cur.id)) end
    local list, want = d[LIST[kind]], nil
    arg = tostring(arg):lower()
    if arg == 'next' or arg == 'prev' then
        local owned = {}
        for _, id in ipairs(state and state.owned and state.owned[kind] or {}) do owned[id] = true end
        local step, i = arg == 'next' and 1 or -1, cur.index
        for _ = 1, #list do
            i = (i - 1 + step) % #list + 1
            if owned[list[i].id] then want = list[i] break end
        end
        if not want then return say('You own no other ' .. kind .. '.') end
    else
        want = d.byId[kind][arg]
        if not want then return say(('No %s is called "%s".'):format(kind, arg)) end
    end
    TriggerServerEvent('skateboard:deckPick', kind, want.id)
    say(('%s: %s'):format(kind, want.name))
end

RegisterCommand('skatedeck', function(_, args) choose('deck', args[1]) end, false)
RegisterCommand('skatetruck', function(_, args) choose('truck', args[1]) end, false)
RegisterCommand('skatewheel', function(_, args) choose('wheel', args[1]) end, false)

AddEventHandler('onResourceStop', function(res)
    if res == GetCurrentResourceName() then Deck.undress() end
end)
