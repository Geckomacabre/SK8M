"""The faults the reviews of 2026-10-07 found, each with the old behaviour patched back in as its control.

usage: python fixtest.py [scenario ...]        (also scenarios of ridetest.py)
"""
import os
import sys

import rig
from rig import A, B, LT, RT, X, Y

OLLIE = [(0.0, 1.0), (0.0, -1.0)]


def back(new, old):
    """A patch that puts an old line back (rig.make checks that it really changes the source)."""
    return lambda s: s.replace(new, old)


def creep_push(r):
    """Rolling backwards too slowly to be fakie, the push must still move the board."""
    r.get_on()
    r.frame(20)
    r.set('speed', -0.3)
    r.sim.hold(A)
    r.frame(150)
    r.sim.hold(A, False)
    return r.state().speed


def grab_after_ollie(r, goofy=True):
    """A real ollie, the back hand's trigger held as the board leaves the ground: frames until the grab's clip plays."""
    sim = r.sim
    r.get_on()
    r.set('speed', 6.0)
    r.frame(30)
    r.flick(OLLIE, settle=0)
    for _ in range(60):
        if r.state().mode == 'air':
            break
        r.frame()
    r.set('vz', 7.0)
    sim.played(clear=True)
    sim.hold(LT if goofy else RT)
    n = None
    for i in range(90):
        r.frame()
        if any('gr_grab_n_fs' in c for c in sim.played()):
            n = i + 1
            break
    sim.hold(LT if goofy else RT, False)
    return n, r.state().grab


def riding():
    ok = True
    r = rig.make(goofy=True)
    v = creep_push(r)
    r.check("pushing while the board creeps backwards (-0.3 m/s) stops it and sends it forward (%.2f m/s)" % v, v > 1.0)
    n, g = grab_after_ollie(rig.make(goofy=True))
    r.check("a hand on the board straight after an ollie: the grab's clip plays within a few frames (%s)" % n,
            n is not None and n <= 8)
    ok &= r.finish('riding')

    r = rig.make(goofy=True, patch={'client.lua': back(
        "if speed < Tune.pushMax then speed = math.min(", "if speed >= 0.0 and speed < Tune.pushMax then speed = math.min(")})
    v = creep_push(r)
    ok &= r.check("control, the old rule (no kick below 0 m/s): the board stays where it was (%.2f m/s)" % v, v <= 0.0)
    r = rig.make(goofy=True, patch={'s3.lua': back(
        "if key == 'trick' and (flipping or not (s.grab or s.onefoot or s.coffin)) then return key end",
        "if key == 'trick' then return key end")})
    n, g = grab_after_ollie(r)
    ok &= r.check("control, the old rule (the ollie's clip is played out first): the grab's clip comes late (%s)" % n,
                  n is None or n > 8)
    return ok


def devtools():
    """The test tools are for the server's admins: /skateramp, /skatetest and skate3_assets' /s3... commands."""
    ok = True
    r = rig.make(goofy=True, server=True, config="Config.TestCommands = 'admin'")
    sim, S = r.sim, r.sim.S
    env = S.serverHandlers['skateboard:mayTest'].env
    env.Config.TestCommands = 'admin'
    r.frame(30)
    sim.command('skateramp', 'kicker')
    r.frame(30)
    r.check("an ordinary player's /skateramp makes no ramp (%d)" % r.T.ramps(), r.T.ramps() == 0)
    before = (S.ent[1].pos.x, S.ent[1].pos.y)
    sim.command('skatetest')
    r.frame(60)
    r.check("... and /skatetest does not start (the player stays put, not on a board)",
            not r.state().riding and (S.ent[1].pos.x, S.ent[1].pos.y) == before)
    allowed = sim.run('skateboard', 'return exports.skateboard:devAllowed()')
    r.check("... and skate3_assets is told no for its own commands", allowed is False)
    r.frame(2)
    S.aces = sim.lua.table_from({'skateboard.dev': True})
    r.frame(125)
    sim.command('skateramp', 'kicker')   # (a refusal asks the server again, at most every 2 s: the next try knows)
    r.frame(30)
    if r.T.ramps() == 0:
        sim.command('skateramp', 'kicker')
    r.frame(30)
    r.check("given the ace skateboard.dev, the same player's /skateramp makes one (%d)" % r.T.ramps(), r.T.ramps() == 1)
    sim.command('skateramp', 'clear')
    r.frame(5)
    p = sim.prints()
    r.check("the only thing printed is /skatetest's refusal (%d)" % len(p), len(p) == 1 and 'admins' in p[0])
    v = sim.violations()
    r.check("no native misuse (%d)" % len(v), not v)
    print(("PASS " if r.ok else "FAIL ") + 'devtools')
    ok &= r.ok

    r = rig.make(goofy=True, server=True, config="Config.TestCommands = true")
    r.frame(30)
    r.sim.command('skateramp', 'kicker')
    r.frame(30)
    ok &= r.check("control, Config.TestCommands = true (a private server): everyone's /skateramp works (%d)" % r.T.ramps(),
                  r.T.ramps() == 1)
    r = rig.make(goofy=True, server=True, config="Config.TestCommands = false")
    r.sim.S.aces = r.sim.lua.table_from({'skateboard.dev': True})
    r.frame(330)
    r.sim.command('skateramp', 'kicker')
    r.frame(30)
    ok &= r.check("control, Config.TestCommands = false: nobody's does, admin or not (%d)" % r.T.ramps(), r.T.ramps() == 0)
    return ok


def new_ped(sim, x=100.0, y=100.0, z=30.0):
    """The game gives the player another ped (a model change, a respawn elsewhere). Returns the new and the old one."""
    old = sim.S.ped
    ped = sim.run('skateboard', 'return CreatePed(4, 1, %r, %r, %r, 0.0, false, false)' % (x, y, z))
    sim.S.ped = ped
    return ped, old


def swap(r):
    sim = r.sim
    board = r.get_on()
    r.set('speed', 6.0)
    r.frame(30)
    ped, old = new_ped(sim)
    r.frame(10)
    p = sim.ent(ped).pos
    return ped, board, (p.x, p.y, p.z)


def zero_frames(r):
    """Frames that report no time at all, on the ground and in the air. Returns whether every number stayed a number."""
    sim = r.sim
    r.get_on()
    r.set('speed', 6.0)
    r.frame(20)
    fine = True
    for air in (False, True):
        if air:
            r.flick(OLLIE)
            r.frame(4)
        sim.S.dt = 0.0
        r.frame(5)
        sim.S.dt = 1 / 60
        r.frame(5)
        s = r.state()
        fine &= all(v == v and abs(v) < 1e6 for v in (s.speed, s.x, s.y, s.z, s.vz, s.facing))
    return fine, r.state().riding


def abort_test(r):
    """/skatetest runway, stopped by an error once it has taken the player there. Returns how far from where they
    stood the player is left, and whether still on the board."""
    sim = r.sim
    r.frame(20)
    p = sim.ent(sim.S.ped).pos
    start = (p.x, p.y, p.z)
    sim.command('skatetest', 'runway')
    for _ in range(60 * 40):
        r.frame()
        if any('RESULT' in x for x in sim.prints()):
            break
    r.frame(120)
    p = sim.ent(sim.S.ped).pos
    said = [x for x in sim.prints() if 'RESULT' in x]
    sim.S.prints = sim.lua.eval('{}')
    return ((p.x - start[0]) ** 2 + (p.y - start[1]) ** 2) ** 0.5, r.state().riding, said


BREAK = ("    if check('place', length >= SHORTEST,", "    error('stopped on purpose')\n    if check('place', length >= SHORTEST,")
OLD_ABORT = ("""            pcall(function()
                if T.state().riding then T.getOff() end
                T.clearRamps()
                if home then goTo(home.x, home.y, home.z, home.h) end
            end)
""", "")


def safety():
    ok = True
    # ---- who may get on
    r = rig.make(goofy=True)
    sim, S = r.sim, r.sim.S
    r.frame(10)
    S.cuffed = True
    r.get_on()
    r.check("a cuffed player cannot get on", not r.state().riding)
    S.cuffed = False
    S.ragdoll = True
    r.get_on()
    r.check("nor one being thrown about (ragdoll)", not r.state().riding)
    S.ragdoll = False
    S.playerState.isDead = True
    r.get_on()
    r.check("nor one the server's framework says is dead (the player's state bag)", not r.state().riding)
    S.playerState.isDead = None
    sim.stand_in('qbx_medical', "exports('IsDead', function() return false end) exports('IsLaststand', function() return SIM.down == true end)")
    S.down = True
    r.get_on()
    r.check("nor one in qbx_medical's last stand", not r.state().riding)
    S.down = False
    sim.run('skateboard', 'Config.CanRide = function(ped) return false end')
    r.get_on()
    r.check("nor one the server's own rule (Config.CanRide) refuses", not r.state().riding)
    sim.run('skateboard', 'Config.CanRide = nil')
    r.get_on()
    r.check("control, none of those: on the board", r.state().riding)
    r.set('speed', 5.0)
    r.frame(20)
    S.cuffed = True
    r.frame(3)
    r.check("cuffed while riding: off the board", not r.state().riding)
    S.cuffed = False
    S.prints = sim.lua.eval('{}')
    ok &= r.finish('safety: who may ride')

    # ---- the player's ped is replaced in the middle of a ride
    r = rig.make(goofy=True)
    ped, board, at = swap(r)
    e = r.sim.ent(ped)
    r.check("the player is given another ped mid-ride: the ride ends, the new ped is left where the game put it "
            "(%.0f, %.0f, %.0f), not frozen" % at, not r.state().riding and at == (100.0, 100.0, 30.0) and not e.frozen)
    b = r.sim.ent(board)
    r.check("... and the board is left in the world, solid and free", r.sim.S.ent[board] is not None
            and b.collision is not False and not b.frozen)
    r.get_on()
    r.frame(10)
    r.check("... and the new ped can get on a board", r.state().riding)
    ok &= r.finish('safety: another ped')
    r = rig.make(goofy=True, patch={'client.lua': back("    if ped ~= sk.rider then return getOff(nil, nil, true) end\n", "")})
    ped, board, at = swap(r)
    ok &= r.check("control, without the check: the ride goes on without the player (the controls stay the ride's)",
                  r.state().riding)

    # ---- frames that take no time
    r = rig.make(goofy=True)
    fine, riding_ = zero_frames(r)
    r.check("frames that report no time (on the ground and in the air): every number of the ride stays a number", fine)
    ok &= r.finish('safety: zero frames')

    # ---- the stance belongs to the ride
    r = rig.make(goofy=True)
    r.get_on()
    r.set('speed', 5.0)
    r.frame(20)
    before = r.state().mirrored
    r.sim.command('skatestance')
    r.frame(20)
    during = r.state().mirrored
    r.get_off()
    r.frame(5)
    r.get_on()
    r.frame(5)
    after = r.state().mirrored
    r.check("/skatestance while riding: the ride keeps its stance (%s -> %s), the next one has the other (%s)" % (before, during, after),
            during == before and after != before)
    r.sim.command('skatestance')
    r.sim.command('skatestance')
    r.get_off()
    r.frame(5)
    r.get_on()
    r.frame(5)
    r.check("... asked for twice while riding: the stance stays", r.state().mirrored == after)
    ok &= r.finish('safety: stance')
    r = rig.make(goofy=True, patch={'client.lua': back("    if riding or off or gettingOn then\n        sk.stance = goofy",
                                                       "    if false then\n        sk.stance = goofy")})
    r.get_on()
    r.set('speed', 5.0)
    r.frame(20)
    before = r.state().mirrored
    r.sim.command('skatestance')
    r.frame(20)
    ok &= r.check("control, changed at once as before: the rider is mirrored in the middle of the ride",
                  r.state().mirrored != before)

    # ---- /skatetest stopped by an error
    r = rig.make(goofy=True, patch={'selftest.lua': lambda s: s.replace(*BREAK)})
    far, on, said = abort_test(r)
    r.check("/skatetest runway stopped by a script error: it says so (%s)" % (said and said[-1][-60:]), bool(said) and 'script error' in said[-1])
    r.check("... and the player is back where they stood (%.1f m away), off the board" % far, far < 1.0 and not on)
    ok &= r.finish('safety: test stopped')
    r = rig.make(goofy=True, patch={'selftest.lua': lambda s: s.replace(*BREAK).replace(*OLD_ABORT)})
    far, on, said = abort_test(r)
    ok &= r.check("control, the old handler: the player is left at the runway (%.0f m away)" % far, far > 100.0)
    return ok


def kerb_carve(r, height=0.15, speed=4.0):
    """Roll off a kerb with the left stick held right over (carving). Returns the state after, and the frames in the air."""
    sim = r.sim
    sim.box(-3.0, 0.0, 0.0, 3.0, 30.0, height)
    r.get_on()
    r.set('pos', (0.0, 28.0, height))
    r.set('speed', speed)
    air, turned = 0, None
    f0 = r.state().facing
    sim.stick(1.0, 0.0, right=False)
    for _ in range(150):
        r.frame()
        st = r.state()
        if st.mode == 'air':
            air += 1
        elif air or not st.riding:
            break
    r.frame(10)
    sim.stick(0.0, 0.0, right=False)
    st = r.state()
    return st, air, f0


def low_fps_jumps(r, fps=20):
    """Jumps of many heights at a low frame rate. Returns how many came down through the floor, of how many."""
    sim = r.sim
    through, n, lowest = 0, 0, 0.0
    for vz in (3.0, 3.6, 4.3, 5.1, 5.8, 6.4, 7.0, 7.7, 8.5, 9.4):
        if not r.state().riding:
            r.get_on()
        r.set('pos', (0.0, 0.0, 0.0))
        r.set('speed', 5.0)
        sim.S.dt = 1 / 60
        r.frame(20)
        r.flick(OLLIE)
        for _ in range(60):
            if r.state().mode == 'air':
                break
            r.frame()
        r.set('vz', vz)
        sim.S.dt = 1.0 / fps
        low = 0.0
        for _ in range(int(4 * fps)):
            r.frame()
            st = r.state()
            low = min(low, st.z)
            if st.mode != 'air' or not st.riding:
                break
        sim.S.dt = 1 / 60
        n += 1
        through += low < -0.3
        lowest = min(lowest, low)
        r.frame(30)
    return through, n, lowest


def steep_rail(r, degrees=30.0, run=5.2):
    """A handrail going down from a platform at `degrees`. The rider ollies onto it from the platform. Returns what
    happened: grinding at all, how far along it was ridden, the most it was ever off the rail's top, the state."""
    import math
    sim = r.sim
    H = 3.0
    drop = run * math.tan(math.radians(degrees))
    sim.box(-3.0, -10.0, 0.0, 3.0, 13.0, H)
    sim.ramp(-0.025, 13.0, 0.025, 13.0 + run, H + 0.3, H + 0.3 - drop, material='METAL_RAILING')
    top = lambda y: H + 0.3 - (y - 13.0) / run * drop
    # (slowly, popping a metre before the rail: a rail this steep falls away faster than a quick rider comes down)
    r.get_on()
    r.set('pos', (0.0, 10.3, H))
    r.set('facing', 0.0)
    r.set('speed', 4.0)
    r.flick(OLLIE, hold=0.3, settle=0)
    ground, far, off, label = 0, 0.0, 0.0, None
    for _ in range(300):
        r.frame()
        st = r.state()
        if st.mode == 'grind':
            ground += 1
            far = max(far, st.y)
            off = max(off, abs(st.z - top(st.y)))
            label = st.grindLabel
        elif ground or not st.riding or st.y > 13.0 + run + 2.0:
            break
    r.frame(30)
    return ground, far - 13.0, off, label, r.state()


def fakie_grind(r):
    """Onto a rail rolling fakie, a pop off it, and down. Returns whether the grind was fakie, the line as scored,
    and the state at the end."""
    sim = r.sim
    sim.rail(x=0.0, y1=15.0, y2=25.0, top=0.3, width=0.05, material='METAL_RAILING')
    r.get_on()
    r.set('pos', (0.0, 8.0, 0.0))
    r.set('facing', 180.0)
    r.set('speed', -8.0)
    r.flick(OLLIE, hold=0.3, settle=0)
    was = None
    for _ in range(120):
        r.frame()
        if r.state().mode == 'grind':
            was = r.state().grindFakie
            break
    r.frame(12)
    r.flick(OLLIE, hold=0.1, settle=0)
    line = ''
    for _ in range(240):
        r.frame()
        st = r.state()
        line = st.line or line
        if st.mode == 'ground' or not st.riding:
            break
    r.frame(20)
    return was, r.state().line or line, r.state()


def drift(r, v):
    """Roll at v m/s with the stick held right. Returns the side of the path the ride says the rider moved to."""
    r.get_on()
    r.set('speed', v)
    r.frame(10)
    r.sim.stick(1.0, 0.0, right=False)
    r.frame(20)
    r.sim.stick(0.0, 0.0, right=False)
    return r.T.lastSide()


def side_grind(r, fakie):
    """Onto a rail that was on the left of the rider's path, rolling forwards or fakie. Returns the grind's label."""
    sim = r.sim
    sim.rail(x=0.0, y1=15.0, y2=25.0, top=0.3, width=0.05, material='METAL_RAILING')
    r.get_on()
    r.set('pos', (0.0, 8.0, 0.0))
    r.set('facing', 180.0 if fakie else 0.0)
    r.set('speed', -8.0 if fakie else 8.0)
    r.flick(OLLIE, hold=0.3, settle=0)
    label = None
    for _ in range(120):
        r.set('lastSide', 1.0)
        r.frame()
        if r.state().mode == 'grind':
            label = r.state().grindLabel
            break
    return label


def bank_jump(r, degrees=30.0):
    """An ollie at the very foot of a bank: the bank goes up faster than the board does. Returns the most the board
    was ever under the bank's surface, and the state at the end."""
    import math
    sim = r.sim
    r.get_on()
    r.set('speed', 8.0)
    r.frame(20)
    r.flick(OLLIE, hold=0.3, settle=0)
    for _ in range(60):
        if r.state().mode == 'air':
            break
        r.frame()
    y0 = r.state().y + 0.15
    k = math.tan(math.radians(degrees))
    sim.ramp(-3.0, y0, 3.0, y0 + 12.0, 0.0, 12.0 * k)
    under = 0.0
    for _ in range(90):
        r.frame()
        st = r.state()
        if not st.riding or st.y > y0 + 11.0:
            break
        if st.y > y0:
            # (in the air the wheels are above the flight path by the tuck of the legs)
            under = max(under, (st.y - y0) * k - (st.z + (st.lift if st.mode == 'air' else 0.0)))
    return under, r.state()


def landing():
    ok = True
    r = rig.make(goofy=True)
    under, st = bank_jump(r)
    r.check("an ollie at the foot of a 30 degree bank: the board is on the bank, never under it (%.0f cm at most); "
            "still riding (%s)" % (under * 100, st.message), under < 0.12 and st.riding)
    ok &= r.finish('landing: bank')
    r = rig.make(goofy=True, patch={'client.lua': back("            if upHit and airTime > 0.05 then", "            if false then")})
    under, st = bank_jump(r)
    ok &= r.check("control, nothing looked for while the board goes up: it goes under the bank (%.0f cm)" % (under * 100), under > 0.3)
    r = rig.make(goofy=True)
    a = drift(r, 5.0)
    b = drift(rig.make(goofy=True), -5.0)
    r.check("the stick held right bends the path to the right rolling forwards (%+.0f) and rolling fakie (%+.0f)" % (a, b),
            a < 0 and b < 0)
    a = side_grind(rig.make(goofy=True), False)
    b = side_grind(rig.make(goofy=True), True)
    r.check("a rail on the left of the path, goofy rider: forwards it is on the toe side (%s), fakie on the heel side (%s)" % (a, b),
            a == 'FS 50-50' and b == 'BS 50-50')
    a = side_grind(rig.make(goofy=False), False)
    b = side_grind(rig.make(goofy=False), True)
    r.check("... regular rider: the other way round (%s, %s)" % (a, b), a == 'BS 50-50' and b == 'FS 50-50')
    ok &= r.finish('landing: sides')
    v = drift(rig.make(goofy=True, patch={'client.lua': back("lastSide = -steer end", "lastSide = -steer * sign(speed) end")}), -5.0)
    ok &= r.check("control, the old rule for the stick: rolling fakie it says the other side (%+.0f)" % v, v > 0)
    v = side_grind(rig.make(goofy=True, patch={'client.lua': back(
        "        if fakie and side ~= 0 then toeSide = not toeSide end\n", "")}), True)
    ok &= r.check("control, the toes always taken to point one way: the fakie grind gets the forward one's side (%s)" % v, v == 'FS 50-50')
    r = rig.make(goofy=True)
    was, line, st = fakie_grind(r)
    r.check("onto a rail rolling fakie and popped off it again: a fakie grind (%s), still rolling fakie after "
            "(%.1f m/s), and no 180 in the line: %s" % (was, st.speed, line),
            was is True and st.riding and st.speed < -1.0 and line == 'Fakie Ollie + 50-50 + Fakie Ollie')
    ok &= r.finish('landing: fakie grind')
    r = rig.make(goofy=True, patch={'client.lua': back("    local turns = math.abs(madeTurns)\n", "    local turns = math.abs(halfTurns)\n")})
    was, line, st = fakie_grind(r)
    ok &= r.check("control, every half turn of the body counted as before: a 180 nobody did (%s)" % line, '180' in line)
    r = rig.make(goofy=True)
    n, far, off, label, st = steep_rail(r)
    r.check("a handrail going down at 30 degrees: landed on, it is a grind (%s, %d frames), ridden %.1f of its 5.2 m, "
            "never more than %.0f cm off its top; still riding after (%s)" % (label, n, far, off * 100, st.message),
            n > 10 and far > 4.5 and off < 0.12 and st.riding)
    ok &= r.finish('landing: steep rail')

    def flat_only(src):
        a = "            on[i] = math.abs(d) < 0.15 or (o ~= nil and math.abs(d) <= RING_SLANT and d * (o - p.z) < 0.0 and\n                math.abs((z + o) * 0.5 - p.z) < 0.1)"
        assert src.count(a) == 1
        return src.replace(a, "            on[i] = math.abs(d) < 0.15")

    r = rig.make(goofy=True, patch={'client.lua': flat_only})
    n, far, off, label, st = steep_rail(r)
    ok &= r.check("control, a rail only where its top is level (as before): the same handrail is not a grind (%d frames)" % n, n == 0)
    r = rig.make(goofy=True)
    n, far, off, label, st = steep_rail(r, 0.0)
    ok &= r.check("control, the same rail lying level: a grind to its end (%d frames, %.1f m)" % (n, far), n > 10 and far > 4.5)
    r = rig.make(goofy=True)
    through, n, lowest = low_fps_jumps(r)
    r.check("%d jumps at 20 frames a second: none comes down through the floor (%d did; lowest %.2f m)" % (n, through, lowest),
            through == 0)
    r.sim.S.prints = r.sim.lua.eval('{}')
    ok &= r.finish('landing: low frame rate')
    r = rig.make(goofy=True)
    st, air, f0 = kerb_carve(r)
    r.check("carving off a 15 cm kerb (%d frames off the ground): still riding (%s), turned on round (%.0f degrees)" % (
        air, st.message, (st.facing - f0 + 180.0) % 360.0 - 180.0), st.riding and air >= 3)
    ok &= r.finish('landing: kerb')
    def old(src):
        a = "    if natural then\n        -- off a kerb while carving: the board went on turning as it does on the ground."
        b = "        if not (air and air.name) and airTime < Tune.naturalAirTime then"
        assert src.count(a) == 1 and src.count(b) == 1
        return src.replace(a, a.replace("if natural then", "if false then")).replace(b, "        if false then")

    r = rig.make(goofy=True, patch={'client.lua': old})
    st, air, f0 = kerb_carve(r)
    ok &= r.check("control, spun and judged like a jump as before: a bail (%s)" % st.message,
                  not st.riding and st.message == 'Landed sideways')
    return ok


def big_ollie(r, vz=7.0, settle=30):
    r.flick(OLLIE)
    for _ in range(60):
        if r.state().mode == 'air':
            break
        r.frame()
    r.set('vz', vz)
    r.frame(settle)


def tip_grab(r, goofy=True):
    """A tail grab begun with the stick up; then the stick let go with the trigger still held; then the trigger too.
    Returns the grab at each of the three moments."""
    sim = r.sim
    back_hand = LT if goofy else RT
    r.get_on()
    r.set('speed', 6.0)
    r.frame(30)
    big_ollie(r, vz=9.0)
    sim.stick(0.0, 0.8)
    r.frame(4)
    sim.hold(back_hand)
    r.frame(20)
    a = r.state().grab
    sim.stick(0.0, 0.0)
    r.frame(30)
    b = r.state().grab
    sim.hold(back_hand, False)
    r.frame(6)
    c = r.state().grab
    return a, b, c


def grabs():
    ok = True
    r = rig.make(goofy=True)
    a, b, c = tip_grab(r)
    r.check("a tail grab begun with the stick up (%s) stays with the stick let go for half a second while the trigger "
            "is held (%s), and ends with the trigger (%s)" % (a, b, c), a == 'tail' and b == 'tail' and c is None)
    ok &= r.finish('grabs: the trigger holds it')

    def old(src):
        a = "                on = (g.hand == 'back' and backHeld) or (g.hand == 'front' and frontHeld)\n"
        assert src.count(a) == 1
        return src.replace(a, a + "                if TIP[g.kind] then g.loose = zone and 0.0 or (g.loose or 0.0) + dt "
                                  "if g.loose > 0.2 then on = false end end\n")

    a, b, c = tip_grab(rig.make(goofy=True, patch={'client.lua': old}))
    ok &= r.check("control, ended 0.2 s after the stick is let go as before: the grab is gone or another (%s)" % b, a == 'tail' and b != 'tail')
    return ok


# the controller as it was before build 15, for the controls that need the whole old file
OLD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "old")


def how_played(r):
    """Every clip the ride plays from now on, with the blend time and the speed it was asked for:
    {clip: (blend, rate)} of the last time each was played."""
    r.sim.run('skate3_assets', """
        local P = Play
        PLAYLOG = {}
        Play = function(id, clip, opts, wait)
            PLAYLOG[#PLAYLOG + 1] = { clip = clip, blend = opts and opts.blend or -1, rate = opts and opts.rate or 1.0 }
            return P(id, clip, opts, wait)
        end
        return true""")

    def read():
        out = {}
        log = r.sim.run('skate3_assets', 'return PLAYLOG')
        for e in log.values():
            out[str(e.clip).replace('_mir', '')] = (round(e.blend, 3), round(e.rate, 3))
        return out
    return read


def chain_times(r):
    """The crouch, a nose manual and out of it, the turn to switch by itself and pushed, the first clip of a grind."""
    sim = r.sim
    sim.rail(x=0.0, y1=215.0, y2=225.0, top=0.3, width=0.05, material='METAL_RAILING')
    r.get_on()
    read = how_played(r)
    r.set('speed', 7.0)
    r.frame(20)
    sim.stick(0.0, -1.0)                 # the crouch
    r.frame(30)
    sim.stick(0.0, 0.0)
    r.frame(40)
    r.set('speed', 7.0)
    sim.stick(0.0, 0.4)                  # part of the way up: a nose manual
    r.frame(60)
    sim.stick(0.0, 0.0)
    r.frame(40)
    got = read()
    # rolling fakie: the turn to switch by itself after a moment ...
    r.set('speed', -6.0)
    r.frame(90)
    alone = read().get('r_switch_ride_n_0_n')
    r.get_off()
    r.frame(5)
    r.get_on()
    read = how_played(r)
    # ... and pushed out of fakie
    r.set('speed', -6.0)
    r.frame(5)
    sim.hold(A)
    r.frame(30)
    sim.hold(A, False)
    pushed = read().get('r_switch_ride_n_0_n')
    r.frame(60)
    # onto a rail
    r.set('pos', (0.0, 208.0, 0.0))
    r.set('facing', 0.0)
    r.set('speed', 8.0)
    r.frame(2)
    r.flick(OLLIE, hold=0.3, settle=0)
    for _ in range(120):
        r.frame()
        if r.state().mode == 'grind':
            break
    r.frame(3)
    g = read()
    grind = [v for k, v in g.items() if k.startswith('g_')]     # (g_5050_fs_hi_0_cyc: the grind's own clip)
    return got, alone, pushed, (grind[0] if grind else None), r.state()


def chains():
    ok = True
    r = rig.make(goofy=True)
    got, alone, pushed, grind, st = chain_times(r)
    r.check("the crouch goes in over 0.2 s at 1.2 times its speed (%s)" % (got.get('r_antic_ollie_n_0_into'),),
            got.get('r_antic_ollie_n_0_into') == (0.2, 1.2))
    r.check("the nose manual: into over 0.1 s (%s), its cycle over 0.3 (%s), out over 0.1 (%s)" % (
        got.get('m_noseidle_n_0_into'), got.get('m_noseidle_n_0_cyc'), got.get('m_noseidle_n_0_out')),
        got.get('m_noseidle_n_0_into') == (0.1, 1.0) and got.get('m_noseidle_n_0_cyc') == (0.3, 1.0)
        and got.get('m_noseidle_n_0_out') == (0.1, 1.0))
    r.check("the turn to switch: by itself over 0.1 s as it is (%s), pushed out of fakie over 0.15 s at 1.25 times (%s)" % (alone, pushed),
            alone == (0.1, 1.0) and pushed == (0.15, 1.25))
    r.check("the first clip of a grind blends in over 0.3 s (%s; grinding %s)" % (grind, st.mode), grind is not None and grind[0] == 0.3)
    ok &= r.finish('chains')
    r = rig.make(goofy=True, patch={'s3.lua': lambda s: open(OLD + r"\s3.lua", encoding='utf-8').read()})
    got, alone, pushed, grind, st = chain_times(r)
    ok &= r.check("control, the clip logic as it was: the crouch at its own speed (%s), the manual 0.2 / 0.1 (%s %s), one way "
                  "to switch (%s %s), the grind in 0.15 (%s)" % (got.get('r_antic_ollie_n_0_into'), got.get('m_noseidle_n_0_into'),
                                                               got.get('m_noseidle_n_0_cyc'), alone, pushed, grind),
                  got.get('r_antic_ollie_n_0_into') == (0.2, 1.0) and got.get('m_noseidle_n_0_into') == (0.2, 1.0)
                  and alone == pushed and grind is not None and grind[0] == 0.15)
    return ok


def run_until(r, cond, frames=600):
    for i in range(frames):
        r.frame()
        if cond(r.state()):
            return i + 1
    return None


def rot_zxy(x, y, z):
    """The game's usual order for three angles (2): about y first, then x, then z. Rows of the matrix."""
    import math
    a, b, c = (math.radians(v) for v in (x, y, z))
    sa, ca, sb, cb, sc, cc = math.sin(a), math.cos(a), math.sin(b), math.cos(b), math.sin(c), math.cos(c)
    return ((cc * cb - sc * sa * sb, -sc * ca, cc * sb + sc * sa * cb),
            (sc * cb + cc * sa * sb, cc * ca, sc * sb - cc * sa * cb),
            (-ca * sb, sa, ca * cb))


def rot_q(q):
    x, y, z, w = q
    return ((1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)),
            (2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)),
            (2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)))


def qmul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz)


def carry_run(r, goofy):
    """Off the board into a stand, a walk with a turn, a run, a stop, and back on. Returns what the board was fixed
    to at each stage."""
    import math
    sim, S = r.sim, r.sim.S
    r.frame(5)
    board = r.get_on()
    r.set('speed', 0.4)
    r.frame(10)
    sim.press(Y)
    r.frame(3)
    out = {'board': board}
    a = sim.ent(board).attached
    out['dismount'] = a and a.to                                   # (during the dismount the track has the board)
    run_until(r, lambda s: s.off == 'stand')
    r.frame(20)
    a = sim.ent(board).attached
    out['stand'] = (a.to, a.bone, a.order, (a.pos.x, a.pos.y, a.pos.z), tuple(a.rot.values())) if a else None
    n0 = S.attaches
    sim.stick(0.0, 0.4, right=False)
    run_until(r, lambda s: s.off == 'move')
    sim.stick(0.6, 0.6, right=False)
    r.frame(30)
    sim.stick(0.0, 1.0, right=False)
    r.frame(40)
    a = sim.ent(board).attached
    out['run'] = (a.to, a.bone) if a else None
    sim.stick(0.0, 0.0, right=False)
    run_until(r, lambda s: s.off == 'stand')
    r.frame(10)
    a = sim.ent(board).attached
    out['stopped'] = (a.to, a.bone) if a else None
    out['calls'] = S.attaches - n0        # (fixed once, not every frame)
    sim.press(Y)
    r.frame(4)
    a = sim.ent(board).attached
    out['mount'] = a and a.to
    out['clip'] = r.state().clip
    n = run_until(r, lambda s: s.riding)
    r.frame(10)
    a = sim.ent(board).attached
    out['riding'] = (n is not None, a and a.to)
    return out


def carry():
    """Skate 3 keeps the board in the hand while it is carried. Seen in the game on 10-08: put where a track said, the
    board left the hand in every start, stop and turn. Now it is fixed to the hand bone while a clip carries it."""
    import math
    ok = True
    for goofy in (True, False):
        who = 'goofy' if goofy else 'regular'
        r = rig.make(goofy=goofy, server=True)
        sim = r.sim
        grip = sim.run('skate3_assets', 'return SkateBoardGrip')
        r.check("the built assets say how the board sits in each hand", grip is not None and grip.R is not None and grip.L is not None)
        o = carry_run(r, goofy)
        hand = 57005 if goofy else 18905
        st = o['stand']
        r.check("%s: stepping off, the board follows the dismount's own track (fixed to nothing)" % who, o['dismount'] is None)
        r.check("%s: standing with it: fixed to the hand bone that carries it (%s; SKEL_%s_Hand), with the game's usual "
                "order of angles (%s)" % (who, st and st[1], 'R' if goofy else 'L', st and st[2]),
                st is not None and st[0] == 1 and st[1] == hand and st[2] == 2)
        # the angles given to the game are the grip's rotation (times the model's own turn about its upright axis)
        g = grip.R if goofy else grip.L
        gq = (g[4], g[5], g[6], g[7])
        want = [rot_q(qmul(gq, (0.0, 0.0, math.sin(math.radians(y) / 2), math.cos(math.radians(y) / 2)))) for y in (0.0, 90.0)]
        got = rot_zxy(*st[4]) if st else None
        err = min(max(abs(a - b) for ra, rb in zip(w, got) for a, b in zip(ra, rb)) for w in want) if got else 9.0
        r.check("%s: ... the three angles make the grip's own rotation (off by %.4f at most)" % (who, err), err < 0.002)
        reach = math.sqrt(sum(v * v for v in st[3])) if st else 9.0
        r.check("%s: ... and the board's middle is a forearm's width from the wrist (%.2f m)" % (who, reach), 0.05 < reach < 0.45)
        r.check("%s: walking, turning, running, stopping: in the same hand throughout (%s, %s), fixed there %d times, not "
                "every frame" % (who, o['run'], o['stopped'], o['calls']),
                o['run'] == (1, hand) and o['stopped'] == (1, hand) and o['calls'] <= 3)
        r.check("%s: the mount (%s) takes it out of the hand: the clip's track puts it down" % (who, o['clip']),
                o['mount'] is None and 'into_mount' in str(o['clip']))
        r.check("%s: ... and the ride has the board under the feet, fixed to nothing" % who, o['riding'] == (True, None))
        ok &= r.finish('carry: ' + who)

    # control: assets as they were (no grip in them): the board is put where the tracks say, as before
    def no_grip(src):
        assert 'local side = t and t.hand and SkateBoardGrip and' in src
        return src.replace('local side = t and t.hand and SkateBoardGrip and', 'local side = false and')

    r = rig.make(goofy=True, server=True, patch={'s3_player.lua': no_grip})
    o = carry_run(r, True)
    ok &= r.check("control, without it: never fixed to the hand (%s, %s)" % (o['stand'], o['run']),
                  o['stand'] is None and o['run'] is None and o['riding'][0])
    return ok


def slam(r, wall_y=12.0, speed=8.0):
    """Ride into a wall across the path. Returns the board and the state when the bail has happened."""
    sim = r.sim
    sim.box(-5, wall_y, 0, 5, wall_y + 1.0, 3)
    board = r.get_on()
    r.set('speed', speed)
    for _ in range(200):
        r.frame()
        if not r.state().riding:
            break
    return board, r.state()


def vec(sim, x, y, z):
    return sim.lua.eval("vector3(%r, %r, %r)" % (float(x), float(y), float(z)))


def bailboard():
    """After a bail the board is a thing lying in the world. The game's physics is not simulated here; what is checked
    is how the board is handed to it and what is done when the physics loses it."""
    import math
    ok = True
    r = rig.make(goofy=True, server=True, target=True)
    sim, S = r.sim, r.sim.S
    board, st = slam(r)
    b = sim.ent(board)
    r.check("riding into a wall: a bail (%s), and the board is still in the world: the same thing, solid, free to move, "
            "with its trucks and wheels" % st.message, 'Slammed' in str(st.message) and S.ent[board] is not None
            and r.state().board == board and b.collision is True and not b.frozen and b.dynamic is True and b.awake is True
            and len(list(r.state().parts.values())) == 2)
    r.check("... let go of clear of the wall and of the ground (%.2f m back from where the ride stopped, %.2f m up), and "
            "thrown back off the wall (%.1f m/s along the way it came, %.1f up)" % (st.y - b.pos.y, b.pos.z, b.velocity.y, b.velocity.z),
            0.4 < st.y - b.pos.y < 0.8 and 0.15 < b.pos.z < 0.4 and -3.0 < b.velocity.y < -0.5 and b.velocity.z > 0.5)
    # it tumbles off and comes to rest: there it stays, a prop in the world
    b.pos = vec(sim, 1.5, st.y - 3.0, 0.02)
    b.velocity = vec(sim, 0.0, 0.0, 0.0)
    r.frame(120)
    b = sim.ent(board)
    r.check("it comes to rest three metres off: it stays there (%.1f, %.1f), the same board, not held in place" % (b.pos.x, b.pos.y),
            S.ent[board] is not None and r.state().board == board and abs(b.pos.x - 1.5) < 0.01 and not b.frozen)
    # ... and can be gone back to and ridden
    r.set('pos', (1.5, st.y - 3.0, 0.0))
    sim.ent(1).pos = vec(sim, 1.5, st.y - 3.5, 1.0)
    r.get_on()
    r.frame(10)
    r.check("... and walked back to, it is the board that is ridden", r.state().riding and r.state().board == board)
    S.prints = sim.lua.eval('{}')
    ok &= r.finish('bailboard: stays')

    # the physics loses it: through the ground
    r = rig.make(goofy=True, server=True)
    sim, S = r.sim, r.sim.S
    board, st = slam(r)
    b = sim.ent(board)
    b.pos = vec(sim, 0.0, st.y - 1.0, -40.0)
    b.velocity = vec(sim, 0.0, 0.0, -20.0)
    r.frame(30)
    b = sim.ent(board)
    r.check("a board that goes through the ground is put back on it where the rider fell, to stay (%.1f, %.1f, %.2f)" % (
        b.pos.x, b.pos.y, b.pos.z), S.ent[board] is not None and abs(b.pos.z) < 0.2 and abs(b.pos.y - st.y) < 1.0
        and b.frozen and (b.grounded or 0) >= 1)
    ok &= r.finish('bailboard: through the ground')
    r = rig.make(goofy=True, server=True, patch={'client.lua': back(
        "    SetEntityVelocity(b, out.x, out.y, hitWall and 1.5 or 3.0)\n    SK.watch(b, home)\n",
        "    SetEntityVelocity(b, out.x, out.y, hitWall and 1.5 or 3.0)\n")})
    sim, S = r.sim, r.sim.S
    board, st = slam(r)
    sim.ent(board).pos = vec(sim, 0.0, st.y - 1.0, -40.0)
    r.frame(30)
    ok &= r.check("control, nobody watching it: it stays under the world (z %.0f)" % sim.ent(board).pos.z, sim.ent(board).pos.z < -30.0)

    # thrown out of sight
    r = rig.make(goofy=True, server=True)
    sim, S = r.sim, r.sim.S
    board, st = slam(r)
    sim.ent(board).pos = vec(sim, 150.0, st.y, 30.0)
    r.frame(30)
    b = sim.ent(board)
    r.check("one thrown 150 m off is put back too (%.1f, %.1f)" % (b.pos.x, b.pos.y), abs(b.pos.x) < 1.0 and b.frozen)
    ok &= r.finish('bailboard: out of sight')

    # taken out of the world (a server's clean-up, the game itself)
    r = rig.make(goofy=True, server=True, target=True)
    sim, S = r.sim, r.sim.S
    board, st = slam(r)
    S.ent[board] = None
    r.frame(40)
    nb = r.state().board
    r.check("one taken out of the world: another lies where the rider fell, with its trucks and wheels (%s -> %s)" % (board, nb),
            nb is not None and nb != board and S.ent[nb] is not None and abs(sim.ent(nb).pos.y - st.y) < 1.0
            and sim.ent(nb).frozen and len(list(r.state().parts.values())) == 2 and r.state().targetAdded)
    ok &= r.finish('bailboard: gone')

    # the physics never takes it
    r = rig.make(goofy=True, server=True)
    sim, S = r.sim, r.sim.S
    board, st = slam(r)
    sim.ent(board).velocity = vec(sim, 0.0, 0.0, 0.0)
    r.frame(90)
    b = sim.ent(board)
    r.check("one the physics does not move is set down on the ground where it is (not left hanging)", (b.grounded or 0) >= 1 and not b.frozen)
    ok &= r.finish('bailboard: not moved')

    # control: handed to the physics as before, inside the wall and thrown at it
    def old(src):
        a = "        if board then SK.throwBoard(f, bailReason == 'Hit a wall' or bailReason == 'Slammed') end\n"
        assert src.count(a) == 1
        return src.replace(a, "        if board then SetEntityVelocity(board, f.x * 0.7, f.y * 0.7, 3.0) end\n")

    r = rig.make(goofy=True, server=True, patch={'client.lua': old})
    sim, S = r.sim, r.sim.S
    board, st = slam(r)
    b = sim.ent(board)
    ok &= r.check("control, as it was: let go of where the ride stopped, at the wall, and thrown on into it (%.2f m back, "
                  "%.1f m/s towards it)" % (st.y - b.pos.y, b.velocity.y), st.y - b.pos.y < 0.2 and b.velocity.y > 3.0)

    # the get-on key far from the board
    for call, want in ((True, 'called'), (False, 'left')):
        r = rig.make(goofy=True, server=True, config="Config.CallBoard = %s" % ('true' if call else 'false'))
        sim, S = r.sim, r.sim.S
        board, st = slam(r)
        sim.ent(board).pos = vec(sim, 6.0, st.y - 8.0, 0.02)
        sim.ent(board).velocity = vec(sim, 0.0, 0.0, 0.0)
        r.frame(90)
        r.get_on()
        r.frame(10)
        s = r.state()
        if call:
            r.check("the get-on key ten metres from the board: it is called for (that one goes, another is under the feet)",
                    s.riding and s.board != board and S.ent[board] is None)
        else:
            r.check("Config.CallBoard = false: the get-on key far from the board leaves it lying there (not riding, "
                    "the board where it was)", not s.riding and s.board == board and S.ent[board] is not None
                    and abs(sim.ent(board).pos.x - 6.0) < 0.01)
        S.prints = sim.lua.eval('{}')
        ok &= r.finish('bailboard: ' + want)
    return ok


SCENARIOS = {'bailboard': bailboard, 'carry': carry, 'chains': chains, 'grabs': grabs, 'riding': riding, 'devtools': devtools, 'safety': safety, 'landing': landing}

if __name__ == "__main__":
    names = sys.argv[1:] or list(SCENARIOS)
    good = True
    for name in names:
        good &= bool(SCENARIOS[name]())
    print("PASS" if good else "FAIL")
    sys.exit(0 if good else 1)
