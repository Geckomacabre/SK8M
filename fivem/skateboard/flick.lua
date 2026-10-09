-- Flick-It gesture matching with Skate 3's own gesture patterns. This file holds no Skate 3 data: the patterns
-- come from `skate3_assets` (built from your own copy of the game) through its FlickPatterns export.
--
-- A pattern is a list of stick positions with a tolerance radius. A trick fires when the stick's recent path passed
-- every position of one of the trick's patterns in order, each within `segTime` seconds of the one before (the
-- first one can be held as long as you like: that is the crouch). The path is judged when the flick ENDS (the stick
-- stops or starts springing back), so a kickflip flick doesn't fire an ollie on its way past the ollie zone.
-- Longer patterns are more specific and win (a 360 flip path also contains a kickflip); between equally long ones
-- the closest fit wins.

Flick = {}

-- One stick's reader: hist = { t, x, y, mag } in pattern space, oldest first; cool = a gesture fired: wait for the
-- stick to come back to the centre or to cross to the other side (ex, ey = where the gesture ended). The right
-- stick's is `main`; Flick.reader() makes another (the left stick's).
local main = { hist = {}, cool = false }
local KEEP = 1.5      -- seconds of stick history kept
local LOOKBACK = 4    -- the flick may have ended this many samples ago
-- The stick is sampled about 60 times a second at most, whatever the frame rate. Sampled more often, a stroke is
-- seen inside positions it only brushes past and a slow roll looks like a stop: the same flick came out as another
-- trick at 144 and 240 frames a second.
local STEP = 0.014

function Flick.reader() return { hist = {}, cool = false } end

function Flick.reset(r)
    r = r or main
    r.hist, r.cool = {}, false
end

-- Pattern space is Skate 3's raw stick: x right = +, y DOWN = +. sx, sy: our stick, x right = +, y up = +.
-- The stick is not mirrored for the rider's stance: Skate 3 reads every rider's stick against the same patterns and
-- swaps the trick for its mirror twin when the rider plays mirrored clips (see S3.trick in s3.lua).
function Flick.toPattern(sx, sy)
    return sx, -sy
end

local function err(s, c, tol)
    local dx, dy = s.x - c[1], s.y - c[2]
    local d = math.sqrt(dx * dx + dy * dy)
    return d <= tol and d / tol or nil
end

-- Match pattern p with its last point at sample e. Returns the number of points, the mean fit (0 = dead on,
-- 1 = at the edge of the tolerance) and the final stroke (from the second-to-last point to the last): the time it
-- took and how fast the stick moved, in stick units per second (the stick's full travel is 2 units).
local function matchAt(hist, p, e, segTime)
    local coords, tol = p.coords, p.tol
    local k = #coords
    local first = err(hist[e], coords[k], tol)
    if not first then return nil end
    local total, j, tPrev, second = first, e, hist[e].t, nil
    for ci = k - 1, 1, -1 do
        local found
        for m = j - 1, 1, -1 do
            local s = hist[m]
            if tPrev - s.t > segTime then break end
            local f = err(s, coords[ci], tol)
            if f then
                found = m
                total = total + f
                break
            end
        end
        if not found then return nil end
        j, tPrev = found, hist[found].t
        if ci == k - 1 then second = found end
    end
    local time, speed = 0.0, 0.0
    if second then
        local a, b = hist[second], hist[e]
        time = b.t - a.t
        speed = math.sqrt((b.x - a.x) ^ 2 + (b.y - a.y) ^ 2) / math.max(time, 0.001)
    end
    return k, total / k, time, speed
end

-- Feed one stick sample (pattern space). When a flick ends and matches one of `set`'s patterns, returns the pattern
-- name, the time the final stroke took (seconds) and its speed (stick units per second; fast flicks pop higher).
function Flick.update(t, x, y, set, segTime, r)
    r = r or main
    local mag = math.sqrt(x * x + y * y)
    if r.cool then
        -- (thrown from one side to the other, the stick may never be sampled near the centre)
        if mag < 0.35 or x * r.ex + y * r.ey < 0.0 then Flick.reset(r) end
        return nil
    end
    local hist = r.hist
    local last = hist[#hist]
    if last and t >= last.t and t - last.t < STEP then return nil end
    hist[#hist + 1] = { t = t, x = x, y = y, mag = mag }
    while #hist > 2 and t - hist[1].t > KEEP do table.remove(hist, 1) end
    local n = #hist
    if not set or n < 2 then return nil end

    local cur, prev = hist[n], hist[n - 1]
    local moved = math.sqrt((cur.x - prev.x) ^ 2 + (cur.y - prev.y) ^ 2)
    if not (prev.mag >= 0.6 and (cur.mag < prev.mag - 0.05 or moved < 0.03)) then return nil end

    local bestName, bestLen, bestFit, bestTime, bestSpeed
    for e = n, math.max(2, n - LOOKBACK), -1 do
        for _, p in ipairs(set) do
            local len, fit, ft, speed = matchAt(hist, p, e, segTime)
            if len and (not bestLen or len > bestLen or (len == bestLen and fit < bestFit)) then
                bestName, bestLen, bestFit, bestTime, bestSpeed = p.name, len, fit, ft, speed
            end
        end
    end
    if bestName then r.cool, r.ex, r.ey = true, cur.x, cur.y end
    return bestName, bestTime, bestSpeed
end
