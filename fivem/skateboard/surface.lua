-- The geometry of riding on a face that is not level: a bank, the curve of a quarter pipe, the wall of a bowl.
--
-- On the ground the board has a face under it (its normal, `u`) and a way its nose points along that face (`d`, a
-- unit vector lying in the face). client.lua keeps the nose's direction as a heading too (`facing`): the heading the
-- nose would have with the face laid flat by the shortest way. Laid flat like that a turn of the board by 10 degrees
-- is facing + 10 on any face, a vertical one included, where a compass heading has no meaning.
--
-- Nothing of Skate 3 is in here, and no game calls: vectors only.

Surf = {}

local UP = vector3(0.0, 0.0, 1.0)
Surf.UP = UP

function Surf.dot(a, b) return a.x * b.x + a.y * b.y + a.z * b.z end

function Surf.cross(a, b)
    return vector3(a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x)
end

-- v made one long; nil when it has no length to speak of
function Surf.unit(v)
    local l = math.sqrt(v.x * v.x + v.y * v.y + v.z * v.z)
    if l < 1e-6 then return nil end
    return vector3(v.x / l, v.y / l, v.z / l)
end

-- The heading (a GTA heading: 0 = north, anticlockwise) of v's level part.
function Surf.heading(v) return math.deg(math.atan(-v.x, v.y)) end

-- v turned by `deg` about the unit vector `a` (anticlockwise seen from a's tip).
function Surf.turn(v, a, deg)
    local r = math.rad(deg)
    local c, s = math.cos(r), math.sin(r)
    local k = (a.x * v.x + a.y * v.y + a.z * v.z) * (1.0 - c)
    return vector3(
        v.x * c + (a.y * v.z - a.z * v.y) * s + a.x * k,
        v.y * c + (a.z * v.x - a.x * v.z) * s + a.y * k,
        v.z * c + (a.x * v.y - a.y * v.x) * s + a.z * k)
end

-- v carried along by the shortest turn that takes the unit vector a to the unit vector b: what happens to the nose
-- of a board that rolls from one face of a ramp onto the next (it keeps its angle to the crease between them).
function Surf.carry(v, a, b)
    local c = a.x * b.x + a.y * b.y + a.z * b.z
    if c > 0.9999999 then return v end
    if c < -0.9999 then return v end -- (the other way up: no shortest turn, and no board does it in one step)
    local kx, ky, kz = a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x
    local kv = (kx * v.x + ky * v.y + kz * v.z) / (1.0 + c)
    return vector3(
        v.x * c + (ky * v.z - kz * v.y) + kx * kv,
        v.y * c + (kz * v.x - kx * v.z) + ky * kv,
        v.z * c + (kx * v.y - ky * v.x) + kz * kv)
end

-- The direction with heading `h` on the level, laid onto the face `u` (see the top of the file).
function Surf.onto(h, u)
    local r = math.rad(h)
    return Surf.carry(vector3(-math.sin(r), math.cos(r), 0.0), UP, u)
end

-- ... and back: the heading of the direction `d` (in the face `u`) with the face laid flat.
function Surf.flat(d, u)
    return Surf.heading(Surf.carry(d, u, UP))
end

-- v with what it has along the unit vector n taken out, made one long: v as it lies in the face n. nil when v
-- stands straight up from that face.
function Surf.along(v, n)
    local k = v.x * n.x + v.y * n.y + v.z * n.z
    return Surf.unit(vector3(v.x - n.x * k, v.y - n.y * k, v.z - n.z * k))
end

-- The direction in the face `n` that lies over the level direction (x, y): the way a board points on a slope when
-- its compass heading is that. nil on a face too steep for a compass heading to say anything.
function Surf.lift(x, y, n)
    if n.z < 0.2 then return nil end
    return Surf.unit(vector3(x, y, -(n.x * x + n.y * y) / n.z))
end

-- Degrees from the unit vector a round to the unit vector b, anticlockwise seen from the tip of n (both in n's face).
function Surf.angle(a, b, n)
    local c = Surf.cross(a, b)
    return math.deg(math.atan(c.x * n.x + c.y * n.y + c.z * n.z, a.x * b.x + a.y * b.y + a.z * b.z))
end

-- The rotation (a quaternion: x, y, z, w) of something that stands on the face `u` and points along heading `h`
-- there: turned to the heading first, then tipped over with the face. With `lean` (degrees) it is rolled about its
-- own forward axis first.
function Surf.quat(u, h, lean)
    -- about z by h
    local r = math.rad(h) * 0.5
    local x, y, z, w = 0.0, 0.0, math.sin(r), math.cos(r)
    if lean and lean ~= 0.0 then
        -- (q = heading * roll about the body's y)
        local l = math.rad(lean) * 0.5
        local s, c = math.sin(l), math.cos(l)
        x, y, z, w = -z * s, w * s, z * c, w * c
    end
    if u.z > 0.9999999 then return x, y, z, w end
    -- the shortest turn from straight up to u: about (-u.y, u.x, 0)
    local ax, ay, aw = -u.y, u.x, 1.0 + u.z
    local l = math.sqrt(ax * ax + ay * ay + aw * aw)
    if l < 1e-6 then ax, ay, aw, l = 1.0, 0.0, 0.0, 1.0 end -- (upside down)
    ax, ay, aw = ax / l, ay / l, aw / l
    -- (ax, ay, 0, aw) * (x, y, z, w)
    return aw * x + ax * w + ay * z,
           aw * y - ax * z + ay * w,
           aw * z + ax * y - ay * x,
           aw * w - ax * x - ay * y
end
