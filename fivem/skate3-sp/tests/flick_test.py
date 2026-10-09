"""Offline test of skateboard/flick.lua against Skate 3's own gesture patterns (skate3_assets/flick_patterns.lua).

Every pattern's own path, played as a stick flick (held at the first point, then a quick stroke through the points, then
let go), must come out as that pattern's trick. Run at 30, 60, 144 and 240 fps, slow and fast, with the stick moving
at a steady speed and as a hand moves it (slowly at each of the pattern's points, fast between them).

usage: python flick_test.py [path to another flick.lua]     (exit code 1 when the frame rate changes what is read)
"""
import math
import os
import sys

from lupa import lua54

SKATE = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "skateboard"))
import os as _os, sys as _sys  # noqa: E401
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "tools"))
import paths  # noqa: E402
ASSETS = paths.work(r"fivem\skate3_assets")


def load(flick_lua):
    L = lua54.LuaRuntime(unpack_returned_tuples=True)
    L.execute(open(ASSETS + r"\flick_patterns.lua", encoding="utf-8").read())
    L.execute(open(flick_lua, encoding="utf-8").read())
    return L.globals()


def stroke(a, b, steps, eased):
    """Points from a to b in a straight line: a flick goes straight between the pattern's points (the patterns put
    extra points on the rim where a trick needs the stick rolled round). eased: slow at both ends, as a thumb is."""
    out = []
    for i in range(1, steps + 1):
        k = i / steps
        if eased:
            k = (1.0 - math.cos(math.pi * k)) / 2.0
        out.append((a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k))
    return out


def play(G, coords, fps, seg, eased=False, set_name='ground'):
    G.Flick.reset()
    dt = 1.0 / fps
    t = 0.0
    path = [(0.0, 0.0)] * 3
    path += [coords[0]] * int(0.25 * fps)  # hold the first point (the crouch)
    for a, b in zip(coords, coords[1:]):
        path += stroke(a, b, max(1, int(seg * fps)), eased)
    path += [coords[-1]]
    # spring back: a stick let go is at the centre in about a 15th of a second
    back = max(4, int(fps / 15))
    path += [(coords[-1][0] * (1.0 - i / back), coords[-1][1] * (1.0 - i / back)) for i in range(1, back + 1)]
    fired = []
    for x, y in path:
        t += dt
        res = G.Flick.update(t, x, y, G.Skate3FlickPatterns[set_name], 0.34)
        name = res[0] if isinstance(res, tuple) else res
        if name:
            fired.append(name)
    return fired


def rearm(G):
    """After a trick the reader must take the next flick once the stick is back in a crouch, without a stop at the
    centre: down (crouch), up (ollie), straight back down and up again is two ollies."""
    G.Flick.reset()
    t, fired = 0.0, []
    path = [(0.0, 1.0)] * 15 + stroke((0.0, 1.0), (0.0, -1.0), 3, False)
    path += stroke((0.0, -1.0), (0.0, 1.0), 6, False) + [(0.0, 1.0)] * 15 + stroke((0.0, 1.0), (0.0, -1.0), 3, False)
    path += stroke((0.0, -1.0), (0.0, 0.0), 4, False)
    for x, y in path:
        t += 1.0 / 60
        res = G.Flick.update(t, x, y, G.Skate3FlickPatterns.ground, 0.34)
        name = res[0] if isinstance(res, tuple) else res
        if name:
            fired.append(name)
    return fired


def main():
    G = load(sys.argv[1] if len(sys.argv) > 1 else SKATE + r"\flick.lua")
    pats = [G.Skate3FlickPatterns.ground[i] for i in range(1, len(G.Skate3FlickPatterns.ground) + 1)]
    print(len(pats), "ground patterns,", len({p.name for p in pats}), "tricks")
    FPS = (30, 60, 144, 240)
    bad = {f: 0 for f in FPS}
    total = 0
    differ = []   # read differently at a high frame rate than at 60
    for seg in (0.05, 0.12, 0.25):
        for eased in (False, True):
            for p in pats:
                coords = [(c[1], c[2]) for c in p.coords.values()]
                got = {fps: play(G, coords, fps, seg, eased) for fps in FPS}
                total += 1
                for fps in FPS:
                    bad[fps] += got[fps] != [p.name]
                for fps in (144, 240):
                    if got[fps] != got[60]:
                        differ.append((p.name, seg, eased, fps, got[60], got[fps]))
    print(f"{total} flicks at each frame rate; not read as themselves: " + ", ".join(f"{f} fps {bad[f]}" for f in FPS))
    # (the patterns overlap, so which sample falls where decides a few flicks at any rate: the test is that a high
    # frame rate misreads no more of them than 60 fps does)
    level = bad[144] <= bad[60] + 2 and bad[240] <= bad[60] + 2
    print(("OK  " if level else "BAD ") + "144 and 240 fps misread no more flicks than 60 fps does")
    again = rearm(G)
    # the stick thrown from the top straight to the bottom, never sampled near the centre (a low frame rate)
    G.Flick.reset()
    t, thrown = 0.0, []
    for x, y in [(0.0, 1.0)] * 8 + [(0.0, -1.0)] * 2 + [(0.0, 1.0)] * 9 + [(0.0, -1.0)] * 2 + [(0.0, 0.0)] * 2:
        t += 1.0 / 20
        res = G.Flick.update(t, x, y, G.Skate3FlickPatterns.ground, 0.34)
        name = res[0] if isinstance(res, tuple) else res
        if name:
            thrown.append(name)
    print(("OK  " if thrown == ['Ollie', 'Ollie'] else "BAD ") + f"the same at 20 fps, the stick never seen at the centre: {thrown}")
    level = level and thrown == ['Ollie', 'Ollie']
    print(("OK  " if again == ['Ollie', 'Ollie'] else "BAD ") + f"down, up, straight down and up again: {again}")
    return level and again == ['Ollie', 'Ollie']


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
