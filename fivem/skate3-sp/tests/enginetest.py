"""Skate 3's engine, the player's side (skateboard/engine.lua): what the script sends the server, and where it puts
the board, the rider and the camera for what the server answers.

The engine itself is not run here (it is WebAssembly run by the server script: fivem/engine has its own checks,
test/server_node.cjs among them). This test plays the server: it takes the script's events, and answers with poses
in Skate 3's space (metres, y up) to look at what the script does in GTA's.

usage: python enginetest.py
"""
import math
import sys

import rig

# The server, stood in for: what the script sends is kept in S.eng.
SERVER = r'''
return function(S)
  S.eng = { starts = {}, places = {}, pads = {}, grounds = {}, rays = {}, stops = 0 }
  local env = setmetatable({}, { __index = _G })
  local function reg(ev, fn) S.serverHandlers[ev] = { fn = fn, env = env } end
  reg('skateboard:engAsk', function() end)
  reg('skateboard:engStart', function(heading, x, y, z)
    S.eng.starts[#S.eng.starts + 1] = heading
    S.eng.places[#S.eng.places + 1] = { x = x, y = y, z = z }
  end)
  reg('skateboard:engRays', function(x, y, z, heading, by)
    S.eng.rays[#S.eng.rays + 1] = { x = x, y = y, z = z, heading = heading, by = by }
  end)
  reg('skateboard:engPads', function(samples) S.eng.pads[#S.eng.pads + 1] = samples end)
  reg('skateboard:engGround', function(n, cell, x0, z0, none, h)
    S.eng.grounds[#S.eng.grounds + 1] = { n = n, cell = cell, x0 = x0, z0 = z0, none = none, h = h }
  end)
  reg('skateboard:engStop', function() S.eng.stops = S.eng.stops + 1 end)
end
'''


def qrot(q, v):
    x, y, z, w = q
    tx, ty, tz = 2 * (y * v[2] - z * v[1]), 2 * (z * v[0] - x * v[2]), 2 * (x * v[1] - y * v[0])
    return (v[0] + w * tx + (y * tz - z * ty), v[1] + w * ty + (z * tx - x * tz), v[2] + w * tz + (x * ty - y * tx))


def near(a, b, tol=1e-3):
    return all(abs(p - q) <= tol for p, q in zip(a, b))


def xyz(v):
    return (v.x, v.y, v.z)


def track_at(track, phase):
    """A clip's board against the ped at a phase: its rotation and the middle of the deck's top (as s3_player's)."""
    frames = track.frames
    n = len(frames)
    f = max(0.0, min(1.0, phase)) * (n - 1) + 1
    i = max(1, min(int(math.floor(f)), n - 1))
    a, b, t = frames[i], frames[min(i + 1, n)], f - i
    sign = 1.0 if sum(a[k] * b[k] for k in range(1, 5)) >= 0.0 else -1.0
    q = [a[k] + (sign * b[k] - a[k]) * t for k in range(1, 5)]
    l = math.sqrt(sum(x * x for x in q))
    return tuple(x / l for x in q), tuple(a[k] + (b[k] - a[k]) * t for k in range(5, 8))


def turned(v, heading):
    """A vector of an entity with this GTA heading (degrees), in the world."""
    c, s = math.cos(math.radians(heading)), math.sin(math.radians(heading))
    return (v[0] * c - v[1] * s, v[0] * s + v[1] * c, v[2])


def make(config="Config.Engine = true", patch=None, have=True):
    """A rig with the server stood in for; have = the server says it has the engine."""
    r = rig.make(config=config, patch=patch)
    sim, S = r.sim, r.sim.S
    sim.lua.execute("function _engine_server(S) " + SERVER.replace("return function(S)", "do").rstrip()[:-3] + " end end")
    sim.lua.globals()._engine_server(S)
    if have:
        sim.lua.eval("function(S) S.resources.skateboard.handlers['skateboard:engHave'](true) end")(S)
    S.keyboard = False
    r.to_client = sim.lua.eval("function(S, ev, ...) S.resources.skateboard.handlers[ev](...) end")
    r.floats = lambda *values: sim.lua.table_from(list(values))
    return r


def ride(r, label):
    """Start the engine where the ped stands and answer as the server would. Returns False when a check fails."""
    sim, S = r.sim, r.sim.S
    pose = lambda n, state, root, v, c, *clip: r.to_client(S, 'skateboard:engPose', n, state, root, v, c, *clip)
    r.frame(5)
    ped = sim.run('skateboard', 'return PlayerPedId()')
    start = xyz(sim.ent(ped).pos)
    heading = sim.ent(ped).heading
    sim.command('sk8engine')
    r.frame(3)
    starts = list(S.eng.starts.values())
    ok = r.check("%s: /sk8engine asks the server for a rider facing the way the ped faces (GTA %.0f = Skate %.3f rad)" % (
        label, heading, starts[0] if starts else -1),
        len(starts) == 1 and abs(starts[0] - math.radians(heading + 180.0)) < 1e-4)
    ok &= r.check("with nothing on the pad, nothing about the pad is sent (%d messages)" % len(list(S.eng.pads.values())),
                  len(list(S.eng.pads.values())) == 0)
    board = sim.run('skateboard', 'return Engine.board()')
    ok &= r.check("a board is made for it, with no collision of its own", board is not None and sim.ent(board).collision is False)
    r.frame(20)
    grounds = list(S.eng.grounds.values())
    g = grounds[0] if grounds else None
    h = list(g.h.values()) if g else []
    ok &= r.check("within 20 frames the ground round the board is sent once: %d x %d samples %.1f m apart, from "
                  "%.1f m west and %.1f m north of the start, all at the start's height (%d of them)" % (
                      g.n if g else 0, g.n if g else 0, g.cell if g else 0, -g.x0 if g else 0, -g.z0 if g else 0, len(h)),
                  len(grounds) == 1 and g.n == 41 and len(h) == 41 * 41 and all(abs(v) < 0.02 for v in h)
                  and abs(g.x0 + 10.0) < 1.01 and abs(g.z0 + 10.0) < 1.01)
    origin = (start[0], start[1], xyz(sim.ent(board).pos)[2])    # (the board is made on the ground under the ped)
    place = list(S.eng.places.values())[0]
    ok &= r.check("the server is told where in GTA's world that is, for its baked map (%.2f %.2f %.2f)" % (place.x, place.y, place.z),
                  near((place.x, place.y), origin[:2], 0.01) and abs(place.z - origin[2]) < 0.3)

    # the pad: A held for a quarter of a second
    sim.hold(223)
    r.frame(15)
    sim.hold(223, False)
    r.frame(6)
    sent = [list(m.values()) for m in S.eng.pads.values()]
    flat = [v for m in sent for v in m]
    downs = [flat[i] == 0x1000 for i in range(0, len(flat), 7)]
    ok &= r.check("A held for a quarter of a second: only the changes are sent, two samples of the pad to a message "
                  "(%d messages: the press, then, with nothing sent while it is held, the release)" % len(sent),
                  len(sent) == 2 and all(len(m) == 14 for m in sent) and any(downs[:2]) and downs[1]
                  and not downs[-1] and flat[1:7] == [0] * 6)

    # the board standing at Skate (1, 0.087, 2), level, nose along Skate +z; the camera 4 m behind and 2 m up
    level = r.floats(1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 1.0, 0.087, 2.0, 1)
    camera = r.floats(0, 2, -4, 1, 0, 0, 0, 1, 0, 0, 0, 1, 60)
    pose(1, 'PhysicsGround', level, r.floats(0, 0, 0), camera)
    r.frame(1)
    e = sim.ent(board)
    q = tuple(e.q.values())
    bottom = S.boardDims[1].z
    ok &= r.check("Skate (1, 0.087, 2) is GTA 1 east and 2 south of the start, the wheels on the ground "
                  "(board at %.3f %.3f %.3f from it)" % tuple(p - o for p, o in zip(xyz(e.pos), origin)),
                  near(xyz(e.pos), (origin[0] + 1.0, origin[1] - 2.0, origin[2] - bottom)))
    ok &= r.check("the board's long side points along Skate +z = GTA south, its top is up",
                  near(qrot(q, (1, 0, 0)), (0, -1, 0)) and near(qrot(q, (0, 0, 1)), (0, 0, 1)))
    p = sim.ent(ped)
    height = sim.run('skateboard', 'return Config.RideHeight')
    ok &= r.check("the rider is over the board, the deck's top %.2f m under the ped's middle, facing as before" % height,
                  near(xyz(p.pos), (origin[0] + 1.0, origin[1] - 2.0, origin[2] + 0.087 + 0.0122 + height))
                  and abs(p.heading - heading) < 1e-3)
    cam = S.cam
    ok &= r.check("the camera is the engine's: 4 m north of the start and 2 m up, looking south, level, 60 degrees",
                  cam is not None and near(xyz(cam.pos), (origin[0], origin[1] + 4.0, origin[2] + 2.0))
                  and near(xyz(cam.rot), (0.0, 0.0, 180.0)) and abs(cam.fov - 60.0) < 1e-3)

    # rolling at 5 m/s along Skate +z, drawn a frame later: carried on by the speed; the rider turns that way
    pose(2, 'PhysicsGround', level, r.floats(0, 0, 5), camera)
    r.frame(1)
    lead = origin[1] - 2.0 - xyz(sim.ent(board).pos)[1]
    ok &= r.check("an answer drawn a frame after it came is carried on by the board's speed (%.3f m further south)" % lead,
                  0.02 < lead < 0.26)
    ok &= r.check("the rider faces the way the board goes (GTA heading %.0f)" % sim.ent(ped).heading,
                  abs(sim.ent(ped).heading - 180.0) < 1e-3)

    # the board rolled a quarter turn about its nose (a flip half way): its top faces GTA west; the rider stays upright
    rolled = r.floats(0, 1, 0, 0, -1, 0, 0, 0, 0, 0, 1, 0, 0.0, 0.6, 0.0, 1)
    pose(3, 'KnownAir', rolled, r.floats(0, 0, 0), camera)
    r.frame(1)
    q = tuple(sim.ent(board).q.values())
    ok &= r.check("a board rolled on its side is drawn on its side (top to the west, nose still south)",
                  near(qrot(q, (0, 0, 1)), (-1, 0, 0)) and near(qrot(q, (1, 0, 0)), (0, -1, 0)))

    # the clip the engine plays: the ped plays the converted one, held at the engine's time in it, and is stood so
    # that the clip's board is the engine's (the deck's middle on the engine's deck, tail to tail)
    def fitted(n, state, root, at, tail, clip, seconds, what):
        before = len(list(S.played.values()))
        pose(n, state, root, r.floats(0, 0, 0), camera, clip, seconds, False)
        r.frame(3)
        a, p = S.anim, sim.ent(ped)
        track = S.tracks[a.dict + '/' + a.clip]
        length = (len(track.frames) - 1) / track.fps
        held = a.clip == clip and a.speed == 0.0 and a.set is not None \
            and seconds / length - 1e-3 <= a.set <= min((seconds + 0.05) / length, 0.999) + 1e-3
        q, anchor = track_at(track, a.set or 0.0)
        deck = tuple(x + y for x, y in zip(xyz(p.pos), turned(anchor, p.heading)))
        want = (origin[0] + at[0], origin[1] - at[2], origin[2] + at[1] + 0.0122)
        y = turned(qrot(q, (0, 1, 0)), p.heading)
        l = math.hypot(y[0], y[1])
        good = r.check("%s: the ped plays %s held at %.2f s of its %.2f s (phase %.3f), started %d time(s)" % (
            what, a.clip, seconds, length, a.set or -1, len(list(S.played.values())) - before), held)
        good &= r.check("   ... the clip's deck is the engine's (%.3f %.3f %.3f from it), the rider upright" % tuple(
            d - w for d, w in zip(deck, want)), near(deck, want))
        good &= r.check("   ... the clip's board lies tail to tail on the engine's (its tail end points %.2f %.2f, "
                        "the engine's %.0f %.0f)" % (y[0] / l, y[1] / l, tail[0], tail[1]),
                        near((y[0] / l, y[1] / l, 0.0), (tail[0], tail[1], 0.0), 2e-3))
        return good, len(list(S.played.values())) - before
    good, started = fitted(4, 'PhysicsGround', level, (1.0, 0.087, 2.0), (0, 1), 'r_idle_hcom_000', 0.30,
                           "nose to Skate +z (GTA south)")
    ok &= good and r.check("   ... the clip is started once", started == 1)
    good, started = fitted(5, 'PhysicsGround', level, (1.0, 0.087, 2.0), (0, 1), 'r_idle_hcom_000', 0.60, "later in the same clip")
    ok &= good and r.check("   ... it is not started again: only its time is set", started == 0)
    east = r.floats(0, 0, -1, 0, 0, 1, 0, 0, 1, 0, 0, 0, 3.0, 0.087, -1.0, 1)
    good, started = fitted(6, 'PhysicsGround', east, (3.0, 0.087, -1.0), (-1, 0), 'r_idle_hcom_p100', 0.10,
                           "nose to Skate +x (GTA east), another clip")
    ok &= good and r.check("   ... which is started once", started == 1)
    pop = r.floats(0, 0, -1, 0, 0, 1, 0, 0, 1, 0, 0, 0, 3.0, 0.9, -1.0, 1)
    good, _ = fitted(7, 'KnownAir', pop, (3.0, 0.9, -1.0), (-1, 0), 'ollie_high_a', 0.20, "0.9 m up in an ollie")
    ok &= good
    before = len(list(S.played.values()))
    pose(8, 'KnownAir', pop, r.floats(0, 0, 0), camera, 'not_a_clip_of_skate_3', 0.10, False)
    r.frame(3)
    pose(9, 'KnownAir', pop, r.floats(0, 0, 0), camera, 'not_a_clip_of_skate_3', 0.15, False)
    r.frame(3)
    lines = [l for l in sim.prints() if 'no converted clip not_a_clip_of_skate_3' in l]
    ok &= r.check("a clip that was not converted: the last one stays (%s), nothing is started, and it is said once (%d)" % (
        S.anim.clip, len(lines)), S.anim.clip == 'ollie_high_a' and len(list(S.played.values())) == before and len(lines) == 1)

    # the normal ride does not start meanwhile
    r.get_on()
    ok &= r.check("getting on the ordinary board does nothing while the engine has the rider", not r.state().riding)

    sim.command('sk8engine')
    r.frame(2)
    ok &= r.check("/sk8engine again ends it: the server is told, the board and the camera are gone",
                  S.eng.stops == 1 and S.ent[board] is None and S.cam is None)
    return ok


def main():
    r = make()
    ok = ride(r, "engine")
    misuse = r.sim.violations()
    ok &= r.check("no native misuse (%d) %s" % (len(misuse), misuse[:3]), not misuse)
    other = [line for line in r.sim.prints() if 'engine:' not in line]
    ok &= r.check("nothing printed but the engine's own lines (%d) %s" % (len(other), other[:2]), not other)
    said = [line for line in r.sim.prints() if 'engine:' in line]
    print("      the engine's lines: " + " | ".join(l.split('engine: ', 1)[1][:60] for l in said))

    # control: with Skate's z taken for GTA's y (north for south), the same checks must fail
    def swapped(src):
        a = "local function gta(x, y, z) return x, -z, y end"
        assert src.count(a) == 1
        return src.replace(a, "local function gta(x, y, z) return x, z, y end")
    print("control: Skate +z taken for GTA north")
    wrong = not ride(make(patch={'engine.lua': swapped}), "control")
    print(("OK  " if wrong else "BAD ") + "the control fails the placement checks")
    ok &= wrong

    # control: with the clips' board taken to be nose first (it is tail first), the rider must come out the wrong
    # way round and the tail-to-tail check fail
    def nose_first(src):
        a = "heading(-nx, -ny) - heading(tx, ty)"
        assert src.count(a) == 1
        return src.replace(a, "heading(nx, ny) - heading(tx, ty)")
    print("control: the clips' board taken to be nose first")
    wrong = not ride(make(patch={'engine.lua': nose_first}), "control")
    print(("OK  " if wrong else "BAD ") + "the control fails the tail-to-tail check")
    ok &= wrong

    # getting on the board the ordinary way starts the engine when it is switched on, and gets off it again
    r3 = make()
    r3.frame(5)
    r3.sim.command('skateboard')
    r3.frame(3)
    ok &= r3.check("with Config.Engine on and a server that has the engine, the get-on key asks the server for a rider "
                   "and does not start the resource's own ride",
                   len(list(r3.sim.S.eng.starts.values())) == 1 and not r3.state().riding
                   and r3.sim.run('skateboard', 'return Engine.active()'))
    r3.sim.command('skateboard')
    r3.frame(3)
    ok &= r3.check("... and the same key again ends it", not r3.sim.run('skateboard', 'return Engine.active()'))

    # the server has no rider to spare: the resource's own ride instead
    r5 = make()
    r5.frame(5)
    r5.sim.command('skateboard')
    r5.frame(2)
    r5.to_client(r5.sim.S, 'skateboard:engError', 'busy')
    r5.frame(6)
    ok &= r5.check("told the engine is busy before it ever answered, the rider is put on the resource's own ride",
                   r5.state().riding and not r5.sim.run('skateboard', 'return Engine.active()'))

    # the server's baked map: no ground is sent while this game's ground is where the engine has the board, and the
    # server is told when it is not
    def on_map(label, patch=None):
        rb = make(patch=patch)
        sim, S = rb.sim, rb.sim.S
        rb.frame(5)
        sim.command('sk8engine')
        rb.frame(3)
        rb.to_client(S, 'skateboard:engReady', 1.0 / 60.0, 5, True)
        camera = rb.floats(0, 2, -4, 1, 0, 0, 0, 1, 0, 0, 0, 1, 60)
        at = lambda n, state, up: rb.to_client(S, 'skateboard:engPose', n, state, rb.floats(
            1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 1.0, 0.087 + up, 2.0, 1), rb.floats(0, 0, 0), camera, 'r_idle_hcom_000', 0.0, False)
        for n in range(90):
            at(n, 'PhysicsGround', 0.0)
            rb.frame(1)
        good = rb.check("%s: on the server's baked map, with the board on this game's ground, no ground is sent and nothing is "
                        "reported (%d grounds, %d reports in 90 frames)" % (label, len(list(S.eng.grounds.values())), len(list(S.eng.rays.values()))),
                        not list(S.eng.grounds.values()) and not list(S.eng.rays.values()))
        for n in range(90):
            at(100 + n, 'PhysicsAir', 1.0)
            rb.frame(1)
        good &= rb.check("a board a metre up in the air is not a map that is off (%d reports)" % len(list(S.eng.rays.values())),
                         not list(S.eng.rays.values()))
        for n in range(120):
            at(200 + n, 'PhysicsGround', 1.0)
            rb.frame(1)
        rays = list(S.eng.rays.values())
        ray = rays[0] if rays else None
        good &= rb.check("the engine rolling a metre over this game's ground: the server is told once, with the ground under the "
                         "board in Skate's space and how far off the map is (%s)" % (
                             "%.2f %.2f %.2f, %.2f m" % (ray.x, ray.y, ray.z, ray.by) if ray else "nothing sent"),
                         len(rays) == 1 and near((ray.x, ray.z), (1.0, 2.0), 0.01) and abs(ray.y) < 0.05 and abs(ray.by - 1.0) < 0.05)
        good &= rb.check("... and from then on this game's ground is sent (%d)" % len(list(S.eng.grounds.values())),
                         len(list(S.eng.grounds.values())) >= 1)
        return good
    ok &= on_map("baked map")

    def never_off(src):
        a = "math.abs(gap) > 0.4"
        assert src.count(a) == 1
        return src.replace(a, "math.abs(gap) > 4.0")
    print("control: a map taken to be off only when it is 4 m off")
    wrong = not on_map("control", patch={'engine.lua': never_off})
    print(("OK  " if wrong else "BAD ") + "the control fails the report check")
    ok &= wrong

    r4 = make(config="")
    r4.frame(5)
    r4.sim.command('skateboard')
    r4.frame(5)
    ok &= r4.check("with Config.Engine off, the get-on key starts the resource's own ride as before",
                   r4.state().riding and not list(r4.sim.S.eng.starts.values()))
    r6 = make(have=False)
    r6.frame(5)
    r6.sim.command('skateboard')
    r6.frame(5)
    ok &= r6.check("on a server without the engine, the get-on key starts the resource's own ride",
                   r6.state().riding and not list(r6.sim.S.eng.starts.values()))
    r2 = make()
    r2.frame(5)
    r2.get_on()
    r2.sim.command('sk8engine')
    r2.frame(2)
    ok &= r2.check("on the ordinary board, /sk8engine does not start the engine", not list(r2.sim.S.eng.starts.values()))
    print("RESULT:", "ok" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
