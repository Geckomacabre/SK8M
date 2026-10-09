"""Skate 3's off-board mode: off the board with it in the hand, walking, running, sprinting, back onto it, and letting
go of it in the air.

usage: python offtest.py        (also the scenario "offboard" of ridetest.py)
"""
import math
import sys

import rig
from rig import A, RT

Y = 23
OLLIE = [(0.0, 1.0), (0.0, -1.0)]


def run_until(r, cond, frames=400):
    for i in range(frames):
        if cond(r.state()):
            return i
        r.frame()
    return None


def speed_over(r, frames=60):
    a = r.state()
    r.frame(frames)
    b = r.state()
    return math.hypot(b.x - a.x, b.y - a.y) / (frames / 60.0)


def offboard():
    ok = True
    for goofy in (True, False):
        who = 'goofy' if goofy else 'regular'
        m = '' if goofy else '_mir'
        r = rig.make(goofy=goofy, server=True)
        sim, S = r.sim, r.sim.S
        r.frame(5)
        board = r.get_on()
        parts = list(r.state().parts.values())
        r.set('speed', 0.4)
        r.frame(10)
        sim.played(clear=True)
        sim.press(Y)
        r.frame(3)
        s = r.state()
        played = sim.played(clear=True)
        r.check(f"{who}: Y while rolling slowly: off the board Skate 3's way, into a stand ({s.off}, {played})",
                not s.riding and s.off == 'stop' and played == ['br_dismount_hi_into_stand_0' + m] and s.offHolding)
        n = run_until(r, lambda s: s.off == 'stand')
        s = r.state()
        ped, b = sim.ent(1), sim.ent(board)
        r.check(f"{who}: ... then stands with the board in the hand ({s.clip}; the board {b.pos.z - s.z:.2f} m above the "
                f"ground, {math.hypot(b.pos.x - ped.pos.x, b.pos.y - ped.pos.y):.2f} m from the body), still the same board "
                f"with its trucks and wheels", n is not None and s.clip == 'br_stand_0_cyc' + m and 0.4 < b.pos.z - s.z < 1.0
                and math.hypot(b.pos.x - ped.pos.x, b.pos.y - ped.pos.y) < 0.6 and s.board == board
                and all(S.ent[e] is not None for e in parts) and ped.frozen)

        # walking: the stick part of the way; the clip's own root motion sets the pace
        sim.played(clear=True)
        sim.stick(0.0, 0.4, right=False)
        run_until(r, lambda s: s.off == 'move')
        played = sim.played(clear=True)
        v = speed_over(r)
        s = r.state()
        r.check(f"{who}: stick part of the way: the start clip, then Skate 3's walk at its own pace ({played}, {v:.2f} m/s)",
                played == ['br_stand_0_into_walk_fwd' + m, 'br_walk_fwd_cyc' + m] and s.offGait == 'walk' and 1.3 < v < 2.0)
        sim.stick(0.0, 1.0, right=False)
        r.frame(20)
        v = speed_over(r)
        r.check(f"{who}: stick all the way: the run ({r.state().clip}, {v:.2f} m/s)",
                r.state().clip == 'br_run_fwd_cyc' + m and 4.5 < v < 6.0)
        sim.hold(A, True)
        r.frame(20)
        v = speed_over(r)
        r.check(f"{who}: A held: the sprint ({r.state().clip}, {v:.2f} m/s)",
                r.state().clip == 'br_sprint_fwd_cyc' + m and 8.0 < v < 10.0)
        sim.hold(A, False)
        r.frame(20)
        h0 = r.state().offHeading
        sim.stick(1.0, 0.0, right=False)
        r.frame(20)
        h1 = r.state().offHeading
        r.check(f"{who}: stick to the right: the rider turns to the right ({(h0 - h1 + 180) % 360 - 180:.0f} degrees in a third of a second)",
                5.0 < (h0 - h1 + 180) % 360 - 180 < 180.0)
        sim.stick(0.0, 1.0, right=False)
        r.frame(30)
        sim.played(clear=True)
        sim.stick(0.0, 0.0, right=False)
        r.frame(3)
        stop = sim.played(clear=True)
        n = run_until(r, lambda s: s.off == 'stand')
        r.check(f"{who}: stick let go: a stop for where the stride was, then the stand ({stop})",
                len(stop) == 1 and stop[0].startswith('br_run_fwd_') and stop[0].endswith('_into_stand_0' + m) and n is not None)

        # back onto the board out of a stand
        sim.played(clear=True)
        sim.press(Y)
        r.frame(3)
        clip = r.state().clip
        n = run_until(r, lambda s: s.riding)
        s = r.state()
        r.check(f"{who}: Y standing: Skate 3's mount out of a stand, then riding the same board ({clip}, {n} frames, "
                f"{s.speed:.1f} m/s)", clip == 'br_stand_0_into_mount' + m and n is not None and s.riding and s.off is None
                and s.board == board and s.mode == 'ground' and 0.0 <= s.speed < 2.5)
        # off at speed: into a run, and back on out of the run
        r.set('speed', 5.0)
        r.frame(20)
        sim.stick(0.0, 1.0, right=False)
        sim.played(clear=True)
        sim.press(Y)
        r.frame(3)
        clip = sim.played(clear=True)
        run_until(r, lambda s: s.off == 'move')
        r.frame(20)
        sim.played(clear=True)
        sim.press(Y)
        r.frame(3)
        mount = sim.played(clear=True)
        n = run_until(r, lambda s: s.riding)
        s = r.state()
        r.check(f"{who}: Y at 5 m/s: off into a run ({clip}); Y in the run: the running mount for that stride ({mount}), "
                f"and the ride goes on rolling ({s.speed:.1f} m/s)",
                clip == ['br_dismount_hi_into_run_fwd' + m] and len(mount) == 1 and mount[0].startswith('br_run_fwd_')
                and mount[0].endswith('_into_mount' + m) and n is not None and s.speed > 2.0)
        sim.stick(0.0, 0.0, right=False)
        ok &= r.finish('offboard ' + who)

    # in the air
    r = rig.make(goofy=True, server=True)
    sim, S = r.sim, r.sim.S
    r.frame(5)
    board = r.get_on()
    r.set('speed', 4.0)
    r.frame(20)
    r.flick(OLLIE)
    run_until(r, lambda s: s.mode == 'air', 60)
    r.set('vz', 6.0)
    r.frame(8)
    sim.played(clear=True)
    sim.press(Y)
    r.frame(2)
    s = r.state()
    played = sim.played(clear=True)
    b = sim.ent(board)
    r.check(f"Y high in the air: the board is kicked away ({played}), it is its own thing now (not frozen, collision on, "
            f"thrown), and the rider is in the air without it ({s.off}, holding {s.offHolding})",
            played == ['br_kickout_hi_into_nb_air'] and s.off == 'air' and not s.offHolding and not s.riding
            and b.frozen is False and b.collision is True and b.velocity is not None)
    n = run_until(r, lambda s: s.off in ('stop', 'into', 'move', 'stand'))
    s = r.state()
    landing = sim.played(clear=True)
    r.check(f"... and comes down on the feet, into a run without the board ({landing}, {s.off})",
            n is not None and len(landing) >= 1 and landing[0].startswith('nb_land_') and s.riding is False)
    run_until(r, lambda s: s.off == 'stand')
    r.check(f"standing without the board plays the no-board stand ({r.state().clip})", r.state().clip == 'nb_stand_0_cyc')
    sim.press(Y)
    r.frame(3)
    s = r.state()
    n = run_until(r, lambda s: s.riding)
    r.check(f"Y without the board: it is fetched and mounted ({s.clip}); riding again on the same board",
            s.clip == 'br_stand_0_into_mount' and n is not None and r.state().board == board and sim.ent(board).frozen)

    # a hand on the board in the air: it comes along
    r.set('speed', 4.0)
    r.frame(20)
    r.flick(OLLIE)
    run_until(r, lambda s: s.mode == 'air', 60)
    r.set('vz', 6.0)
    sim.hold(RT, True)
    r.frame(25)
    grab = r.state().grab
    sim.played(clear=True)
    sim.press(Y)
    r.frame(2)
    s = r.state()
    played = sim.played(clear=True)
    sim.hold(RT, False)
    r.check(f"Y in the air with a hand on the board ({grab}): the board comes along in that hand ({played}, holding {s.offHolding})",
            grab is not None and len(played) == 1 and played[0].startswith('br_dismount_') and played[0].endswith('_into_br_air')
            and s.off == 'air' and s.offHolding)
    n = run_until(r, lambda s: s.off in ('stop', 'into'))
    landing = sim.played(clear=True)
    r.check(f"... and the landing is the one with the board ({landing})", n is not None and landing and landing[0].startswith('br_land_'))
    run_until(r, lambda s: s.off == 'stand')
    sim.press(Y)
    run_until(r, lambda s: s.riding)

    # control: in the last 0.3 s before a landing Skate 3 does not let go of the board
    r.set('speed', 4.0)
    r.frame(20)
    r.flick(OLLIE)
    run_until(r, lambda s: s.mode == 'air' and s.ttl <= 0.25, 120)
    in_air = r.state().mode == 'air'
    sim.press(Y)
    r.frame(2)
    r.check(f"control, Y within 0.3 s of landing: nothing happens, still on the board (in the air {in_air})",
            in_air and r.state().riding and r.state().off is None)
    run_until(r, lambda s: s.mode == 'ground', 120)
    ok &= r.finish('offboard: air')

    # the world: a wall stops the rider, a kerb is walked up, a ledge is a fall, a long fall is a bail
    r = rig.make(goofy=True, server=True)
    sim, S = r.sim, r.sim.S
    sim.box(-5, 12, 0, 5, 13, 3)            # a wall across the way at y = 12
    r.frame(5)
    r.get_on()
    r.set('speed', 0.3)
    r.frame(20)   # (the ride loop sleeps up to a quarter second while nobody rides)
    sim.press(Y)
    run_until(r, lambda s: s.off == 'stand')
    sim.stick(0.0, 1.0, right=False)
    r.frame(360)
    s = r.state()
    r.check(f"running at a wall: stopped in front of it (y {s.y:.2f}, the wall is at 12)", 9.0 < s.y < 12.0 and s.off is not None)
    sim.stick(0.0, 0.0, right=False)
    ok &= r.finish('offboard: wall')

    r = rig.make(goofy=True, server=True)
    sim, S = r.sim, r.sim.S
    sim.box(-5, 6, 0, 5, 30, 0.3)           # a kerb 0.3 m up from y = 6 to 30, then a 0.3 m step down
    sim.box(-5, 30, -6, 5, 31, 0.3)
    r.frame(5)
    r.get_on()
    r.set('speed', 0.3)
    r.frame(20)   # (the ride loop sleeps up to a quarter second while nobody rides)
    sim.press(Y)
    run_until(r, lambda s: s.off == 'stand')
    sim.stick(0.0, 0.4, right=False)
    run_until(r, lambda s: s.y > 8.0, 900)
    s = r.state()
    r.check(f"walking up a 0.3 m kerb: on top of it (z {s.z:.2f})", abs(s.z - 0.3) < 0.02 and s.off == 'move')
    sim.stick(0.0, 0.0, right=False)
    ok &= r.finish('offboard: kerb')

    r = rig.make(goofy=True, server=True)
    sim, S = r.sim, r.sim.S
    env = sim.lua.eval('function(S) S.boxes = {} end')
    env(S)
    sim.box(-50, -50, -10, 50, 8, 0)        # the ground ends at y = 8 ...
    sim.box(-50, 8, -40, 50, 80, -30)       # ... with a 30 m drop
    r.frame(5)
    r.get_on()
    r.set('speed', 0.3)
    r.frame(20)   # (the ride loop sleeps up to a quarter second while nobody rides)
    sim.press(Y)
    run_until(r, lambda s: s.off == 'stand')
    sim.stick(0.0, 1.0, right=False)
    fell = run_until(r, lambda s: s.off == 'air', 600)
    done = run_until(r, lambda s: s.off is None, 600)
    r.check(f"running off a 30 m drop: a fall, and a fall that long is a bail (fell {fell is not None}, "
            f"ragdoll {'ragdoll' in sim.log()})", fell is not None and done is not None and 'ragdoll' in sim.log()
            and not r.state().riding)
    sim.stick(0.0, 0.0, right=False)
    ok &= r.finish('offboard: drop')

    # putting the board away; and the controls
    r = rig.make(goofy=True, server=True)
    sim, S = r.sim, r.sim.S
    r.frame(5)
    board = r.get_on()
    r.set('speed', 0.3)
    r.frame(20)
    sim.press(Y)
    run_until(r, lambda s: s.off == 'stand')
    sim.command('skateboard')
    r.frame(5)
    s = r.state()
    r.check("the get on / off key with the board in the hand: the board is put away and the game has the player back",
            s.off is None and not s.riding and s.board is None and S.ent[board] is None and sim.ent(1).frozen is False
            and len(list(s.parts.values())) == 0)
    ok &= r.finish('offboard: put away')

    for label, kw in (("switched off in the config", dict(config="Config.OffBoard.enabled = false")),
                      ("without Skate 3's clips", dict(stock=True))):
        r = rig.make(goofy=True, server=True, **kw)
        sim = r.sim
        r.frame(5)
        board = r.get_on()
        r.set('speed', 0.3)
        r.frame(5)
        sim.press(Y)
        r.frame(5)
        s = r.state()
        r.check(f"control, {label}: Y steps off the old way (the board stays on the ground, the game has the player)",
                s.off is None and not s.riding and s.board == board and sim.ent(1).frozen is False)
        ok &= r.finish('offboard: ' + label)
    return ok


SCENARIOS = {'offboard': offboard}

if __name__ == "__main__":
    good = offboard()
    print("PASS" if good else "FAIL")
    sys.exit(0 if good else 1)
