"""Skate 3's engine hosted by the resource (skateboard/engine.lua): what the script sends the page, and where it puts
the board, the rider and the camera for what the page answers.

The engine itself is not run here (it is WebAssembly in the page: fivem/engine has its own checks, and the page side
is checked in a browser). This test plays the page: it answers the script's messages with poses in Skate 3's space
(metres, y up) and looks at what the script does in GTA's.

usage: python enginetest.py
"""
import math
import sys

import rig


def qrot(q, v):
    x, y, z, w = q
    tx, ty, tz = 2 * (y * v[2] - z * v[1]), 2 * (z * v[0] - x * v[2]), 2 * (x * v[1] - y * v[0])
    return (v[0] + w * tx + (y * tz - z * ty), v[1] + w * ty + (z * tx - x * tz), v[2] + w * tz + (x * ty - y * tx))


def near(a, b, tol=1e-3):
    return all(abs(p - q) <= tol for p, q in zip(a, b))


def xyz(v):
    return (v.x, v.y, v.z)


def ride(r, label):
    """Start the engine where the ped stands and answer as the page would. Returns False when a check fails."""
    sim, S = r.sim, r.sim.S
    lua = sim.lua
    answer = lua.eval("function(S, data) S.resources.skateboard.nuiCallbacks.eng(data, function() end) end")
    table = lua.eval("function(k, n, s, r, v, c) return { k = k, n = n, s = s, r = r, v = v, c = c } end")
    floats = lambda *values: lua.table_from(list(values))
    r.frame(5)
    ped = sim.run('skateboard', 'return PlayerPedId()')
    start = xyz(sim.ent(ped).pos)
    heading = sim.ent(ped).heading
    before = len(list(S.nui.values()))
    sim.command('sk8engine')
    r.frame(3)
    sent = [m for m in list(S.nui.values())[before:] if m.t == 'eng']
    ok = r.check("%s: /sk8engine tells the page to start the engine with skate3_assets' files, facing the way the "
                 "ped faces (GTA %.0f = Skate %.3f rad)" % (label, heading, sent[0].heading if sent else -1),
                 bool(sent) and sent[0].op == 'start' and sent[0].base == 'https://cfx-nui-skate3_assets/engine/'
                 and abs(sent[0].heading - math.radians(heading + 180.0)) < 1e-4)
    pads = [m for m in sent if m.op == 'pad']
    ok &= r.check("... and hands it the pad every frame (%d in 3 frames), nothing pressed" % len(pads),
                  len(pads) >= 2 and all(m.buttons == 0 and m.lx == 0 and m.ry == 0 for m in pads))
    board = sim.run('skateboard', 'return Engine.board()')
    ok &= r.check("a board is made for it, with no collision of its own", board is not None and sim.ent(board).collision is False)
    origin = (start[0], start[1], xyz(sim.ent(board).pos)[2])    # (the board is made on the ground under the ped)

    # the board standing at Skate (1, 0.087, 2), level, nose along Skate +z; the camera 4 m behind and 2 m up
    level = floats(1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 1.0, 0.087, 2.0, 1)
    camera = floats(0, 2, -4, 1, 0, 0, 0, 1, 0, 0, 0, 1, 60)
    answer(S, table('pose', 1, 'PhysicsGround', level, floats(0, 0, 0), camera))
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
    answer(S, table('pose', 2, 'PhysicsGround', level, floats(0, 0, 5), camera))
    r.frame(1)
    lead = origin[1] - 2.0 - xyz(sim.ent(board).pos)[1]
    ok &= r.check("an answer drawn a frame after it came is carried on by the board's speed (%.3f m further south)" % lead,
                  0.02 < lead < 0.26)
    ok &= r.check("the rider faces the way the board goes (GTA heading %.0f)" % sim.ent(ped).heading,
                  abs(sim.ent(ped).heading - 180.0) < 1e-3)

    # the board rolled a quarter turn about its nose (a flip half way): its top faces GTA west; the rider stays upright
    rolled = floats(0, 1, 0, 0, -1, 0, 0, 0, 0, 0, 1, 0, 0.0, 0.6, 0.0, 1)
    answer(S, table('pose', 3, 'KnownAir', rolled, floats(0, 0, 0), camera))
    r.frame(1)
    q = tuple(sim.ent(board).q.values())
    ok &= r.check("a board rolled on its side is drawn on its side (top to the west, nose still south)",
                  near(qrot(q, (0, 0, 1)), (-1, 0, 0)) and near(qrot(q, (1, 0, 0)), (0, -1, 0)))

    # the normal ride does not start meanwhile
    r.get_on()
    ok &= r.check("getting on the ordinary board does nothing while the engine has the rider", not r.state().riding)

    sim.command('sk8engine')
    r.frame(2)
    stops = [m for m in list(S.nui.values()) if m.t == 'eng' and m.op == 'stop']
    ok &= r.check("/sk8engine again ends it: the page is told, the board and the camera are gone",
                  len(stops) == 1 and S.ent[board] is None and S.cam is None)
    return ok


def main():
    r = rig.make()
    ok = ride(r, "engine")
    misuse = r.sim.violations()
    ok &= r.check("no native misuse (%d) %s" % (len(misuse), misuse[:3]), not misuse)
    other = [line for line in r.sim.prints() if 'engine:' not in line]
    ok &= r.check("nothing printed but the engine's own lines (%d) %s" % (len(other), other[:2]), not other)
    said = [line for line in r.sim.prints() if 'engine:' in line]
    print("      the engine's lines: " + " | ".join(l.split('engine: ', 1)[1][:60] for l in said))

    # control: with Skate's z taken for GTA's y (north for south), the same checks must fail
    changed = []

    def swapped(src):
        a = "local function gta(x, y, z) return x, -z, y end"
        if a not in src:           # (skate3_assets has a file of the same name: its export of where the engine is)
            return src + "-- (not the file under test)"
        changed.append(1)
        return src.replace(a, "local function gta(x, y, z) return x, z, y end")
    print("control: Skate +z taken for GTA north")
    c = rig.make(patch={'engine.lua': swapped})
    wrong = not ride(c, "control") and len(changed) == 1
    print(("OK  " if wrong else "BAD ") + "the control fails the placement checks")
    ok &= wrong

    r2 = rig.make()
    r2.frame(5)
    r2.get_on()
    before = len(list(r2.sim.S.nui.values()))
    r2.sim.command('sk8engine')
    r2.frame(2)
    started = [m for m in list(r2.sim.S.nui.values())[before:] if m.t == 'eng']
    ok &= r2.check("on the ordinary board, /sk8engine does not start the engine", not started)
    print("RESULT:", "ok" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
