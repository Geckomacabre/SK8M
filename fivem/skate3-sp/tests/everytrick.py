"""Every trick the controller is said to do, done on the simulated board.

`tools/trick_status.py` keeps a hand-written list (DONE) of the names in Skate 3's scoring table that the skateboard
can do, and `TRICKS.md` is counted from it. This file is the proof of that list: for every name in it the trick is
done with the controller's own inputs (stick, triggers, buttons), in both stances, and the ride has to put it into
the line under exactly that name of Skate 3's table, with points from the table. A name that cannot be produced that
way is reported, and so is a name in DONE that this file has no way of doing.

usage: python everytrick.py [goofy|regular] [family ...]      families: flick late flips grabs ground grinds
"""
import math
import os
import sys

import rig
import ridetest as RT
from rig import A, B, LT, RB, RT as RTRIG, X, Y
from ridetest import OLLIE, airborne, big_ollie, flip_run, roll

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import trick_status  # noqa: E402

# the ride notes every trick that goes into the line: its name in Skate 3's table, and whether the table has it
HOOK = "local function addToLine(label, key, points, scale)\n"
NOTE = ("    Tune._scored = Tune._scored or {}\n"
        "    Tune._scored[#Tune._scored + 1] = Tune.scoreName(key) .. '=' ..\n"
        "        ((Tune.scoring() and Tune.scoring().base[Tune.scoreName(key)] ~= nil) and '1' or '0')\n")

# the stick path a mirrored (regular) rider flicks for a trick is its twin's (Skate 3 does not mirror the stick)
TWIN = {}
for a, b in (('Kickflip', 'Heelflip'), ('PopShuvit', 'FSPopShuvit'), ('VarialKickflip', 'VarialHeelflip'),
             ('Hardflip', 'InwardHeelflip'), ('360PopShuvit', 'FS360PopShuvit'), ('360Flip', 'Laserflip'),
             ('360Hardflip', '360InwardHeelflip')):
    for p in ('', 'N_'):
        TWIN[p + a], TWIN[p + b] = p + b, p + a
for a, b in (('L_F_Kickflip', 'L_F_Heelflip'), ('L_B_Kickflip', 'L_B_Heelflip'), ('L_FS_Shuvit', 'L_BS_Shuvit'),
             ('FS_Varial', 'BS_Varial')):
    TWIN[a], TWIN[b] = b, a

FLIPS = ['Kickflip', 'Heelflip', 'PopShuvit', 'FSPopShuvit', 'VarialKickflip', 'VarialHeelflip', 'Hardflip',
         'InwardHeelflip', '360PopShuvit', 'FS360PopShuvit', '360Flip', 'Laserflip', '360Hardflip', '360InwardHeelflip']


class Rider:
    """One rider in one stance, with the inputs named the way the clips are authored (back hand, front foot ...)."""

    def __init__(self, goofy, **world):
        self.goofy = goofy
        self.who = 'goofy' if goofy else 'regular'
        self.k = 1.0 if goofy else -1.0
        self.r = rig.make(goofy=goofy, patch={'client.lua': lambda s: s.replace(HOOK, HOOK + NOTE, 1)}, **world)
        self.sim = self.r.sim
        self.board = self.r.get_on()
        self.back, self.front = (LT, RTRIG) if goofy else (RTRIG, LT)
        self.front_foot, self.back_foot = (A, X) if goofy else (X, A)
        # the right stick for "the nose to the left / right" (the tail goes the stick's way; a mirrored rider's is turned)
        self.side = {'left': (1.0 if goofy else -1.0, 0.0), 'right': (-1.0 if goofy else 1.0, 0.0), 'up': (0.0, 1.0),
                     'down': (0.0, -1.0), None: (0.0, 0.0)}
        self.score_name = self.sim.run('skateboard', 'return Tune.scoreName')
        self.scored()

    def gesture(self, trick):
        return trick if self.goofy else TWIN.get(trick, trick)

    def pat(self, trick, set_name='ground', which=0):
        return self.r.pattern(self.gesture(trick), set_name, which)

    def scored(self):
        """What went into the line since the last call: {name: 1 if Skate 3's scoring table has that name, else 0}."""
        t = self.sim.run('skateboard', "local t = Tune._scored or {}; Tune._scored = {}; return table.concat(t, ',')")
        out = {}
        for item in (t or '').split(','):
            if item:
                name, points = item.rsplit('=', 1)
                out[name] = float(points)
        return out

    def release(self):
        for b in (LT, RTRIG, A, X, Y, B, RB):
            self.sim.hold(b, False)
        self.sim.stick(0.0, 0.0)
        self.sim.stick(0.0, 0.0, right=False)

    def fresh(self, speed=6.0, settle=100):
        """Back on the board if need be, nothing held, rolling at `speed`, the last landing's trick lock over."""
        self.release()
        if not self.r.state().riding:
            self.r.get_on()
            self.board = self.r.state().board
        self.r.frame(settle)
        roll(self.r, speed, 40)
        self.scored()


class Tally:
    def __init__(self):
        self.got, self.bad, self.how = {}, {}, {}
        self.unknown = {}   # what went into the line under a name Skate 3's table does not have: {name: how}

    def note(self, who, name, scored, how='', detail=''):
        """`name` was wanted; `scored` is what went into the line."""
        key = (who, name)
        for other, points in scored.items():
            if points <= 0 and other != 'spin':     # ('spin' is a turn of the body alone: no name of its own)
                self.unknown.setdefault(other, f'{who}, while doing {name} [{how}]')
        if name in scored and scored[name] > 0:
            self.got[key] = how
            self.bad.pop(key, None)
            return True
        if key not in self.got:
            why = ('went in under a name the table does not have' if name in scored else
                   'line got ' + (', '.join(sorted(scored)) or 'nothing')) + (f' ({detail})' if detail else '')
            self.bad[key] = why + (f' [{how}]' if how else '')
        return False


def search(R, tally, name, tries, run):
    """Try parameter sets until `name` goes into the line. run(params) -> detail text."""
    for params in tries:
        R.fresh()
        detail = run(params) or ''
        if tally.note(R.who, name, R.scored(), how=str(params), detail=detail):
            return True
    return False


# ---------------------------------------------------------------------------------------------------- families

def flick(R, tally):
    """Ollie, nollie and the fourteen flip tricks with their nollie versions: one flick of the right stick."""
    for trick in ['Ollie', 'Nollie'] + FLIPS + ['N_' + f for f in FLIPS]:
        name = R.score_name(trick)
        R.fresh()
        d = flip_run(R.r, R.board, R.pat(trick))
        tally.note(R.who, name, R.scored(), how='flick', detail=d['state'].message or '')


def late(R, tally):
    """The six late flips: a flick of the right stick in the air (Skate 3's air gesture set)."""
    for gesture in ('L_F_Kickflip', 'L_F_Heelflip', 'L_B_Kickflip', 'L_B_Heelflip', 'L_FS_Shuvit', 'L_BS_Shuvit'):
        name = R.score_name(gesture)
        tries = [(which, at) for which in range(6) for at in (12, 20)]

        def run(p):
            which, at = p
            try:
                coords = R.pat(gesture, 'air', which)
            except IndexError:
                return 'no such pattern'
            d = flip_run(R.r, R.board, OLLIE, boost=8.0, late=(coords, at))
            return d['state'].message or ''
        search(R, tally, name, tries, run)


def flips(R, tally):
    """What can be done to a flip: the flick held (2 / 3 / 4 flips), a second flick (underflip), a push button (dark
    catch), the ways out of a dark catch, a late flip caught dark, a foot off in a plain ollie."""
    late_kick = R.pat('L_F_Kickflip', 'air')
    for base in ('Kickflip', 'Heelflip', 'N_Kickflip', 'N_Heelflip'):
        sname = R.score_name(base)
        coords, twin = R.pat(base), R.pat(TWIN[base])
        # more flips: how long the flick is held
        for n, holds in ((2, (26, 22, 30, 34)), (3, (50, 44, 56, 62)), (4, (300,))):
            search(R, tally, f'{sname}{n}', [(h, 9.0) for h in holds] + [(h, 9.5) for h in holds],
                   lambda p: flip_run(R.r, R.board, coords, hold=p[0], boost=p[1])['state'].message)
        # underflip: a second flick, after 1, 2, 3 or 4 flips
        search(R, tally, f'{sname}_underflip', [(0, 6.0), (0, 8.0)],
               lambda p: flip_run(R.r, R.board, coords, boost=p[1], second=twin)['state'].message)
        # (in the air the stick is read against the air gestures, and a reader that has fired waits for the stick to
        # come back to the middle: so the flick is held, let go, and a late-flip gesture flicked from the middle)
        again = [(0.0, 0.0)] + late_kick[1:]
        for n in (2, 3, 4):
            tries = [(h, b) for b in (10.5, 9.5) for h in range(14 + 12 * (n - 2), 100, 2)]
            search(R, tally, f'{sname}{n}_underflip', tries,
                   lambda p: flip_run(R.r, R.board, coords, hold=p[0], boost=p[1], second=again)['state'].message)
        # dark catch: a push button, then the button again to turn the board back over (so the jump is landed)
        search(R, tally, f'{sname}_darkcatch', [(6, 45, 8.0), (4, 45, 8.0), (8, 50, 8.0)],
               lambda p: flip_run(R.r, R.board, coords, boost=p[2], press=(RB, p[0]), again=(RB, p[1]))['state'].message)
        for n in (2, 3, 4):
            tries = [(pr, pr + gap, b) for b in (10.5, 9.5) for gap in (26, 38, 50) for pr in range(18 + 12 * (n - 2), 100, 4)]
            search(R, tally, f'{sname}{n}_darkcatch', tries,
                   lambda p: flip_run(R.r, R.board, coords, hold=p[0] + 40, boost=p[2], press=(RB, p[0]),
                                      again=(RB, p[1]))['state'].message)
    for base in ('PopShuvit', 'FSPopShuvit', 'N_PopShuvit', 'N_FSPopShuvit'):
        coords = R.pat(base)
        search(R, tally, R.score_name(base) + '_underflip', [(6.0,), (8.0,)],
               lambda p: flip_run(R.r, R.board, coords, boost=p[0], second=R.pat('Kickflip'))['state'].message)
    for base in ('360Flip', 'Laserflip', '360Hardflip', '360InwardHeelflip'):
        for pre in ('', 'N_'):
            coords = R.pat(pre + base)
            search(R, tally, R.score_name(pre + base) + '_darkcatch', [(6, 55, 8.0), (4, 55, 8.0), (8, 60, 9.0)],
                   lambda p: flip_run(R.r, R.board, coords, boost=p[2], press=(RB, p[0]), again=(RB, p[1]))['state'].message)
    # out of the dark catch by a late-flip gesture
    kick = R.pat('Kickflip')
    for gesture, name in (('L_F_Kickflip', 'darktolightkickflip'), ('L_F_Heelflip', 'darktolightheelflip'),
                          ('L_BS_Shuvit', 'darktolightbsshuv'), ('L_FS_Shuvit', 'darktolightfsshuv')):
        tries = [(which, at) for which in range(4) for at in (40, 50)]

        def run(p):
            try:
                c = R.pat(gesture, 'air', p[0])
            except IndexError:
                return 'no such pattern'
            return flip_run(R.r, R.board, kick, boost=8.0, press=(RB, 6), late=(c, p[1]))['state'].message
        search(R, tally, name, tries, run)
    # a late flip with a push button held is caught dark; the button of the other foot then turns it back over
    search(R, tally, 'lateflip_darkcatch', [(12, 50), (12, 60), (16, 60)],
           lambda p: flip_run(R.r, R.board, OLLIE, boost=8.0, late=(late_kick, p[0]), late_hold=RB,
                              again=(RB, p[1]))['state'].message)
    # a foot off the board in a plain ollie
    for button, kind in ((R.front_foot, 'front'), (R.back_foot, 'back')):
        search(R, tally, 'ollie_onefoot_' + kind, [(10, 40)],
               lambda p: flip_run(R.r, R.board, OLLIE, boost=8.0, foot=(button, p[0], p[1]))['state'].message)


def grabs(R, tally):
    """Every grab in the air and what is made of it: which grab by the hand and where the stick is held when it goes
    on; the stick moved afterwards (tweaks); a foot off, both feet off; the other hand; finger flips."""
    r, sim = R.r, R.sim
    back, front, both = (R.back,), (R.front,), (R.back, R.front)

    def hang(n):
        for _ in range(n):
            if r.state().vz < -1.5:
                r.set('vz', 1.5)
            r.frame()

    def jump(pre, hands):
        """A big ollie, the stick held at `pre`, then the hand(s) on the board."""
        R.fresh()
        big_ollie(r, 6.0, settle=25)
        sim.stick(*R.side[pre])
        hang(4)
        for b in hands:
            sim.hold(b)
        hang(28)

    def done(name, how):
        st0 = r.state()
        R.release()
        hang(30)
        airborne(r, 500)
        r.frame(25)
        st = r.state()
        tally.note(R.who, name, R.scored(), how=how,
                   detail=f"in hand: {st0.grab} / {st0.gvar}; riding {st.riding} {st.message or ''}")

    # which grab
    for name, pre, hands in (('fsgrab', None, back), ('bsgrab', None, front), ('dblgrab', None, both),
                             ('tailgrab', 'up', back), ('seatbeltgrab', 'up', front), ('crailgrab', 'down', back),
                             ('nosegrab', 'down', front), ('stalegrab', 'right', back), ('mutegrab', 'right', front)):
        jump(pre, hands)
        done(name, f'stick {pre}, then the hand')
    # the stick moved after the hand is on: tweaks
    for base, pre, hands, zones in (('fsgrab', None, back, ('up', 'down', 'left', 'right')),
                                    ('bsgrab', None, front, ('up', 'down', 'left', 'right')),
                                    ('stalegrab', 'right', back, ('up', 'down', 'left')),
                                    ('mutegrab', 'right', front, ('up', 'down', 'left')),
                                    ('tailgrab', 'up', back, ('left', 'right')), ('seatbeltgrab', 'up', front, ('left', 'right')),
                                    ('crailgrab', 'down', back, ('left', 'right')), ('nosegrab', 'down', front, ('left', 'right'))):
        for zone in zones:
            jump(pre, hands)
            sim.stick(*R.side[zone])
            hang(25)
            done(f'{base}_{zone}', f'{base}, then the stick {zone}')
    # a push button: that foot off the board
    for name, pre, hands, button in (
            ('fs_onefoot_right', None, back, R.front_foot), ('fs_backfoot', None, back, R.back_foot),
            ('bs_onefoot_behind', None, front, R.front_foot), ('bs_onefoot_front', None, front, R.back_foot),
            ('tailgrab_onefoot_behind', 'up', back, R.front_foot), ('tailgrab_onefoot_front', 'up', back, R.back_foot),
            ('nosegrab_onefoot_behind', 'down', front, R.front_foot), ('nosegrab_onefoot_front', 'down', front, R.back_foot)):
        jump(pre, hands)
        sim.hold(button)
        hang(60)
        sim.hold(button, False)
        hang(45)
        done(name, 'a push button while grabbing')
    # the brake button (or both push buttons on a tail / nose grab): both feet off
    for name, pre, hands, buttons in (('nofoot_air', None, back, (B,)), ('christ_air', None, front, (B,)),
                                      ('superman', None, both, (B,)), ('tailgrab_airwalk', 'up', back, (B,)),
                                      ('nosegrab_airwalk', 'down', front, (A, X))):
        jump(pre, hands)
        for b in buttons:
            sim.hold(b)
        hang(60)
        for b in buttons:
            sim.hold(b, False)
        hang(45)
        done(name, 'feet off while grabbing')
    # the other hand as well on a nose grab
    jump('down', front)
    sim.hold(R.back)
    hang(60)
    sim.hold(R.back, False)
    hang(45)
    done('rocketair', 'nose grab, then the other hand')
    # finger flips: a flick of the right stick with a hand on the board
    fs_var, bs_var = R.gesture('FS_Varial'), R.gesture('BS_Varial')
    for name, pre, hands, gesture in (
            ('fsgrab_fingerflip', None, back, 'Fingerflip'), ('bsgrab_fingerflip', None, front, 'Fingerflip'),
            ('fsgrabvarial_fingerflip', None, back, bs_var), ('fsgrabtostalegrab_fingerflip', None, back, fs_var),
            ('bsgrabvarial_fingerflip', None, front, bs_var), ('bsgrabtomutegrab_fingerflip', None, front, fs_var),
            ('mutegrabtobsgrab_fingerflip', 'right', front, fs_var), ('stalegrabtofsgrab_fingerflip', 'right', back, fs_var),
            ('stalegrab_fingerflip', 'right', back, 'Fingerflip'), ('mutegrab_fingerflip', 'right', front, 'Fingerflip'),
            ('tailgrab_fingerflip', 'up', back, 'Fingerflip'), ('nosegrab_fingerflip', 'down', front, 'Fingerflip'),
            ('crailtotail_fingerflip', 'down', back, fs_var), ('seatbelttonose_fingerflip', 'up', front, fs_var)):
        jump(pre, hands)
        # the gesture that starts where the stick is being held (up or down), or any of them from the middle
        held = R.side[pre] if pre in ('up', 'down') else None
        coords = r.pattern(gesture, 'grab')
        for which in range(12):
            try:
                c = r.pattern(gesture, 'grab', which)
            except IndexError:
                break
            if held and (c[0][1] < -0.8) == (held[1] > 0):   # pattern space: y DOWN is +
                coords = c
                break
        path = [coords[0]] * 4
        for a, b in zip(coords, coords[1:]):
            path += [(a[0] + (b[0] - a[0]) * i / 3, a[1] + (b[1] - a[1]) * i / 3) for i in range(1, 4)]
        path += [(coords[-1][0] * q, coords[-1][1] * q) for q in (0.7, 0.4, 0.1, 0.0)]
        for x, y in path:
            sim.stick(x, -y)
            hang(1)
        sim.stick(0.0, 0.0)
        hang(40)
        done(name, f'{gesture} flicked while grabbing')


def ground(R, tally):
    """On the ground: manuals, a hand on the board, the coffin, foot plants, no comply, hippy jump, reverts."""
    r, sim = R.r, R.sim

    def ride_out():
        n = 0
        for _ in range(400):
            r.frame()
            st = r.state()
            if st.mode == 'air':
                n += 1
            elif n or not st.riding:
                break
        R.release()
        r.frame(40)

    # manuals: the right stick held part of the way
    for name, y in (('tailmanual', -0.4), ('nosemanual', 0.4)):
        R.fresh(7.0)
        sim.stick(0.0, y)
        r.frame(70)
        sim.stick(0.0, 0.0)
        r.frame(30)
        tally.note(R.who, name, R.scored(), how='stick part way')
    # a hand on the board while rolling
    for name, hands in (('gnd_fsgrab', (R.back,)), ('gnd_bsgrab', (R.front,)), ('gnd_dblgrab', (R.back, R.front))):
        R.fresh(6.0)
        for b in hands:
            sim.hold(b)
        r.frame(60)
        R.release()
        r.frame(60)
        tally.note(R.who, name, R.scored(), how='trigger on the ground')
    # the coffin: both hands on the board, then both push buttons as well
    R.fresh(7.0)
    sim.hold(R.back)
    sim.hold(R.front)
    r.frame(50)
    sim.hold(A)
    sim.hold(X)
    r.frame(90)
    lying = r.state().coffin
    sim.hold(A, False)
    sim.hold(X, False)
    r.frame(80)
    R.release()
    r.frame(80)
    tally.note(R.who, 'coffin', R.scored(), how='both triggers, then both push buttons', detail=f'lying {lying}')
    # a foot planted out of a ground grab
    for name, hand, foot in (('fsboneless', R.back, R.front_foot), ('fsfastplant', R.back, R.back_foot),
                             ('bsboneless', R.front, R.front_foot), ('bsfastplant', R.front, R.back_foot)):
        R.fresh(5.0)
        sim.hold(hand)
        r.frame(45)
        sim.press(foot)
        ride_out()
        tally.note(R.who, name, R.scored(), how='a hand on the board, then a push button')
    # no comply: the front foot's push button, then a flick
    R.fresh(4.0)
    sim.hold(R.front_foot)
    r.frame(3)
    r.flick(OLLIE, hold=0.05, settle=0)
    sim.hold(R.front_foot, False)
    ride_out()
    tally.note(R.who, 'nocomply', R.scored(), how="the front foot's push button, then a flick")
    # hippy jump: both push buttons held, then let go
    R.fresh(5.0)
    sim.hold(A)
    sim.hold(X)
    r.frame(45)
    sim.hold(A, False)
    sim.hold(X, False)
    r.frame(200)
    tally.note(R.who, 'hippyjump', R.scored(), how='both push buttons, let go')
    # reverts: the left stick swept through the bottom half of its circle, either way
    want = {'fsrevert', 'bsrevert'}
    for gesture in ('SlideFs180', 'SlideBs180'):
        if r.state().riding:
            r.get_off()
        R.fresh(5.0)
        coords = r.pattern(gesture, 'left')
        path = [coords[0]] * 4
        for a, b in zip(coords, coords[1:]):
            path += [(a[0] + (b[0] - a[0]) * i / 4, a[1] + (b[1] - a[1]) * i / 4) for i in range(1, 5)]
        path += [(coords[-1][0] * q, coords[-1][1] * q) for q in (0.7, 0.4, 0.1, 0.0)]
        for i in range(120):
            x, y = path[i] if i < len(path) else (0.0, 0.0)
            sim.stick(x, -y, right=False)
            r.frame()
        got = R.scored()
        for name in sorted(want):
            if tally.note(R.who, name, got, how=f'left stick {gesture}'):
                want.discard(name)


def grinds(R, tally):
    """Every grind and slide by its own name, both sides; a hand on the board on each grind that has one; the
    darkslide and the three ways out of it; and the table's side-less names.

    The rail runs along +y from y = 10. `turn` is how far the body is turned in the air (+ = to the left), `stick` the
    right stick held in the air (up = nose down), `side` which side of its path the rider last steered towards (what
    the ride names the side by when the rail is dead ahead), `x0` / `heading` where the run-up starts and points."""
    r, sim, k = R.r, R.sim, R.k
    kick = R.pat('Kickflip')

    def onto(turn=0.0, stick=0.0, side=1.0, x0=0.0, heading=0.0, dark=False, speed=8.0, exact=False):
        """Roll at the rail, pop, turn the body in the air, hold the stick. Returns the state once grinding, or None."""
        if r.state().riding:
            r.get_off()
        R.release()
        r.get_on()
        R.board = r.state().board
        r.frame(20)
        r.set('pos', (x0, 0.0, 0.0))
        r.set('facing', heading)
        r.set('speed', speed)
        for _ in range(600):
            if r.state().y >= 7.3:
                break
            r.set('speed', speed)
            r.frame()
        coords = kick if dark else OLLIE
        for _ in range(16):
            sim.stick(0.0, -1.0)
            r.frame()
        for a, b in zip(coords, coords[1:]):
            for i in range(1, 4):
                sim.stick(a[0] + (b[0] - a[0]) * i / 3, -(a[1] + (b[1] - a[1]) * i / 3))
                r.frame()
        sim.stick(0.0, 0.0)
        r.frame(2)
        if dark:
            sim.press(RB)
        left, result = 0, None
        for _ in range(240):
            st = r.state()
            if st.mode == 'air':
                left += 1
                if left == 1 and side is not None:
                    r.set('lastSide', side)
                turning = abs(st.spin) < abs(turn) - (0.5 if exact else 4.0)
                sim.stick((-1.0 if turn > 0 else 1.0) if turning else 0.0, 0.0, right=False)
                sim.stick(0.0, stick if left > 6 else 0.0)
            if st.mode == 'grind':
                result = st
                break
            if (left and st.mode == 'ground') or not st.riding:
                break
            r.frame()
        sim.stick(0.0, 0.0)
        sim.stick(0.0, 0.0, right=False)
        return result

    def off_the_end(hands=()):
        """Ride the grind to the end of the rail (a hand on the board for a while on the way), land, and settle."""
        r.frame(12)
        for b in hands:
            sim.hold(b)
        if hands:
            r.frame(50)
        R.release()
        for _ in range(900):
            if r.state().mode != 'grind':
                break
            r.frame()
        airborne(r, 200)
        r.frame(25)

    def ride(name, hands=(), **kw):
        R.scored()
        st = onto(**kw)
        if st is None:
            st2 = r.state()
            tally.note(R.who, name, {}, how=str(kw), detail=f"no grind: {st2.mode} {st2.message or ''}")
            return None
        off_the_end(hands)
        tally.note(R.who, name, R.scored(), how=str(kw) + (' + hands' if hands else ''),
                   detail=f"it was a {st.grindLabel}")
        return st

    UP, DOWN = 0.8, -0.8
    for s, pre in ((1.0, 'fs_'), (-1.0, 'bs_')):
        over, back = 40.0 * s * k, -40.0 * s * k       # the nose turned over the rail to its far side / back from it
        across, lip = 90.0 * s * k, -90.0 * s * k      # the board across the rail: nose over it / tail over it
        side = s * k
        cases = {
            '50_50': dict(), 'nosegrind': dict(stick=UP), '5_o': dict(stick=DOWN),
            'crook': dict(turn=over, stick=UP), 'overcrook': dict(turn=back, stick=UP), 'salad': dict(turn=over, stick=DOWN),
            'feeble': dict(turn=over), 'smith': dict(turn=back),
            # the front truck on the rail: the rail off to the side the nose points to
            'willy': dict(turn=over, x0=0.4 * s * k, side=None),
            'board': dict(turn=across), 'noseslide': dict(turn=across, stick=UP), 'blunt': dict(turn=across, stick=DOWN),
            'lip': dict(turn=lip), 'noseblunt': dict(turn=lip, stick=UP), 'tailslide': dict(turn=lip, stick=DOWN),
        }
        for g, kw in cases.items():
            kw.setdefault('side', side)
            ride(pre + g, **kw)
        # overwilly: the front truck on the rail with the nose pointing back: the board has gone over the rail. The
        # run-up crosses the rail's line at a small angle, from the side the grind is named for.
        tries = [dict(turn=back, x0=x * s * k, heading=h * s * k, side=None)
                 for h in (6.0, 8.0, 10.0, 12.0) for x in (0.15, 0.25, 0.35, 0.45)]
        for kw in tries:
            ride(pre + 'overwilly', **kw)
            if (R.who, pre + 'overwilly') in tally.got:
                break
        # a hand on the board (the back hand, the front hand, both), on the grinds that have a grab for it
        grabs_on = {
            '50_50': (('fsgrab', R.back), ('bsgrab', R.front)), '5_o': (('fsgrab', R.back), ('nosegrab', R.front)),
            'nosegrind': (('tailgrab', R.back), ('bsgrab', R.front)), 'crook': (('tailgrab', R.back), ('bsgrab', R.front)),
            'overcrook': (('tailgrab', R.back), ('bsgrab', R.front)), 'salad': (('fsgrab', R.back), ('nosegrab', R.front)),
            'board': (('tail', R.back), ('nose', R.front), ('double', (R.back, R.front))),
            'lip': (('tail', R.back), ('nose', R.front), ('double', (R.back, R.front))),
            'noseslide': (('tailgrab', R.back),), 'tailslide': (('nosegrab', R.front),),
            'blunt': (('tailgrab', R.front),), 'noseblunt': (('tailgrab', R.back),),
        }
        for g, variants in grabs_on.items():
            for suffix, hand in variants:
                kw = dict(cases[g], speed=9.0)
                ride(f'{pre}{g}_{suffix}', hands=hand if isinstance(hand, tuple) else (hand,), **kw)
    # the darkslide: a kickflip caught upside down, landed across a rail; the side is the way the body is turned
    for pre, turn in (('fs_', 90.0 * k), ('bs_', -90.0 * k)):
        ride(pre + 'darkslide', turn=turn, dark=True)
        for suffix, hand in (('tail', (R.back,)), ('nose', (R.front,)), ('double', (R.back, R.front))):
            ride(f'{pre}darkslide_{suffix}', hands=hand, turn=turn, dark=True, speed=9.0)
        # out of it by a flick: an ollie's goes straight, a kickflip's to the left, a heelflip's to the right
        for gesture, way in (('Ollie', 'straight'), ('Kickflip', 'left'), ('Heelflip', 'right')):
            R.scored()
            st = onto(turn=turn, dark=True)
            name = f'darkslideout_{pre[:2]}{way}'
            if st is None:
                tally.note(R.who, name, {}, how=gesture, detail='no darkslide')
                continue
            r.frame(20)
            # (across the rail the gestures are turned with the board: Skate 3's own turned pattern sets)
            r.flick(R.pat(gesture, 'groundN90' if turn > 0 else 'ground90'), hold=0.2)
            airborne(r, 300)
            r.frame(25)
            tally.note(R.who, name, R.scored(), how=f'{gesture} flicked on the darkslide')
    # the table's side-less names: straight at the rail with no side to name it by (no steering since getting on)
    for name, kw in (('grind5050', dict()), ('grindnose', dict(stick=UP)), ('grind5_o', dict(stick=DOWN)),
                     ('grindcrooks', dict(turn=40.0, stick=UP)), ('grindsalad', dict(turn=-40.0, stick=DOWN)),
                     ('grindfeeble', dict(turn=-40.0)), ('grindsmith', dict(turn=40.0)),
                     ('slideboard', dict(turn=90.0)), ('slidenose', dict(turn=90.0, stick=UP)),
                     ('slidetail', dict(turn=90.0, stick=DOWN))):
        ride(name, side=0.0, **kw)
    # ... and the two that need the front truck on a rail that is dead ahead: a few centimetres of room at most
    for name, sign in (('grindwilly', -1.0), ('grindoverwilly', 1.0)):
        for x in (0.049, 0.045, 0.04):
            for t in (19.0, 18.0, 20.0, 21.0):
                ride(name, turn=t * sign, x0=x * sign, side=None, exact=True)
                if (R.who, name) in tally.got:
                    break
            if (R.who, name) in tally.got:
                break


FAMILIES = {'flick': flick, 'late': late, 'flips': flips, 'grabs': grabs, 'ground': ground, 'grinds': grinds}
WORLD = {'grinds': dict(rail=dict(x=0.0, y1=10.0, y2=24.0, top=0.3))}


def main():
    args = sys.argv[1:]
    stances = [a for a in args if a in ('goofy', 'regular')] or ['goofy', 'regular']
    fams = [a for a in args if a in FAMILIES] or list(FAMILIES)
    tally = Tally()
    for stance in stances:
        for fam in fams:
            R = Rider(stance == 'goofy', **WORLD.get(fam, {}))
            FAMILIES[fam](R, tally)
            v, p = R.sim.violations(), R.sim.prints()
            print(f"{stance:8s} {fam:7s} done   native misuse {len(v)}   script errors printed {len(p)}")
            for line in (v + p)[:6]:
                print("      " + line[:240])
    done = set(trick_status.DONE)
    for stance in stances:
        got = {n for (w, n) in tally.got if w == stance}
        bad = {n: why for (w, n), why in tally.bad.items() if w == stance}
        print(f"\n{stance}: {len(got)} names done and scored under their own name, {len(bad)} NOT")
        for n in sorted(bad):
            print(f"   BAD {n}: {bad[n]}")
        if len(fams) == len(FAMILIES):
            untried = sorted(done - got - set(bad))
            print(f"   names in DONE that this file never tries: {len(untried)} {untried}")
    print()
    print(f"went into the line under a name that is NOT in Skate 3's table: {len(tally.unknown)}")
    for n in sorted(tally.unknown):
        print(f"   {n}: {tally.unknown[n]}")
    return 0 if not (tally.bad or tally.unknown) else 1


if __name__ == "__main__":
    sys.exit(main())
