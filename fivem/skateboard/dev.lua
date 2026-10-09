-- Who may use the test tools: /skatetest, /skateramp and skate3_assets' own /s3... commands. They move the player,
-- make ramps and drive the controls, so on a public server they are for its admins. Config.TestCommands:
--   'admin' = the players the server says may (see server.lua),  true = everyone,  false = nobody.
-- (These are commands of the player's own game: the check keeps them out of ordinary players' hands. It is not what
-- stops a cheat, and nothing here is trusted by the server.)
Dev = { why = 'This command is for the server\'s admins (ace "skateboard.dev").' }

local allowed -- the server's answer, once it has come

RegisterNetEvent('skateboard:mayTest', function(yes) allowed = yes == true end)

local asked = -10000
local function ask()
    local now = GetGameTimer()
    if now - asked < 2000 then return end
    asked = now
    TriggerServerEvent('skateboard:mayTest')
end

function Dev.may()
    local t = Config.TestCommands
    if t == true then return true end
    if t ~= 'admin' then return false end
    if allowed ~= true then ask() end -- (told no: perhaps the permission has been given since; the next try will know)
    return allowed == true
end

CreateThread(function()
    -- (asked again now and then: permissions are given and taken while the server runs)
    while Config.TestCommands == 'admin' do
        asked = GetGameTimer()
        TriggerServerEvent('skateboard:mayTest')
        Wait(allowed == nil and 5000 or 60000)
    end
end)

exports('devAllowed', function() return Dev.may() end)
