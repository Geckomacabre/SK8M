"""Riding faces that are not level: banks, the curve of a quarter pipe, the wall of a bowl.

usage: python surftest.py [scenario ...]        (also scenarios of ridetest.py)

The world for these is made of triangles (harness.Sim.mesh), in facets like the game's own collision: a curve is a
row of flat pieces, and a ray gives back the flat piece's normal.
"""
import math
import sys

import rig
from harness import qrot

G = 9.81


# ---------------------------------------------------------------- shapes

def quad(p1, p2, p3, p4, toward):
    """Two triangles for the four corners, turned so that rays hit them from the side `toward` points to."""
    e1 = [p2[i] - p1[i] for i in range(3)]
    e2 = [p3[i] - p1[i] for i in range(3)]
    n = (e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0])
    if sum(n[i] * toward[i] for i in range(3)) >= 0:
        return [(p1, p2, p3), (p1, p3, p4)]
    return [(p1, p3, p2), (p1, p4, p3)]


def quarter_pipe(sim, y0=20.0, radius=2.4, angle=90.0, vert=0.3, facets=8, x1=-6.0, x2=6.0, deck=3.0):
    """A quarter pipe across the +y way: the floor (z = 0) curves up from y0, `angle` degrees round a circle of
    `radius`, then `vert` metres straight on at that angle, then a deck. Returns (lip y, lip z)."""
    pts = [(y0 + radius * math.sin(math.radians(angle * i / facets)), radius * (1 - math.cos(math.radians(angle * i / facets))))
           for i in range(facets + 1)]
    if vert > 0:
        a = math.radians(angle)
        pts.append((pts[-1][0] + vert * math.cos(a), pts[-1][1] + vert * math.sin(a)))
    tris = []
    for (ya, za), (yb, zb) in zip(pts, pts[1:]):
        tris += quad((x1, ya, za), (x2, ya, za), (x2, yb, zb), (x1, yb, zb), (0.0, -1.0, 0.3))
    ly, lz = pts[-1]
    tris += quad((x1, ly, lz), (x2, ly, lz), (x2, ly + deck, lz), (x1, ly + deck, lz), (0.0, 0.0, 1.0))  # the deck
    sim.mesh(tris)
    return ly, lz


def bowl(sim, cx=0.0, cy=30.0, flat=3.0, radius=2.0, angle=80.0, facets=6, around=48, deck=2.0):
    """A round bowl: a flat floor of radius `flat` (z = 0), walls curving up `angle` degrees round a circle of
    `radius`, a deck round the top. Returns (rim radius, rim height)."""
    rings = [(flat + radius * math.sin(math.radians(angle * i / facets)), radius * (1 - math.cos(math.radians(angle * i / facets))))
             for i in range(facets + 1)]
    rings.append((rings[-1][0] + deck, rings[-1][1]))
    tris = []
    for k, ((ra, za), (rb, zb)) in enumerate(zip(rings, rings[1:])):
        for j in range(around):
            f1, f2 = 2 * math.pi * j / around, 2 * math.pi * (j + 1) / around
            mid = (f1 + f2) / 2

            def p(r, f, z):
                return (cx + r * math.cos(f), cy + r * math.sin(f), z)

            toward = (-math.cos(mid), -math.sin(mid), 0.5) if k < len(rings) - 2 else (0.0, 0.0, 1.0)
            tris += quad(p(ra, f1, za), p(ra, f2, za), p(rb, f2, zb), p(rb, f1, zb), toward)
    sim.mesh(tris)
    return rings[-2]


def up_of(sim, e):
    return qrot(sim.ent(e).q, (0.0, 0.0, 1.0))


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def rig_ang(a):
    return (a + 180.0) % 360.0 - 180.0


def back_to(old, new):
    """A patch that puts an old line back (rig.make checks that it really changes the source)."""
    return lambda s: s.replace(new, old)


# ---------------------------------------------------------------- rides

def face_normal(z, radius, angle):
    """The normal of the quarter pipe's curve at height z (the smooth curve the facets stand for)."""
    c = max(-1.0, min(1.0, 1.0 - z / radius))
    a = min(math.acos(c), math.radians(angle))
    return (0.0, -math.sin(a), math.cos(a))


def in_pipe(y, z, radius, angle, vert, lip, y0=20.0):
    """Is the point in the open air of the quarter pipe (not inside its curve or under its deck)? And how far from
    the curve's face, roughly (metres; negative = inside it)."""
    ly, lz = lip
    if z >= lz:
        return True, z - lz if y > ly else math.hypot(max(y - ly, 0.0), z - lz) + 0.0
    top = radius * (1 - math.cos(math.radians(angle)))
    if z > top:      # the straight piece at the top
        a = math.radians(angle)
        wall = y0 + radius * math.sin(a) + (z - top) / math.tan(a) if angle < 90.0 else ly
    else:
        wall = y0 + radius * math.sin(math.acos(max(-1.0, min(1.0, 1.0 - max(z, 0.0) / radius))))
    return y < wall and z > -0.01, wall - y


def ride_pipe(patch=None, speed=8.0, facets=8, radius=2.4, angle=90.0, vert=0.3, frames=700, spin=None, pop_at=None,
              config='', fps=60):
    """Straight at a quarter pipe from the flat. spin = degrees to turn in the air (the left stick is held until the
    body is nearly there); pop_at = the height at which an ollie is asked for on the way up."""
    r = rig.make(patch=patch, config=config)
    sim = r.sim
    ly, lz = quarter_pipe(sim, radius=radius, angle=angle, vert=vert, facets=facets)
    board = r.get_on()
    r.frame(20)
    sim.S.dt = 1.0 / fps
    frames = int(frames * fps / 60)
    r.set('pos', (0.0, 12.0, 0.0))
    r.set('speed', speed)
    out = dict(top=0.0, air=0, lip=(ly, lz), back=None, steepest=1.0, away=1.0, landed_at=None, air_y=[], air_away=1.0,
               facing=None, popped=False, cam_in=0, cam_near=9.0, cam_frames=0)
    was_air, far = False, False
    for i in range(frames):
        st = r.state()
        turning = spin and st.mode == 'air' and abs(st.spin) < abs(spin) - 25.0
        sim.stick(math.copysign(1.0, -spin) if turning else 0.0, 0.0, right=False)
        if pop_at and not out['popped'] and st.mode == 'ground' and st.z >= pop_at and st.speed > 0:
            r.T.requestPop('Ollie', 'Ollie', 1.0)
            out['popped'] = True
        r.frame()
        st = r.state()
        if not st.riding:
            break
        out['top'] = max(out['top'], st.z)
        cam = sim.S.cam
        if cam and cam.pos and st.z > 0.6:
            # the camera while the rider is up on the curve or over it: in the open, and not shut in against him
            free, _ = in_pipe(cam.pos.y, cam.pos.z, radius, angle, vert, (ly, lz))
            out['cam_frames'] += 1
            out['cam_in'] += 0 if free else 1
            out['cam_near'] = min(out['cam_near'], math.dist((cam.pos.x, cam.pos.y, cam.pos.z), (st.x, st.y, st.z)))
        if st.mode == 'air':
            out['air'] += 1
            out['air_y'].append(st.y)
            if st.z > lz:
                # over the top the rider stays turned to the ramp he will come down on
                out['air_away'] = min(out['air_away'], dot(up_of(sim, 1), face_normal(lz, radius, angle)))
            was_air = True
        else:
            if was_air and out['landed_at'] is None and st.z > 0.3:
                out['landed_at'] = (st.y, st.z, st.speed)
            was_air = False
            if st.z > 0.4 and out['landed_at'] is None:
                # how far the board and the rider are from standing square on the face under them
                n = face_normal(st.z, radius, angle)
                out['away'] = min(out['away'], dot(up_of(sim, board), n), dot(up_of(sim, 1), n))
                out['steepest'] = min(out['steepest'], n[2])
        far = far or st.y > 20.0
        if st.mode == 'ground' and st.y < 16.0 and far:
            out['back'], out['facing'] = st.speed, st.facing
            break
    sim.stick(0.0, 0.0, right=False)
    sim.S.dt = 1 / 60
    out['state'] = r.state()
    return r, out


def spot(o):
    return o['landed_at'] and tuple(round(x, 2) for x in o['landed_at'])


def transitions():
    ok = True

    # ---- 1. straight up a quarter pipe: no fall, out over the top, back in, away again
    r, o = ride_pipe()
    st = o['state']
    natural_top = o['top']
    ok &= r.check(f"up a 2.4 m quarter pipe at 8 m/s: still riding ({st.message}), {o['top']:.2f} m up (the lip is at {o['lip'][1]:.2f})",
                  st.riding and o['top'] > o['lip'][1] + 0.5)
    ok &= r.check(f"... the board and the rider stand square on the curve all the way up (worst: {o['away']:.3f} of 1, on a face "
                  f"{math.degrees(math.acos(o['steepest'])):.0f} degrees steep), and stay turned to it over the top ({o['air_away']:.3f})",
                  o['away'] > 0.93 and o['steepest'] < 0.3 and o['air_away'] > 0.93)
    ok &= r.check(f"... {o['air']} frames in the air over the top, never out over the deck (furthest y {max(o['air_y'] or [0]):.2f}, "
                  f"lip {o['lip'][0]:.2f}), down on the curve again at {spot(o)}",
                  o['air'] > 30 and o['landed_at'] is not None and max(o['air_y']) < o['lip'][0] + 0.02
                  and o['landed_at'][0] < o['lip'][0] and 1.0 < o['landed_at'][1] < o['lip'][1])
    ok &= r.check(f"... and rolls back out over the flat at {o['back'] and round(o['back'], 2)} m/s (backwards: nobody turned round)",
                  o['back'] is not None and -8.6 < o['back'] < -7.0)
    ok &= r.check(f"... the camera stays in the open and off the rider all the while ({o['cam_in']} of {o['cam_frames']} frames inside "
                  f"the ramp, never nearer than {o['cam_near']:.2f} m)", o['cam_frames'] > 60 and o['cam_in'] == 0 and o['cam_near'] > 1.2)
    ok &= r.finish('transitions: quarter pipe')

    # the same ride at other frame rates
    for fps in (20, 30, 144):
        r, o = ride_pipe(fps=fps)
        st = o['state']
        ok &= r.check(f"at {fps} frames a second: riding ({st.message}), {o['top']:.2f} m up, down on the curve at {spot(o)}, "
                      f"back at {o['back'] and round(o['back'], 2)} m/s",
                      st.riding and abs(o['top'] - natural_top) < 0.25 and o['landed_at'] is not None
                      and o['landed_at'][0] < o['lip'][0] and o['back'] is not None and -8.6 < o['back'] < -7.0)
        ok &= r.finish(f'transitions: {fps} fps')

    # control: the wall rule as it was (a face steeper than 70 degrees to the LEVEL is a wall)
    def old_wall(src):
        a = "            local hit, _, n = ray(pos + u * 0.35, target + u * 0.35 + dir * 0.35, board)\n"
        b = "            if hit and Surf.dot(n, u) < 0.35 then\n"
        c = "        local step = speed * dt\n"
        assert src.count(a) == 1 and src.count(b) == 1 and src.count(c) == 1
        # (the look ahead on the level, as it was, and how the face found stands to the level)
        return src.replace(c, c + "        local len0 = math.abs(step) * math.sqrt(math.max(1.0 - d.z * d.z, 0.0))\n").replace(
            a, "            local lv = fwd(facing) * (speed > 0 and 1.0 or -1.0)\n"
               "            local hit, _, n = ray(pos + vector3(0, 0, 0.35), pos + lv * (len0 + 0.35) + vector3(0, 0, 0.35), board)\n"
        ).replace(b, "            if hit and n.z < 0.35 then\n")

    r, o = ride_pipe(patch={'client.lua': old_wall})
    good = not o['state'].riding and o['state'].message == 'Slammed'
    print(("OK  " if good else "BAD ") + f"control, the old wall rule: {o['state'].message} at {o['top']:.2f} m up")
    ok &= good
    # control: the rider drawn upright, as he was
    r, o = ride_pipe(patch={'client.lua': back_to("            ux = 0.0, uy = 0.0, uz = 1.0,\n",
                                                  "            ux = sk.up.x, uy = sk.up.y, uz = sk.up.z,\n")})
    good = o['away'] < 0.5
    print(("OK  " if good else "BAD ") + f"control, drawn upright: the rider is {o['away']:.3f} of 1 from square on the curve")
    ok &= good

    # ---- 2. half a turn in the air: down forwards
    r, o = ride_pipe(spin=180.0)
    st = o['state']
    ok &= r.check(f"with half a turn in the air ('{st.line}'): riding ({st.message}), down on the curve at {spot(o)}, "
                  f"away forwards at {o['back'] and round(o['back'], 2)} m/s",
                  st.riding and o['landed_at'] is not None and o['landed_at'][2] > 4.0 and o['back'] is not None and o['back'] > 7.0)
    ok &= r.finish('transitions: 180 out of the pipe')
    # ... and a quarter turn is a landing across the board's line
    r, o = ride_pipe(spin=90.0, patch={'client.lua': back_to("            local want = spin\n",
                                                             "            local want = SK.square()\n")})
    good = not o['state'].riding and o['state'].message == 'Landed sideways'
    print(("OK  " if good else "BAD ") + f"a quarter turn, and no squaring up before the landing: {o['state'].message}")
    ok &= good

    # ---- 3. an ollie on the way up: higher (Skate 3's pop off a steep face), and still back on the curve
    r, o = ride_pipe(pop_at=1.6)
    st = o['state']
    ok &= r.check(f"an ollie on the curve: {o['top']:.2f} m up ({natural_top:.2f} without), riding ({st.message}), line '{st.line}', "
                  f"down on the curve at {spot(o)}",
                  st.riding and o['top'] > natural_top + 0.5 and o['landed_at'] is not None and 'Ollie' in (st.line or '')
                  and max(o['air_y']) < o['lip'][0] + 0.02)
    ok &= r.finish('transitions: ollie out of the pipe')

    # ---- 4. the shapes the game has: a curve in four pieces, one that stops short of upright, a slow run at it
    r, o = ride_pipe(facets=4)
    st = o['state']
    ok &= r.check(f"a curve of four flat pieces (22 degrees apiece): riding ({st.message}), {o['top']:.2f} m up, back at "
                  f"{o['back'] and round(o['back'], 2)} m/s",
                  st.riding and o['top'] > o['lip'][1] + 0.3 and o['back'] is not None and o['back'] < -6.5)
    ok &= r.finish('transitions: four facets')
    r, o = ride_pipe(angle=70.0, vert=0.0)
    st = o['state']
    ok &= r.check(f"a ramp that ends 70 degrees steep: riding ({st.message}), {o['top']:.2f} m up (lip {o['lip'][1]:.2f}), down on the curve "
                  f"({spot(o)}), back at {o['back'] and round(o['back'], 2)} m/s",
                  st.riding and o['top'] > o['lip'][1] + 0.3 and o['landed_at'] is not None and o['landed_at'][0] < o['lip'][0]
                  and o['back'] is not None and o['back'] < -6.5)
    ok &= r.finish('transitions: 70 degree lip')
    r, o = ride_pipe(speed=4.0)
    st = o['state']
    ok &= r.check(f"at 4 m/s: up to {o['top']:.2f} m and back down, {o['air']} frames off the curve, away at "
                  f"{o['back'] and round(abs(o['back']), 2)} m/s",
                  st.riding and 0.6 < o['top'] < 1.0 and o['air'] == 0 and o['back'] is not None and 3.3 < abs(o['back']) < 4.2)
    ok &= r.finish('transitions: slow')

    # ---- 5. a wall is still a wall
    r = rig.make()
    r.sim.box(-3.0, 20.0, 0.0, 3.0, 21.0, 3.0)
    r.get_on()
    r.set('pos', (0.0, 12.0, 0.0))
    r.set('speed', 8.0)
    for _ in range(120):
        r.frame()
        if not r.state().riding:
            break
    ok &= r.check(f"into a wall at 8 m/s: {r.state().message}", not r.state().riding and r.state().message == 'Slammed')

    print(("PASS " if ok else "FAIL ") + "transitions")
    return ok


def banks():
    """Gravity across the board: riding across a bank the line bends down the hill, as a board's does."""
    ok = True
    slope = math.radians(30.0)

    def across(patch=None, angle=30.0, speed=6.0, seconds=1.0):
        r = rig.make(patch=patch)
        sim = r.sim
        rise = math.tan(math.radians(angle))
        sim.ramp(-60.0, 20.0, 60.0, 50.0, 0.0, 30.0 * rise)
        board = r.get_on()
        r.set('pos', (-40.0, 35.0, 15.0 * rise))
        r.set('facing', -90.0)  # along +x: straight across the hill
        r.set('speed', speed)
        for _ in range(40):  # (the ride loop sleeps a moment after getting on: the clock starts when the board moves)
            r.frame()
            if speed == 0.0 or r.state().x > -40.0 + 0.01:
                break
        a = r.state()
        r.frame(int(seconds * 60))
        b = r.state()
        n = (0.0, -math.sin(math.radians(angle)), math.cos(math.radians(angle)))
        return r, a, b, min(dot(up_of(sim, board), n), dot(up_of(sim, 1), n))

    r, a, b, square = across()
    down = (a.y - b.y) / math.cos(slope)      # metres down the face
    want = 0.5 * G * math.sin(slope) * 1.0
    v = math.hypot(6.0, G * math.sin(slope) * 1.0)
    ok &= r.check(f"a second across a 30 degree bank at 6 m/s, hands off: the line bends {down:.2f} m down the face ({want:.2f} = "
                  f"what gravity does to anything rolling there), now at {b.speed:.2f} m/s ({v:.2f})",
                  abs(down - want) < 0.3 and abs(b.speed - v) < 0.35 and b.riding)
    ok &= r.check(f"... the board and the rider stand square on the bank ({square:.3f} of 1)", square > 0.985)
    ok &= r.finish('banks: across a bank')
    r, a, b, _ = across(patch={'client.lua': back_to("            local across = 0.0\n",
                                                     "            local across = Surf.dot(pull, Surf.cross(u, d)) * Tune.carve(steep)\n")})
    good = abs(a.y - b.y) < 0.05
    print(("OK  " if good else "BAD ") + f"control, no pull across the board: {abs(a.y - b.y):.2f} m off a straight line across the hill")
    ok &= good

    r, a, b, _ = across(angle=2.5, seconds=2.0)
    ok &= r.check(f"across a street's camber (2.5 degrees) for two seconds: the board keeps its line ({abs(a.y - b.y) * 100:.0f} cm off it)",
                  abs(a.y - b.y) < 0.05)
    ok &= r.finish('banks: camber')

    # standing still across a bank the board comes round and rolls off down it
    r, a, b, _ = across(speed=0.0, seconds=3.0)
    ok &= r.check(f"left standing across the bank: three seconds on the board has come round by {abs(rig_ang(b.facing - a.facing)):.0f} degrees and "
                  f"rolls at {abs(b.speed):.1f} m/s, {(a.y - b.y):.1f} m down the hill",
                  abs(b.speed) > 4.0 and a.y - b.y > 4.0 and b.riding)
    ok &= r.finish('banks: standing')

    # ---- the wall of a bowl: in at an angle, round the wall and out again
    def into_bowl(speed, patch=None):
        r = rig.make(patch=patch)
        sim = r.sim
        rim, top = bowl(sim)
        board = r.get_on()
        r.set('pos', (-1.0, 28.6, 0.0))
        r.set('facing', -90.0)
        r.set('speed', speed)
        o = dict(high=0.0, square=1.0, on_wall=0, left=False, air=0, far=0.0, rim=rim, top=top, h0=r.state().facing)
        for i in range(600):
            r.frame()
            st = r.state()
            if not st.riding:
                break
            rad = math.hypot(st.x, st.y - 30.0)
            if st.z > 0.05:
                o['on_wall'] += 1
                o['high'] = max(o['high'], st.z)
                o['far'] = max(o['far'], rad)
                if st.mode == 'air':
                    o['air'] += 1
                a = math.acos(max(-1.0, min(1.0, 1.0 - st.z / 2.0)))
                n = (-math.sin(a) * st.x / rad, -math.sin(a) * (st.y - 30.0) / rad, math.cos(a))
                if st.mode == 'ground' and 0.3 < st.z < top - 0.05:
                    o['square'] = min(o['square'], dot(up_of(sim, board), n), dot(up_of(sim, 1), n))
            elif o['on_wall']:
                o['left'] = True
                break
        o['state'] = r.state()
        o['turned'] = abs(rig_ang(o['state'].facing - o['h0']))
        return r, o

    r, o = into_bowl(5.5)
    st = o['state']
    ok &= r.check(f"into the wall of a bowl at an angle, 5.5 m/s: riding ({st.message}), {o['high']:.2f} m up the wall (its rim is at "
                  f"{o['top']:.2f}), square to it ({o['square']:.3f} of 1), round and out on the floor again nose first at "
                  f"{st.speed:.2f} m/s, turned {o['turned']:.0f} degrees",
                  st.riding and o['left'] and 1.0 < o['high'] < o['top'] and o['square'] > 0.9 and st.speed > 5.0
                  and o['turned'] > 120.0 and o['air'] == 0)
    ok &= r.finish('banks: bowl')
    r, o = into_bowl(5.5, patch={'client.lua': back_to("            local across = 0.0\n",
                                                       "            local across = Surf.dot(pull, Surf.cross(u, d)) * Tune.carve(steep)\n")})
    st = o['state']
    good = not (o['left'] and st.speed > 5.0 and o['turned'] > 120.0)
    print(("OK  " if good else "BAD ") + f"control, no pull across the board: it does not come round ({st.speed:.2f} m/s, "
          f"turned {o['turned']:.0f} degrees, {'back on the floor' if o['left'] else 'still on the wall'})")
    ok &= good
    r, o = into_bowl(7.0)
    st = o['state']
    ok &= r.check(f"the same at 7 m/s: out over the rim ({o['high']:.2f} m up, {o['air']} frames in the air) along the top of the wall, "
                  f"never further out than {o['far']:.2f} m (the rim is at {o['rim']:.2f}), and down on the wall again: riding "
                  f"({st.message}), {abs(st.speed):.2f} m/s on the floor",
                  st.riding and o['left'] and o['high'] > o['top'] + 0.3 and o['air'] > 20 and o['far'] < o['rim'] + 0.02
                  and abs(st.speed) > 6.0)
    ok &= r.finish('banks: out of the bowl')

    print(("PASS " if ok else "FAIL ") + "banks")
    return ok


def creases():
    """Where the ground bends away: fast enough the board flies on, slowly it rolls over."""
    ok = True

    def onto_deck(speed, patch=None):
        r = rig.make(patch=patch)
        sim = r.sim
        rise = 1.5 * math.tan(math.radians(15.0))
        sim.ramp(-3.0, 20.0, 3.0, 21.5, 0.0, rise)
        sim.box(-3.0, 21.5, 0.0, 3.0, 40.0, rise)
        r.get_on()
        r.set('pos', (0.0, 14.0, 0.0))
        r.set('speed', speed)
        air, top, at_top = 0, 0.0, None
        for _ in range(400):
            r.frame()
            st = r.state()
            if not st.riding or st.y > 30.0 or abs(st.speed) < 0.05:
                break
            if st.mode == 'air':
                air += 1
                top = max(top, st.z - rise)
            elif st.y < 21.5:
                at_top = st.speed
        return r, air, top, at_top

    r, air, top, v = onto_deck(8.0)
    want = (v * math.sin(math.radians(15.0))) ** 2 / (2 * G)
    ok &= r.check(f"up a 15 degree ramp onto its deck at {v:.1f} m/s: off the brow for {air} frames, {top * 100:.0f} cm over the deck "
                  f"({want * 100:.0f} by its speed), riding on", air > 8 and abs(top - want) < 0.05 and r.state().riding)
    ok &= r.finish('creases: fast')
    r, air, top, v = onto_deck(4.2)
    ok &= r.check(f"the same at {v:.1f} m/s: the wheels stay on the ground ({air} frames in the air)",
                  air == 0 and r.state().riding and r.state().y > 25.0)
    ok &= r.finish('creases: slow')

    print(("PASS " if ok else "FAIL ") + "creases")
    return ok


SCENARIOS = {'transitions': transitions, 'banks': banks, 'creases': creases}

if __name__ == "__main__":
    want = sys.argv[1:] or list(SCENARIOS)
    good = True
    for name in want:
        print(f"\n===== {name}")
        good &= SCENARIOS[name]()
    print("ALL OK" if good else "FAILURES")
    sys.exit(0 if good else 1)
