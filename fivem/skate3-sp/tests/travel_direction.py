"""Which end of the baked board track is the nose, and does the converted skater ride nose-first?

The board tracks store the board's rotation relative to the ped (long axis on the track's y). In the riding pose that
y axis points to the ped's BACK: the track's +y is the TAIL end, and the nose is -y, the way the ped faces. Checked
here on what the tricks do with the board:
  an ollie pops the tail:  the tail end slaps down in the takeoff
  a nollie pops the nose:  the other way round
  a manual rides on the back wheels (tail end down), a nose manual on the front ones
  a 5-0 grinds on the back truck (tail end down), a nosegrind on the front one

usage: python travel_direction.py
"""
import glob
import re
import sys

import os as _os, sys as _sys  # noqa: E401
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "tools"))
import paths  # noqa: E402
TRACKS = paths.work(r"ycd_all")
ROW = re.compile(r"\{([-\d.e]+),([-\d.e]+),([-\d.e]+),([-\d.e]+),[-\d.e]+,[-\d.e]+,[-\d.e]+\}")


def load(clip):
    for path in glob.glob(TRACKS + r"\*_board.lua"):
        for line in open(path):
            if f'/{clip}"]' in line:
                return [tuple(float(v) for v in m) for m in ROW.findall(line)]
    raise KeyError(clip)


def tail_height(q):
    """z of the track's +y axis (the tail end) rotated by q: > 0 when the tail end points up."""
    x, y, z, w = q
    return 2 * (y * z + w * x)


def tail_forward(q):
    """y of the track's +y axis rotated by q: < 0 when the tail end points to the ped's back."""
    x, y, z, w = q
    return 1 - 2 * (x * x + z * z)


def main():
    ok = True
    ride = load('r_idle_hcom_000')[0]
    good = tail_forward(ride) < -0.99
    ok &= good
    print(f"{'OK ' if good else 'BAD'} riding pose: the track's +y (tail) end points to the ped's back "
          f"({tail_forward(ride):+.2f}), so the rider faces the nose")
    cases = [('ollie_high_g', 'tail'), ('nollie_high_g', 'nose'), ('m_idle_n_0_cyc', 'tail'),
             ('m_noseidle_n_0_cyc', 'nose'), ('g_50_bs_hi_0_cyc', 'tail'), ('g_ngrind_bs_hi_0_cyc', 'nose')]
    for clip, end in cases:
        hs = [tail_height(q) for q in load(clip)]
        low, high = min(hs), max(hs)
        down = 'tail' if -low > high else 'nose'
        good = down == end and max(-low, high) > 0.08
        ok &= good
        print(f"{'OK ' if good else 'BAD'} {clip:22s} {down} end down (tail-end height {low:+.2f} .. {high:+.2f}), "
              f"expected the {end}")
    print("ALL OK" if ok else "FAILURES")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
