-- The client asks before dropping a board; the server checks the player owns the item. Nothing is ever given
-- or taken here: the item stays in the inventory while you ride, so there is nothing to dupe or lose.

local cache = {} -- [source] = { time, result } so spammed requests reuse the last answer

local function ownsBoard(src)
    if not Config.RequireItem or GetResourceState('ox_inventory') ~= 'started' then return true end
    return (exports.ox_inventory:GetItemCount(src, Config.ItemName) or 0) > 0
end

RegisterNetEvent('skateboard:requestBoard', function()
    local src = source
    local now = GetGameTimer()
    local c = cache[src]
    if not c or now - c.time >= 750 then
        c = { time = now, result = ownsBoard(src) }
        cache[src] = c
    end
    TriggerClientEvent('skateboard:boardReply', src, c.result)
end)

local function ace(src, name)
    local v = IsPlayerAceAllowed(src, name)
    return v == true or v == 1
end

-- The test tools are for the server's admins unless config.lua says otherwise (see dev.lua).
RegisterNetEvent('skateboard:mayTest', function()
    local src = source
    local t, yes = Config.TestCommands, false
    if t == true then
        yes = true
    elseif t == 'admin' then
        yes = ace(src, 'skateboard.dev') or ace(src, 'group.admin')
    end
    TriggerClientEvent('skateboard:mayTest', src, yes)
end)

-- Who may place and remove skate shops: the server's admins. The check is made here, not left to the command's own
-- "restricted" switch: that wants the ace command.skateshop, and a server that hands its admins their commands one
-- by one never gave it (on the server this was made for, nobody could place a shop).
local function shopAdmin(src)
    return ace(src, 'command.skateshop') or ace(src, 'skateboard.admin') or ace(src, 'skateboard.dev') or
        ace(src, 'group.admin')
end

-- The same question for the helmet (/skatehelmet; using the item itself goes through ox_inventory, which has
-- already checked it).
local helmets = {}
RegisterNetEvent('skateboard:requestHelmet', function()
    local src = source
    local now = GetGameTimer()
    local c = helmets[src]
    if not c or now - c.time >= 750 then
        local need = Config.Helmet.enabled and Config.RequireItem and GetResourceState('ox_inventory') == 'started'
        c = { time = now, result = Config.Helmet.enabled and
            (not need or (exports.ox_inventory:GetItemCount(src, Config.Helmet.item) or 0) > 0) }
        helmets[src] = c
    end
    TriggerClientEvent('skateboard:helmetReply', src, c.result)
end)

AddEventHandler('playerDropped', function()
    cache[source] = nil
    helmets[source] = nil
end)

-- ------------------------------------------------------------------ the skate shops
-- The list of shops ({ x, y, z, h }): the ones in config.lua and the ones admins have placed, which are kept in
-- this resource's own storage on the server. Clients are sent the list; ox_inventory is told what the shops sell.

local placed = {}

local function shopList()
    local list = {}
    for _, s in ipairs(Config.Shop.locations) do list[#list + 1] = { x = s.x or s[1], y = s.y or s[2], z = s.z or s[3], h = s.h or s[4] or 0.0 } end
    for _, s in ipairs(placed) do list[#list + 1] = s end
    return list
end

local function registerShops()
    if not Config.Shop.enabled or GetResourceState('ox_inventory') ~= 'started' then return end
    -- (ox_inventory looks under `targets` when it runs with ox_target and under `locations` when not)
    local spots, targets = {}, {}
    for i, s in ipairs(shopList()) do
        spots[i] = vector3(s.x, s.y, s.z)
        targets[i] = { loc = spots[i], distance = 3.0 }
    end
    exports.ox_inventory:RegisterShop(Config.Shop.id, { name = Config.Shop.name, inventory = Config.Shop.items,
                                                       locations = spots, targets = targets })
end

local function shopsChanged()
    SetResourceKvp('skateshops', json.encode(placed))
    registerShops()
    TriggerClientEvent('skateboard:shopList', -1, shopList())
end

if Config.Shop.enabled then
    local saved = GetResourceKvpString('skateshops')
    local ok, list = pcall(function() return saved and json.decode(saved) or {} end)
    placed = (ok and type(list) == 'table') and list or {}
    registerShops()
end

RegisterNetEvent('skateboard:shops', function()
    if Config.Shop.enabled then TriggerClientEvent('skateboard:shopList', source, shopList()) end
end)

AddEventHandler('onResourceStart', function(res)
    if res == 'ox_inventory' then registerShops() end -- (it has forgotten the shops)
end)

-- /skateshop place | remove | list. Admins only: the command is restricted (the ace "command.skateshop").
RegisterCommand('skateshop', function(src, args)
    if not Config.Shop.enabled or src == 0 then return end
    local function tell(msg) TriggerClientEvent('chat:addMessage', src, { args = { 'skate shop', msg } }) end
    if not shopAdmin(src) then
        return tell('Placing shops is for the server\'s admins (ace "skateboard.admin", or the group "group.admin").')
    end
    local ped = GetPlayerPed(src)
    local c, what = GetEntityCoords(ped), (args[1] or ''):lower()
    if what == 'place' then
        placed[#placed + 1] = { x = c.x, y = c.y, z = c.z, h = GetEntityHeading(ped) }
        shopsChanged()
        tell(('Shop %d placed here.'):format(#shopList()))
    elseif what == 'remove' then
        local best, bestD
        for i, s in ipairs(placed) do
            local d = #(c - vector3(s.x, s.y, s.z))
            if d < 30.0 and (not best or d < bestD) then best, bestD = i, d end
        end
        if not best then return tell('No placed shop within 30 m. (Shops from config.lua are taken out there.)') end
        table.remove(placed, best)
        shopsChanged()
        tell('Shop removed.')
    elseif what == 'list' then
        local list = shopList()
        if #list == 0 then return tell('No shops yet: /skateshop place puts one where you stand.') end
        for i, s in ipairs(list) do tell(('%d: %.1f, %.1f, %.1f'):format(i, s.x, s.y, s.z)) end
    else
        tell('/skateshop place | remove | list')
    end
end, false)
