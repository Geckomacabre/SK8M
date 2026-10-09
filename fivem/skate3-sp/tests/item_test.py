"""Offline test of the ox_inventory / ox_target flow: client.lua + server.lua in one Lua state, natives stubbed."""
import os

from lupa import lua54

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "skateboard"))
L = lua54.LuaRuntime(unpack_returned_tuples=True)

L.execute(r'''
local V = {}
V.__index = V
function vector3(x, y, z) return setmetatable({x = x, y = y, z = z}, V) end
V.__add = function(a, b) return vector3(a.x + b.x, a.y + b.y, a.z + b.z) end
V.__sub = function(a, b) return vector3(a.x - b.x, a.y - b.y, a.z - b.z) end
V.__mul = function(a, s) return vector3(a.x * s, a.y * s, a.z * s) end
V.__len = function(a) return math.sqrt(a.x * a.x + a.y * a.y + a.z * a.z) end

LOG, NOTES, NET, CLIENT_EVENTS, SERVER_EVENTS, EXPORTS = {}, {}, {}, {}, {}, {}
STATE = { ox_inventory = 'started', ox_target = 'missing' }
ITEMS = 0
TARGETS = {}
local t = 0
function GetGameTimer() t = t + 16 return t end
function ADVANCE(ms) t = t + ms end -- a real player doesn't press F6 again within 0.75 s
function Wait() end
RUN_THREADS = false -- threads created while the file loads are the endless main loops; skip those
function CreateThread(fn) if RUN_THREADS then fn() end end
function GetResourceState(r) return STATE[r] or 'missing' end
function RegisterNetEvent(name, fn) if fn then (IS_SERVER and SERVER_EVENTS or CLIENT_EVENTS)[name] = fn end end
function AddEventHandler(name, fn) end
function TriggerServerEvent(name, ...) source = 1; SERVER_EVENTS[name](...) end
function TriggerClientEvent(name, target, ...) CLIENT_EVENTS[name](...) end
COMMANDS = {}
function RegisterCommand(name, fn) COMMANDS[name] = fn end
function RegisterKeyMapping() end

local inv = { GetItemCount = function(self, src, item) return ITEMS end }
local target = {
  addLocalEntity = function(self, ent, opts) TARGETS[ent] = opts end,
  removeLocalEntity = function(self, ent) TARGETS[ent] = nil end,
}
exports = setmetatable({}, {
  __call = function(_, name, fn) EXPORTS[name] = fn end,
  __index = function(_, res)
    if res == 'ox_inventory' then return inv end
    if res == 'ox_target' then
      if STATE.ox_target ~= 'started' then error('ox_target not started') end
      return target
    end
  end,
})

local pedPos = vector3(0, 0, 1)
local ents, nextEnt = {}, 100
function PlayerPedId() return 1 end
function GetEntityCoords(e) if e == 1 then return pedPos end return ents[e] or vector3(0, 0, 0) end
function DoesEntityExist(e) return e == 1 or ents[e] ~= nil end
function CreateObject(model, x, y, z) nextEnt = nextEnt + 1; ents[nextEnt] = vector3(x, y, z); LOG[#LOG+1] = 'create'; return nextEnt end
function DeleteObject(e) ents[e] = nil; LOG[#LOG+1] = 'delete' end
function SetEntityCoords(e, x, y, z) if ents[e] then ents[e] = vector3(x, y, z) end end
function SetEntityCoordsNoOffset(e, x, y, z) if e == 1 then pedPos = vector3(x, y, z) elseif ents[e] then ents[e] = vector3(x, y, z) end end
function IsModelInCdimage() return true end
function HasModelLoaded() return true end
function DoesAnimDictExist() return true end
function HasAnimDictLoaded() return true end
function IsPedInAnyVehicle() return false end
function IsEntityDead() return false end
function GetEntityHeading() return 0.0 end
function StartExpensiveSynchronousShapeTestLosProbe() return 1 end
function GetShapeTestResult() return 2, 1, vector3(pedPos.x, pedPos.y, 0), vector3(0, 0, 1) end
function BeginTextCommandThefeedPost() end
function AddTextComponentSubstringPlayerName(s) NOTES[#NOTES+1] = s end
function EndTextCommandThefeedPostTicker() end
setmetatable(_G, { __index = function(_, k) return function() return 0 end end })
''')

L.execute(open(ROOT + r"\config.lua", encoding="utf-8").read())
L.execute("Config.SkateCam = false")
L.execute("IS_SERVER = true")
L.execute(open(ROOT + r"\server.lua", encoding="utf-8").read())
L.execute(open(ROOT + r"\s3.lua", encoding="utf-8").read())
L.execute("IS_SERVER = false")
api = L.execute(open(ROOT + r"\client.lua", encoding="utf-8").read() + r'''
return {
  state = function() return riding, board, targetAdded end,
  getOff = getOff, pickUp = pickUp,
}
''')
G = L.globals()
G.RUN_THREADS = True
ok = True


def check(label, cond):
    global ok
    ok &= bool(cond)
    print(("OK  " if cond else "BAD ") + label)


def notes():
    return [n for n in G.NOTES.values()]


_cmd = G.COMMANDS['skateboard']
_use = G.EXPORTS['useBoard']


class _Later:
    """Wrap a call so a second passes first (past the server's request cache)."""
    def __init__(self, fn):
        self.fn = fn

    def __call__(self, *a):
        G.ADVANCE(1000)
        return self.fn(*a)


G.COMMANDS['skateboard'] = _Later(_cmd)
G.EXPORTS['useBoard'] = _Later(_use)


# 1. no item: F6 refuses and says why
G.ITEMS = 0
G.COMMANDS['skateboard']()
riding, board, _ = api.state()
check("no item -> not riding, no board", not riding and not board)
check("no item -> told you need a skateboard", any('need a skateboard' in n for n in notes()))

# 2. with the item: F6 drops a board and you're on it
G.ITEMS = 1
G.COMMANDS['skateboard']()
riding, board, _ = api.state()
check("item -> riding with a board", riding and board)

# 3. F6 again: step off, board stays on the ground
G.COMMANDS['skateboard']()
riding, board, _ = api.state()
check("step off -> board left on the ground", not riding and board)

# 4. inventory 'use' while the board is down: get back on (no new board)
creates_before = list(G.LOG.values()).count('create')
G.EXPORTS['useBoard']()
riding, board2, _ = api.state()
check("use item next to board -> back on the same board", riding and board2 == board
      and list(G.LOG.values()).count('create') == creates_before)

# 5. inventory 'use' while riding: step off and pick it up
G.EXPORTS['useBoard']()
riding, board3, _ = api.state()
check("use item while riding -> off and board picked up", not riding and not board3
      and list(G.LOG.values())[-1] == 'delete')

# 6. ox_target running: options are added to the board, and removed when it's picked up
G.STATE.ox_target = 'started'
G.COMMANDS['skateboard']()      # on (new board)
G.COMMANDS['skateboard']()      # off
riding, board4, target_added = api.state()
opts = G.TARGETS[board4]
names = [opts[i].name for i in range(1, len(opts) + 1)] if opts else []
check("ox_target options on the board: " + ", ".join(names), target_added and names == ['skateboard_ride', 'skateboard_pickup'])
opts[2].onSelect()               # "Pick up skateboard"
riding, board5, _ = api.state()
check("ox_target pick up removes board and its options", not board5 and G.TARGETS[board4] is None)

# 7. without ox_inventory, anyone can skate
G.STATE.ox_inventory = 'missing'
G.ITEMS = 0
G.COMMANDS['skateboard']()
riding, board6, _ = api.state()
check("no ox_inventory -> free board", riding and board6)

print("ALL OK" if ok else "FAILURES")
