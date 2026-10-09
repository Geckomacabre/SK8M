"""A small FiveM client simulator for testing the skateboard resources offline (Python + lupa, Lua 5.4).

What it models, because each of these has bitten this project in the real game:
  * every global the scripts touch must be a real FiveM native (checked against the native database, by name or
    alias), called with the right NUMBER of arguments and plausible types; anything else is recorded in
    `sim.violations` and fails the test;
  * SetEntityCoordsNoOffset(ped, x, y, z, keepTasks, ...) with keepTasks = false clears the ped's tasks, i.e. stops
    the clip that is playing (the bug that kept the Skate 3 clips from ever playing in game);
  * a clip started with TaskPlayAnim only counts as playing from the next frame;
  * each resource has its own globals; exports copy their arguments (a table changed on the far side does not
    change the caller's);
  * threads are coroutines that run once per frame, resource by resource in start order.

The world is a set of boxes (floor, rails, ledges, walls) that the shape-test natives hit. A box can be turned
about its own middle (a rail at any heading) and can have a surface material.

Native database: fivem_natives.json + fivem_natives_cfx.json (kept on the server PC under _tools/nativedb_src; a
local copy next to this file, or in $NATIVE_DB, is used when present).
"""
import json
import math
import os
import re
import shutil

from lupa import lua54

HERE = os.path.dirname(os.path.abspath(__file__))
import sys  # noqa: E402
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import paths  # noqa: E402
DB_SRC = paths.NATIVE_DB    # where the native reference is copied from the first time (tools/paths.py)
DB_DIR = os.environ.get("NATIVE_DB") or os.path.join(HERE, "nativedb")


def _load_db():
    os.makedirs(DB_DIR, exist_ok=True)
    out = {}
    for name in ("fivem_natives.json", "fivem_natives_cfx.json"):
        local = os.path.join(DB_DIR, name)
        if not os.path.exists(local):
            shutil.copy2(os.path.join(DB_SRC, name), local)
        for natives in json.load(open(local, encoding="utf-8")).values():
            for h, n in natives.items():
                names = [n.get("name")] + list(n.get("aliases") or [])
                for nm in names:
                    if nm and not nm.startswith("0x"):
                        out.setdefault(lua_name(nm), n)
    return out


def lua_name(native):
    """SCREAMING_SNAKE (optionally with a leading underscore) -> the Lua global FiveM generates for it."""
    parts = [p for p in native.strip("_").split("_") if p]
    out = ""
    for p in parts:
        word = p[0].upper() + p[1:].lower()
        out += ("_" + word) if p[0].isdigit() else word
    return out


def _spec(n):
    """How a native is called from Lua: (argument types, result kind). Out-pointers are returned, not passed -
    except when the only pointer is the first parameter (DeleteObject(obj)), as FiveM's own generator does."""
    params = n.get("params", [])
    pointers = [p for p in params if p["type"].endswith("*") and p["type"] != "char*"]
    single = len(pointers) == 1 and params and params[0] is pointers[0]
    args = [p["type"] for p in params if single or p not in pointers]
    loose = any(t.startswith("Any") or t == "Vector3" for t in (p["type"] for p in params))
    return args, (n.get("results") or "void"), loose


PRELUDE = r'''
local V = {}
V.__index = V
function vector3(x, y, z) return setmetatable({x = x, y = y, z = z}, V) end
V.__add = function(a, b) return vector3(a.x + b.x, a.y + b.y, a.z + b.z) end
V.__sub = function(a, b) return vector3(a.x - b.x, a.y - b.y, a.z - b.z) end
V.__mul = function(a, s)
  if type(a) == 'number' then a, s = s, a end
  return vector3(a.x * s, a.y * s, a.z * s)
end
V.__div = function(a, s) return vector3(a.x / s, a.y / s, a.z / s) end
V.__unm = function(a) return vector3(-a.x, -a.y, -a.z) end
V.__len = function(a) return math.sqrt(a.x * a.x + a.y * a.y + a.z * a.z) end
V.__eq = function(a, b) return a.x == b.x and a.y == b.y and a.z == b.z end
vec3 = vector3
local function isvec(v) return getmetatable(v) == V end

SIM = {
  now = 0.0, dt = 1 / 60, frame = 0,
  input = { normal = {}, pressed = {}, just = {} }, keyboard = false,
  ent = {}, nextEnt = 100, ped = 1, pedModel = 1885233650,
  anim = nil, upper = nil, played = {}, log = {}, prints = {}, violations = {}, events = {},
  modelDims = {}, props = {}, propCount = 40, blips = {},
  boxes = {}, skelOffset = vector3(0, 0, 0), boardDims = { vector3(-0.45, -0.12, 0.0), vector3(0.45, 0.12, 0.144) },
  resources = {}, order = {}, commands = {}, state = {}, tracks = nil, clipLength = nil,
  dictsLoaded = true, keepTasksMatters = true,
  optional = { SkateBoardTracks = true, Skate3Tuning = true, Skate3Sounds = true, Skate3Decks = true },
  nui = {},
}
local S = SIM
S.ent[1] = { pos = vector3(0, 0, 1), q = {0, 0, 0, 1}, heading = 0.0, ped = true }

local function violation(msg)
  S.violations[#S.violations + 1] = msg
end

-- ---------------------------------------------------------------- exports (arguments are copied, like msgpack)
local function copy(v, depth)
  local t = type(v)
  if t == 'table' then
    if isvec(v) then return vector3(v.x, v.y, v.z) end
    if getmetatable(v) then error('a table with a metatable cannot cross an export') end
    local out = {}
    for k, x in pairs(v) do out[copy(k, depth + 1)] = copy(x, depth + 1) end
    return out
  elseif t == 'thread' or t == 'userdata' then
    error('a ' .. t .. ' cannot cross an export')
  end
  return v -- numbers, strings, booleans; functions cross as references
end
local function copyAll(...)
  local n = select('#', ...)
  local out = {}
  for i = 1, n do out[i] = copy((select(i, ...)), 0) end
  return table.unpack(out, 1, n)
end

local registry = {}
local function makeExports(resName)
  return setmetatable({}, {
    __call = function(_, name, fn) registry[resName] = registry[resName] or {}; registry[resName][name] = fn end,
    __index = function(_, res)
      if S.state[res] ~= 'started' then error('No such export resource ' .. tostring(res)) end
      return setmetatable({}, { __index = function(_, name)
        local fn = registry[res] and registry[res][name]
        if not fn then error('No such export ' .. tostring(name) .. ' in resource ' .. tostring(res)) end
        return function(_, ...) return copyAll(fn(copyAll(...))) end
      end })
    end,
  })
end

-- ---------------------------------------------------------------- world: ray against axis-aligned boxes
local function rayBox(b, x1, y1, z1, x2, y2, z2)
  local o, d = { x1, y1, z1 }, { x2 - x1, y2 - y1, z2 - z1 }
  local lo, hi = { b[1], b[2], b[3] }, { b[4], b[5], b[6] }
  local tmin, tmax, axis, sgn = 0.0, 1.0, nil, 0
  for i = 1, 3 do
    if math.abs(d[i]) < 1e-12 then
      if o[i] < lo[i] or o[i] > hi[i] then return nil end
    else
      local t1, t2 = (lo[i] - o[i]) / d[i], (hi[i] - o[i]) / d[i]
      local s = -1
      if t1 > t2 then t1, t2, s = t2, t1, 1 end
      if t1 > tmin then tmin, axis, sgn = t1, i, s end
      if t2 < tmax then tmax = t2 end
      if tmin > tmax then return nil end
    end
  end
  if not axis then return nil end -- started inside the box
  local n = { 0, 0, 0 }
  n[axis] = sgn
  return tmin, vector3(n[1], n[2], n[3])
end

-- b[7] = the box turned by this many degrees about its own middle (GTA heading: anticlockwise seen from above)
local function rayTurnedBox(b, x1, y1, z1, x2, y2, z2)
  local yaw = b[7] or 0.0
  if yaw == 0.0 then return rayBox(b, x1, y1, z1, x2, y2, z2) end
  local cx, cy = (b[1] + b[4]) * 0.5, (b[2] + b[5]) * 0.5
  local c, s = math.cos(math.rad(yaw)), math.sin(math.rad(yaw))
  local function inv(x, y) x, y = x - cx, y - cy; return cx + x * c + y * s, cy - x * s + y * c end
  local ax, ay = inv(x1, y1)
  local bx, by = inv(x2, y2)
  local t, n = rayBox(b, ax, ay, z1, bx, by, z2)
  if not t then return nil end
  return t, vector3(n.x * c - n.y * s, n.x * s + n.y * c, n.z)
end

-- A sloping top: z runs from r[5] at y = r[2] to r[6] at y = r[4], for x in r[1] .. r[3]. Solid from above only.
local function rayRamp(r, x1, y1, z1, x2, y2, z2)
  local dy, dz = r[4] - r[2], r[6] - r[5]
  local len = math.sqrt(dy * dy + dz * dz)
  local ny, nz = -dz / len, dy / len                 -- the top's normal
  local d1 = (y1 - r[2]) * ny + (z1 - r[5]) * nz     -- how far above the top the ray starts and ends
  local d2 = (y2 - r[2]) * ny + (z2 - r[5]) * nz
  if d1 < 0 or d2 > 0 or d1 == d2 then return nil end
  local t = d1 / (d1 - d2)
  local x, y = x1 + (x2 - x1) * t, y1 + (y2 - y1) * t
  if x < r[1] or x > r[3] or y < r[2] or y > r[4] then return nil end
  return t, vector3(0.0, ny, nz)
end

-- A triangle: t[1..9] its corners (anticlockwise seen from outside), t[10..12] its normal. Solid from outside only,
-- as the faces of the game's collision are.
local function rayTri(t, x1, y1, z1, x2, y2, z2)
  local nx, ny, nz = t[10], t[11], t[12]
  local d1 = (x1 - t[1]) * nx + (y1 - t[2]) * ny + (z1 - t[3]) * nz
  local d2 = (x2 - t[1]) * nx + (y2 - t[2]) * ny + (z2 - t[3]) * nz
  if d1 < 0 or d2 > 0 or d1 == d2 then return nil end
  local k = d1 / (d1 - d2)
  local px, py, pz = x1 + (x2 - x1) * k, y1 + (y2 - y1) * k, z1 + (z2 - z1) * k
  for i = 1, 7, 3 do
    local j = i < 7 and i + 3 or 1
    local ex, ey, ez = t[j] - t[i], t[j + 1] - t[i + 1], t[j + 2] - t[i + 2]
    local qx, qy, qz = px - t[i], py - t[i + 1], pz - t[i + 2]
    if (ey * qz - ez * qy) * nx + (ez * qx - ex * qz) * ny + (ex * qy - ey * qx) * nz < -1e-9 then return nil end
  end
  return k
end

-- does the stretch from 1 to 2 come near the box b (lo x, y, z, hi x, y, z)?
local function segBox(b, x1, y1, z1, x2, y2, z2)
  return math.max(x1, x2) >= b[1] and math.min(x1, x2) <= b[4] and math.max(y1, y2) >= b[2]
     and math.min(y1, y2) <= b[5] and math.max(z1, z2) >= b[3] and math.min(z1, z2) <= b[6]
end

local lastRay
local IMPL = {}
function IMPL.StartExpensiveSynchronousShapeTestLosProbe(x1, y1, z1, x2, y2, z2, flags, ignore, p8)
  lastRay = { x1, y1, z1, x2, y2, z2, flags, ignore }
  S.rays = (S.rays or 0) + 1
  return 1
end
-- A vehicle is a box turned to its heading (S.vehicle); rays see it only when they ask for vehicles (flag 2), and
-- the world only when they ask for the world (flag 1).
local function vehicleBox(v)
  local d = S.modelDims[v.model]
  return { v.pos.x + d[1].x, v.pos.y + d[1].y, v.pos.z + (v.bodyLo or d[1].z), v.pos.x + d[2].x, v.pos.y + d[2].y, v.pos.z + d[2].z,
           v.heading, 0 }
end
local function cast()
  local x1, y1, z1, x2, y2, z2, flags, ignore = table.unpack(lastRay, 1, 8)
  flags = flags or 1
  local best, bestN, bestB
  if (flags & 1) ~= 0 then
    for _, b in ipairs(S.boxes) do
      local t, n = rayTurnedBox(b, x1, y1, z1, x2, y2, z2)
      if t and (not best or t < best) then best, bestN, bestB = t, n, b end
    end
    for _, r in ipairs(S.ramps or {}) do
      local t, n = rayRamp(r, x1, y1, z1, x2, y2, z2)
      if t and (not best or t < best) then best, bestN, bestB = t, n, r end
    end
    for _, m in ipairs(S.meshes or {}) do
      if segBox(m.box, x1, y1, z1, x2, y2, z2) then
        for _, tri in ipairs(m.tris) do
          local t = rayTri(tri, x1, y1, z1, x2, y2, z2)
          if t and (not best or t < best) then best, bestN, bestB = t, vector3(tri[10], tri[11], tri[12]), m end
        end
      end
    end
  end
  if (flags & 2) ~= 0 then
    for e, v in pairs(S.ent) do
      if v.vehicle and e ~= ignore then
        local b = vehicleBox(v)
        local t, n = rayTurnedBox(b, x1, y1, z1, x2, y2, z2)
        if t and (not best or t < best) then best, bestN, bestB = t, n, b end
      end
    end
  end
  if not best then return nil end
  return vector3(x1 + (x2 - x1) * best, y1 + (y2 - y1) * best, z1 + (z2 - z1) * best), bestN, bestB
end
function IMPL.GetShapeTestResult(handle)
  local p, n = cast()
  if not p then return 2, 0, vector3(0, 0, 0), vector3(0, 0, 0), 0 end
  return 2, 1, p, n, 0
end
function IMPL.GetShapeTestResultIncludingMaterial(handle)
  local p, n, b = cast()
  if not p then return 2, 0, vector3(0, 0, 0), vector3(0, 0, 0), 0, 0 end
  return 2, 1, p, n, b[8] or 0, 0
end
function IMPL.GetResourceKvpInt(key) S.kvp = S.kvp or {}; return S.kvp[key] or 0 end
function IMPL.SetResourceKvpInt(key, value) S.kvp = S.kvp or {}; S.kvp[key] = value end
function IMPL.GetGroundZFor_3dCoord(x, y, z, includeWater)
  lastRay = { x, y, z, x, y, z - 50.0 }
  local _, hit, p = IMPL.GetShapeTestResult(1)
  return hit == 1, hit == 1 and p.z or 0.0
end

-- ---------------------------------------------------------------- entities
local function ent(e)
  local r = S.ent[e]
  if not r then error('entity ' .. tostring(e) .. ' does not exist') end
  return r
end
local function qmul(a, b)
  return { a[4] * b[1] + a[1] * b[4] + a[2] * b[3] - a[3] * b[2], a[4] * b[2] - a[1] * b[3] + a[2] * b[4] + a[3] * b[1],
           a[4] * b[3] + a[1] * b[2] - a[2] * b[1] + a[3] * b[4], a[4] * b[4] - a[1] * b[1] - a[2] * b[2] - a[3] * b[3] }
end
local function qaxis(x, y, z, deg)
  local h = math.rad(deg) * 0.5
  return { x * math.sin(h), y * math.sin(h), z * math.sin(h), math.cos(h) }
end
local function qrot(q, v)
  local x, y, z, w = q[1], q[2], q[3], q[4]
  local tx, ty, tz = 2 * (y * v.z - z * v.y), 2 * (z * v.x - x * v.z), 2 * (x * v.y - y * v.x)
  return vector3(v.x + w * tx + (y * tz - z * ty), v.y + w * ty + (z * tx - x * tz), v.z + w * tz + (x * ty - y * tx))
end
S.qrot = qrot
local function headingOf(q)
  local f = qrot(q, vector3(0, 1, 0))
  return math.deg(math.atan(-f.x, f.y)) % 360.0
end
local function dropTasks(e)
  if e == S.ped then
    if S.anim then S.log[#S.log + 1] = 'tasks cleared: ' .. S.anim.clip end
    S.anim, S.upper = nil, nil
  end
end

function IMPL.PlayerPedId() return S.ped end
function IMPL.GetEntityCoords(e, alive) return ent(e).pos end
function IMPL.SetEntityCoordsNoOffset(e, x, y, z, keepTasks, keepIK, doWarp)
  local r = ent(e)
  r.pos = vector3(x, y, z)
  r.moves = (r.moves or 0) + 1
  if r.ped and not keepTasks and S.keepTasksMatters then dropTasks(e) end
end
function IMPL.SetEntityCoords(e, x, y, z, alive, deadFlag, ragdollFlag, clearArea)
  local r = ent(e)
  r.pos = vector3(x, y, z)
  if r.ped then dropTasks(e) end
end
function IMPL.SetEntityQuaternion(e, x, y, z, w) local r = ent(e); r.q = { x, y, z, w }; r.heading = headingOf(r.q) end
function IMPL.SetEntityRotation(e, pitch, roll, yaw, order, deadCheck)
  local r = ent(e)
  r.rot = { pitch, roll, yaw }
  r.q = qmul(qaxis(0, 0, 1, yaw), qmul(qaxis(1, 0, 0, pitch), qaxis(0, 1, 0, roll)))
  r.heading = yaw % 360.0
end
function IMPL.SetEntityHeading(e, h) local r = ent(e); r.heading = h % 360.0; r.q = qaxis(0, 0, 1, h) end
function IMPL.GetEntityHeading(e) return ent(e).heading or 0.0 end
function IMPL.AttachEntityToEntity(e1, e2, bone, x, y, z, rx, ry, rz, p9, soft, collision, isPed, order, syncRot)
  local r = ent(e1)
  r.attached = { to = e2, bone = bone, pos = vector3(x, y, z), rot = { rx, ry, rz }, order = order }
  S.attaches = (S.attaches or 0) + 1
end
function IMPL.GetEntityQuaternion(e) local q = ent(e).q or { 0.0, 0.0, 0.0, 1.0 }; return q[1], q[2], q[3], q[4] end
function IMPL.DetachEntity(e, dynamic, collision) ent(e).attached = nil end
function IMPL.DoesEntityExist(e) return S.ent[e] ~= nil end
function IMPL.DeleteObject(e) S.ent[e] = nil end
function IMPL.CreateObject(model, x, y, z, isNetwork, netMission, doorFlag)
  S.nextEnt = S.nextEnt + 1
  S.ent[S.nextEnt] = { pos = vector3(x, y, z), q = { 0, 0, 0, 1 }, heading = 0.0, model = model, networked = isNetwork }
  return S.nextEnt
end
function IMPL.GetEntityModel(e) local r = ent(e); return r.ped and S.pedModel or r.model or 0 end
function IMPL.GetModelDimensions(model)
  local d = S.modelDims[model] or S.boardDims
  return d[1], d[2]
end
-- vehicles (S.vehicle): the model's box, where points of it are in the world, how fast it is going
function S.vehicle(model, x, y, z, heading, speed, lo, hi, class)
  S.modelDims[model] = { lo, hi }
  S.nextEnt = S.nextEnt + 1
  local h = math.rad(heading)
  S.ent[S.nextEnt] = { pos = vector3(x, y, z), q = qaxis(0, 0, 1, heading), heading = heading % 360.0, model = model,
                       vehicle = true, class = class or 1, speed = speed, turn = 0.0 }
  return S.nextEnt
end
local function entOffset(e, x, y, z)
  local r = ent(e)
  return r.pos + qrot(qaxis(0, 0, 1, r.heading or 0.0), vector3(x, y, z))
end
function IMPL.GetOffsetFromEntityInWorldCoords(e, x, y, z) return entOffset(e, x, y, z) end
function IMPL.GetOffsetFromEntityGivenWorldCoords(e, x, y, z)
  local r = ent(e)
  return qrot(qaxis(0, 0, 1, -(r.heading or 0.0)), vector3(x, y, z) - r.pos)
end
function IMPL.GetEntityVelocity(e)
  local r = ent(e)
  if not r.vehicle then return r.velocity or vector3(0, 0, 0) end
  local h = math.rad(r.heading)
  return vector3(-math.sin(h) * r.speed, math.cos(h) * r.speed, 0.0)
end
function IMPL.GetVehicleClass(e) return ent(e).class or 0 end
function IMPL.GetGamePool(name)
  local out = {}
  if name == 'CVehicle' then
    for e, v in pairs(S.ent) do
      if v.vehicle then out[#out + 1] = e end
    end
    table.sort(out)
  end
  return out
end
-- head props (hats, helmets): slot -> { drawable, texture }; S.propCount drawables in each slot
function IMPL.GetPedPropIndex(ped, slot) local p = S.props[slot]; return p and p[1] or -1 end
function IMPL.GetPedPropTextureIndex(ped, slot) local p = S.props[slot]; return p and p[2] or -1 end
function IMPL.GetNumberOfPedPropDrawableVariations(ped, slot) return S.propCount end
function IMPL.SetPedPropIndex(ped, slot, drawable, texture, attach)
  if drawable < 0 or drawable >= S.propCount then violation('SetPedPropIndex: no such drawable ' .. tostring(drawable)) end
  S.props[slot] = { drawable, texture }
end
function IMPL.ClearPedProp(ped, slot) S.props[slot] = nil end
function IMPL.GivePedHelmet(ped, cannotRemove, flag, texture) S.props[0] = { 'game helmet', texture } end
function IMPL.RemovePedHelmet(ped, instantly)
  if S.props[0] and S.props[0][1] == 'game helmet' then S.props[0] = nil end
end
function IMPL.SetPedCanLosePropsOnDamage(ped, toggle, p2) S.propsStay = not toggle end
-- other peds (a shopkeeper), blips, commands run from script
function IMPL.CreatePed(kind, model, x, y, z, heading, isNetwork, scriptHost)
  S.nextEnt = S.nextEnt + 1
  S.ent[S.nextEnt] = { pos = vector3(x, y, z), q = qaxis(0, 0, 1, heading), heading = heading % 360.0, model = model,
                       npc = true, networked = isNetwork }
  return S.nextEnt
end
function IMPL.DeleteEntity(e) S.ent[e] = nil end
function IMPL.TaskStartScenarioInPlace(ped, name, delay, enter) ent(ped).scenario = name end
function IMPL.SetEntityInvincible(e, toggle) ent(e).invincible = toggle end
function IMPL.AddBlipForCoord(x, y, z)
  S.nextBlip = (S.nextBlip or 0) + 1
  S.blips[S.nextBlip] = { pos = vector3(x, y, z) }
  return S.nextBlip
end
function IMPL.SetBlipSprite(b, sprite) S.blips[b].sprite = sprite end
function IMPL.DoesBlipExist(b) return S.blips[b] ~= nil end
function IMPL.RemoveBlip(b) S.blips[b] = nil end
function IMPL.SetNuiFocus(focus, cursor) S.nuiFocus = focus end
function IMPL.ExecuteCommand(line)
  local args = {}
  for word in line:gmatch('%S+') do args[#args + 1] = word end
  S.command(table.remove(args, 1), args)
end
function IMPL.GetEntityMatrix(e)
  local r = ent(e)
  local q = r.q
  return qrot(q, vector3(0, 1, 0)), qrot(q, vector3(1, 0, 0)), qrot(q, vector3(0, 0, 1)), r.pos
end
function IMPL.IsEntityPositionFrozen(e) return ent(e).frozen == true end
function IMPL.HasCollisionLoadedAroundEntity(e) return true end
function IMPL.IsModelInCdimage(model) return true end
function IMPL.RequestModel(model) end
function IMPL.HasModelLoaded(model) return true end
function IMPL.SetModelAsNoLongerNeeded(model) end
function IMPL.FreezeEntityPosition(e, toggle) ent(e).frozen = toggle end
function IMPL.SetEntityCollision(e, toggle, keepPhysics) ent(e).collision = toggle end
function IMPL.SetEntityAsMissionEntity(e, a, b) end
function IMPL.SetEntityVelocity(e, x, y, z) ent(e).velocity = vector3(x, y, z); S.log[#S.log + 1] = 'velocity ' .. e end
function IMPL.SetPedToRagdoll(ped, t1, t2, kind, a, b, c) S.log[#S.log + 1] = 'ragdoll'; dropTasks(ped); return true end
function IMPL.PlaceObjectOnGroundProperly(e)
  -- (the world's ground here is z = 0 unless a box or a ramp is under the thing)
  local r = ent(e)
  r.grounded = (r.grounded or 0) + 1
  return true
end
function IMPL.SetEntityDynamic(e, toggle) ent(e).dynamic = toggle end
function IMPL.ActivatePhysics(e) ent(e).awake = true end
function IMPL.GetEntitySpeed(e) local v = ent(e).velocity; return v and #v or 0.0 end
function IMPL.IsEntityDead(e) return false end
function IMPL.IsPedFatallyInjured(ped) return false end
function IMPL.IsPedCuffed(ped) return ped == S.ped and S.cuffed == true end
function IMPL.IsPedRagdoll(ped) return ped == S.ped and S.ragdoll == true end
function IMPL.IsPedBeingStunned(ped, p1) return false end
function IMPL.IsPedSwimming(ped) return false end
function IMPL.IsPedFalling(ped) return false end
function IMPL.IsPedInAnyVehicle(ped, atGetIn) return false end
function IMPL.SetPedCanLegIk(ped, toggle) end
function IMPL.SetPedLegIkMode(ped, mode) end
function IMPL.GetPedBoneIndex(ped, bone) return bone end -- (the index stands for the bone here: tests read it back)

-- ---------------------------------------------------------------- animation
function IMPL.DoesAnimDictExist(d) return d:find('^skate3@') ~= nil or d == 'pickup_object' or d:find('^mini@') ~= nil end
function IMPL.RequestAnimDict(d) end
function IMPL.HasAnimDictLoaded(d) return S.dictsLoaded end
function IMPL.GetAnimDuration(d, c) return S.clipLength and S.clipLength(c) or 1.0 end
function IMPL.TaskPlayAnim(ped, dict, clip, blendIn, blendOut, duration, flags, startPhase, a, b, c)
  if blendIn <= 0 then violation('TaskPlayAnim blendIn must be > 0 (' .. clip .. ')') end
  if blendOut >= 0 then violation('TaskPlayAnim blendOut must be < 0 (' .. clip .. ')') end
  if (flags & 48) ~= 0 then
    S.upper = { dict = dict, clip = clip, flags = flags }
    return
  end
  S.anim = { dict = dict, clip = clip, t0 = S.now, frame = S.frame, loop = (flags & 1) ~= 0, hold = (flags & 2) ~= 0,
             speed = 1.0, phase0 = startPhase, blendIn = blendIn, flags = flags }
  S.played[#S.played + 1] = clip
end
local function animPhase(a)
  if a.set then return a.set end
  local len = S.clipLength and S.clipLength(a.clip) or 1.0
  local p = a.phase0 + (S.now - a.t0) / math.max(len, 0.01)
  if a.loop then return p % 1.0 end
  return math.min(1.0, p)
end
function IMPL.IsEntityPlayingAnim(e, dict, clip, kind)
  local a = S.anim
  if e ~= S.ped or not a or a.dict ~= dict or a.clip ~= clip or S.frame <= a.frame then return false end
  if not a.loop and not a.hold and animPhase(a) >= 1.0 then return false end
  return true
end
function IMPL.SetEntityAnimSpeed(e, dict, clip, speed) if S.anim and S.anim.clip == clip then S.anim.speed = speed end end
function IMPL.SetEntityAnimCurrentTime(e, dict, clip, t)
  local a = S.anim
  if not (a and a.clip == clip) then return end
  if a.speed == 0.0 then a.set = t else a.phase0, a.t0 = t, S.now end
end
function IMPL.GetEntityAnimCurrentTime(e, dict, clip)
  local a = S.anim
  if not (a and a.clip == clip) then return 0.0 end
  return animPhase(a)
end
function IMPL.StopAnimTask(ped, dict, clip, blendOut)
  if blendOut >= 0 then violation('StopAnimTask blendOut must be < 0 (Rockstar passes -8 / -1)') end
  if S.upper and S.upper.clip == clip then S.upper = nil
  elseif S.anim and S.anim.clip == clip then S.anim = nil end
end
function IMPL.ClearPedTasks(ped) dropTasks(ped) end
function IMPL.ClearPedTasksImmediately(ped) dropTasks(ped) end

-- Foot bones. With a Skate 3 clip playing, toe and ankle both sit straight above the sole point the converter
-- baked for that clip (its "anchor", plus S.skelOffset for another skeleton), so the converter's own formula gives
-- back exactly that point. With no clip playing the ped just stands: soles 1 m under its origin.
function S.feetLocal()
  local a = S.anim
  local tr = a and S.frame > a.frame and S.tracks and S.tracks[a.dict .. '/' .. a.clip]
  if not tr then return nil end
  local fr, p = tr.frames, math.max(0.0, math.min(1.0, animPhase(a)))
  local n = #fr
  local f = p * (n - 1) + 1
  local i = math.max(1, math.min(math.floor(f), n - 1))
  local x, y, t = fr[i], fr[math.min(i + 1, n)], f - i
  return vector3(x[5] + (y[5] - x[5]) * t, x[6] + (y[6] - x[6]) * t, x[7] + (y[7] - x[7]) * t) + S.skelOffset
end
function IMPL.GetPedBoneCoords(ped, tag, ox, oy, oz)
  local e, sole = ent(ped), S.feetLocal()
  if not sole then sole = vector3(0, 0, -1.0) end
  return e.pos + qrot(e.q, sole + vector3(0, 0, 0.0925))
end

-- ---------------------------------------------------------------- controls, time, misc
function IMPL.GetDisabledControlNormal(pad, c) return S.input.normal[c] or 0.0 end
function IMPL.IsDisabledControlPressed(pad, c) return S.input.pressed[c] or false end
function IMPL.IsDisabledControlJustPressed(pad, c) return S.input.just[c] or false end
function IMPL.IsControlJustPressed(pad, c) return S.input.just[c] or false end
function IMPL.IsPauseMenuActive() return S.paused or false end
function IMPL.GetProfileSetting(id) return id == 300 and (S.sfx or 10) or 0 end -- 300 = the game's SFX volume, 0 .. 10
function IMPL.DisableControlAction(pad, c, disable) end
function IMPL.IsUsingKeyboard(pad) return S.keyboard end
function IMPL.GetGameTimer() return math.floor(S.now * 1000 + 0.5) end
function IMPL.GetFrameTime() return S.dt end
function IMPL.GetResourceState(res) return S.state[res] or 'missing' end
function IMPL.GetGameBuildNumber() return 3788 end
function IMPL.CreateCam(name, active) S.cam = { id = 900 }; return 900 end
function IMPL.SetCamCoord(cam, x, y, z) if S.cam then S.cam.pos = vector3(x, y, z) end end
function IMPL.SetCamRot(cam, rx, ry, rz, order) if S.cam then S.cam.rot, S.cam.look = vector3(rx, ry, rz), nil end end
function IMPL.SetCamFov(cam, fov) if S.cam then S.cam.fov = fov end end
function IMPL.PointCamAtCoord(cam, x, y, z) if S.cam then S.cam.look = vector3(x, y, z) end end
function IMPL.DestroyCam(cam, thisScriptCheck) S.cam = nil end
function IMPL.DoesCamExist(cam) return S.cam ~= nil end
function IMPL.GetCamCoord(cam) return S.cam and S.cam.pos or vector3(0, 0, 0) end
function IMPL.GetCamRot(cam, order) return S.cam and S.cam.rot or vector3(0, 0, 0) end
function IMPL.GetCamFov(cam) return S.cam and S.cam.fov or 50.0 end
-- What is on the screen: the scripted camera when there is one, else a stand-in for the game's own (3 m behind the
-- ped and 1 m up, looking the way it faces). S.view overrides both (a test putting the camera somewhere).
function IMPL.GetFinalRenderedCamCoord()
  if S.view then return S.view.pos end
  if S.cam and S.cam.pos then return S.cam.pos end
  local p, h = ent(1).pos, math.rad(ent(1).heading or 0.0)
  return vector3(p.x + math.sin(h) * 3.0, p.y - math.cos(h) * 3.0, p.z + 1.0)
end
function IMPL.GetFinalRenderedCamRot(order)
  if S.view then return S.view.rot end
  if S.cam and S.cam.rot then return S.cam.rot end
  return vector3(0.0, 0.0, ent(1).heading or 0.0)
end
function IMPL.GetEntityHealth(e) return 200 end
function IMPL.SetEntityProofs(e, bullet, fire, explosion, collision, melee, steam, keep, water)
  S.log[#S.log + 1] = 'proofs ' .. e .. (collision and ' collision' or ' none')
end

-- ---------------------------------------------------------------- native checking
local TYPES = { float = 'number', int = 'number', Hash = 'number', Entity = 'number', Ped = 'number', Object = 'number',
                Vehicle = 'number', Player = 'number', Cam = 'number', BOOL = 'boolean', ['char*'] = 'string',
                func = 'function', long = 'number' }
-- natives whose trailing arguments everyone leaves out, harmlessly (name -> fewest arguments):
-- GetEntityCoords(entity): the second parameter ("alive") is unused by the game.
local SHORT = { GetEntityCoords = 1 }
local function checked(name, spec, impl)
  local args, result, loose = spec.args, spec.result, spec.loose
  return function(...)
    local n = select('#', ...)
    if not loose then
      if n ~= #args and not (SHORT[name] and n >= SHORT[name] and n <= #args) then
        violation(('%s called with %d arguments, takes %d (%s)'):format(name, n, #args, table.concat(args, ', ')))
      end
      for i = 1, math.min(n, #args) do
        local v, want = (select(i, ...)), TYPES[args[i]:gsub('%*$', '')] or TYPES[args[i]]
        if v == nil then
          violation(('%s argument %d (%s) is nil'):format(name, i, args[i]))
        elseif want and type(v) ~= want and not (want == 'number' and math.type(v)) then
          violation(('%s argument %d (%s) is a %s'):format(name, i, args[i], type(v)))
        end
      end
    end
    if impl then return impl(...) end
    if result == 'BOOL' then return false end
    if result == 'Vector3' then return vector3(0, 0, 0) end
    if result == 'char*' then return '' end
    if result == 'void' then return end
    return 0
  end
end

local function jenkins(s)
  local h = 0
  for i = 1, #s do
    h = (h + s:lower():byte(i)) & 0xFFFFFFFF
    h = (h + (h << 10)) & 0xFFFFFFFF
    h = h ~ (h >> 6)
  end
  h = (h + (h << 3)) & 0xFFFFFFFF
  h = h ~ (h >> 11)
  h = (h + (h << 15)) & 0xFFFFFFFF
  if h >= 0x80000000 then h = h - 0x100000000 end
  return h
end

-- ---------------------------------------------------------------- one environment per resource
local LUA = { 'assert', 'error', 'ipairs', 'next', 'pairs', 'pcall', 'xpcall', 'select', 'tonumber', 'tostring', 'type',
              'rawget', 'rawset', 'rawequal', 'rawlen', 'setmetatable', 'getmetatable', 'load', 'math', 'string',
              'table', 'coroutine', 'utf8', 'os' }

function S.newResource(name)
  local env = { vector3 = vector3, vec3 = vector3, joaat = jenkins, GetHashKey = jenkins }
  for _, k in ipairs(LUA) do env[k] = _G[k] end
  env._G = env
  local res = { name = name, env = env, threads = {}, handlers = {} }
  S.resources[name], S.order[#S.order + 1] = res, name
  env.exports = makeExports(name)
  env.print = function(...)
    local parts = {}
    for i = 1, select('#', ...) do parts[i] = tostring((select(i, ...))) end
    S.prints[#S.prints + 1] = '[' .. name .. '] ' .. table.concat(parts, '\t')
  end
  env.CreateThread = function(fn) res.threads[#res.threads + 1] = { co = coroutine.create(fn), wake = 0.0 } end
  env.Wait = function(ms) coroutine.yield(ms or 0) end
  env.Citizen = { CreateThread = env.CreateThread, Wait = env.Wait }
  S.playerState = S.playerState or {}
  env.LocalPlayer = { state = S.playerState } -- (FiveM's own: the player's state bag)
  env.GetCurrentResourceName = function() return name end
  env.RegisterCommand = checked('RegisterCommand', { args = { 'char*', 'func', 'BOOL' }, result = 'void' },
    function(cmd, fn, restricted) S.commands[cmd] = { fn = fn, resource = name } end)
  env.RegisterNetEvent = function(ev, fn) if fn then res.handlers[ev] = fn end end
  env.AddEventHandler = function(ev, fn) res.handlers[ev] = fn end
  env.TriggerEvent = function(ev, ...)
    for _, r in pairs(S.resources) do
      if r.handlers[ev] then r.handlers[ev](...) end
    end
  end
  env.SendNUIMessage = function(msg)
    if type(msg) ~= 'table' then violation('SendNUIMessage wants a table') return end
    S.nui[#S.nui + 1] = msg
    if S.nuiPage then S.nuiPage(res, msg) end -- a stand-in for the resource's page (set by the test)
  end
  res.nuiCallbacks = {}
  env.RegisterNUICallback = function(name, fn)
    if type(name) ~= 'string' or type(fn) ~= 'function' then violation('RegisterNUICallback wants a name and a function') return end
    res.nuiCallbacks[name] = fn
  end
  env.TriggerServerEvent = function(ev, ...)
    S.events[#S.events + 1] = ev
    S.toServer(ev, ...)
  end
  env.SIM = S -- for the stand-in resources the tests write (ox_target ...); the real scripts never touch it
  setmetatable(env, { __index = function(_, k)
    if S.optional[k] then return nil end -- a global the scripts define themselves and test for first
    local spec = NATIVE_SPEC(k)
    if not spec then
      violation(('unknown global "%s" (not a FiveM native, in resource %s)'):format(tostring(k), name))
      return nil
    end
    local fn = checked(k, { args = spec[1], result = spec[2], loose = spec[3] }, IMPL[k])
    rawset(env, k, fn)
    return fn
  end })
  return env
end

-- A server-side script environment (just enough for server.lua: events, exports, the clock). Client <-> server
-- events are delivered at once.
S.serverHandlers, S.playerSrc = {}, 1
function S.newServerResource(name)
  local env = { vector3 = vector3, SIM = S }
  for _, k in ipairs(LUA) do env[k] = _G[k] end
  env._G = env
  env.exports = makeExports(name)
  env.print = function(...) S.prints[#S.prints + 1] = '[' .. name .. ' server] ' .. tostring((...)) end
  env.GetResourceState = function(res) return S.state[res] or 'missing' end
  env.GetGameTimer = function() return math.floor(S.now * 1000 + 0.5) end
  env.GetCurrentResourceName = function() return name end
  env.RegisterNetEvent = function(ev, fn) if fn then S.serverHandlers[ev] = { fn = fn, env = env } end end
  env.AddEventHandler = function(ev, fn) S.serverHandlers[ev] = { fn = fn, env = env } end
  -- commands (S.serverCommands[name](source, args); restricted ones are noted), the resource's own storage, the
  -- player's ped as the server sees it, and a json that only has to give back what it was given
  S.serverCommands, S.serverRestricted, S.serverKvp, S.jsonStore = S.serverCommands or {}, S.serverRestricted or {}, S.serverKvp or {}, S.jsonStore or {}
  env.RegisterCommand = function(cmd, fn, restricted) S.serverCommands[cmd], S.serverRestricted[cmd] = fn, restricted end
  env.SetResourceKvp = function(key, value) S.serverKvp[key] = value end
  env.GetResourceKvpString = function(key) return S.serverKvp[key] end
  env.json = {
    encode = function(t) local id = 'json#' .. (#S.jsonStore + 1); S.jsonStore[#S.jsonStore + 1] = copy(t, 0); return id end,
    decode = function(s) return copy(S.jsonStore[tonumber(s:match('#(%d+)$'))], 0) end,
  }
  env.GetPlayerPed = function(src) return S.ped end
  env.IsPlayerAceAllowed = function(src, ace) return S.aces ~= nil and S.aces[ace] == true end
  env.GetPlayerIdentifierByType = function(src, kind) return kind == 'license' and ('license:test' .. tostring(src)) or nil end
  env.GetEntityCoords = function(e) return ent(e).pos end
  env.GetEntityHeading = function(e) return ent(e).heading or 0.0 end
  env.TriggerClientEvent = function(ev, target, ...)
    for _, r in pairs(S.resources) do
      if r.handlers[ev] then r.handlers[ev](copyAll(...)) end
    end
  end
  setmetatable(env, { __index = function(_, k)
    violation(('unknown global "%s" in the server script of %s'):format(tostring(k), name))
  end })
  return env
end
function S.toServer(ev, ...)
  local h = S.serverHandlers[ev]
  if not h then return end
  rawset(h.env, 'source', S.playerSrc)
  h.fn(copyAll(...))
end

-- threads: resume every thread that is due; returns the first error
function S.step()
  S.frame = S.frame + 1
  S.now = S.now + S.dt
  for _, v in pairs(S.ent) do
    if v.vehicle then -- vehicles drive on by themselves: straight, or round at v.turn degrees a second
      v.heading = (v.heading + v.turn * S.dt) % 360.0
      v.q = qaxis(0, 0, 1, v.heading)
      local h = math.rad(v.heading)
      v.pos = vector3(v.pos.x - math.sin(h) * v.speed * S.dt, v.pos.y + math.cos(h) * v.speed * S.dt, v.pos.z)
    end
  end
  for _, name in ipairs(S.order) do
    local res = S.resources[name]
    if S.state[name] == 'started' then
      for _, th in ipairs(res.threads) do
        if not th.dead and S.now * 1000 >= th.wake - 1e-6 then
          local ok, ms = coroutine.resume(th.co)
          if not ok then
            th.dead = true
            S.prints[#S.prints + 1] = 'SCRIPT ERROR in ' .. name .. ': ' .. tostring(ms)
          elseif coroutine.status(th.co) == 'dead' then
            th.dead = true
          else
            th.wake = S.now * 1000 + (tonumber(ms) or 0)
          end
        end
      end
    end
  end
  S.input.just = {}
end

-- run fn as a thread of `resource` (commands, key presses) so it may Wait
function S.spawn(resource, fn)
  local res = S.resources[resource]
  res.threads[#res.threads + 1] = { co = coroutine.create(fn), wake = 0.0 }
end

-- a chat / key-mapping command, run as a thread of the resource that registered it
function S.command(name, args)
  local entry = S.commands[name]
  if not entry then error('no such command ' .. tostring(name)) end
  S.spawn(entry.resource, function() entry.fn(0, args, name) end)
end
'''


def joaat(name):
    """GTA's name hash (Jenkins one-at-a-time, lower case), as an unsigned 32 bit number."""
    h = 0
    for ch in name.lower().encode():
        h = (h + ch) & 0xFFFFFFFF
        h = (h + (h << 10)) & 0xFFFFFFFF
        h ^= h >> 6
    h = (h + (h << 3)) & 0xFFFFFFFF
    h ^= h >> 11
    h = (h + (h << 15)) & 0xFFFFFFFF
    return h


class Sim:
    """One simulated FiveM client."""

    def __init__(self):
        self.lua = lua54.LuaRuntime(unpack_returned_tuples=True)
        self.db = _load_db()
        specs = {}

        def native_spec(name):
            if name not in specs:
                n = self.db.get(name)
                if not n:
                    specs[name] = None
                else:
                    args, result, loose = _spec(n)
                    specs[name] = self.lua.table_from([self.lua.table_from(args), result, loose])
            return specs[name]

        self.lua.globals().NATIVE_SPEC = native_spec
        self.lua.execute(PRELUDE)
        self.S = self.lua.globals().SIM
        self.box(-1e6, -1e6, -10, 1e6, 1e6, 0)  # the floor: top at z = 0

    # ---------------------------------------------------------------- world
    def box(self, x1, y1, z1, x2, y2, z2, yaw=0.0, material=None):
        """yaw: turned by this many degrees about its own middle. material: a name from GTA's materials.dat."""
        self.S.boxes[len(self.S.boxes) + 1] = self.lua.table_from(
            [x1, y1, z1, x2, y2, z2, float(yaw), joaat(material) if material else 0])

    def ramp(self, x1, y1, x2, y2, z1, z2, material=None):
        """A sloping top: its height runs from z1 at y1 to z2 at y2, between x1 and x2."""
        if not self.S.ramps:
            self.S.ramps = self.lua.eval('{}')
        self.S.ramps[len(self.S.ramps) + 1] = self.lua.table_from(
            [x1, y1, x2, y2, z1, z2, 0.0, joaat(material) if material else 0])

    def mesh(self, tris, material=None):
        """Faces of any shape: triangles ((ax, ay, az), (bx, by, bz), (cx, cy, cz)), each anticlockwise seen from the
        side rays hit it from (the other side lets them through, as the game's collision does). For the curve of a
        quarter pipe, the wall of a bowl."""
        if not self.S.meshes:
            self.S.meshes = self.lua.eval('{}')
        rows, lo, hi = [], [1e30] * 3, [-1e30] * 3
        for a, b, c in tris:
            e1 = [b[i] - a[i] for i in range(3)]
            e2 = [c[i] - a[i] for i in range(3)]
            n = [e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0]]
            l = math.sqrt(sum(x * x for x in n))
            if l < 1e-12:
                continue
            rows.append(self.lua.table_from([float(x) for x in (*a, *b, *c)] + [x / l for x in n]))
            for p in (a, b, c):
                for i in range(3):
                    lo[i], hi[i] = min(lo[i], p[i]), max(hi[i], p[i])
        m = self.lua.eval('{}')
        m.tris = self.lua.table_from(rows)
        m.box = self.lua.table_from([x - 0.01 for x in lo] + [x + 0.01 for x in hi])
        m[8] = joaat(material) if material else 0
        self.S.meshes[len(self.S.meshes) + 1] = m

    def vehicle(self, x=0.0, y=10.0, heading=0.0, speed=0.0, width=1.9, length=4.6, height=1.4, cls=1,
                model=0x5EDAD0):
        """A car: a box on its wheels, driving on at `speed` m/s the way it points. Returns its entity (a Lua
        table: .speed and .turn (degrees a second) may be changed while it drives)."""
        lo = self.lua.eval("vector3(%r, %r, %r)" % (-width / 2, -length / 2, -0.5))
        hi = self.lua.eval("vector3(%r, %r, %r)" % (width / 2, length / 2, height - 0.5))
        e = self.S.vehicle(model, x, y, 0.5, float(heading), float(speed), lo, hi, cls)
        return e, self.S.ent[e]

    def rail(self, x=0.0, y1=10.0, y2=30.0, top=0.5, width=0.1, heading=0.0, material=None):
        """A rail (a thin wall up to `top`). It runs along +y from y1 to y2; with a heading it is turned about its
        own middle, so that it runs that way instead."""
        self.box(x - width / 2, y1, 0.0, x + width / 2, y2, top, yaw=heading, material=material)

    # ---------------------------------------------------------------- resources
    def resource(self, name, files, patch=None, start=True):
        """Load a resource: its own globals, files run in order. patch: {filename: fn(source) -> source}."""
        env = self.S.newResource(name)
        self.S.state[name] = 'started' if start else 'stopped'
        for path in files:
            src = open(path, encoding="utf-8").read()
            fn = (patch or {}).get(os.path.basename(path))
            if fn:
                new = fn(src)
                assert new != src, f"patch for {path} changed nothing"
                src = new
            chunk = self.lua.eval("function(src, name, env) return assert(load(src, '@' .. name, 't', env)) end")(
                src, os.path.basename(path), env)
            chunk()
        return env

    def server(self, name, files=(), code=''):
        """The server side of a resource: files (and/or a piece of Lua) run in a server environment."""
        env = self.S.newServerResource(name)
        self.S.state[name] = 'started'
        load = self.lua.eval("function(src, name, env) return assert(load(src, '@' .. name, 't', env)) end")
        for path in files:
            load(open(path, encoding="utf-8").read(), os.path.basename(path), env)()
        if code:
            load(code, name + ' (test)', env)()
        return env

    def stand_in(self, name, code):
        """A stand-in client resource written in the test (e.g. a fake ox_target)."""
        env = self.S.newResource(name)
        self.S.state[name] = 'started'
        self.lua.eval("function(src, name, env) return assert(load(src, '@' .. name, 't', env)) end")(code, name, env)()
        return env

    def run(self, resource, code):
        """Evaluate Lua in a resource's globals (to reach its locals, append accessors to its last file instead)."""
        env = self.S.resources[resource].env
        return self.lua.eval("function(src, env) return assert(load(src, '=test', 't', env))() end")(code, env)

    # ---------------------------------------------------------------- time
    def frame(self, n=1, each=None):
        for _ in range(n):
            self.S.step()
            if each:
                each()

    def command(self, name, *args):
        self.S.command(name, self.lua.table_from(list(args)))

    # ---------------------------------------------------------------- input
    def stick(self, x=0.0, y=0.0, right=True):
        """Right stick (Flick-It) by default, left stick with right=False. x right +, y UP +."""
        n = self.S.input.normal
        if right:
            n[1], n[2] = x, -y
        else:
            n[30], n[31] = x, -y

    def hold(self, control, down=True):
        # (a button that goes down reports "just pressed" for a frame, as the game's does)
        if down and not self.S.input.pressed[control]:
            self.S.input.just[control] = True
        self.S.input.pressed[control] = down

    def press(self, control):
        self.S.input.just[control] = True

    # ---------------------------------------------------------------- reading back
    def ent(self, e):
        return self.S.ent[e]

    @property
    def anim(self):
        return self.S.anim

    def played(self, clear=False):
        out = [str(c) for c in self.S.played.values()]
        if clear:
            self.S.played = self.lua.table()
        return out

    def prints(self):
        return [str(p) for p in self.S.prints.values()]

    def violations(self):
        return sorted(set(str(v) for v in self.S.violations.values()))

    def log(self):
        return [str(v) for v in self.S.log.values()]


def qrot(q, v):
    x, y, z, w = q[1], q[2], q[3], q[4]
    tx, ty, tz = 2 * (y * v[2] - z * v[1]), 2 * (z * v[0] - x * v[2]), 2 * (x * v[1] - y * v[0])
    return (v[0] + w * tx + (y * tz - z * ty), v[1] + w * ty + (z * tx - x * tz), v[2] + w * tz + (x * ty - y * tx))
