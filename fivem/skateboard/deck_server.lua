-- Each player's board parts, kept by the server: which Skate 3 decks, trucks and wheels they own and which three are on
-- their board. Clients only ask; nothing a client says is taken on trust (the part has to exist, has to be owned or
-- paid for, and the answer is what the server has stored).
-- The catalogue (ids and prices) is Skate 3's own, read from skate3_assets; without it there is nothing to choose.

local KINDS = { deck = 'stock', truck = 'trucks', wheel = 'wheels' }
local cat              -- { deck = { [id] = part }, truck = ..., wheel = ..., default = { deck, truck, wheel } }
local players = {}     -- [licence] = { owned = { deck = { [id] = true } ... }, design = { deck, truck, wheel } }

local function catalogue()
    if cat ~= nil then return cat or nil end
    cat = false
    if Config.Decks.enabled and GetResourceState('skate3_assets') == 'started' then
        local ok, t = pcall(function() return exports.skate3_assets:Decks() end)
        if ok and type(t) == 'table' and type(t.default) == 'table' then
            cat = { default = t.default }
            for kind, list in pairs(KINDS) do
                cat[kind] = {}
                for _, p in ipairs(t[list] or {}) do cat[kind][p.id] = p end
            end
        end
    end
    return cat or nil
end

AddEventHandler('onResourceStart', function(res)
    if res == 'skate3_assets' then cat = nil end -- (it may have been rebuilt)
end)

local function licence(src)
    return GetPlayerIdentifierByType(src, 'license') or ('player:' .. tostring(src))
end

local function load(src)
    local key = licence(src)
    local p = players[key]
    if not p then
        local saved = GetResourceKvpString('deck:' .. key)
        local ok, t = pcall(function() return saved and json.decode(saved) or nil end)
        p = (ok and type(t) == 'table') and t or {}
        p.owned = type(p.owned) == 'table' and p.owned or {}
        p.design = type(p.design) == 'table' and p.design or {}
        players[key] = p
    end
    -- everybody owns the board nobody has designed yet; a part that has left the catalogue is not on a board
    local c = catalogue()
    for kind in pairs(KINDS) do
        p.owned[kind] = type(p.owned[kind]) == 'table' and p.owned[kind] or {}
        if c then
            p.owned[kind][c.default[kind]] = true
            if type(p.design[kind]) ~= 'string' or not c[kind][p.design[kind]] then p.design[kind] = c.default[kind] end
        end
    end
    return p, key
end

local function save(key)
    SetResourceKvp('deck:' .. key, json.encode(players[key]))
end

local function hasMoney() return not Config.Decks.free and GetResourceState('ox_inventory') == 'started' end

-- What a client is told: the ids it owns per kind (everything, when parts cost nothing), its board, its money.
local function stateOf(src)
    local c = catalogue()
    if not c then return nil end
    local p = load(src)
    local owned = {}
    for kind in pairs(KINDS) do
        owned[kind] = {}
        for id in pairs(hasMoney() and p.owned[kind] or c[kind]) do owned[kind][#owned[kind] + 1] = id end
        table.sort(owned[kind])
    end
    return { owned = owned, design = { deck = p.design.deck, truck = p.design.truck, wheel = p.design.wheel },
             money = hasMoney() and (exports.ox_inventory:GetItemCount(src, Config.Decks.currency) or 0) or false }
end

RegisterNetEvent('skateboard:deckState', function()
    local src = source
    local s = stateOf(src)
    if s then TriggerClientEvent('skateboard:deckState', src, s) end
end)

-- Put a part on my board; buy it first if I do not own it. buy = false: only switch to a part I own (the commands).
RegisterNetEvent('skateboard:deckPick', function(kind, id, buy)
    local src = source
    local c = catalogue()
    if not c or type(kind) ~= 'string' or type(id) ~= 'string' or not KINDS[kind] or #id > 64 then return end
    local part = c[kind][id]
    local p, key = load(src)
    local err, code
    if not part then
        err, code = 'There is no such part.', 'unknown'
    elseif hasMoney() and not p.owned[kind][id] then
        local price = math.max(0, math.floor(tonumber(part.price) or 0))
        if buy ~= true then
            err, code = 'You do not own that one. The skate shop sells it.', 'notowned'
        elseif price > 0 and (exports.ox_inventory:GetItemCount(src, Config.Decks.currency) or 0) < price then
            err, code = 'You cannot afford that.', 'funds'
        elseif price > 0 and not exports.ox_inventory:RemoveItem(src, Config.Decks.currency, price) then
            err, code = 'The payment did not go through.', 'pay'
        else
            p.owned[kind][id] = true
        end
    end
    if not err then
        p.design[kind] = id
        save(key)
    end
    TriggerClientEvent('skateboard:deckState', src, stateOf(src), err, code)
end)

AddEventHandler('playerDropped', function()
    players[licence(source)] = nil -- (it is in storage; this is only the copy in memory)
end)
