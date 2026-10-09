-- The skate shop: a shopkeeper standing where an admin put one (/skateshop place, see server.lua) or where
-- config.lua says. With ox_inventory running the shopkeeper sells the skate items through ox_inventory's own shop
-- window (the money is ox_inventory's business); with or without it you can try helmets on there.
-- The server keeps the list of shops and sends it; this file only shows them.

local shops = {}          -- { { x, y, z, h } } as the server has them
local shown = {}          -- [index] = { ped, blip, target }
local keeper              -- the shopkeeper's model, once it is in memory

local function hasInventory() return GetResourceState('ox_inventory') == 'started' end
local function hasTarget() return Config.UseTarget and GetResourceState('ox_target') == 'started' end

local function say(msg)
    BeginTextCommandThefeedPost('STRING')
    AddTextComponentSubstringPlayerName(msg)
    EndTextCommandThefeedPostTicker(false, false)
end

local function openShop(i)
    if not hasInventory() then
        say('This shop sells through ox_inventory, which is not running. Helmets: /skatehelmet next.')
        return
    end
    exports.ox_inventory:openInventory('shop', { type = Config.Shop.id, id = i })
end

local function removePed(e)
    if e.ped and DoesEntityExist(e.ped) then
        if e.target then pcall(function() exports.ox_target:removeLocalEntity(e.ped, { 'skateshop_buy', 'skateshop_board', 'skateshop_next', 'skateshop_prev' }) end) end
        DeleteEntity(e.ped)
    end
    e.ped, e.target = nil, nil
end

local function clear()
    for _, e in pairs(shown) do
        removePed(e)
        if e.blip and DoesBlipExist(e.blip) then RemoveBlip(e.blip) end
    end
    shown = {}
end

local function addBlip(s)
    local b = Config.Shop.blip
    if not b then return nil end
    local blip = AddBlipForCoord(s.x, s.y, s.z)
    SetBlipSprite(blip, b.sprite)
    SetBlipColour(blip, b.colour)
    SetBlipScale(blip, b.scale)
    SetBlipAsShortRange(blip, true)
    BeginTextCommandSetBlipName('STRING')
    AddTextComponentSubstringPlayerName(Config.Shop.name)
    EndTextCommandSetBlipName(blip)
    return blip
end

local function addPed(i, s, e)
    local model = joaat(Config.Shop.ped)
    if not keeper then
        if not IsModelInCdimage(model) then return end
        RequestModel(model)
        local deadline = GetGameTimer() + 5000
        while not HasModelLoaded(model) and GetGameTimer() < deadline do Wait(50) end
        if not HasModelLoaded(model) then return end
        keeper = model
    end
    local ped = CreatePed(4, model, s.x, s.y, s.z - 1.0, s.h, false, true)
    if not ped or ped == 0 then return end
    FreezeEntityPosition(ped, true)
    SetEntityInvincible(ped, true)
    SetBlockingOfNonTemporaryEvents(ped, true)
    TaskStartScenarioInPlace(ped, Config.Shop.scenario, 0, true)
    e.ped = ped
    if hasTarget() then
        e.target = pcall(function()
            exports.ox_target:addLocalEntity(ped, {
                { name = 'skateshop_buy', icon = 'fa-solid fa-store', label = Config.Shop.name, distance = 2.5,
                  canInteract = hasInventory, onSelect = function() openShop(i) end },
                { name = 'skateshop_board', icon = 'fa-solid fa-person-skating', label = 'Skateboard: deck, trucks, wheels',
                  distance = 2.5, canInteract = function() return Deck.available() end,
                  onSelect = function() Deck.open() end },
                { name = 'skateshop_next', icon = 'fa-solid fa-helmet-safety', label = 'Try the next helmet', distance = 2.5,
                  canInteract = function() return Config.Helmet.enabled end,
                  onSelect = function() ExecuteCommand('skatehelmet next') end },
                { name = 'skateshop_prev', icon = 'fa-solid fa-helmet-safety', label = 'Try the helmet before', distance = 2.5,
                  canInteract = function() return Config.Helmet.enabled end,
                  onSelect = function() ExecuteCommand('skatehelmet prev') end },
            })
        end)
    end
end

-- Is the player at a skate shop (within a few steps of a shopkeeper)? /skatedeck opens the board page there.
function SkateShopNear()
    local here = GetEntityCoords(PlayerPedId())
    for _, s in ipairs(shops) do
        if #(here - vector3(s.x, s.y, s.z)) < 4.0 then return true end
    end
    return false
end

RegisterNetEvent('skateboard:shopList', function(list)
    if not Config.Shop.enabled then return end
    clear()
    shops = type(list) == 'table' and list or {}
    for i, s in ipairs(shops) do shown[i] = { blip = addBlip(s) } end
end)

CreateThread(function()
    if not Config.Shop.enabled then return end
    TriggerServerEvent('skateboard:shops')
    while true do
        local here = GetEntityCoords(PlayerPedId())
        local near
        for i, s in ipairs(shops) do
            local e = shown[i]
            local d = #(here - vector3(s.x, s.y, s.z))
            -- the shopkeeper is there while you are near (and gone again when you are far off)
            if e and d < 60.0 and not (e.ped and DoesEntityExist(e.ped)) then
                addPed(i, s, e)
            elseif e and d > 80.0 and e.ped then
                removePed(e)
            end
            if e and e.ped and not e.target and d < 2.0 then near = i end
        end
        if near then
            -- no ox_target: stand by the shopkeeper and press E for the shop, G for the board parts
            local board = Deck.available()
            BeginTextCommandDisplayHelp('STRING')
            AddTextComponentSubstringPlayerName('~INPUT_CONTEXT~ ' .. Config.Shop.name ..
                (board and '   ~INPUT_DETONATE~ Skateboard: deck, trucks, wheels' or ''))
            EndTextCommandDisplayHelp(0, false, false, -1)
            if IsControlJustPressed(0, 51) then
                openShop(near)
            elseif board and IsControlJustPressed(0, 47) then
                Deck.open()
            end
        end
        Wait(near and 0 or 500)
    end
end)

AddEventHandler('onResourceStop', function(res)
    if res == GetCurrentResourceName() then clear() end
end)
