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
  S.eng = { starts = {}, pads = {}, grounds = {}, stops = 0 }
  local env = setmetatable({}, { __index = _G })
  local function reg(ev, fn) S.serverHandlers[ev] = { fn = fn, env = env } end
  reg('skateboard:engAsk', function() end)
  reg('skateboard:engStart', function(heading) S.eng.starts[#S.eng.starts + 1] = heading end)
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
    pose = lambda n, state, root, v, c: r.to_client(S, 'skateboard:engPose', n, state, root, v, c)
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
