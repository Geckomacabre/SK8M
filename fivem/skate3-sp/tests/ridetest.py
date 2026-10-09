"""Offline ride tests: the skateboard controller and the skate3_assets clip player in the FiveM simulator.

usage: python ridetest.py [scenario ...]      (no arguments = all)
Scenarios: basics goofy freemode keeptasks watchdog push tricks alltricks late grabs manual switch grinds bails stock
           inventory tuning lock camera selftest sound anyrail padbutton slopes airlegs groundgrabs flips allgrabs allgrinds groundtricks

The asset build carries Skate 3's own tuning table, so the default rider runs on Skate 3's numbers (normal mode);
rig.make(tuning=False) is an asset build without it (the numbers in config.lua).

Each scenario builds a fresh simulated client (harness.py / rig.py). Negative controls are part of the suite: the
`keeptasks` scenario re-runs the ride with the old SetEntityCoordsNoOffset(..., false, false, false) patched back in
and requires the checks to FAIL there.
"""
import math
import os
import sys

import rig
import boardtest
import fixtest
import offtest
import skitchtest
import surftest
from rig import A, B, LT, RB, RT, X, Y
from harness import qrot

D = math.sqrt(0.5)
OLLIE = [(0.0, 1.0), (0.0, -1.0)]              # pattern space: x right +, y DOWN +
UP_LEFT = [(0.0, 1.0), (-0.72, -0.69)]          # regular kickflip (the raw "Heelflip" path)
UP_RIGHT = [(0.0, 1.0), (0.9, -0.42)]           # regular heelflip (the raw "Kickflip" path)


def airborne(r, frames=240, each=None):
    """Run until the rider is back on the ground (or off the board). Returns frames spent in the air."""
    n, left = 0, False
    for _ in range(frames):
        r.frame(1, each)
        s = r.state()
        if s.mode == 'air':
            left = True
            n += 1
        elif left or not s.riding:
            break
    return n


def roll(r, speed=6.0, frames=30):
    r.set('speed', speed)
    r.frame(frames)


def big_ollie(r, vz=7.0, settle=30):
    """Ollie, then (once the board has left the ground) turn it into a big jump and let the ollie's own clips finish."""
    r.flick(OLLIE)
    for _ in range(60):
        if r.state().mode == 'air':
            break
        r.frame()
    r.set('vz', vz)
    r.frame(settle)


# ---------------------------------------------------------------------------------------------------- scenarios

def basics(goofy=False, offset=(0.0, 0.0, 0.0), name='basics'):
    r = rig.make(goofy=goofy, offset=offset)
    m = '' if goofy else '_mir'
    sim = r.sim
    names = sim.run('skateboard', r'''
      local missing, list = {}, S3.clipNames()
      for _, c in ipairs(list) do
        if not exports.skate3_assets:HasClip(c) then missing[#missing + 1] = c end
        if not c:find('^b_gstr_') and not exports.skate3_assets:HasClip(c .. '_mir') then missing[#missing + 1] = c .. '_mir' end
      end
      return #list .. ' clips (plus mirrored copies) checked, missing: ' .. table.concat(missing, ' ')''')
    r.check(str(names)[:160], str(names).endswith('missing: '))

    board = r.get_on()
    r.check("board spawned", board is not None)
    r.frame(40)
    s = r.state()
    r.check(f"rolling pose plays ({s.clip})", s.clip == 'r_lean_hcom_s4' + m)
    playing = sim.run('skate3_assets', "return IsEntityPlayingAnim(1, '%s', '%s', 3)" %
                      (sim.anim.dict if sim.anim else '', sim.anim.clip if sim.anim else ''))
    r.check("the game is still playing the clip after 40 frames of being moved", playing is True)
    b, p = sim.ent(board), sim.ent(1)
    r.check(f"board sits on the ground (origin z={b.pos.z:.3f}, expect 0)", abs(b.pos.z) < 0.01)
    r.check(f"ped origin above the deck (z={p.pos.z:.2f})", 1.1 < p.pos.z < 1.4)
    r.check("board not attached to the ped", b.attached is None)
    r.check("ped frozen while riding", p.frozen is True)
    if any(offset):
        # another skeleton: the feet start off the baked anchors and the correction takes them up over ~half a second
        first = r.feet_vs_deck(board)
        r.frame(150)
        r.check(f"skeleton correction: feet {first * 100:.1f} cm off at first, taken up while riding", first > 0.02)
    gap = r.feet_vs_deck(board)
    r.check(f"feet on the deck standing still ({gap * 100:.1f} cm apart)", gap is not None and gap < 0.015)
    axis = r.board_axis(board)
    r.check(f"board points the way the rider faces (axis y {axis[1]:+.2f})", abs(axis[1]) > 0.99)

    # steering leans the body; the pose steps through the static lean clips
    roll(r, 6.0, 20)
    sim.stick(1.0, 0.0, right=False)
    r.frame(60)
    right = r.state().clip
    sim.stick(-1.0, 0.0, right=False)
    r.frame(90)
    left = r.state().clip
    sim.stick(0.0, 0.0, right=False)
    # authored (goofy): _s0 = lean left .. _s8 = lean right; the mirrored copies run the other way
    want_right, want_left = ('r_lean_hcom_s8', 'r_lean_hcom_s0') if goofy else ('r_lean_hcom_s0_mir', 'r_lean_hcom_s8_mir')
    r.check(f"steering right leans right ({right}), left leans left ({left})", right == want_right and left == want_left)
    r.check(f"board stays on the ground while leaning (z={sim.ent(board).pos.z:.3f})", abs(sim.ent(board).pos.z) < 0.01)
    r.frame(60)
    gap = r.feet_vs_deck(board)
    r.check(f"feet on the deck while rolling ({gap * 100:.1f} cm apart)", gap is not None and gap < 0.015)
    heading = r.state().facing
    r.check(f"turning left then right changed the heading sensibly ({heading:.0f})", abs(rig_ang(heading)) < 80)

    # brake: foot drag, then standing with a foot down, then back to riding
    sim.played(clear=True)
    r.set('speed', 5.0)
    sim.hold(B)
    slowed = None
    for i in range(200):
        r.frame()
        if slowed is None and abs(r.state().speed) < 0.1:
            slowed = i
    played = sim.played()
    r.check(f"brake stops the board (after {slowed} frames)", slowed is not None and slowed < 120)
    r.check("brake plays into > cycle > stand", all(c + m in played for c in
            ('r_brake_n_n_0_into', 'r_brake_n_n_0_cyc', 'r_stand_fromlsbrake_n_0_tr', 'r_stand_idle2_n_0_cyc')))
    sim.hold(B, False)
    sim.played(clear=True)
    r.frame(60)
    played = sim.played()
    r.check(f"letting go steps back onto the board ({' > '.join(played)})",
            played[:1] == ['r_stand_idle2_n_0_out' + m] and r.state().clip.startswith('r_lean_hcom_s'))

    # gestures (arms only, layered over the ride)
    sim.command('skateboard_gesture')
    r.frame(2)
    first = sim.S.upper.clip if sim.S.upper else None
    parts = []
    for _ in range(300):
        r.frame()
        c = sim.S.upper.clip if sim.S.upper else None
        if c and (not parts or parts[-1] != c):
            parts.append(c)
    r.check(f"gesture plays into, loop, out and ends ({first} > {' > '.join(parts)})",
            first == 'b_gstr_shaka_both_into' and parts[-2:] == ['b_gstr_shaka_both_cyc', 'b_gstr_shaka_both_out']
            and sim.S.upper is None)

    # step off
    r.get_off()
    s = r.state()
    r.check("stepped off: not riding, ped unfrozen, board left on the ground",
            not s.riding and sim.ent(1).frozen is False and sim.S.ent[board] is not None)
    return r.finish(name)


def rig_ang(a):
    return (a + 180.0) % 360.0 - 180.0


def keeptasks():
    """The bug that stopped the clips in game, as a negative control: with keepTasks = false the simulator (like the
    game) clears the ped's tasks on every move, and the checks that passed in `basics` must fail."""
    def old(src):
        return src.replace("SetEntityCoordsNoOffset(r.ped, pedPos.x, pedPos.y, pedPos.z, true, true, false)",
                           "SetEntityCoordsNoOffset(r.ped, pedPos.x, pedPos.y, pedPos.z, false, false, false)")
    ok = True
    for label, patch, expect in (("fixed (keepTasks = true)", None, True),
                                 ("old code (keepTasks = false)", {'s3_player.lua': old}, False)):
        r = rig.make(patch=patch)
        board = r.get_on()
        r.frame(60)
        sim = r.sim
        a = sim.anim
        playing = bool(a) and sim.run('skate3_assets', "return IsEntityPlayingAnim(1, '%s', '%s', 3)" % (a.dict, a.clip))
        gap = r.feet_vs_deck(board)
        replays = sim.run('skateboard', 'return S3.replays()')
        feet = "no clip" if gap is None else f"{gap * 100:.1f} cm"
        good = playing and gap is not None and gap < 0.015 and replays == 0
        print(f"   {label}: clip playing {playing}, feet vs deck {feet}, clip restarts {replays}")
        ok &= (good == expect)
        print(("OK  " if good == expect else "BAD ") + (f"{label}: the ride {'works' if expect else 'is broken, as it was in game'}"))
    print(("PASS " if ok else "FAIL ") + "keeptasks")
    return ok


def watchdog():
    """Something outside the ride clears the ped's tasks (the game does this now and then): the clip must come back."""
    r = rig.make()
    board = r.get_on()
    roll(r, 5.0, 60)
    sim = r.sim
    before = sim.anim.clip
    sim.run('skate3_assets', 'ClearPedTasks(1)')
    r.check("clip dropped by the game", sim.anim is None)
    r.frame(20)
    after = sim.anim.clip if sim.anim else None
    replays = sim.run('skateboard', 'return S3.replays()')
    r.check(f"clip restarted within 20 frames ({before} > {after}), counted ({replays})", after == before and replays == 1)
    r.frame(30)
    gap = r.feet_vs_deck(board)
    r.check(f"feet back on the deck ({gap * 100:.1f} cm)", gap is not None and gap < 0.015)
    return r.finish('watchdog')


def push():
    ok = True
    for goofy in (False, True):
        r = rig.make(goofy=goofy)
        m = '' if goofy else '_mir'
        sim = r.sim
        board = r.get_on()
        r.frame(20)
        sim.played(clear=True)
        # A = right foot: the back foot of a regular rider (a normal push), the front foot of a goofy one (mongo)
        zs, speeds = [], []
        sim.hold(A)
        for _ in range(240):
            r.frame()
            zs.append(sim.ent(1).pos.z)
            speeds.append(r.state().speed)
        sim.hold(A, False)
        played = sim.played()
        base = 'r_pushlsp_lstr_mongo_0' if goofy else 'r_pushlsp_lstr_n_0'
        r.check(f"{'goofy' if goofy else 'regular'}: A pushes with the right foot = {'mongo' if goofy else 'normal'} push "
                f"({played[0]})", played[0] == base + '_into' + m)
        contacts = sum(1 for c in played if '_cyc1' in c)
        r.check("push chain cycles contact > recover while held",
                contacts >= 3 and sum(1 for c in played if '_cyc2' in c) >= 3 and played.count(base + '_into' + m) == 1)
        # Skate 3 (normal mode): each push adds MaxPushDVStart .. MaxPushDVEnd = 0.6 .. 0.5 m/s by speed, times
        # Config.S3PushScale, up to MaxPushableSpeed; nothing slows the board below 8 m/s while the controls are in use
        scale = sim.run('skateboard', 'return Config.S3PushScale')
        gain = lambda v: (0.6 + (0.5 - 0.6) * min(v / 8.5, 1.0)) * scale
        v = 0.0
        for _ in range(contacts):
            v = min(8.5, v + gain(v))
        r.check(f"{contacts} pushes in 4 s, each adding Skate 3's push speed x {scale:g} ({speeds[-1]:.3f} m/s; {v:.3f} "
                f"when the last one is through)", v - gain(0.0) - 0.01 < speeds[-1] < v + 0.001)
        r.check("speed only ever rises while pushing on the flat", all(b >= a - 0.02 for a, b in zip(speeds, speeds[1:])))
        jump = max(abs(a - b) for a, b in zip(zs, zs[1:]))
        r.check(f"body bobs while pushing ({min(zs):.2f}..{max(zs):.2f}), no pops (max step {jump * 100:.1f} cm)",
                max(zs) - min(zs) > 0.08 and jump < 0.06)
        sim.played(clear=True)
        r.frame(120)
        played = sim.played()
        r.check(f"letting go plays the push-out and returns to the riding pose ({' > '.join(played[-3:])})",
                any('_out_front' in c for c in played) and r.state().clip.startswith('r_lean_hcom_s'))
        gap = r.feet_vs_deck(board)
        r.check(f"feet on the deck after pushing ({gap * 100:.1f} cm)", gap is not None and gap < 0.015)
        # a tap is one whole kick
        r.set('speed', 0.0)
        r.frame(30)
        sim.hold(A)
        r.frame(3)
        sim.hold(A, False)
        r.frame(150)
        r.check(f"a tap of the button is one whole kick ({r.state().speed:.3f} m/s; the first kick adds {gain(0.0):.2f})",
                abs(r.state().speed - gain(0.0)) < 0.001)
        # rolling faster the high-speed push clips play, and pushing stops adding speed at MaxPushableSpeed (8.5)
        r.set('speed', 7.6)
        sim.played(clear=True)
        sim.hold(A)
        r.frame(300)
        sim.hold(A, False)
        fast = [c for c in sim.played() if 'pushhsp' in c]
        top = r.state().speed
        r.check(f"faster rolling plays the high-speed push clips ({len(fast)} plays)", len(fast) >= 4)
        r.check(f"pushing tops out at Skate 3's pushing speed ({top:.2f} m/s)", 8.3 < top <= 8.5001)
        r.frame(120)
        # X = the other foot
        sim.played(clear=True)
        sim.hold(X)
        r.frame(30)
        sim.hold(X, False)
        played = sim.played()
        other = 'r_pushhsp_lstr_n_0' if goofy else 'r_pushhsp_lstr_mongo_0'
        r.check(f"X pushes with the left foot ({played[0] if played else None})", bool(played) and played[0] == other + '_into' + m)
        ok &= r.finish('push ' + ('goofy' if goofy else 'regular'))
    return ok


# Skate 3 swaps a gesture's trick for its mirror twin when the rider plays mirrored clips (regular stance).
_PAIRS = [('Kickflip', 'Heelflip'), ('PopShuvit', 'FSPopShuvit'), ('VarialKickflip', 'VarialHeelflip'),
          ('Hardflip', 'InwardHeelflip'), ('360PopShuvit', 'FS360PopShuvit'), ('360Flip', 'Laserflip'),
          ('360Hardflip', '360InwardHeelflip')]
SWAP = {}
for _a, _b in _PAIRS:
    SWAP[_a], SWAP[_b], SWAP['N_' + _a], SWAP['N_' + _b] = _b, _a, 'N_' + _b, 'N_' + _a


def do_trick(r, board, coords, seg=0.05, boost=None, hold=0.3):
    """Flick a gesture and ride out the jump. Returns what happened."""
    sim = r.sim
    sim.played(clear=True)
    seen = {'antic': None, 'label': None, 'peak': 0.0, 'min_up': 1.0, 'max_step': 0.0, 'air': 0}
    last = [sim.ent(1).pos.z]

    def watch():
        s = r.state()
        if s.antic:
            seen['antic'] = s.antic
        if s.mode == 'air':
            seen['air'] += 1
            if s.air:
                seen['label'] = s.air
            if boost and seen['air'] == 2:
                r.set('vz', boost)
        if sim.S.ent[board]:
            seen['peak'] = max(seen['peak'], sim.ent(board).pos.z)
            seen['min_up'] = min(seen['min_up'], r.board_up(board))
        z = sim.ent(1).pos.z
        seen['max_step'] = max(seen['max_step'], abs(z - last[0]))
        last[0] = z

    r.flick(coords, seg=seg, hold=hold, each=watch)
    for _ in range(360):
        r.frame(1, watch)
        s = r.state()
        if not s.riding or (seen['air'] > 0 and s.mode != 'air'):
            break
    r.frame(20, watch)
    seen['played'] = sim.played()
    seen['state'] = r.state()
    return seen


def upright_in_line(r, board):
    s = r.state()
    axis = r.board_axis(board)
    travel = (-math.sin(math.radians(s.facing)), math.cos(math.radians(s.facing)))
    along = abs(axis[0] * travel[0] + axis[1] * travel[1])
    return r.board_up(board) > 0.95 and along > 0.95


def tricks():
    ok = True
    for goofy in (False, True):
        who = 'goofy' if goofy else 'regular'
        r = rig.make(goofy=goofy)
        m = '' if goofy else '_mir'
        sim = r.sim
        board = r.get_on()
        roll(r, 6.0, 30)

        t = do_trick(r, board, OLLIE, hold=0.9)   # held long enough to see the crouch cycle
        played, s = t['played'], t['state']
        print(f"   {who} ollie: {' > '.join(played)}")
        r.check(f"pulling the stick down crouches ({t['antic']})", t['antic'] == 'ollie')
        for c in ('r_antic_ollie_n_0_into', 'r_lean_antic_ollie_s4', 'ollie_high_g', 'ollie_high_a'):
            r.check(f"played {c + m}", c + m in played)
        r.check(f"landed with a landing clip ({[c for c in played if c.startswith('l_')]})",
                any(c.startswith('l_hcom_limp_') and c.endswith(m or c[-1]) for c in played))
        r.check(f"ollie landed and counted (line '{s.line}')", s.riding and s.line == 'Ollie')
        r.check(f"board peak {t['peak']:.2f} m, {t['air'] / 60:.2f} s in the air", 0.4 < t['peak'] < 1.6 and 20 < t['air'] < 70)
        r.check(f"ped height continuous through takeoff and landing (max step {t['max_step'] * 100:.1f} cm)",
                t['max_step'] < 0.12)
        r.check("board upright and in line after landing", upright_in_line(r, board))
        r.frame(40)
        gap = r.feet_vs_deck(board)
        r.check(f"feet on the deck after the landing ({gap * 100:.1f} cm)", gap is not None and gap < 0.015)

        # the same stick path is a kickflip for one stance and a heelflip for the other, as in Skate 3
        for coords, regular_trick, goofy_trick in ((UP_LEFT, 'kickflip', 'heelflip'), (UP_RIGHT, 'heelflip', 'kickflip')):
            trick = goofy_trick if goofy else regular_trick
            roll(r, 6.0, 30)
            t = do_trick(r, board, coords)
            played, s = t['played'], t['state']
            print(f"   {who} {trick}: {' > '.join(played)}")
            r.check(f"{who}: down then up-{'left' if coords is UP_LEFT else 'right'} is a {trick} ('{t['label']}')",
                    t['label'] == trick.capitalize())
            for c in (trick + '_in_high_g', trick + '_in_high_a', 't_' + trick + '_hi_4flips_0_out1'):
                r.check(f"played {c + m}", c + m in played)
            r.check(f"board went upside down during the flip (min up.z {t['min_up']:.2f})", t['min_up'] < -0.8)
            r.check(f"landed it (line ends '{s.line[-40:]}'), board upright and in line",
                    s.riding and s.line.endswith(trick.capitalize()) and upright_in_line(r, board))
            r.frame(120)
        ok &= r.finish('tricks ' + who)
    return ok


def alltricks():
    """Every one of Skate 3's 78 ground gesture patterns, played as a stick path, for both stances; plus a flick
    straight through the crouch of each trick (the weakest pop) for the low version."""
    ok = True
    for goofy in (False, True):
        who = 'goofy' if goofy else 'regular'
        r = rig.make(goofy=goofy)
        m = '' if goofy else '_mir'
        sim = r.sim
        board = r.get_on()
        pats = [p for p in r.patterns.ground.values() if p.coords is not None]
        good, bad, lows = 0, [], 0
        first_of = {}
        for p in pats:
            first_of.setdefault(p.name, p)
        runs = [(p, 0.3) for p in pats] + [(p, 0.017) for p in first_of.values()]
        for p, hold in runs:
            if not r.state().riding:
                r.get_on()
                board = r.state().board
            r.set('pos', (0.0, 0.0, 0.0))
            roll(r, 6.0, 40)
            coords = [(c[1], c[2]) for c in p.coords.values()]
            want = p.name if goofy else SWAP.get(p.name, p.name)
            label = sim.run('skateboard', "return S3.trickLabel('%s')" % want)
            t = do_trick(r, board, coords, hold=hold)
            s, played = t['state'], t['played']
            # which version of the clips: the high one after a held crouch (the stick pulled right out: Skate 3's
            # AnticMag > 0.9) or out of a manual, the low one when the stick was never in the crouch. A flick
            # straight through is the low one for the straight flicks; gestures that sweep round through the
            # shuvit wind-ups spend long enough there for the high one.
            height = 'high' if s.popHigh else 'low'
            x0, y0 = coords[0]
            if hold > 0.2:
                in_manual = abs(x0) < 0.35 and 0.22 < abs(y0) < 0.58
                expect = 'high' if (math.hypot(x0, y0) >= 0.9 or in_manual) else 'low'
            else:
                expect = 'low' if len(coords) == 2 else height
            clips_ok = any(f'_{height}_g' in c for c in played) and not any(
                ('_low_' if height == 'high' else '_high_') in c for c in played)
            landed = s.riding and upright_in_line(r, board)
            if (t['label'] == label and landed and clips_ok and height == expect
                    and all(c.endswith(m) or not m for c in played if c[:2] != 'b_')):
                good += 1
                lows += hold < 0.1 and height == 'low'
            else:
                bad.append(f"{p.name}/{expect}: got '{t['label']}' want '{label}', landed {landed}, {height} clips, "
                           f"msg {s.message}, clips {played[:4]}")
        for line in bad[:12]:
            print("      " + line[:260])
        r.check(f"{who}: {good} of {len(runs)} gesture paths gave their trick and landed it "
                f"({lows} of {len(first_of)} flicks without a crouch gave the low version)",
                good >= len(runs) - 4 and lows >= 6)
        ok &= r.finish('alltricks ' + who)
    return ok


def late():
    ok = True
    for goofy in (False, True):
        who = 'goofy' if goofy else 'regular'
        r = rig.make(goofy=goofy)
        m = '' if goofy else '_mir'
        sim = r.sim
        board = r.get_on()
        for gesture, own, twin in (('L_F_Kickflip', 'Late Kickflip', 'Late Heelflip'),
                                   ('L_BS_Shuvit', 'Late Shuvit', 'Late FS Shuvit')):
            if not r.state().riding:
                r.get_on()
                board = r.state().board
            roll(r, 6.0, 40)
            big_ollie(r)                # a big jump, so there is time for a late flip
            sim.played(clear=True)
            r.flick(r.pattern(gesture, 'air'), hold=0.1)
            played = sim.played()
            airborne(r, 400)
            r.frame(20)
            s = r.state()
            want = own if goofy else twin
            late_clips = [c for c in played if c.startswith('t_late_')]
            r.check(f"{who}: {gesture} in the air is a {want} (line '{s.line}', clip {late_clips})",
                    s.riding and want in s.line and len(late_clips) == 1 and late_clips[0].endswith(m or 'n'))
            r.check("board upright and in line after the late flip", upright_in_line(r, board))
            r.frame(90)
        ok &= r.finish('late ' + who)
    return ok


def grabs():
    """Triggers in the air. Skate 3: the left trigger is the back hand of the clips as authored (goofy), the right
    one for a mirrored (regular) rider; the stick up / down picks tail / nose side."""
    ok = True
    for goofy in (False, True):
        who = 'goofy' if goofy else 'regular'
        back, front = (LT, RT) if goofy else (RT, LT)
        r = rig.make(goofy=goofy)
        m = '' if goofy else '_mir'
        sim = r.sim
        board = r.get_on()
        cases = [((back,), 0.0, 'fs', 'FS Grab', 'gr_grab_n_fs_0'), ((front,), 0.0, 'bs', 'BS Grab', 'gr_grab_n_bs_0'),
                 ((back, front), 0.0, 'dbl', 'Double Grab', 'gr_grab_n_dbl_0'),
                 ((back,), 0.8, 'tail', 'Tail Grab', 'gr_tailgrab_n_bs_0'), ((back,), -0.8, 'crail', 'Crail', 'gr_crailgrab_n_0'),
                 ((front,), -0.8, 'nose', 'Nose Grab', 'gr_nosegrab_n_bs_0'),
                 ((front,), 0.8, 'seatbelt', 'Seatbelt', 'gr_seatbeltgrab_n_0')]
        for buttons, stick_y, kind, label, clip in cases:
            if not r.state().riding:
                r.get_on()
                board = r.state().board
            roll(r, 6.0, 40)
            big_ollie(r)
            sim.played(clear=True)
            sim.stick(0.0, stick_y)
            r.frame(4)
            for b in buttons:
                sim.hold(b)
            r.frame(30)
            got = r.state().grab
            for b in buttons:
                sim.hold(b, False)
            sim.stick(0.0, 0.0)
            played = sim.played()
            airborne(r, 400)
            r.frame(20)
            s = r.state()
            r.check(f"{who}: {'+'.join('RT' if b == RT else 'LT' for b in buttons)}"
                    f"{' + stick up' if stick_y > 0 else (' + stick down' if stick_y < 0 else '')} = {label} "
                    f"({got}; {played[:2]}; line '{s.line}')",
                    got == kind and played[:2] == [clip + '_into' + m, clip + '_cyc' + m] and s.riding and label in s.line)
            r.frame(90)
        # landing with a hand still on the board is a grab landing, not a bail
        roll(r, 6.0, 40)
        big_ollie(r, 5.0)
        sim.hold(back)
        sim.played(clear=True)
        airborne(r, 400)
        sim.hold(back, False)
        r.frame(5)
        played = sim.played()
        r.check(f"{who}: landing while grabbing plays the grab landing ({played[-2:]})",
                r.state().riding and 'l_fsgrab' + m in played)
        ok &= r.finish('grabs ' + who)
    return ok


def manual():
    r = rig.make()
    sim = r.sim
    board = r.get_on()
    roll(r, 7.0, 30)
    sim.played(clear=True)
    sim.stick(0.0, -0.4)                 # part of the way down
    r.frame(8)
    r.check("no manual before the stick has been held 0.2 s", r.state().manual is None or sim.played() == [])
    r.frame(60)
    s = r.state()
    q = sim.ent(board).q
    axis = rig.qrot(q, (1, 0, 0))
    r.check(f"holding the stick part way down is a manual ({s.manual}, {s.clip})",
            s.manual == 'Manual' and s.clip == 'm_idle_n_0_cyc_mir')
    r.check(f"the board is tipped (long axis z {axis[2]:+.2f}) with its low end on the ground "
            f"(origin z {sim.ent(board).pos.z:.2f})", abs(axis[2]) > 0.1 and sim.ent(board).pos.z < 0.12)
    sim.stick(0.0, 0.0)
    r.frame(30)
    s = r.state()
    r.check(f"letting go ends it and it counts (line '{s.line}')", s.manual is None and s.line == 'Manual')
    r.frame(90)
    roll(r, 7.0, 10)
    sim.played(clear=True)
    sim.stick(0.0, 0.4)
    r.frame(60)
    s = r.state()
    r.check(f"part way up is a nose manual ({s.manual}; {sim.played()[:2]})",
            s.manual == 'Nose Manual' and sim.played()[:2] == ['m_noseidle_n_0_into_mir', 'm_noseidle_n_0_cyc_mir'])
    # pop straight out of the manual
    t = do_trick(r, board, [(0.0, -0.4), (0.0, -1.0), (0.0, 1.0)], seg=0.05)
    s = t['state']
    r.check(f"flicking out of the nose manual pops a nollie (line '{s.line}')", s.riding and s.line.endswith('Nollie')
            and 'Nose Manual' in s.line)
    return r.finish('manual')


def switch():
    """A 180 lands rolling backwards (fakie); after 0.6 s the rider turns round on the board and rides switch."""
    r = rig.make()
    sim = r.sim
    board = r.get_on()
    roll(r, 6.0, 30)
    before = r.state()
    cam_steps, cam_last = [], [None]

    def watch_cam():
        c, s = sim.S.cam, r.state()
        rel = (c.pos.x - s.x, c.pos.y - s.y, c.pos.z)     # beside the board, and its height in the world
        if cam_last[0] is not None:
            cam_steps.append(math.dist(rel, cam_last[0]))
        cam_last[0] = rel

    r.flick(OLLIE, each=watch_cam)
    sim.stick(1.0, 0.0, right=False)      # left stick right: spin clockwise
    spun = 0
    for _ in range(120):
        r.frame(1, watch_cam)
        s = r.state()
        if s.mode == 'air' and abs(s.spin) < 178.0:
            spun += 1
        else:
            sim.stick(0.0, 0.0, right=False)
        if s.mode == 'ground' and spun:
            break
    s = r.state()
    r.check(f"180 landed fakie: facing turned {rig_ang(s.facing - before.facing):+.0f}, speed {s.speed:+.1f} "
            f"(line '{s.line}')", s.riding and abs(abs(rig_ang(s.facing - before.facing)) - 180) < 1 and s.speed < -3
            and s.line == 'BS 180 Ollie')
    played_land = sim.played(clear=True)
    r.check(f"a spin lands with the 'nice' landing ({[c for c in played_land if c.startswith('l_')]})",
            any(c.startswith('l_nice_') for c in played_land))
    gaps, board_steps, last = [], [], None
    seen_switch = False
    for i in range(140):
        r.frame(1, watch_cam)
        s = r.state()
        seen_switch |= s.switching
        b = sim.ent(board).pos
        if last is not None:
            board_steps.append(math.dist((b.x, b.y, b.z), last))
        last = (b.x, b.y, b.z)
        g = r.feet_vs_deck(board)
        if g is not None and i > 100:
            gaps.append(g)
    s = r.state()
    played = sim.played()
    r.check(f"after 0.6 s fakie the stance switch plays ({[c for c in played if 'switch' in c]})",
            seen_switch and 'r_switch_ride_n_0_n_mir' in played)
    r.check(f"now riding switch: the other clip set, rolling forwards again (speed {s.speed:+.1f}, clip {s.clip})",
            s.switch and not s.mirrored and s.speed > 3 and s.clip == 'r_lean_hcom_s4'
            and abs(rig_ang(s.facing - before.facing)) < 1)
    r.check(f"the board rolled on smoothly through the switch (max step {max(board_steps) * 100:.1f} cm at 6 m/s)",
            max(board_steps) < 0.16)
    r.check(f"feet on the deck after the switch ({max(gaps) * 100:.1f} cm)", max(gaps) < 0.015)
    r.check(f"the camera moved smoothly through the jump, the fakie landing and the switch (largest step "
            f"{max(cam_steps) * 100:.1f} cm a frame; the rider falls up to 7 cm a frame, and the frame of the touchdown takes "
            f"up the last few cm of the fall and of the legs at once)", max(cam_steps) < 0.13)
    cx = sim.S.cam.pos.x - s.x
    r.check(f"riding switch the camera has come round to the side the chest now faces ({cx:+.2f} m to the right)", cx < -0.2)
    # tricks are now named switch, and the stick is read for the other clip set
    t = do_trick(r, board, UP_LEFT)
    r.check(f"riding switch, down then up-left is a switch heelflip ('{t['label']}')", t['label'] == 'Switch Heelflip'
            and 'heelflip_in_high_a' in t['played'])
    return r.finish('switch')


def grinds():
    """A 0.3 m rail along +y from y = 10 to 30. Ollie onto it in different ways."""
    ok = True

    def approach(r, turn=0.0, stick_y=0.0, side=0.0, speed=8.0, pop_at=7.3):
        """Roll at the rail, ollie, turn the body `turn` degrees (+ = left) in the air, hold the right stick."""
        sim = r.sim
        if r.state().riding:      # a clean start every time
            r.get_off()
        r.get_on()
        r.frame(20)
        r.set('pos', (0.0, 0.0, 0.0))
        r.set('facing', 0.0)
        r.set('speed', speed)
        r.set('lastSide', side)
        for _ in range(600):
            if r.state().y >= pop_at:
                break
            r.set('speed', speed)
            r.frame()
        r.flick(OLLIE, hold=0.3, settle=0)
        left = 0
        result = None
        for i in range(200):
            s = r.state()
            if s.mode == 'air':
                left += 1
                # left stick: right = clockwise. Let go a frame's turn short of the angle.
                turning = abs(s.spin) < abs(turn) - 4.0
                sim.stick((-1.0 if turn > 0 else 1.0) if turning else 0.0, 0.0, right=False)
                sim.stick(0.0, stick_y if left > 6 else 0.0)
            if s.mode == 'grind':
                result = s
                break
            if left and s.mode == 'ground' or not s.riding:
                break
            r.frame()
        sim.stick(0.0, 0.0)
        sim.stick(0.0, 0.0, right=False)
        return result

    for goofy in (False, True):
        who = 'goofy' if goofy else 'regular'
        r = rig.make(goofy=goofy, rail=dict(x=0.0, y1=10.0, y2=30.0, top=0.3))
        m = '' if goofy else '_mir'
        sim = r.sim
        board = r.get_on()
        cases = [
            ("straight", dict(), '50-50', 'g_5050_fs_hi_0_cyc', 0.0),
            ("straight, tail down", dict(stick_y=-0.8), '5-0', 'g_50_bs_hi_0_cyc', 0.0),
            ("straight, nose down", dict(stick_y=0.8), 'Nosegrind', 'g_ngrind_bs_hi_0_cyc', 0.0),
            ("turned 10 left (inside Skate 3's 16 degrees for a 50-50)", dict(turn=10.0), '50-50', None, 0.0),
            ("turned 90 left", dict(turn=90.0), 'Boardslide', None, 90.0),
            ("turned 90 right", dict(turn=-90.0), 'Boardslide', None, -90.0),
            ("turned 90 left, rail was on the left", dict(turn=90.0, side=1.0), None, None, 90.0),
            ("turned 90 left, nose down", dict(turn=90.0, stick_y=0.8), 'Noseslide', None, 90.0),
            ("turned 90 right, tail down", dict(turn=-90.0, stick_y=-0.8), 'Tailslide', None, -90.0),
            ("turned 40 left, nose down", dict(turn=40.0, stick_y=0.8), 'Crooked', None, None),
            ("turned 40 left", dict(turn=40.0), None, None, None),
            ("turned 180 (backwards)", dict(turn=-180.0), '50-50', 'g_5050_bf_hi_0_cyc', 180.0),
        ]
        for label, kw, name, clip, turn in cases:
            s = approach(r, **kw)
            if not r.check(f"{who}: {label} lands in a grind", s is not None):
                print("      state:", r.state().mode, r.state().message)
                continue
            r.frame(25)
            st = r.state()
            b = sim.ent(st.board)
            head = sim.ent(1).heading
            info = f"{st.grindLabel}, clip {st.clip}, rider turned {rig_ang(head):+.0f}, board z {b.pos.z:.2f}"
            good = st.mode == 'grind' and (name is None or st.grind == name) and (clip is None or st.clip == clip + m)
            if turn is not None:
                good &= abs(rig_ang(head - turn)) < 1.0
            good &= st.clip is not None and st.clip.startswith('g_') and st.clip.endswith(m or 'cyc')
            good &= 0.1 < b.pos.z < 0.5
            r.check(f"{who}: {label} = {info}", good)
            # the grind's clip must travel the way the board is actually going: forward-facing slides chest first
            if st.grind in ('Boardslide', 'Lipslide', 'Noseslide', 'Tailslide'):
                d = sim.run('skateboard', "return S3.GRINDS['%s'].fwd" % st.grind)
                forward_clip = st.grindSide == d
                # chest side: left of the rider for the clips as authored, right when mirrored
                chest_heading = head + (90.0 if goofy else -90.0)
                forward_actual = abs(rig_ang(chest_heading - 0.0)) < 45.0
                r.check(f"      slide clip faces the way it travels (clip {'forward' if forward_clip else 'backward'}-facing, "
                        f"rider's chest {'towards' if forward_actual else 'away from'} travel)", forward_clip == forward_actual)
            r.frame(30)
        # leaning on the rail picks the leaning clips
        s = approach(r)
        r.frame(20)
        sim.stick(1.0, 0.0, right=False)
        r.frame(40)
        leaned = r.state().clip
        sim.stick(0.0, 0.0, right=False)
        r.check(f"{who}: left stick leans the rider on the rail ({leaned})", leaned in
                ('g_5050_fs_hi_r_cyc' + m, 'g_5050_fs_hi_l_cyc' + m))
        # ride it to the end
        for _ in range(400):
            r.frame()
            if r.state().mode != 'grind':
                break
        airborne(r, 200)
        r.frame(30)
        st = r.state()
        r.check(f"{who}: off the end of the rail and rolling (y {st.y:.1f}, counted: {'50-50' in st.line + str(st.message)})",
                st.riding and st.mode == 'ground' and st.y > 30 and '50-50' in st.line + str(st.message))
        # pop out of a grind with a trick
        s = approach(r)
        r.frame(20)
        t = do_trick(r, r.state().board, OLLIE)
        r.check(f"{who}: flick on the rail pops out ({t['label']}, {t['played'][:2]})",
                t['label'] is not None and 'Ollie' in t['label'] and t['air'] > 5)
        ok &= r.finish('grinds ' + who)
    return ok


def bails():
    ok = True
    # landing in the middle of a flip
    r = rig.make(tuning=False, config="Config.PopMin, Config.PopMax = 0.03, 0.03")
    sim = r.sim
    board = r.get_on()
    roll(r, 6.0, 30)
    t = do_trick(r, board, UP_LEFT)
    s = t['state']
    r.check(f"tiny pop with a kickflip bails as under-flipped (msg {s.message})", not s.riding and 'Under-flipped' in str(s.message))
    log = sim.log()
    r.check("bail: ragdoll, ped unfrozen, board handed back to physics",
            'ragdoll' in log and sim.ent(1).frozen is False and sim.ent(board).collision is True
            and sim.ent(board).velocity is not None)
    ok &= r.finish('bails under-flip')

    def spin_and_land(r, degrees):
        sim = r.sim
        roll(r, 6.0, 30)
        r.flick(OLLIE)
        for _ in range(120):
            s = r.state()
            if s.mode == 'air':
                sim.stick(1.0 if abs(s.spin) < degrees - 4.0 else 0.0, 0.0, right=False)
            if s.mode == 'air' and abs(s.spin) >= degrees - 4.0:
                break
            r.frame()
        sim.stick(0.0, 0.0, right=False)
        sim.played(clear=True)
        airborne(r)
        return r.state()

    # landing sideways. Skate 3 lets the deck come down up to 1.1 rad (63 degrees) off line, and on easy / normal
    # the body squares up by itself just before the landing (MaxAutoBodySpinSpeed 8 rad/s; hardcore 0.5).
    r = rig.make(config="Config.Mode = 'hardcore'")
    board = r.get_on()
    s = spin_and_land(r, 86.0)
    r.check(f"hardcore: landing 90 degrees off bails (msg {s.message})", not s.riding and 'sideways' in str(s.message))
    r.check("a bail is a tumble, not an injury: collision damage is off while it lasts",
            'proofs 1 collision' in r.sim.log())
    ok &= r.finish('bails sideways')

    r = rig.make(config="Config.Mode = 'hardcore'")
    board = r.get_on()
    s = spin_and_land(r, 45.0)
    played = r.sim.played()
    r.check(f"hardcore: landing 45 degrees off is a sketchy landing, not a bail ({[c for c in played if c.startswith('l_')]})",
            s.riding and any(c.startswith('l_sketch_') for c in played))
    ok &= r.finish('bails sketchy')

    r = rig.make()
    board = r.get_on()
    s = spin_and_land(r, 86.0)
    played = r.sim.played()
    r.check(f"normal: let go 90 degrees off, the body squares up before the landing and rides away "
            f"({[c for c in played if c.startswith('l_')]}, msg {s.message})", s.riding and s.mode == 'ground'
            and not any(c.startswith('l_sketch_') for c in played))
    ok &= r.finish('bails landing assist')

    r = rig.make(tuning=False, config="Config.AutoSpinSpeed = 0.0")
    board = r.get_on()
    s = spin_and_land(r, 50.0)
    r.check(f"without Skate 3's numbers and without the assist 50 degrees off is outside Config.LandTolerance "
            f"(msg {s.message})", not s.riding and 'sideways' in str(s.message))
    ok &= r.finish('bails sideways, config numbers')

    # a wall
    r = rig.make()
    sim = r.sim
    sim.box(-5, 12, 0, 5, 13, 3)
    board = r.get_on()
    r.set('speed', 8.0)
    for _ in range(200):
        r.frame()
        if not r.state().riding:
            break
    s = r.state()
    r.check(f"rolling into a wall at speed slams (msg {s.message}, y {s.y:.1f})", not s.riding and 'Slammed' in str(s.message))
    ok &= r.finish('bails wall')
    return ok


def stock():
    """skate3_assets not running: stock GTA poses, the built-in stick reader, the board attached to the ped."""
    r = rig.make(stock=True)
    sim = r.sim
    board = r.get_on()
    r.frame(30)   # the ride loop sleeps 250 ms at a time while nobody rides
    r.check("stock pose plays and the board is attached to the ped",
            sim.anim is not None and sim.anim.clip == 'base' and sim.ent(board).attached is not None)
    sim.hold(A)
    r.frame(200)
    sim.hold(A, False)
    r.check(f"pushing reaches speed ({r.state().speed:.1f})", r.state().speed > 5)
    playing = sim.run('skateboard', "return IsEntityPlayingAnim(1, 'mini@strip_club@idles@bouncer@base', 'base', 3)")
    r.check("the stock pose survives being moved every frame (keepTasks)", playing is True)
    # built-in reader: down, then up-left = kickflip for a regular rider
    for x, y in [(0, -1)] * 20 + [(-D * i / 4, -1 + (1 + D) * i / 4) for i in range(1, 5)] + [(0, 0)] * 6:
        sim.stick(x, y)
        r.frame()
    airborne(r)
    r.frame(10)
    s = r.state()
    r.check(f"flicked kickflip lands and counts (line '{s.line}')", s.riding and s.line == 'Kickflip')
    r.get_off()
    r.check("stepped off", not r.state().riding)
    return r.finish('stock')


def inventory():
    """The ox_inventory / ox_target flow: client.lua and server.lua with stand-in ox resources."""
    # (the plain way of stepping off: Skate 3's off-board mode has its own scenario, "offboard")
    r = rig.make(inventory=0, config="Config.OffBoard.enabled = false")
    sim = r.sim
    S = sim.S

    def cmd(name='skateboard'):
        sim.command(name)
        r.frame(50)      # past the server's 0.75 s answer cache

    cmd()
    s = r.state()
    r.check("no item: not riding, no board, the server was asked", not s.riding and s.board is None and S.itemQueries == 1)
    S.items = 1
    cmd()
    s = r.state()
    board = s.board
    r.check("with the item: the toggle key drops a board and you are on it", s.riding and board is not None)
    cmd()
    s = r.state()
    r.check("toggle again: stepped off, the board stays on the ground", not s.riding and s.board == board
            and sim.S.ent[board] is not None)
    entities = len(list(S.ent.keys()))
    sim.run('skateboard', "exports.skateboard:useBoard()")
    r.frame(50)
    s = r.state()
    r.check("using the item next to the board: back on the same board", s.riding and s.board == board
            and len(list(S.ent.keys())) == entities)
    sim.run('skateboard', "exports.skateboard:useBoard()")
    r.frame(80)
    s = r.state()
    r.check("using the item while riding: off, and the board is picked up", not s.riding and s.board is None
            and sim.S.ent[board] is None)
    # the server answers repeated requests from its cache
    before = S.itemQueries
    for _ in range(5):
        sim.command('skateboard')
        r.frame(2)
    r.frame(60)
    r.check(f"five quick presses ask ox_inventory once ({S.itemQueries - before})", S.itemQueries - before == 1)
    if r.state().riding:
        r.get_off()
    ok = r.finish('inventory')

    r = rig.make(inventory=1, target=True)
    sim = r.sim
    sim.command('skateboard')
    r.frame(50)
    sim.command('skateboard')
    r.frame(50)
    s = r.state()
    opts = sim.S.targets[s.board] if sim.S.targets else None
    names = [opts[i].name for i in range(1, len(opts) + 1)] if opts else []
    r.check("ox_target options on the board: " + ", ".join(names), s.targetAdded and names == ['skateboard_ride', 'skateboard_pickup'])
    board = s.board
    opts[2].onSelect()
    r.frame(80)
    r.check("ox_target 'Pick up' removes the board and its options", r.state().board is None and sim.S.targets[board] is None)
    ok &= r.finish('inventory with ox_target')

    r = rig.make()   # no ox_inventory at all: anyone can skate
    r.sim.command('skateboard')
    r.frame(50)
    r.check("without ox_inventory the toggle key just works", r.state().riding)
    ok &= r.finish('inventory absent')
    return ok


def tuning():
    """Skate 3's own numbers (the tuning table the asset build carries) are what the ride runs on."""
    ok = True
    num = lambda r, code: r.sim.run('skateboard', 'return ' + code)

    raw = "Config.S3PushScale = 1.0\n"      # the push numbers as the database has them
    r = rig.make(config=raw)
    sim = r.sim
    board = r.get_on()
    r.check("on the board, Skate 3's tuning is in use", r.state().tuned is True)
    for code, want, what in (
            ("Tune.gravity", 9.8, "physics.WorldGravity"), ("Tune.pushMax", 8.5, "physics_push.MaxPushableSpeed"),
            ("Tune.pushGain(0.0)", 0.6, "physics_mode normal MaxPushDVStart"),
            ("Tune.pushGain(8.5)", 0.5, "physics_mode normal MaxPushDVEnd"),
            ("Tune.popRise(0.0, 5.0)", 1.33 - 0.95, "JumpMinHeight - AbsoluteMinHeight"),
            ("Tune.popRise(1.0, 5.0)", 1.71 - 0.95, "JumpMaxHeight - AbsoluteMinHeight"),
            ("Tune.hardLanding", 11.2, "Wipeout_AirMaxSpeedIntoGround"),
            ("Tune.landTolerance", math.degrees(1.1), "Wipeout_GroundMaxAngularDeckError"),
            ("Tune.grindStraight", 16.0, "AngleRange50_50"), ("Tune.slideRange", 30.0, "AngleRangeBoardSlide"),
            ("Tune.tipSlideRange", 40.0, "AngleRangeTipSlide"), ("Tune.truck", 0.243, "DeckCenterToTruck"),
            ("Tune.grindLockDist", 0.9, "physics_mode normal GrindLockDist"),
            ("Tune.grindFriction(0.0, false)", 0.1 * 9.8 * 0.6328125, "FrictionCoefficient x g x FrictionVsTime(0)"),
            ("Tune.friction(6.0, 0.0, false)", 0.0, "smooth surface friction at 6 m/s"),
            ("Tune.friction(8.0, 5.0, false)", 0.5, "FrictionVsSpeed_NoInput at 8 m/s"),
            ("Tune.spinRate(1.0, 0.2443)", math.degrees(7.939286), "PropBodySpinVsTime peak"),
            ("Tune.autoSpin", math.degrees(8.0), "physics_mode normal MaxAutoBodySpinSpeed"),
            ("Tune.baseScore('Kickflip')", 100, "scoring_trick kickflip"),
            ("Tune.baseScore('360Flip')", 250, "scoring_trick 360flip"),
            ("Tune.baseScore('Smith')", 150, "scoring_trick fs_smith"),
            ("Tune.baseScore('grab_tail')", 80, "scoring_trick tailgrab"),
            ("Tune.baseScore('L_F_Kickflip')", 150, "scoring_trick latekickflip"),
            ("Tune.lineSeconds", 5.0, "MaxSecondsGroundSequenceMaintainsLine"),
            ("Tune.fov(12.0)", 80.3, "12 mm lens")):
        got = num(r, code)
        r.check(f"{code} = {got:.4g} ({what})", abs(got - want) < 0.06)

    # rolling: nothing slows the board while the controls are in use; let go of them for 3 s and it starts to
    roll(r, 6.0, 5)
    sim.stick(0.3, 0.0, right=False)
    r.frame(300)
    sim.stick(0.0, 0.0, right=False)
    v = r.state().speed
    r.check(f"5 s of rolling with a hand on the stick loses no speed ({v:.3f} m/s)", abs(v - 6.0) < 0.001)
    r.frame(170)
    v1 = r.state().speed
    r.frame(180)
    v2 = r.state().speed
    r.check(f"hands off: nothing for 3 s ({v1:.3f}), then Skate 3's no-input friction ({v2:.2f} after 3 s more, "
            f"about 0.46 m/s per second)", abs(v1 - 6.0) < 0.001 and 4.4 < v2 < 4.9)

    # pop height comes from the crouch: a flick straight through is the weakest, a held crouch the strongest
    lo, hi = 1.33 - 0.95, 1.71 - 0.95        # JumpMinHeight / JumpMaxHeight above AbsoluteMinHeight
    for hold, what in ((0.017, "a flick straight through the crouch"), (0.07, "a third of the crouch time"),
                       (0.12, "over half the crouch time"), (0.4, "a held crouch")):
        strength = min(int(hold * 60) / 60.0 / 0.2, 1.0)
        want = lo + (hi - lo) * strength
        r.set('pos', (0.0, 0.0, 0.0))
        roll(r, 6.0, 40)
        zs = []
        r.flick(OLLIE, hold=hold, each=lambda: zs.append(r.state().z))
        for _ in range(120):
            r.frame()
            zs.append(r.state().z)
        s = r.state()
        r.check(f"ollie after {what}: the rider rises {max(zs):.3f} m (Skate 3: {want:.3f}), "
                f"{'high' if s.popHigh else 'low'} clips, landed {s.riding}",
                abs(max(zs) - want) < 0.01 and s.riding and s.popHigh == (strength >= 0.5))
        r.frame(330)
    # out of a manual there is no crouch: a fixed medium pop, and it scores as out of the manual
    r.set('pos', (0.0, 0.0, 0.0))
    roll(r, 6.0, 40)
    sim.stick(0.0, -0.4)
    r.frame(40)
    in_manual = r.state().manual
    zs = []
    r.flick([(0.0, 0.4), (0.0, -1.0)], hold=0.0, each=lambda: zs.append(r.state().z))
    for _ in range(120):
        r.frame()
        zs.append(r.state().z)
    s = r.state()
    want = lo + (hi - lo) * 0.5
    r.check(f"ollie out of a {in_manual}: rises {max(zs):.3f} m (the medium pop, {want:.3f}), line '{s.line}', "
            f"{s.lineScore} points", abs(max(zs) - want) < 0.01 and s.line == 'Manual + Ollie' and s.riding)
    manual_points = num(r, "Tune.baseScore('manual_tail')")
    r.check(f"      the ollie is worth more out of the manual: 10 x 1.1 on top of the manual's {manual_points:g} and its distance",
            s.lineScore >= manual_points + 11)
    r.frame(330)
    # very fast, pops get lower (MaxHeightVsSpeed); never lower than the trick clips need
    zs = []
    r.set('pos', (0.0, 0.0, 0.0))
    roll(r, 20.0, 20)
    r.flick(OLLIE, hold=0.4, each=lambda: (r.set('speed', 20.0), zs.append(r.state().z)))
    for _ in range(120):
        r.frame()
        zs.append(r.state().z)
    r.check(f"at 72 km/h a full pop lifts the rider only {max(zs):.3f} m (the floor, Config.PopFloor)", abs(max(zs) - 0.34) < 0.01)
    r.set('speed', 0.0)
    r.frame(400)

    # points: Skate 3's base scores; a repeat in the same line is worth half; the points behind the line set its
    # multiplier and run down while just rolling
    def kickflip():
        r.set('pos', (0.0, 0.0, 0.0))
        roll(r, 6.0, 20)
        before = [0.0]
        r.flick(UP_LEFT, each=lambda: before.__setitem__(0, r.state().momentum))
        for _ in range(240):
            s = r.state()
            if s.mode == 'air':
                before[0] = s.momentum
            elif s.line.endswith('Kickflip') and not s.pending:
                break
            r.frame()
        return before[0], r.state()

    banked = r.state().total
    m0, s1 = kickflip()
    r.check(f"kickflip = Skate 3's 100 points ({s1.lineScore}), now behind the line ({s1.momentum:.0f})",
            s1.lineScore == 100 and m0 == 0.0 and 95 <= s1.momentum <= 100)
    r.frame(30)
    drained = s1.momentum - r.state().momentum
    r.check(f"rolling, the points behind the line run down at 100 a second ({drained:.0f} in half a second)", 45 <= drained <= 55)
    m1, s2 = kickflip()
    mult = 1.5 if m1 >= 50 else 1.0
    r.check(f"a second kickflip in the line: half the points, times the line's multiplier ({mult}): "
            f"+{s2.lineScore - s1.lineScore}", s2.lineScore - s1.lineScore == round(50 * mult) and s2.line == 'Kickflip + Kickflip')
    for _ in range(400):
        r.frame()
        if r.state().line == '':
            break
    s = r.state()
    r.check(f"5 s of rolling banks the line as it stands (+{s.total - banked})", s.total - banked == s2.lineScore
            and s.line == '')
    ok &= r.finish('tuning normal')

    # the other difficulty sets, the switch, and an asset build without the table
    for config, kw, checks in (
            ("Config.Mode = 'easy'", {}, (("Tune.pushGain(0.0)", 1.5), ("Tune.popRise(0.0, 5.0)", 0.76), ("Tune.grindLockDist", 1.35))),
            ("Config.Mode = 'hardcore'", {}, (("Tune.pushGain(8.5)", 0.25), ("Tune.popRise(0.0, 5.0)", 0.34), ("Tune.grindLockDist", 0.15))),
            ("Config.UseSkate3Tuning = false", {}, (("Tune.pushGain(0.0)", 2.2), ("Tune.gravity", 9.81), ("Tune.landTolerance", 40.0),
                                                    ("Tune.baseScore('Kickflip')", 250))),
            ("", {'tuning': False}, (("Tune.pushGain(0.0)", 2.2), ("Tune.popRise(1.0, 5.0)", 0.66), ("Tune.grindStraight", 25.0))),
            ("Config.S3PushScale = 2.0", {}, (("Tune.pushGain(0.0)", 1.2),))):
        r = rig.make(config=(raw if 'S3PushScale' not in config else '') + config, **kw)
        board = r.get_on()
        label = config or 'asset build without the tuning table'
        skate3 = 'UseSkate3Tuning' not in config and kw.get('tuning', True)
        r.check(f"{label}: Skate 3's numbers {'in use' if skate3 else 'not in use'}", r.state().tuned is skate3)
        for code, want in checks:
            got = num(r, code)
            r.check(f"{label}: {code} = {got:.4g}", abs(got - want) < 0.011)
        roll(r, 6.0, 30)
        t = do_trick(r, board, UP_LEFT)
        r.check(f"{label}: a kickflip still pops, flips and lands ('{t['label']}', line '{t['state'].line}')",
                t['state'].riding and t['state'].line == 'Kickflip')
        ok &= r.finish('tuning: ' + label)

    # the skateboard resource carries none of Skate 3's numbers itself
    r = rig.make(stock=True)
    r.get_on()
    r.check("without skate3_assets: the numbers in config.lua", r.state().tuned is False and num(r, "Tune.pushGain(0.0)") == 2.2)
    ok &= r.finish('tuning stock')

    r = rig.make()
    r.get_on()
    scale = num(r, "Config.S3PushScale")
    r.check(f"as shipped a kick adds the database number x Config.S3PushScale ({scale:g}): {num(r, 'Tune.pushGain(0.0)'):.2f} m/s",
            abs(num(r, "Tune.pushGain(0.0)") - 0.6 * scale) < 1e-6)
    ok &= r.finish('tuning push scale')
    return ok


def lock():
    """Skate 3 pulls a jump onto a rail that runs beside it (physics_mode.GrindLockDist: easy 1.35 m, normal 0.9 m,
    hardcore 0.15 m). A 0.3 m high rail along +y at x = 0, from y = 10 to 30; the rider rolls along x = `side`."""
    ok = True

    def jump_beside(r, side, facing=0.0, x0=None):
        sim = r.sim
        if r.state().riding:
            r.get_off()
        r.get_on()
        r.frame(20)
        r.set('pos', (side if x0 is None else x0, 0.0, 0.0))
        r.set('facing', facing)
        r.set('speed', 8.0)
        r.set('lastSide', 0.0)
        for _ in range(600):
            if r.state().y >= 9.0:
                break
            r.set('speed', 8.0)
            r.frame()
        r.flick(OLLIE, hold=0.3, settle=0)
        left, xs = 0, []
        for _ in range(200):
            s = r.state()
            if s.mode == 'air':
                left += 1
                xs.append(s.x)
            if s.mode == 'grind' or (left and s.mode == 'ground') or not s.riding:
                break
            r.frame()
        r.frame(25)
        return r.state(), xs

    for label, config, side, grinds_it in (
            ("normal, rail 0.5 m to the left", "", 0.5, True),
            ("normal, rail 0.5 m to the right", "", -0.5, True),
            ("normal, rail 0.8 m to the side", "", 0.8, True),
            ("normal, rail 1.2 m to the side (out of reach)", "", 1.2, False),
            ("lock switched off, rail 0.5 m to the side", "Config.GrindLock = false", 0.5, False),
            ("hardcore, rail 0.5 m to the side (out of reach)", "Config.Mode = 'hardcore'", 0.5, False),
            ("hardcore, rail 0.1 m to the side", "Config.Mode = 'hardcore'", 0.1, True),
            ("easy, rail 1.2 m to the side", "Config.Mode = 'easy'", 1.2, True)):
        r = rig.make(config=config, rail=dict(x=0.0, y1=10.0, y2=30.0, top=0.3))
        s, xs = jump_beside(r, side)
        b = r.sim.ent(s.board).pos if s.riding else None
        info = f"mode {s.mode}, x {s.x:+.2f}, {s.grindLabel or s.message or ''}"
        if grinds_it:
            step = max(abs(a - c) for a, c in zip(xs, xs[1:])) if len(xs) > 1 else 9.0
            r.check(f"{label}: pulled onto the rail and grinding ({info})", s.mode == 'grind' and abs(s.x) < 0.03)
            r.check(f"      the drift is smooth (largest sideways step {step * 100:.1f} cm a frame)", step < 0.06)
            # a regular rider's chest faces right: a rail on the left (x = +side, the rider heads +y) is behind the
            # back = backside
            want = 'BS 50-50' if side > 0 else 'FS 50-50'
            r.check(f"      the side the rail was on names the grind ({s.grindLabel}, expect {want})", s.grindLabel == want)
        else:
            r.check(f"{label}: not pulled over, lands beside the rail ({info})", s.riding and s.mode == 'ground'
                    and abs(s.x - side) < 0.05)
        ok &= r.finish('lock: ' + label)

    # a rail across the way is not one to lock on to
    r = rig.make()
    r.sim.box(-5.0, 12.0, 0.0, 5.0, 12.1, 0.3)
    s, xs = jump_beside(r, 0.0)
    r.check(f"a rail lying across the line of flight does not pull the board sideways (x {s.x:+.3f})", abs(s.x) < 0.01)
    ok &= r.finish('lock: across')

    # a ledge: the board is pulled to its edge and sits just inside it
    r = rig.make()
    r.sim.box(-3.0, 10.0, 0.0, 0.0, 30.0, 0.4)       # a block to the left of x = 0 (its edge runs along x = 0)
    s, xs = jump_beside(r, 0.6)
    r.check(f"a ledge 0.6 m to the side: pulled onto its edge and grinding (mode {s.mode}, x {s.x:+.2f}, {s.grindLabel})",
            s.mode == 'grind' and -0.12 < s.x < 0.0)
    ok &= r.finish('lock: ledge')
    return ok


def approach():
    """Getting onto a rail as a player does it: not from a run-up laid along the rail, but at an angle to it, and
    aimed a little short of it or past it. Rails as thin as the game's handrails (5 cm; the lock's probes stand 6 cm
    apart). An ollie at 8 m/s; without any pull the board would come down `miss` metres to the side of the rail.

    Controls, the lock as it was before 2026-10-06 (night): the probes always in the same places (a thin rail between
    two of them is never seen, and the board stays where it cannot see it), the rail not followed between two looks
    (on a slanting approach the board is pulled onto the rail early and carried on past it), and only the very middle
    of the board counting at touchdown."""
    ok = True
    misses = (0.4, 0.3, 0.2, 0.1, 0.05, 0.0, -0.05, -0.1, -0.2, -0.3, -0.4)
    angles = (0.0, 3.0, 6.0, 10.0, 15.0)

    def old_lock(src):
        src = src.replace("local off, z, slant = seekRail(target, travelH, boardZ, (n % 3) * 0.02)",
                          "local off, z, slant = seekRail(target, travelH, boardZ, 0.0)")
        src = src.replace("elseif lock and lock.off and lock.miss < 2 then", "elseif false then")
        src = src.replace("local drift = lock.slant * math.abs(speed) -- metres a second the rail goes off to the left",
                          "local drift = 0.0")
        src = src.replace("local off2, z2 = edgeBeside(far, left, Tune.grindLockDist + 0.3, top, bottom, phase, 0.03)",
                          "local off2, z2 = edgeBeside(far, left, Tune.grindLockDist + 0.3, top, bottom, phase)")
        return src.replace("if not landHit and lock and lock.off and math.abs(lock.off) <= Config.GrindCatch then",
                           "if false then")

    def count(r, width):
        sim = r.sim

        def run(x0, heading):
            if r.state().riding:
                r.get_off()
            r.get_on()
            r.frame(20)
            r.set('pos', (x0, 0.0, 0.0))
            r.set('facing', heading)
            r.set('speed', 8.0)
            r.frame(1)
            for _ in range(16):
                r.set('speed', 8.0)
                sim.stick(0.0, -1.0)
                r.frame()
            for a, b in zip(OLLIE, OLLIE[1:]):
                for i in range(1, 4):
                    sim.stick(a[0] + (b[0] - a[0]) * i / 3, -(a[1] + (b[1] - a[1]) * i / 3))
                    r.frame()
            sim.stick(0.0, 0.0)
            left = 0
            for _ in range(300):
                st = r.state()
                if st.mode == 'air':
                    left += 1
                if st.mode == 'grind' or (left and st.mode == 'ground') or not st.riding:
                    return st
                r.frame()
            return r.state()

        d = run(30.0, 0.0).y        # how far from the start of the run-up the board comes down (well away from the rail)
        rows = {}
        for h in angles:
            rows[h] = sum(1 for miss in misses
                          if run(d * math.sin(math.radians(h)) + miss, h).mode == 'grind')
        return rows

    for width in (0.1, 0.05):
        got = {}
        for label, patch in (('now', None), ('old lock', {'client.lua': old_lock})):
            r = rig.make(rail=dict(x=0.0, y1=-40.0, y2=80.0, top=0.3, width=width), patch=patch)
            r.get_on()
            got[label] = count(r, width)
            if label == 'now':
                ok &= r.finish(f'approach: {width * 100:.0f} cm rail')
        now, old = got['now'], got['old lock']
        text = ', '.join(f"{h:.0f} deg {now[h]} (old {old[h]})" for h in angles)
        ok &= r.check(f"{width * 100:.0f} cm rail, {len(misses)} aims per angle, landed in a grind: {text}",
                      all(now[h] >= len(misses) - 1 for h in angles))
        ok &= r.check(f"{width * 100:.0f} cm rail: the old lock loses jumps this one lands (control: "
                      f"{sum(old.values())} of {len(misses) * len(angles)} against {sum(now.values())})",
                      sum(old.values()) <= sum(now.values()) - 5 and all(now[h] >= old[h] for h in angles))
    return ok


def camera():
    """Skate 3's follow camera: each situation's shot from camera_shots (distance, heading round the rider,
    elevation, reference height, lens), on the side the rider's chest faces."""
    ok = True
    for goofy in (False, True):
        who = 'goofy' if goofy else 'regular'
        r = rig.make(goofy=goofy)
        sim = r.sim
        board = r.get_on()

        def cam_rel():
            c, s = sim.S.cam, r.state()
            dx, dy, dz = c.pos.x - s.x, c.pos.y - s.y, c.pos.z - s.z
            return dx, dy, dz, c       # the rider heads +y: +x is to the right

        roll(r, 1.0, 5)
        for _ in range(240):
            r.set('speed', 1.0)
            r.frame()
        dx, dy, dz, c = cam_rel()
        # chase_flat_slow: 1.8 m from a point 0.9 m above the board, 20 degrees round from straight behind, 7 up
        flat = 1.8 * math.cos(math.radians(7.0))
        want = (flat * math.sin(math.radians(20.0)) * (-1 if goofy else 1), -flat * math.cos(math.radians(20.0)),
                0.9 + 1.8 * math.sin(math.radians(7.0)))
        r.check(f"{who}, rolling slowly: camera {dx:+.2f} right, {dy:+.2f} ahead, {dz:.2f} up "
                f"(shot: {want[0]:+.2f}, {want[1]:+.2f}, {want[2]:.2f})",
                math.dist((dx, dy, dz), want) < 0.05)
        r.check(f"      on the side the chest faces ({'left' if goofy else 'right'}), fisheye lens ({c.fov:.1f} degrees)",
                (dx < 0) == goofy and abs(c.fov - 80.3) < 0.1)
        # looking at the point is 7 degrees down and 20 degrees in towards the rider; the shot then turns the view
        # 15 degrees back out (towards the way the rider is going) and 4 further down
        r.check(f"      aimed with the shot's yaw and pitch (pitch {c.rot.x:.1f}, yaw {c.rot.z:.1f})",
                c.rot is not None and abs(c.rot.x - (-7.0 - 4.0)) < 0.5
                and abs(rig_ang(c.rot.z - (-5.0 if goofy else 5.0))) < 0.5)
        for _ in range(300):
            r.set('speed', 9.0)
            r.frame()
        dx, dy, dz, c = cam_rel()
        r.check(f"{who}, rolling fast: straight behind, further back ({dx:+.2f} right, {dy:+.2f} ahead, {dz:.2f} up)",
                abs(dx) < 0.03 and abs(dy + 2.5 * math.cos(math.radians(5.0))) < 0.05)
        ok &= r.finish('camera ' + who)

    r = rig.make(config="Config.UseSkate3Camera = false")
    r.get_on()
    r.frame(120)
    c, s = r.sim.S.cam, r.state()
    r.check(f"Config.UseSkate3Camera = false: the simple camera from config.lua ({s.y - c.pos.y:.2f} m behind)",
            c.look is not None and abs((s.y - c.pos.y) - 3.2) < 0.1)
    ok &= r.finish('camera simple')
    return ok


def selftest():
    """/skatetest, the scripted ride the resource carries for checking itself in the real game, run here first: its
    own timeline and its reading of the ride have to be right before its verdict in game means anything."""
    ok = True
    # the third run is a control: one recording of the sound pack will not load, and the test has to say so
    for label, kw, lost in (("Skate 3 clips and numbers", {}, None), ("stock poses", {'stock': True}, None),
                            ("one recording will not load (control)", {}, 'pop_2.ogg')):
        r = rig.make(**kw)
        sim = r.sim
        if lost:
            there = sim.S.soundFile
            sim.S.soundFile = lambda name, there=there, lost=lost: name != lost and there(name)
        sim.command('skatetest')
        lines, rail = [], False
        for _ in range(60 * 170):
            r.frame()
            lines = [p for p in sim.prints() if '[skatetest]' in p]
            if not rail and any('rail:' in p for p in lines):
                sim.box(-0.05, 40.0, 0.0, 0.05, 44.0, 0.3)     # the rail it just spawned (the prop has no shape here)
                rail = True
            if lines and 'RESULT' in lines[-1]:
                break
        for line in lines:
            print("      " + line.split('[skatetest] ', 1)[1][:900])
        result = lines[-1] if lines else ''
        r.check(f"{label}: the scripted ride ran to its end ({result.split('RESULT: ')[-1][:60]})", 'RESULT:' in result)
        bad = [x for x in lines if '] BAD' in x]
        heard = [x.split('[skatetest] ', 1)[1].strip()[:110] for x in lines if 'sound' in x.split('[skatetest] ', 1)[1][:16]]
        if lost:
            r.check(f"{label}: the sound step, and only it, is BAD ({heard})", len(bad) == 1 and '] BAD sound' in bad[0])
        else:
            r.check(f"{label}: every step it checks passes here ({len(bad)} BAD)", not bad and ' 0 BAD' in result)
            r.check(f"{label}: it says what it heard of the sounds ({heard})",
                    len(heard) == 1 and ('no Skate 3 sound pack' in heard[0] if kw.get('stock') else heard[0].startswith('OK  sound')))
        r.check("the rider is off the board and the real controls are back", not r.state().riding
                and sim.run('skateboard', 'return SkateTest.state().riding') is False)
        sim.S.prints = sim.lua.eval('{}')      # its report is not a script error
        ok &= r.finish('selftest: ' + label)
    return ok


def sound():
    """What the ride tells the sound page (html/sound.js): the rolling and scraping levels, and the one-off sounds."""
    r = rig.make(rail=dict(x=0.0, y1=14.0, y2=40.0, top=0.3, material='METAL_RAILING'))
    sim = r.sim
    nui = lambda: [dict(m) for m in sim.S.nui.values()]
    hits = lambda: [m['name'] for m in nui() if m.get('t') == 'hit']
    states = lambda: [m for m in nui() if m.get('t') == 'state']
    board = r.get_on()
    r.frame(30)
    r.check("getting on sets the volume (half way, the game's SFX setting at full)",
            any(m.get('t') == 'config' and m.get('volume') == 0.5 for m in nui()))
    cfg = [m for m in nui() if m.get('t') == 'config'][-1]
    pack = dict(cfg['sounds']) if cfg.get('sounds') else {}
    need = ['roll_concrete_smooth', 'roll_asphalt_smooth', 'roll_wood', 'roll_metal', 'wheels', 'wheels_manual', 'pop',
            'land', 'land_big', 'flip', 'push', 'lock', 'bail', 'grind_concrete', 'grind_metal', 'slide_concrete']
    missing = [n for n in need if n not in pack]
    r.check(f"getting on hands over Skate 3's sound pack ({len(pack)} sounds from {cfg.get('base')}; missing {missing})",
            not missing and str(cfg.get('base')).startswith('https://cfx-nui-skate3_assets/'))
    files = [f for s in pack.values() for f in dict(s)['files'].values()]
    lost = [f for f in files if not os.path.exists(os.path.join(rig.ASSETS, 'sounds', f))]
    r.check(f"every recording the pack names is there ({len(files)} files, {len(lost)} missing)", files and not lost)
    r.check("standing still nothing rolls", states() and states()[-1]['roll'] == 0.0)
    sim.hold(A)
    r.frame(60)
    sim.hold(A, False)
    r.check(f"a kick is heard ({hits()})", 'push' in hits())
    r.frame(120)                    # the push runs out
    r.set('speed', 6.0)
    r.frame(12)
    st = states()[-1]
    r.check(f"rolling is heard, louder with speed (roll {st['roll']:.1f}, grind {st['grind']}, slide {st['slide']})",
            abs(st['roll'] - 6.0) < 0.2 and st['grind'] == 0.0 and st['slide'] == 0.0)
    r.check(f"on plain ground it is the smooth concrete recording ({st.get('surface')})", st.get('surface') == 'concrete_smooth')
    # the volume follows the game's own SFX setting, and the rider's own /skatevolume
    volumes = lambda: [m['volume'] for m in nui() if m.get('t') == 'config' and m.get('volume') is not None]
    r.set('pos', (30.0, 100.0, 0.0))          # open ground, away from the rail
    sim.S.sfx = 5
    r.frame(90)
    r.check(f"the game's SFX volume turned down to half: the board follows within a second or so ({volumes()[-1]})",
            abs(volumes()[-1] - 0.25) < 1e-6)
    sim.S.sfx = 10
    sim.command('skatevolume', '30')
    r.frame(3)
    r.check(f"/skatevolume 30 sets it at once ({volumes()[-1]})", abs(volumes()[-1] - 0.30) < 1e-6)
    r.frame(90)
    r.check(f"... and it stays there ({volumes()[-1]})", abs(volumes()[-1] - 0.30) < 1e-6)
    sim.command('skatevolume', '50')
    r.frame(3)
    # a drain cover across the way, crossed in a moment, is not a change of ground
    sim.box(27.0, 200.0, -1.0, 33.0, 200.6, 0.01, material='METAL_MANHOLE')
    r.set('pos', (30.0, 190.0, 0.0))
    r.set('speed', 6.0)
    r.frame(40)                               # plain ground under the wheels for certain
    r.set('pos', (30.0, 197.0, 0.0))
    heard = set()
    for _ in range(60):
        r.frame()
        heard.add(states()[-1].get('surface'))
    r.check(f"0.6 m of metal crossed at 6 m/s is not heard as another surface ({sorted(heard)})", heard == {'concrete_smooth'})
    r.set('pos', (0.0, 0.0, 0.0))
    r.frame(30)
    # boards laid on the ground (2 cm up) and a road: the recording follows what the wheels are on
    sim.box(-3.0, -40.0, -1.0, 3.0, -20.0, 0.02, material='WOOD_SOLID_LARGE')
    sim.box(-3.0, -80.0, -1.0, 3.0, -60.0, 0.02, material='TARMAC')
    seen = {}
    for name, y in (('wood', -30.0), ('asphalt_smooth', -70.0)):
        r.set('pos', (0.0, y, 0.02))
        r.set('speed', 3.0)
        r.frame(30)
        seen[name] = states()[-1].get('surface')
    r.check(f"wood and tarmac under the wheels are heard as such ({seen})", all(k == v for k, v in seen.items()))
    r.set('pos', (0.0, 0.0, 0.0))
    r.set('speed', 6.0)
    r.frame(30)
    n0 = len(states())
    r.frame(120)
    per_second = (len(states()) - n0) / 2.0
    st = states()[-1]
    r.check(f"about twenty updates a second ({per_second:.0f})", 16 <= per_second <= 24)
    # the sounds come from the board: each update says where it is from the camera (right, up, behind)
    at = list(st['at'].values()) if st.get('at') else None
    cam = sim.run('skateboard', 'local c = GetFinalRenderedCamCoord(); return {c.x, c.y, c.z}')
    brd = sim.ent(board).pos
    far = math.dist((cam[1], cam[2], cam[3]), (brd.x, brd.y, brd.z))
    r.check(f"the board is placed in front of the camera, a little below it, as far off as it is (at {[round(v, 2) for v in at or []]}, "
            f"{far:.2f} m from the camera)",
            at is not None and at[2] < -1.0 and at[1] < 0.0 and abs(at[0]) < 1.0 and abs(math.hypot(*at) - far) < 0.05)
    world = dict(cfg['world']) if cfg.get('world') else None
    r.check(f"getting on asks for the sounds to be played from the board ({world})",
            world is not None and world.get('model') == 'HRTF' and world.get('near') == 3.5)
    # the camera put 10 m to the rider's right, looking at him: the board is straight ahead of it, 10 m off; and
    # looking the way the rider looks from there, the board is 10 m to its LEFT
    s0 = r.state()
    for label, yaw, want in (("looking at the rider", s0.facing + 90.0, (0.0, -10.0)), ("looking the way the rider looks", s0.facing, (-10.0, 0.0))):
        h = math.radians(s0.facing)
        right = (math.cos(h), math.sin(h))
        sim.S.view = sim.lua.eval("{ pos = vector3(%r, %r, %r), rot = vector3(0.0, 0.0, %r) }" % (
            brd.x + right[0] * 10.0, brd.y + right[1] * 10.0, brd.z, yaw))
        r.frame(6)
        at = list(states()[-1]['at'].values())
        # the rider has rolled on a little meanwhile: allow for it
        r.check(f"camera 10 m to the rider's right, {label}: the board is heard at right {at[0]:+.1f}, behind {at[2]:+.1f} "
                f"(expected about {want[0]:+.0f}, {want[1]:+.0f})", abs(at[0] - want[0]) < 1.5 and abs(at[2] - want[1]) < 1.5)
    sim.S.view = None
    r.frame(3)
    # ollie onto the rail
    r.set('pos', (0.0, 6.0, 0.0))
    r.set('facing', 0.0)
    r.set('speed', 8.0)
    r.flick(OLLIE, hold=0.3, settle=0)
    for _ in range(120):
        r.frame()
        if r.state().mode == 'grind':
            break
    r.frame(12)
    st = states()[-1]
    r.check(f"the pop, the landing and the trucks locking on are heard ({hits()[-4:]})",
            hits()[-3:] == ['pop', 'land', 'lock'])
    r.check(f"grinding is heard instead of rolling, and that the rail is metal (roll {st['roll']}, grind {st['grind']:.1f}, rail {st.get('rail')})",
            st['roll'] == 0.0 and st['grind'] > 3.0 and st['slide'] == 0.0 and st.get('rail') == 'metal')
    in_air = [m for m in states() if m['roll'] == 0.0 and m['grind'] == 0.0]
    r.check(f"in the air nothing rolls or scrapes and the wheels spin free ({len(in_air)} updates)",
            len(in_air) > 3 and all(m['air'] >= 1.0 for m in in_air if m.get('air')) and any(m.get('air') for m in in_air))
    # a flip trick: the board is heard whipping round
    r.get_off()
    r.get_on()
    r.set('pos', (5.0, 0.0, 0.0))
    r.set('speed', 5.0)
    n = len(hits())
    r.flick(UP_LEFT, hold=0.3, settle=40)
    r.check(f"a flip trick adds the board's whip to the pop ({hits()[n:]})", hits()[n:n + 2] == ['pop', 'flip'])
    # a manual: the free wheels are heard, the others still roll
    r.frame(80)
    r.set('speed', 5.0)
    sim.stick(0.0, -0.4)
    r.frame(70)
    st = states()[-1]
    r.check(f"in a manual two wheels roll and two spin free (manual {r.state().manual}, roll {st['roll']:.1f}, manual wheels {st.get('manual')}, quiet {st.get('quiet')})",
            r.state().manual is not None and st['roll'] > 1.0 and (st.get('manual') or 0) >= 1.0 and st.get('quiet'))
    sim.stick(0.0, 0.0)
    r.frame(20)
    # picking another of the game's grind recordings
    sim.command('skatesound', 'grind_metal', '12')
    r.frame(2)
    picks = [m for m in nui() if m.get('t') == 'pick']
    files = list(dict(dict(picks[-1])['sound'])['files'].values()) if picks else []
    r.check(f"/skatesound grind_metal 12 hands the player the game's 12th grind and plays it ({files})",
            bool(picks) and picks[-1]['name'] == 'grind_metal' and files == ['grind_12_0.ogg', 'grind_12_1.ogg', 'grind_12_2.ogg']
            and picks[-1].get('preview'))
    r.get_off()
    r.get_on()
    cfg = [m for m in nui() if m.get('t') == 'config'][-1]
    kept = list(dict(dict(cfg['sounds'])['grind_metal'])['files'].values())
    r.check(f"the pick is kept for the next ride ({kept[0]})", kept[0] == 'grind_12_0.ogg')
    # a wall
    r.get_off()
    r.get_on()
    sim.box(-5, 60, 0, 5, 61, 3)
    r.set('pos', (0.0, 50.0, 0.0))
    r.set('speed', 8.0)
    for _ in range(200):
        r.frame()
        if not r.state().riding:
            break
    last = nui()[-3:]
    r.check(f"a bail is heard and everything else stops ({[(m.get('t'), m.get('name')) for m in last]})",
            hits()[-1] == 'bail' and any(m.get('t') == 'stop' for m in last))
    plain = sim.run('skateboard', "Config.SoundFromBoard = false; return true")
    r.get_on()
    r.set('speed', 4.0)
    r.frame(20)
    cfg2 = [m for m in nui() if m.get('t') == 'config'][-1]
    r.check(f"Config.SoundFromBoard = false: plain sound is asked for and no place is sent (world {cfg2.get('world')}, at {states()[-1].get('at')})",
            cfg2.get('world') is False and states()[-1].get('at') is None)
    r.get_off()
    off = sim.run('skateboard', "Config.Sound = false; return true")
    n = len(nui())
    r.get_on()
    r.set('speed', 5.0)
    r.frame(60)
    r.check("Config.Sound = false: nothing is sent", len(nui()) == n)
    return r.finish('sound')


# The rail finder as it was when the grind step failed in the game: it only tried every tenth degree.
OLD_FINDRAIL = '''local function findRail(p, travel)
    local best, bestDiff
    for a = 0, 170, 10 do
        local d = fwd(a)
        local z1, z2 = probe(p + d * 0.5, 0.25, 0.25), probe(p - d * 0.5, 0.25, 0.25)
        if z1 and z2 and math.abs(z1 - p.z) < 0.15 and math.abs(z2 - p.z) < 0.15 then
            local perp = fwd(a + 90.0)
            local s1, s2 = probe(p + perp * 0.35, 0.25, 0.25), probe(p - perp * 0.35, 0.25, 0.25)
            if not s1 or not s2 then
                local diff = math.abs(angDiff(a, travel))
                if diff > 90.0 then diff = 180.0 - diff end
                if not bestDiff or diff < bestDiff then best, bestDiff = a, diff end
            end
        end
    end
    if not best or bestDiff > 75.0 then return nil end
    if math.abs(angDiff(best, travel)) > 90.0 then best = best + 180.0 end
    return best, bestDiff
end

'''


def anyrail():
    """A thin rail (5 cm wide, like the skate park rail prop) is found and ridden to its end whichever way it
    points, a rail that bends is followed, and so is the edge of a ledge at an angle. Negative control: the rail
    finder that only tried every tenth degree (the one in the game when /skatetest's grind step failed) misses
    the same rail at 15 degrees."""
    def old(src):
        a = src.index('local RING_STEP, RING_R')
        b = src.index('-- Is there a top at height z under each point')
        return src[:a] + OLD_FINDRAIL + src[b:]

    def seg_dist(p, a, b):
        ax, ay, bx, by = a[0], a[1], b[0], b[1]
        t = ((p[0] - ax) * (bx - ax) + (p[1] - ay) * (by - ay)) / ((bx - ax) ** 2 + (by - ay) ** 2)
        t = max(0.0, min(1.0, t))
        return math.hypot(p[0] - (ax + (bx - ax) * t), p[1] - (ay + (by - ay) * t))

    def run(heading, patch=None, bend=0.0, ledge=False):
        r = rig.make(patch=patch)
        sim = r.sim
        L = 10.0
        f = (-math.sin(math.radians(heading)), math.cos(math.radians(heading)))
        mid = (f[0] * 20.0, f[1] * 20.0)
        a, b = (mid[0] - f[0] * L / 2, mid[1] - f[1] * L / 2), (mid[0] + f[0] * L / 2, mid[1] + f[1] * L / 2)
        segs = [(a, b)]
        if ledge:
            # a block 2 m wide whose left edge lies 5 cm to the left of the rider's line
            right = (math.cos(math.radians(heading)), math.sin(math.radians(heading)))
            c = (mid[0] + right[0] * 0.95, mid[1] + right[1] * 0.95)
            sim.box(c[0] - 1.0, c[1] - L / 2, 0.0, c[0] + 1.0, c[1] + L / 2, 0.3, yaw=heading)
        else:
            sim.rail(x=mid[0], y1=mid[1] - L / 2, y2=mid[1] + L / 2, top=0.3, width=0.05, heading=heading,
                     material='METAL_RAILING')
        if bend:
            f2 = (-math.sin(math.radians(heading + bend)), math.cos(math.radians(heading + bend)))
            m2 = (b[0] + f2[0] * L / 2, b[1] + f2[1] * L / 2)
            sim.rail(x=m2[0], y1=m2[1] - L / 2, y2=m2[1] + L / 2, top=0.3, width=0.05, heading=heading + bend,
                     material='METAL_RAILING')
            segs.append((b, (b[0] + f2[0] * L, b[1] + f2[1] * L)))
        r.get_on()
        r.set('pos', (a[0] - f[0] * 7.0, a[1] - f[1] * 7.0, 0.0))     # lands about 1.5 m along the rail
        r.set('facing', heading)
        r.set('speed', 8.0)
        r.flick(OLLIE, hold=0.3, settle=0)
        frames, worst, dist, rays = 0, 0.0, 0.0, 0
        for _ in range(500):
            before = sim.S.rays or 0
            r.frame()
            rays = max(rays, (sim.S.rays or 0) - before)
            st = r.state()
            if st.mode == 'grind':
                frames += 1
                if frames > 20:     # once it has come across from where it landed
                    worst = max(worst, min(seg_dist((st.x, st.y), *s) for s in segs))
                dist = st.grindDist
            elif frames:
                break
        return r, frames, worst, dist, rays

    ok = True
    for heading in (0, 15, 33, 45, 77, 90, 138, 200, 291):
        r, frames, worst, dist, rays = run(heading)
        good = frames > 30 and dist > 6.0 and worst < 0.03
        ok &= r.check(f"a 5 cm rail pointing {heading:3d} degrees: landed on and ridden to its end "
                      f"({frames} frames, {dist:.1f} m, never more than {worst * 100:.1f} cm off it, {rays} rays in the busiest frame)", good)
        ok &= r.finish(f'anyrail: {heading} degrees')
    r, frames, worst, dist, rays = run(40, bend=4.0)
    ok &= r.check(f"a rail that turns 4 degrees half way is followed round the bend ({dist:.1f} m of 18 or so, "
                  f"never more than {worst * 100:.1f} cm off it)", dist > 12.0 and worst < 0.04)
    ok &= r.finish('anyrail: bend')
    r, frames, worst, dist, rays = run(25, ledge=True)
    ok &= r.check(f"the edge of a ledge at 25 degrees is ridden to its end ({frames} frames, {dist:.1f} m, "
                  f"{worst * 100:.1f} cm from the edge at most)", frames > 30 and dist > 6.0 and worst < 0.12)
    ok &= r.finish('anyrail: ledge')
    # the controls: the old finder works when the rail lines up with one of its headings, and fails between them
    r, frames, worst, dist, rays = run(0, patch={'client.lua': old})
    control = frames > 30 and dist > 6.0
    print(("OK  " if control else "BAD ") + f"old rail finder, rail at 0 degrees: grinds ({frames} frames, {dist:.1f} m)")
    r, frames, worst, dist, rays = run(15, patch={'client.lua': old})
    broken = frames == 0
    print(("OK  " if broken else "BAD ") + f"old rail finder, rail at 15 degrees: no grind, as in the game ({frames} frames, mode {r.state().mode})")
    ok &= control and broken
    print(("PASS " if ok else "FAIL ") + "anyrail")
    return ok


def slopes():
    """Hills, lips and landings: gravity along a slope, leaving the ground the way the board was going, and a
    landing judged by how the board meets the ground (not by how fast it was falling). Kinds of ground too.
    The old rules are run as controls where they give a different answer."""
    G = 9.81
    ok = True

    def old_rolloff(src):
        a = "                SK.fly(d * speed)\n"
        assert src.count(a) == 1
        return src.replace(a, "                SK.fly(vector3(d.x * speed, d.y * speed, math.max(d.z * speed, 0.0)))\n")

    def old_landing(src):
        a = "    if into > Tune.hardLanding then return getOff('Too high') end\n"
        assert src.count(a) == 1
        return src.replace(a, "    speed, into = before, math.max(0.0, -landedVz)\n" + a)

    # ---- 1. uphill: 30 degrees takes g sin 30 off the speed, and only cos 30 of it is level travel
    r = rig.make()
    sim = r.sim
    sim.ramp(-3.0, 20.0, 3.0, 60.0, 0.0, 40.0 * math.tan(math.radians(30.0)))
    r.get_on()
    r.set('pos', (0.0, 12.0, 0.0))
    r.set('speed', 8.0)
    for _ in range(200):
        r.frame()
        if r.state().y > 21.5:
            break
    a = r.state()
    r.frame(30)
    b = r.state()
    lost, want = a.speed - b.speed, G * 0.5 * 0.5
    run = b.y - a.y
    ok &= r.check(f"30 degrees uphill for half a second takes {lost:.2f} m/s off (g sin 30 = {want:.2f}; the old rule's g tan 30 = {G * math.tan(math.radians(30)) * 0.5:.2f})",
                  abs(lost - want) < 0.08)
    ok &= r.check(f"... and the board covers {run:.2f} m of level ground ({(a.speed + b.speed) / 2 * math.cos(math.radians(30)) * 0.5:.2f} = its speed along the slope x cos 30)",
                  abs(run - (a.speed + b.speed) / 2 * math.cos(math.radians(30)) * 0.5) < 0.08)
    ok &= r.finish('slopes: uphill')

    # ---- 2. a kicker: off the lip the board flies the way the ramp pointed
    r = rig.make()
    sim = r.sim
    sim.ramp(-3.0, 20.0, 3.0, 23.0, 0.0, 0.8)
    r.get_on()
    r.set('pos', (0.0, 12.0, 0.0))
    r.set('speed', 8.0)
    peak, air_speed, lip = 0.0, None, None
    for _ in range(260):
        r.frame()
        st = r.state()
        if st.mode == 'air':
            peak = max(peak, st.z)
            air_speed = st.speed
        elif air_speed is not None:
            break
        else:
            lip = st.speed
    v = math.sqrt(64.0 - 2 * G * 0.8)
    sin, cos = 0.8 / math.hypot(3.0, 0.8), 3.0 / math.hypot(3.0, 0.8)
    want_peak = 0.8 + (v * sin) ** 2 / (2 * G)
    ok &= r.check(f"up a 3 m kicker at 8 m/s: {lip:.2f} m/s at the lip ({v:.2f} by its height), peak {peak:.3f} m ({want_peak:.3f}), "
                  f"{air_speed:.2f} m/s over the ground in the air ({v * cos:.2f})",
                  abs(lip - v) < 0.12 and abs(peak - want_peak) < 0.035 and abs(air_speed - v * cos) < 0.12)
    ok &= r.finish('slopes: kicker')

    # ---- 3. rolling off the end of a downhill: the board is already going down
    frames = {}
    for label, patch in (("now", None), ("old rule (starts level)", {'client.lua': old_rolloff})):
        r = rig.make(patch=patch)
        sim = r.sim
        sim.box(-3.0, 0.0, 0.0, 3.0, 20.0, 2.0)
        sim.ramp(-3.0, 20.0, 3.0, 20.0 + 1.0 / math.tan(math.radians(15.0)), 2.0, 1.0)
        r.get_on()
        r.set('pos', (0.0, 12.0, 2.0))
        r.set('speed', 5.0)  # (faster, the board clears the brow of the downhill and flies from there: surftest.creases)
        n, v_end = 0, None
        for _ in range(300):
            r.frame()
            st = r.state()
            if st.mode == 'air':
                n += 1
            elif n:
                break
            else:
                v_end = st.speed
        frames[label] = (n, v_end, r)
    n, v_end, r = frames["now"]
    vz0 = v_end * math.sin(math.radians(15.0))
    t = (-vz0 + math.sqrt(vz0 * vz0 + 2 * G * 1.0)) / G
    # (the rider is tucked up in the air, so the flight path dips a little below the ground before the board touches:
    # a few frames more than the bare fall, the same for both rules)
    n_old = frames["old rule (starts level)"][0]
    sooner = (math.sqrt(2.0 / G) - t) * 60
    ok &= r.check(f"off the end of a 15 degree downhill at {v_end:.1f} m/s, 1 m up: down in {n} frames, {n_old - n} sooner than "
                  f"leaving level ({sooner:.0f} expected; the bare fall is {t * 60:.0f} frames)",
                  abs((n_old - n) - sooner) <= 2 and abs(n - t * 60) <= 3)
    ok &= r.finish('slopes: roll-off')

    # ---- 4. and 5. landing on a 30 degree downhill: soft and fast. From high up the old rule called it a bail.
    def drop(height, ramp_y, patch=None, flat=False):
        r = rig.make(patch=patch)
        sim = r.sim
        sim.box(-3.0, 0.0, 0.0, 3.0, 30.0, height)
        if not flat:
            sim.ramp(-3.0, ramp_y, 3.0, ramp_y + 3.0 / math.tan(math.radians(30.0)), 3.0, 0.0)
        r.get_on()
        r.set('pos', (0.0, 22.0, height))
        r.set('speed', 6.0)
        flew, after = False, None
        for _ in range(400):
            r.frame()
            st = r.state()
            if not st.riding:
                break
            if st.mode == 'air':
                flew = True
            elif flew:
                after = st.speed
                break
        return r, after

    r, after = drop(5.0, 32.0)
    ok &= r.check(f"a 4 m drop onto a 30 degree downhill at 6 m/s: rolls away at {after and round(after, 2)} m/s (9.60 = what is left along the slope)",
                  after is not None and abs(after - 9.60) < 0.35)
    ok &= r.finish('slopes: landing downhill')
    r, after = drop(5.0, 32.0, patch={'client.lua': old_landing})
    good = after is not None and abs(after - 6.0) < 0.3
    print(("OK  " if good else "BAD ") + f"control, the old rule: rolls away at {after and round(after, 2)} m/s (nothing gained)")
    ok &= good

    r, after = drop(10.5, 34.0)
    ok &= r.check(f"9 m down onto the same slope: landed, rolling at {after and round(after, 2)} m/s (12.26; 9.2 m/s into the ground, the limit is 11.2)",
                  after is not None and abs(after - 12.26) < 0.45 and r.state().riding)
    ok &= r.finish('slopes: high landing downhill')
    r, after = drop(10.5, 34.0, patch={'client.lua': old_landing})
    good = not r.state().riding and r.state().message == 'Too high'
    print(("OK  " if good else "BAD ") + f"control, the old rule: bail ({r.state().message}) - it only looked at the fall")
    ok &= good
    r, after = drop(10.5, 34.0, flat=True)
    ok &= r.check(f"the same drop onto the flat is still a bail ({r.state().message})", not r.state().riding and r.state().message == 'Too high')
    sim_prints = r.sim.prints()
    ok &= r.finish('slopes: high landing flat')

    # ---- 6. kinds of ground: grass and sand stop the board, as Skate 3's surfaces do
    seen = {}
    for material, kind, limit in ((None, 'smooth', None), ('GRASS', 'slow', 3.6), ('SAND_LOOSE', 'veryslow', 0.5)):
        r = rig.make()
        sim = r.sim
        if material:
            sim.box(-3.0, 20.0, -1.0, 3.0, 80.0, 0.02, material=material)
        r.get_on()
        r.set('pos', (0.0, 15.0, 0.0))
        r.set('speed', 6.0)
        for _ in range(120):
            r.frame()
            if r.state().y > 20.3:
                break
        r.frame(30)
        st = r.state()
        seen[material or 'concrete'] = (round(st.speed, 2), st.ground)
        if material:
            ok &= r.check(f"half a second on {material}: {st.speed:.2f} m/s left of 6 (ground '{st.ground}')", st.ground == kind and st.speed < limit)
        else:
            ok &= r.check(f"half a second on plain ground: still {st.speed:.2f} m/s (ground '{st.ground}')", st.ground == 'smooth' and st.speed > 5.95)
        ok &= r.finish(f'slopes: ground {material or "plain"}')

    # ---- 7. the ground falling away: a little is followed, more is a fall (it used to be put down half a metre)
    def old_follow(src):
        a = "                if drop > math.max(0.0, down) * len * 1.5 + 0.03 then hit = false end\n"
        b = "target - u * (Tune.naturalDrop + len * 1.75), board)"
        assert src.count(a) == 1 and src.count(b) == 1
        return src.replace(a, "").replace(b, "target - u * 0.5, board)")

    def ledge(height, patch=None, speed=4.0):
        r = rig.make(patch=patch)
        sim = r.sim
        sim.box(-3.0, 0.0, 0.0, 3.0, 30.0, height)
        r.get_on()
        r.set('pos', (0.0, 24.0, height))
        r.set('speed', speed)
        sim.played(clear=True)
        air, zs = 0, []
        for _ in range(240):
            r.frame()
            st = r.state()
            if st.y > 29.5:
                zs.append(st.z)
            if st.mode == 'air':
                air += 1
            if st.y > 34.0:
                break
        biggest = max((a - b for a, b in zip(zs, zs[1:])), default=0.0)
        return r, air, biggest, [c for c in sim.played() if c.startswith('l_') or c.startswith('ia_')]

    r, air, step, clips = ledge(0.30)
    want = math.sqrt(2 * 0.30 / G) * 60
    ok &= r.check(f"off a 30 cm ledge at 4 m/s: a fall of {air} frames ({want:.0f} by its height), never more than {step * 100:.0f} cm down in a frame",
                  abs(air - want) <= 3 and step < 0.10)
    ok &= r.finish('slopes: ledge')
    r, air_old, step_old, _ = ledge(0.30, patch={'client.lua': old_follow})
    good = air_old == 0 and step_old > 0.25
    print(("OK  " if good else "BAD ") + f"control, the old rule: {air_old} frames in the air, put down {step_old * 100:.0f} cm in one frame")
    ok &= good
    r, air, step, clips = ledge(0.15)
    ok &= r.check(f"off a 15 cm kerb: {air} frames off the ground and no jump made of it (clips {clips})",
                  3 <= air <= 13 and not clips and r.state().riding)
    ok &= r.finish('slopes: kerb')
    r, air, step, clips = ledge(0.08)
    ok &= r.check(f"an 8 cm drop: the wheels stay on the ground ({air} frames in the air)", air == 0)
    ok &= r.finish('slopes: small drop')
    r, air, step, clips = ledge(1.0, speed=5.0)
    ok &= r.check(f"off a 1 m ledge: {air} frames of fall and a landing is played ({clips[-2:]})",
                  abs(air - math.sqrt(2 * 1.0 / G) * 60) <= 4 and any(c.startswith('l_') for c in clips))
    ok &= r.finish('slopes: 1 m ledge')

    # up to the end of a ledge the board lies flat: it does not dip its nose at the drop it has not reached yet.
    # Control: the two-truck rule as it was, which took the ground a metre down for the front truck's.
    def dip(patch=None):
        r = rig.make(patch=patch)
        sim = r.sim
        sim.box(-3.0, 0.0, 0.0, 3.0, 30.0, 1.0)
        board = r.get_on()
        r.set('pos', (0.0, 26.0, 1.0))
        r.set('speed', 4.0)
        worst = 0.0
        for _ in range(120):
            r.frame()
            st = r.state()
            if st.mode != 'ground' or st.y > 29.99:
                break
            worst = max(worst, abs(math.degrees(math.asin(max(-1.0, min(1.0, r.board_axis(board)[2]))))))
        return r, worst

    def old_tilt(src):
        a = "    if hit and math.abs(Surf.dot(hp - p, u)) <= Config.TruckStep then return hp end\n"
        assert src.count(a) == 1
        return src.replace(a, "    if hit then return hp end\n")

    r, worst = dip()
    ok &= r.check(f"rolling up to the end of a 1 m ledge the board lies flat (most it tilts: {worst:.1f} degrees)", worst < 2.0)
    ok &= r.finish('slopes: ledge end')
    r, worst_old = dip({'client.lua': old_tilt})
    good = worst_old > 15.0
    print(("OK  " if good else "BAD ") + f"control, the old rule: the nose dips {worst_old:.1f} degrees before the drop")
    ok &= good

    # ---- 8. steering has a little weight: the board comes to the turn the stick asks for (Skate 3: Damping 0.7)
    r = rig.make()
    sim = r.sim
    r.get_on()
    roll(r, 5.0, 30)
    h0 = r.state().facing
    sim.stick(1.0, 0.0, right=False)
    rates, last = [], h0
    for _ in range(30):
        r.frame()
        h = r.state().facing
        rates.append(abs(rig_ang(h - last)) * 60.0)
        last = h
    sim.stick(0.0, 0.0, right=False)
    full = rates[-1]
    n63 = next(i for i, v in enumerate(rates) if v >= 0.63 * full) + 1
    ok &= r.check(f"full stick at 5 m/s: the turn builds over a few frames ({rates[0]:.0f}, {rates[2]:.0f}, {rates[5]:.0f} ... {full:.0f} degrees a second; "
                  f"63 % after {n63} frames, 5 or 6 by Skate 3's damping)", 4 <= n63 <= 7 and rates[0] < 0.25 * full)
    ok &= r.finish('slopes: steering')

    # ---- the ride's own report of a landing and a bail (Config.Log)
    r = rig.make(config='Config.Log = true')
    sim = r.sim
    sim.box(-3.0, 0.0, 0.0, 3.0, 30.0, 10.5)
    r.get_on()
    r.set('pos', (0.0, 22.0, 10.5))
    r.set('speed', 6.0)
    for _ in range(300):
        r.frame()
        if not r.state().riding:
            break
    lines = [p for p in sim.prints() if '[skateboard]' in p]
    good = any('landed: 14.' in p for p in lines) and any('bail: Too high' in p for p in lines)
    print(("OK  " if good else "BAD ") + f"the F8 console says what happened: {[p.split('[skateboard] ')[-1][:100] for p in lines]}")
    ok &= good
    print(("PASS " if ok else "FAIL ") + "slopes")
    return ok


def airlegs():
    """In the air the rider is tucked at the top and reaches for the ground with the legs before the board comes down
    (Skate 3: ControlAirLegExtension). So the board touches down with the legs out: no sinking into the ground in a
    ball, no standing up out of it afterwards, and the jump lasts what its height says. Control: the legs left
    tucked, as they were when the user's recording was made."""
    G = 9.8
    ok = True
    runs = {}
    for label, config in (("legs reach for the ground", ""), ("legs left tucked (control)", "Config.AirExtendTime = 0.0")):
        r = rig.make(config=config)
        sim = r.sim
        r.get_on()
        roll(r, 6.0, 30)
        sim.played(clear=True)
        r.flick(OLLIE, hold=0.4, settle=0)
        frames, lift_land, peak, clips, hips = 0, None, 0.0, [], []
        last_lift = 0.0
        landed_at = None
        for i in range(200):
            r.frame()
            st = r.state()
            if st.mode == 'air':
                frames += 1
                peak = max(peak, st.z)
                last_lift = st.lift
            elif frames and landed_at is None:
                landed_at, lift_land = i, last_lift
            if landed_at is not None:
                hips.append(sim.ent(1).pos.z)
                if len(hips) >= 14:
                    break
        clips = [c for c in sim.played()]
        rise_after = max(hips) - hips[0] if hips else 0.0
        runs[label] = dict(frames=frames, lift=lift_land, peak=peak, clips=clips, rise=rise_after, r=r)
        print(f"   {label}: {frames} frames in the air, peak {peak:.2f} m, feet tucked {lift_land * 100:.0f} cm at touchdown, "
              f"hips come up {rise_after * 100:.0f} cm in the quarter second after it; {' > '.join(c for c in clips[-5:])}")
    a, b = runs["legs reach for the ground"], runs["legs left tucked (control)"]
    r = a['r']
    hang = 2 * math.sqrt(2 * a['peak'] / G) * 60
    ok &= r.check(f"the extend clip plays before the landing clip ({[c for c in a['clips'] if 'extend' in c or c.startswith('l_')][:3]})",
                  any('ia_extend_lo_n_0_cyc' in c for c in a['clips']))
    ok &= r.check(f"the board touches down with the legs out: feet {a['lift'] * 100:.0f} cm above the path (tucked: {b['lift'] * 100:.0f} cm)",
                  a['lift'] < 0.10 and b['lift'] > 0.25)
    ok &= r.check(f"the jump lasts what its height says: {a['frames']} frames for a {a['peak']:.2f} m pop ({hang:.0f} by the fall alone; tucked: {b['frames']})",
                  abs(a['frames'] - hang) <= 3 and b['frames'] - a['frames'] >= 3)
    ok &= r.check(f"no standing up out of the landing: the hips rise {a['rise'] * 100:.0f} cm after touchdown (tucked: {b['rise'] * 100:.0f} cm)",
                  a['rise'] < 0.08 and b['rise'] > 0.15)
    ok &= r.finish('airlegs')
    return ok


def padbutton():
    """The controller's D-pad: right gets on and off, left plays a gesture. Read from the game's controls, not
    from a FiveM key binding (the game turned that down). On the keyboard the same controls are D and A, which
    must do nothing."""
    r = rig.make()
    sim = r.sim
    sim.S.keyboard = False
    sim.press(235)
    r.frame(8)
    r.check("controller, D-pad right: on the board", r.state().riding)
    sim.press(234)
    r.frame(6)
    upper = sim.S.upper.clip if sim.S.upper else None
    r.check(f"controller, D-pad left while riding: a gesture plays ({upper})", upper is not None and '_gstr_' in upper)
    r.frame(200)
    sim.press(235)
    r.frame(8)
    r.check("controller, D-pad right again: off the board", not r.state().riding)
    sim.S.keyboard = True
    r.frame(30)                 # the reader looks at what is in use a few times a second
    sim.press(235)
    r.frame(40)
    r.check("keyboard in use: the D key (the same control) does not put you on the board", not r.state().riding)
    sim.S.keyboard = False
    sim.S.paused = True
    r.frame(30)
    sim.press(235)
    r.frame(40)
    r.check("pause menu up: the D-pad does nothing", not r.state().riding)
    sim.S.paused = False
    return r.finish('padbutton')


def groundgrabs():
    """Triggers on the ground (Skate 3's onground.xml "Grabbing"): a hand on the board while rolling, the same hand
    as in the air; with both hands on it and both push buttons held as well the rider lies back on the board (the
    coffin). Controls: the same button presses without a trigger held, and without Skate 3's clips."""
    ok = True
    for goofy in (False, True):
        who = 'goofy' if goofy else 'regular'
        back, front = (LT, RT) if goofy else (RT, LT)
        m = '' if goofy else '_mir'
        # a mirrored rider's copy of the clip made for carving left carves right
        left, right = ('l', 'r') if goofy else ('r', 'l')
        r = rig.make(goofy=goofy)
        sim = r.sim
        r.get_on()

        def clip():
            return r.state().clip

        for buttons, kind, label, word in (((back,), 'fs', 'FS Ground Grab', 'fs'), ((front,), 'bs', 'BS Ground Grab', 'bs'),
                                           ((back, front), 'dbl', 'Double Ground Grab', 'dbl')):
            roll(r, 5.0, 40)
            sim.played(clear=True)
            for b in buttons:
                sim.hold(b)
            r.frame(50)
            s = r.state()
            played = sim.played()
            cyc = f'gr_ground_n_{word}_0_cyc{m}'
            r.check(f"{who}: {'+'.join('RT' if b == RT else 'LT' for b in buttons)} on the ground = {label} "
                    f"({s.ggrab}; {played[:2]})",
                    s.ggrab == kind and s.mode == 'ground' and played[:2] == [f'gr_crouch2grab_n_{word}_0_into{m}', cyc])
            # the board is steered as before, and the rider carves with a hand on it
            sim.stick(-1.0, 0.0, right=False)
            r.frame(40)
            c_left = clip()
            sim.stick(1.0, 0.0, right=False)
            r.frame(60)
            c_right = clip()
            sim.stick(0.0, 0.0, right=False)
            r.frame(50)
            carve = 'gr_ground_n_dbl_carve_%s_cyc' if word == 'dbl' else f'gr_ground_{word}_carve_%s_cyc'
            r.check(f"{who}: {label}: carving left and right plays the clips made for it ({c_left}, {c_right}, then {clip()})",
                    c_left == carve % left + m and c_right == carve % right + m and clip() == cyc)
            sim.played(clear=True)
            for b in buttons:
                sim.hold(b, False)
            r.frame(40)
            s = r.state()
            played = sim.played()
            r.check(f"{who}: letting go: the way out of it is played and the rider rides on ({played[:2]}; line '{s.line}')",
                    s.ggrab is None and played[0] == f'gr_ground_n_{word}_0_out{m}' and played[1].startswith('r_lean_hcom')
                    and label in s.line and s.lineScore > 0)
            r.frame(200)

        # a hand on the board comes before the push, the brake and the crouch
        def gain(hold_trigger, button):
            roll(r, 3.0, 30)
            if hold_trigger:
                # (both hands: with one hand a push button plants that foot, see `groundtricks`)
                sim.hold(back)
                sim.hold(front)
                r.frame(30)
            v0 = r.state().speed
            sim.hold(button)
            r.frame(60)
            sim.hold(button, False)
            v1 = r.state().speed
            sim.hold(back, False)
            sim.hold(front, False)
            r.frame(90)
            return v1 - v0

        with_hand, without = gain(True, A), gain(False, A)
        r.check(f"{who}: one push button with both hands on the board does not push ({with_hand:+.2f} m/s; without the hands {without:+.2f})",
                abs(with_hand) < 0.05 and without > 0.5)
        with_hand, without = gain(True, B), gain(False, B)
        r.check(f"{who}: ... and the brake does not brake ({with_hand:+.2f} m/s; without the hand {without:+.2f})",
                abs(with_hand) < 0.05 and without < -1.0)
        roll(r, 5.0, 30)
        sim.hold(back)
        r.frame(30)
        r.flick(OLLIE)
        r.frame(20)
        s = r.state()
        r.check(f"{who}: ... and a flick does not pop (mode {s.mode}, hand {s.ggrab})", s.mode == 'ground' and s.ggrab == 'fs')
        sim.hold(back, False)
        r.frame(120)
        r.flick(OLLIE)
        popped = airborne(r) > 10
        r.check(f"{who}: control, the same flick without the hand pops", popped)
        r.frame(120)

        # one hand, then the other as well: the game's own clip from the one grab to the other
        roll(r, 5.0, 30)
        sim.hold(back)
        r.frame(40)
        sim.played(clear=True)
        sim.hold(front)
        r.frame(30)
        played = sim.played()
        r.check(f"{who}: FS grab, then the other hand too: over to the double grab ({played[:2]})",
                r.state().ggrab == 'dbl' and played[:2] == [f'gr_grab_n_fs2dbl_0_tr{m}', f'gr_ground_n_dbl_0_cyc{m}'])

        # the coffin: both push buttons as well
        sim.played(clear=True)
        sim.hold(A)
        sim.hold(X)
        r.frame(70)
        s = r.state()
        played = sim.played()
        r.check(f"{who}: both hands and both push buttons: the coffin ({played[:2]}; coffin {s.coffin})",
                s.coffin and played[:2] == [f'gr_ground_n_coffin_0_into{m}', f'gr_ground_n_coffin_0_cyc{m}'])
        sim.stick(-1.0, 0.0, right=False)
        r.frame(40)
        c_left = clip()
        h0 = r.state().facing
        sim.stick(1.0, 0.0, right=False)
        r.frame(60)
        c_right = clip()
        h1 = r.state().facing
        sim.stick(0.0, 0.0, right=False)
        r.frame(50)
        r.check(f"{who}: lying on the board it is still steered ({c_left}, {c_right}; turned {h1 - h0:+.0f} degrees)",
                c_left == f'gr_ground_n_coffin_{"left" if left == "l" else "right"}_cyc{m}'
                and c_right == f'gr_ground_n_coffin_{"right" if left == "l" else "left"}_cyc{m}' and abs(h1 - h0) > 20)
        # lying on it costs speed: Skate 3's CoffinAcceleration, 0.4 m/s per second
        r.set('speed', 5.0)
        r.frame(120)
        lost = 5.0 - r.state().speed
        r.check(f"{who}: two seconds lying on the board cost {lost:.2f} m/s (0.80 by Skate 3's number)", abs(lost - 0.8) < 0.05)
        # the push buttons let go: sits up into the double grab
        sim.played(clear=True)
        sim.hold(A, False)
        sim.hold(X, False)
        r.frame(80)
        s = r.state()
        played = sim.played()
        r.check(f"{who}: push buttons let go: sits up into the double grab ({played[:2]}; line '{s.line}')",
                not s.coffin and s.ggrab == 'dbl' and 'Coffin' in s.line
                and played[:2] == [f'gr_ground_n_coffin_2hgrab_out{m}', f'gr_ground_n_dbl_0_cyc{m}'])
        r.set('speed', 5.0)
        r.frame(120)
        kept = 5.0 - r.state().speed
        r.check(f"{who}: control, two seconds with both hands on the board but sitting cost {kept:.2f} m/s", abs(kept) < 0.05)
        # back down, then everything let go at once: sits up as into the FS grab and rides on
        sim.hold(A)
        sim.hold(X)
        r.frame(70)
        lying = r.state().coffin
        sim.played(clear=True)
        for b in (A, X, back, front):
            sim.hold(b, False)
        r.frame(80)
        s = r.state()
        played = sim.played()
        r.check(f"{who}: everything let go: up and riding ({played[:2]}; lying before {lying})",
                lying and not s.coffin and s.ggrab is None and s.riding
                and played[0] == f'gr_ground_n_coffin_fsgrab_out{m}' and played[1].startswith('r_lean_hcom'))
        ok &= r.finish('groundgrabs ' + who)

    # off a kerb with a hand on the board: no jump is made of it; off a ledge: the air grab's cycle, then its landing
    def drop(height, lie=False):
        r = rig.make()
        sim = r.sim
        sim.box(-3.0, 0.0, 0.0, 3.0, 30.0, height)
        r.get_on()
        r.set('pos', (0.0, 18.0, height))
        r.set('speed', 4.0)
        sim.hold(RT)
        if lie:
            sim.hold(LT)
        r.frame(50)
        if lie:
            sim.hold(A)
            sim.hold(X)
            r.frame(70)
        r.set('pos', (0.0, 24.0, height))
        r.set('speed', 4.0)
        sim.played(clear=True)
        air, lying, lift = 0, True, 0.0
        for _ in range(300):
            r.frame()
            st = r.state()
            if st.mode == 'air':
                air += 1
                lift = max(lift, st.lift or 0.0)
            lying = lying and (st.coffin or not lie)
            if st.y > 36.0 or not st.riding:
                break
        return r, air, sim.played(), lying, lift

    fall = lambda h: math.sqrt(2 * h / 9.8) * 60
    r, air, played, _, lift = drop(0.15)
    s = r.state()
    ok &= r.check(f"off a 15 cm kerb with a hand on the board: {air} frames off the ground ({fall(0.15):.0f} by its "
                  f"height), the hand stays ({s.ggrab}; clips {played})",
                  3 <= air <= 13 and s.ggrab == 'fs' and s.riding and not played)
    ok &= r.finish('groundgrabs: kerb')
    r, air, played, _, lift = drop(1.0)
    s = r.state()
    ok &= r.check(f"off a 1 m ledge with a hand on the board: {air} frames of fall ({fall(1.0):.0f} by its height; the "
                  f"board {lift * 100:.0f} cm above its path), the air grab's cycle, its landing, then the hand on the "
                  f"ground again ({played}; {s.ggrab})",
                  abs(air - fall(1.0)) <= 3 and lift < 0.05 and s.riding and s.ggrab == 'fs'
                  and played[:2] == ['gr_grab_n_fs_0_cyc_mir', 'l_fsgrab_mir'] and played[-1] == 'gr_ground_n_fs_0_cyc_mir')
    ok &= r.finish('groundgrabs: ledge')
    r, air, played, lying, lift = drop(1.0, lie=True)
    s = r.state()
    ok &= r.check(f"off a 1 m ledge lying on the board: {air} frames of fall ({fall(1.0):.0f} by its height; the board "
                  f"{lift * 100:.0f} cm above its path), lying on it all the way and nothing else played ({played}; "
                  f"coffin {s.coffin})",
                  abs(air - fall(1.0)) <= 3 and lift < 0.05 and s.riding and s.coffin and lying and not played)
    ok &= r.finish('groundgrabs: coffin off a ledge')
    # control: the same fall with the hips taken up to their standing height, as for a jump (the player's rule
    # before): the board is carried up off its path and the fall lasts longer
    old_low = lambda src: src.replace("low = mode == 'air' and (coffin ~= nil or (air ~= nil and air.groundGrab == true)),", "low = false,")
    def drop_old():
        r = rig.make(patch={'client.lua': old_low})
        sim = r.sim
        sim.box(-3.0, 0.0, 0.0, 3.0, 30.0, 1.0)
        r.get_on()
        r.set('pos', (0.0, 18.0, 1.0))
        r.set('speed', 4.0)
        for b in (RT, LT):
            sim.hold(b)
        r.frame(50)
        sim.hold(A)
        sim.hold(X)
        r.frame(70)
        r.set('pos', (0.0, 24.0, 1.0))
        r.set('speed', 4.0)
        air, lift = 0, 0.0
        for _ in range(300):
            r.frame()
            st = r.state()
            if st.mode == 'air':
                air += 1
                lift = max(lift, st.lift or 0.0)
            if st.y > 36.0 or not st.riding:
                break
        return air, lift
    air_old, lift_old = drop_old()
    good = air_old > fall(1.0) + 4 and lift_old > 0.3
    print(("OK  " if good else "BAD ") + f"control, without that rule: {air_old} frames, the board {lift_old * 100:.0f} cm above its path")
    ok &= good

    # in the air: out of the double grab, the same two buttons
    r = rig.make()
    sim = r.sim
    r.get_on()
    roll(r, 6.0, 40)
    big_ollie(r)
    sim.hold(LT)
    sim.hold(RT)
    r.frame(20)
    sim.played(clear=True)
    sim.hold(A)
    sim.hold(X)
    r.frame(25)
    s = r.state()
    in_air = s.coffin and s.mode == 'air'
    airborne(r, 400)
    r.frame(30)
    s2 = r.state()
    played = sim.played()
    ok &= r.check(f"in the air, both hands and both push buttons: the coffin, and it lands lying down ({played}; "
                  f"in the air {in_air}, on the ground {s2.coffin})",
                  in_air and s2.riding and s2.coffin and played == ['gr_ground_n_coffin_0_into_mir', 'gr_ground_n_coffin_0_cyc_mir'])
    for b in (A, X, LT, RT):
        sim.hold(b, False)
    r.frame(90)
    s = r.state()
    ok &= r.check(f"... and counts once the rider is up again (line '{s.line}')", 'Coffin' in s.line and not s.coffin)
    ok &= r.finish('groundgrabs: coffin in the air')

    # control: without Skate 3's clips there is no pose for any of it, so the triggers do nothing on the ground
    r = rig.make(stock=True)
    sim = r.sim
    r.get_on()
    roll(r, 5.0, 30)
    sim.hold(LT)
    sim.hold(RT)
    sim.hold(A)
    sim.hold(X)
    r.frame(60)
    s = r.state()
    ok &= r.check(f"control, stock poses: no ground grab and no coffin ({s.ggrab}, {s.coffin})",
                  s.ggrab is None and not s.coffin and s.riding)
    ok &= r.finish('groundgrabs: stock')
    return ok


def flip_run(r, board, coords, hold=0, boost=None, second=None, press=None, late=None, late_hold=None,
             again=None, foot=None, crouch=16):
    """One jump with everything that can be done to a flip. coords = the flick (pattern space).
    hold    keep the stick where the flick ended for this many frames after it (the game: more flips)
    crouch  frames the stick sits in the crouch before the flick (a long crouch is a strong pop)
    boost   vz set two frames into the air (a big jump, for the time)
    second  a second flick's coords, played straight after the first (underflip)
    press   (control, frames after the flick) a button tapped during the flip (dark catch)
    late    (coords, air frame) a late-flip gesture flicked in the air; late_hold = a control held with it
    again   (control, air frame) a button tapped later in the air (the quick way out of a dark catch)
    foot    (control, from air frame, for frames) a push button held in the air
    Returns what was seen."""
    sim = r.sim
    sim.played(clear=True)
    seen = {'air': 0, 'turns': 0.0, 'dark': False, 'flips': None, 'onefoot': None, 'label': None, 'airTricks': 0}
    up0 = [None]

    def watch():
        st = r.state()
        if st.mode == 'air':
            seen['air'] += 1
            if boost and seen['air'] == 2:
                r.set('vz', boost)
            seen['dark'] = seen['dark'] or st.dark
            seen['flips'] = st.flips or seen['flips']
            seen['onefoot'] = st.onefoot or seen['onefoot']
            seen['label'] = st.air or seen['label']
            seen['airTricks'] = max(seen['airTricks'], st.airTricks)
            if sim.S.ent[board]:
                # how far the board has rolled over, by its up axis going round
                u = qrot(sim.ent(board).q, (0, 0, 1))
                side = qrot(sim.ent(board).q, (0, 1, 0))  # (the stub prop is long on x: y is across it)
                a = math.atan2(side[2], u[2])
                if up0[0] is not None:
                    d = (a - up0[0] + math.pi) % (2 * math.pi) - math.pi
                    seen['turns'] += d / (2 * math.pi)
                up0[0] = a

    def stick(x, y):
        sim.stick(x, -y)

    # the crouch (held long enough for a strong pop), the flick, then the stick held where it ended or let go
    before = r.state().line or ''
    for _ in range(crouch):
        stick(0.0, 1.0 if coords[0][1] > 0 else -1.0)  # (the nose end for a nollie)
        r.frame(1, watch)
    for _ in range(3):
        stick(*coords[0])
        r.frame(1, watch)
    for a, b in zip(coords, coords[1:]):
        for i in range(1, 4):
            stick(a[0] + (b[0] - a[0]) * i / 3, a[1] + (b[1] - a[1]) * i / 3)
            r.frame(1, watch)
    path = [coords[-1]] * hold if hold else [(coords[-1][0] * k, coords[-1][1] * k) for k in (0.7, 0.4, 0.1, 0.0)]
    if second:
        path += [second[0]]
        for a, b in zip(second, second[1:]):
            path += [(a[0] + (b[0] - a[0]) * i / 3, a[1] + (b[1] - a[1]) * i / 3) for i in range(1, 4)]
        path += [(second[-1][0] * k, second[-1][1] * k) for k in (0.7, 0.4, 0.1, 0.0)]
    n = 0
    late_path = None
    for _ in range(600):
        if n < len(path):
            stick(*path[n])
        elif late_path:
            stick(*late_path.pop(0))
        else:
            stick(0.0, 0.0)
        if press and n == press[1]:
            sim.press(press[0])
        if late and seen['air'] == late[1] and late_path is None:
            c = late[0]
            late_path = [c[0]] * 6
            for a, b in zip(c, c[1:]):
                late_path += [(a[0] + (b[0] - a[0]) * i / 3, a[1] + (b[1] - a[1]) * i / 3) for i in range(1, 4)]
            late_path += [(c[-1][0] * k, c[-1][1] * k) for k in (0.7, 0.4, 0.1, 0.0)]
            if late_hold:
                sim.hold(late_hold)
        if again and seen['air'] == again[1]:
            sim.press(again[0])
        if foot:
            sim.hold(foot[0], foot[1] <= seen['air'] < foot[1] + foot[2])
        r.frame(1, watch)
        n += 1
        st = r.state()
        if not st.riding or (seen['air'] > 0 and st.mode != 'air'):
            break
    if late_hold:
        sim.hold(late_hold, False)
    sim.stick(0.0, 0.0)
    r.frame(25, watch)
    seen['played'] = sim.played()
    seen['state'] = r.state()
    line = seen['state'].line or ''
    # this jump's own part of the line (a fall empties the line)
    seen['line'] = line[len(before):].lstrip(' +') if (before and line.startswith(before)) else line
    seen['ragdoll'] = 'ragdoll' in [str(x) for x in sim.S.log.values()]
    return seen


def flips():
    """What can be done to a flip (Skate 3's Tricks/T_Kickflip.xml, T_TrickWithUnderflip.xml, T_TrickWithDarkCatch.xml,
    air.xml): the flick held = more flips while there is the time, a second flick = underflip, a push button = dark
    catch, late flips out of the dark catch; and a foot off the board in a plain jump. Controls: the same jumps without
    the extra input, and a held flick in a jump too short for a second flip."""
    ok = True
    for goofy in (True, False):
        who = 'goofy' if goofy else 'regular'
        m = '' if goofy else '_mir'
        r = rig.make(goofy=goofy)
        sim = r.sim
        board = r.get_on()
        # the stick paths of the clips as authored: a mirrored (regular) rider gets the twin of each
        kick = r.pattern('Kickflip') if goofy else r.pattern('Heelflip')
        heel = r.pattern('Heelflip') if goofy else r.pattern('Kickflip')
        late = r.pattern('L_F_Kickflip', 'air') if goofy else r.pattern('L_F_Heelflip', 'air')

        def fresh():
            nonlocal board
            if not r.state().riding:
                r.get_on()
                board = r.state().board
            r.frame(100)
            roll(r, 6.0, 40)

        def run(label, want, coords, clips=None, riding=True, dark=None, **kw):
            """One jump: this jump's part of the line must be `want`; clips (if given) must all have played."""
            fresh()
            d = flip_run(r, board, coords, **kw)
            st = d['state']
            good = st.riding == riding and d['line'] == want
            if riding:
                good = good and upright_in_line(r, board)
            if dark is not None:
                good = good and d['dark'] == dark
            missing = [c for c in (clips or []) if c + m not in d['played']]
            r.check(f"{who}: {label}: '{d['line']}'" + ('' if riding else f" then off the board ('{st.message}')")
                    + (f", MISSING clips {missing}" if missing else ''), good and not missing)
            return d

        # ---- how many flips
        for label, hold, boost, n, want, crouch in (
                ('a kickflip, the stick let go', 0, 9.0, 1, 'Kickflip', 16),
                ('the flick held in a weak pop: no time for more (control)', 200, None, 1, 'Kickflip', 0),
                ('the flick held in the strongest pop on the flat: time for one more', 200, None, 2, 'Double Kickflip', 16),
                ('the flick held for 26 frames of a big jump', 26, 9.0, 2, 'Double Kickflip', 16),
                ('the flick held for 50 frames', 50, 9.0, 3, 'Triple Kickflip', 16),
                ('the flick held all the way', 300, 9.0, 4, 'Quad Kickflip', 16)):
            d = run(label, want, kick, hold=hold, boost=boost, crouch=crouch)
            turns = abs(d['turns'])
            r.check(f"{who}:     ... the board went round {turns:.2f} times in {d['air']} frames of air", abs(turns - n) < 0.15)
        clips = [c for c in d['played'] if c.startswith('t_') or c.startswith('kickflip')]
        r.check(f"{who}: the quad's clips are the game's chain ({clips})",
                clips == [x + m for x in ('kickflip_in_high_g', 'kickflip_in_high_a', 't_hi_kick_cyc1', 't_hi_kick_cyc2',
                                          't_hi_kick_cyc3', 't_hi_kick_out4')])

        # ---- underflip: a second flick straight after the first
        run('kickflip, then a second flick', 'Kickflip Underflip', kick, boost=6.0, second=heel,
            clips=['t_kickflip_hi_uflip_0_out1', 't_heelflip_hi_4flips_0_out1'])
        run('pop shuvit, then a second flick', 'Pop Shuvit Underflip',
            r.pattern('PopShuvit') if goofy else r.pattern('FSPopShuvit'), boost=6.0, second=kick,
            clips=['t_popshuvit_hi_uflip_out1'])

        # ---- dark catch: a push button while the board turns
        d = run('kickflip + push button, caught upside down, down on the grip tape', '', kick, boost=4.0, press=(RB, 6),
                riding=False, dark=True, clips=['t_kickflip_hi_dcatch_0_out1', 'ia_ds_idle_n_n_0_cyc'])
        r.check(f"{who}:     ... the rider steps off, no fall ('{d['state'].message}', ragdoll {d['ragdoll']})",
                d['state'].message == 'Landed on the grip tape' and not d['ragdoll'])
        run('... flicked the right way up again with a late-flip gesture', 'Kickflip Dark Catch + Dark to Light Kickflip',
            kick, boost=8.0, press=(RB, 6), late=(late, 40), dark=True, clips=['t_darktolight_kickflip_hi'])
        run('... or the button pressed again, which counts for nothing', 'Kickflip Dark Catch', kick, boost=8.0,
            press=(RB, 6), again=(RB, 40), dark=True, clips=['t_darktolight_kickflip_hi'])
        run('360 flip + push button', '360 Flip Dark Catch + Dark to Light Kickflip',
            r.pattern('360Flip') if goofy else r.pattern('Laserflip'), boost=8.0, press=(RB, 6), late=(late, 50), dark=True,
            clips=['t_360flip_hi_dcatch_out1'])
        run('the flick held, then the push button: caught after one and a half',
            'Double Kickflip Dark Catch + Dark to Light Kickflip', kick, hold=60, boost=9.0, press=(RB, 30), late=(late, 80),
            dark=True, clips=['t_kickflip_hi_dcatch_0_out2'])
        d = run('ollie, a late flip with a push button held: caught upside down', '', OLLIE, boost=4.0, late=(late, 12),
                late_hold=RB, riding=False, dark=True, clips=['t_ds_late_heelflip_hi_0_n'])
        run('control, the same kickflip with no button', 'Kickflip', kick, boost=8.0, dark=False)
        run('control, a push button during the flip (the dark catch is the right bumper, as in Skate 3): a plain kickflip',
            'Kickflip', kick, boost=8.0, press=(A, 6), dark=False)

        # ---- a foot off the board in a plain jump
        kind = 'front' if goofy else 'back'       # the A button is the right foot: in front for a goofy rider
        d = run("ollie, then the right foot's push button held: that foot off",
                'Ollie + ' + ('One Foot' if kind == 'front' else 'Back Foot Off'), OLLIE, boost=8.0, foot=(A, 10, 40),
                clips=[f'1ft_air_ollie_n_{kind}_high_into', f'1ft_air_ollie_n_{kind}_high_cyc', f'1ft_air_ollie_n_{kind}_high_out'])
        r.check(f"{who}:     ... ({d['onefoot']})", d['onefoot'] == kind)
        d = run('control, the button in a small ollie with under half a second of air left: the foot stays on', 'Ollie',
                OLLIE, foot=(A, 25, 40))
        r.check(f"{who}:     ... ({d['onefoot']})", d['onefoot'] is None)
        d = run('control, the button already held when the board leaves the ground (a push held on): the foot stays on',
                'Ollie', OLLIE, boost=8.0, foot=(A, -1000, 5000))
        r.check(f"{who}:     ... ({d['onefoot']})", d['onefoot'] is None)
        ok &= r.finish('flips ' + who)

    # every flip that has a variant, once each (the clips as authored): the window each needs is found in its clips
    r = rig.make(goofy=True)
    sim = r.sim
    board = r.get_on()
    late = r.pattern('L_F_Kickflip', 'air')
    bad = []

    def one(name, want, **kw):
        nonlocal board
        if not r.state().riding:
            r.get_on()
            board = r.state().board
        r.frame(100)
        roll(r, 6.0, 40)
        d = flip_run(r, board, r.pattern(name), **kw)
        if not (d['state'].riding and d['line'] == want and upright_in_line(r, board)):
            bad.append(f"{name}: '{d['line']}' for '{want}'")

    n = 0
    for name, label in (('Kickflip', 'Kickflip'), ('Heelflip', 'Heelflip'), ('N_Kickflip', 'Nollie Kickflip'),
                        ('N_Heelflip', 'Nollie Heelflip')):
        twin = {'Kickflip': 'Heelflip', 'Heelflip': 'Kickflip', 'N_Kickflip': 'N_Heelflip', 'N_Heelflip': 'N_Kickflip'}[name]
        one(name, 'Quad ' + label, hold=300, boost=9.0)
        one(name, 'Triple ' + label, hold=50, boost=9.0)
        one(name, label + ' Underflip', boost=6.0, second=r.pattern(twin))
        one(name, label + ' Dark Catch', boost=8.0, press=(RB, 6), again=(RB, 45))
        one(name, 'Triple ' + label + ' Dark Catch', hold=90, boost=9.5, press=(RB, 55), again=(RB, 105))
        n += 5
    for name, label in (('PopShuvit', 'Pop Shuvit'), ('FSPopShuvit', 'FS Pop Shuvit'), ('N_PopShuvit', 'Nollie Pop Shuvit'),
                        ('N_FSPopShuvit', 'Nollie FS Pop Shuvit')):
        one(name, label + ' Underflip', boost=6.0, second=r.pattern('Kickflip'))
        n += 1
    for name, label in (('360Flip', '360 Flip'), ('Laserflip', 'Laser Flip'), ('360Hardflip', '360 Hardflip'),
                        ('360InwardHeelflip', '360 Inward Heelflip'), ('N_360Flip', 'Nollie 360 Flip'),
                        ('N_Laserflip', 'Nollie Laser Flip'), ('N_360Hardflip', 'Nollie 360 Hardflip'),
                        ('N_360InwardHeelflip', 'Nollie 360 Inward Heelflip')):
        one(name, label + ' Dark Catch', boost=8.0, press=(RB, 6), again=(RB, 55))
        n += 1
    ok &= r.check(f"every flip with a variant, once each: {n - len(bad)} of {n} come out as named" + (f"; NOT: {bad}" if bad else ''),
                  not bad)
    ok &= r.finish('flips: every variant')
    return ok


def allgrabs():
    """Every grab in the air and what can be made of it (Skate 3's air.xml, T_Grab.xml, StaleMuteGrab.xml,
    BoardAdjust*.xml, GrabsTweaks/*.xml): the grab is settled when the hand goes on, by where the stick is held then;
    the stick moved afterwards tweaks it; push buttons take a foot off, the brake button both (Skate 3's trick book:
    button 4, the brake's; Y is button 5 and gets off the board); flicks of the stick flip the board by hand.
    Controls: the stick moved after the hand is on must NOT change which grab it is; Y steps off the board with or
    without a hand on it; the brake button with no hand on the board does nothing in the air."""
    ok = True
    for goofy in (True, False):
        who = 'goofy' if goofy else 'regular'
        m = '' if goofy else '_mir'
        back, front = (LT, RT) if goofy else (RT, LT)
        r = rig.make(goofy=goofy)
        sim = r.sim
        board = r.get_on()
        # the stick for "the nose to the left / right": the tail goes the stick's way, and a mirrored rider's is turned
        side = {'left': (1.0 if goofy else -1.0, 0.0), 'right': (-1.0 if goofy else 1.0, 0.0), 'up': (0.0, 1.0),
                'down': (0.0, -1.0), None: (0.0, 0.0)}
        front_foot, back_foot = (A, X) if goofy else (X, A)

        def hang(n):
            """n frames in the air without coming down."""
            for _ in range(n):
                if r.state().vz < -1.5:
                    r.set('vz', 1.5)
                r.frame()

        def jump(pre=None, hands=()):
            nonlocal board
            if not r.state().riding:
                r.get_on()
                board = r.state().board
            r.frame(100)
            roll(r, 6.0, 40)
            big_ollie(r, 6.0, settle=25)
            sim.stick(*side[pre])
            hang(4)
            for b in hands:
                sim.hold(b)
            sim.played(clear=True)
            hang(28)

        def done():
            before = r.state().line or ''
            for b in (LT, RT, A, X, Y, B):
                sim.hold(b, False)
            sim.stick(0.0, 0.0)
            played = sim.played()
            hang(30)
            airborne(r, 500)
            r.frame(25)
            st = r.state()
            return st, played

        def last(st, n=1):
            return ' + '.join((st.line or '').split(' + ')[-n:])

        # ---- which grab: the stick BEFORE the hand
        for pre, hand, kind, label, clip in (
                (None, back, 'fs', 'FS Grab', 'gr_grab_n_fs_0'), (None, front, 'bs', 'BS Grab', 'gr_grab_n_bs_0'),
                ('up', back, 'tail', 'Tail Grab', 'gr_tailgrab_n_bs_0'), ('up', front, 'seatbelt', 'Seatbelt', 'gr_seatbeltgrab_n_0'),
                ('down', back, 'crail', 'Crail', 'gr_crailgrab_n_0'), ('down', front, 'nose', 'Nose Grab', 'gr_nosegrab_n_bs_0'),
                ('right', back, 'stale', 'Stalefish', 'gr_stalegrab_n_0'), ('right', front, 'mute', 'Mute', 'gr_mutegrab_n_0'),
                ('left', back, 'fs', 'FS Grab', 'gr_grab_n_fs_0')):
            jump(pre, (hand,))
            got = r.state().grab
            # a stale / mute stays with the stick let go; the others here are held as they began
            if kind in ('stale', 'mute'):
                sim.stick(0.0, 0.0)
                hang(15)
                got = (got, r.state().grab)
                kind = (kind, kind)
            st, played = done()
            r.check(f"{who}: stick {pre or 'not held'}, then the {'back' if hand == back else 'front'} hand: {label} "
                    f"({got}; {played[:2]}; '{last(st)}')",
                    got == kind and played[:2] == [clip + '_into' + m, clip + '_cyc' + m] and st.riding
                    and (last(st) == label or (pre == 'left' and last(st) in ('Stiffy', 'Cross Bone'))))

        # ---- the stick AFTER the hand tweaks the grab: it does not change which grab it is
        for hand, base, tweaks in (
                (back, 'fs', (('up', 'Nosebone', 'gr_nbone_n_fs_0_cyc'), ('down', 'Tailbone', 'gr_tbone_n_fs_0_cyc'),
                              ('left', 'Stiffy', 'gr_stiffy_n_fs_0_cyc'), ('right', 'Tuck Knee', 'gr_tknee_n_fs_0_cyc'))),
                (front, 'bs', (('up', 'Melon', 'gr_melon_n_bs_0_cyc'), ('down', 'Japan', 'gr_japan_n_bs_0_cyc'),
                               ('left', 'Cross Bone', 'gr_cbone_n_bs_0_cyc'), ('right', 'Method', 'gr_method_n_bs_0_cyc')))):
            bad = []
            for zone, label, clip in tweaks:
                jump(None, (hand,))
                sim.stick(*side[zone])
                hang(25)
                st0 = r.state()
                st, played = done()
                if not (st0.grab == base and st0.gvar == 'tw_' + zone and st0.clip == clip + m and last(st) == label and st.riding):
                    bad.append(f"{zone}: {st0.grab} / {st0.gvar} / {st0.clip} / '{last(st)}'")
            r.check(f"{who}: {base} grab, then the stick: still that grab, tweaked four ways (" +
                    ', '.join(t[1] for t in tweaks) + ')' + (f"; NOT: {bad}" if bad else ''), not bad)
        jump('up', (back,))
        sim.stick(*side['left'])
        hang(25)
        st0 = r.state()
        sim.stick(0.0, 0.0)
        hang(30)
        st1 = r.state()
        st, played = done()
        # (BoardAdjustUp.xml "TailGrab": the stick is wanted to begin it, the trigger to keep it)
        r.check(f"{who}: tail grab, the stick round to the side: the shifty ({st0.grab}, {st0.clip}); the stick let go: "
                f"the trigger holds the tail grab ({st1.grab}); '{last(st, 1)}'",
                st0.grab == 'tail' and st0.clip == 'gr_tailgrab_shifty_bs_0_cyc' + m and st1.grab == 'tail'
                and last(st, 1) == 'BS Shifty Tail Grab')
        jump('right', (front,))
        sim.stick(*side['up'])
        hang(25)
        st0 = r.state()
        st, played = done()
        r.check(f"{who}: mute, then the stick up: Mute Nosebone ({st0.clip}; '{last(st)}')",
                st0.grab == 'mute' and st0.clip == 'gr_mutegrab_n_nose_cyc' + m and last(st) == 'Mute Nosebone')

        # ---- feet off
        for pre, hand, button, label, clip in (
                (None, back, front_foot, 'FS Grab One Foot', '1ft_air_grab_n_fsr'),
                (None, back, back_foot, 'FS Grab Back Foot Off', '1ft_air_grab_n_fsl'),
                (None, front, front_foot, 'BS Grab One Foot', '1ft_air_grab_n_bsr'),
                ('up', back, back_foot, 'Tail Grab Back Foot Off', '1ft_air_grab_n_taill'),
                ('down', front, front_foot, 'Nose Grab One Foot', '1ft_air_grab_n_noser'),
                (None, back, B, 'No Foot Air', 'gr_dsmnt_nofoot_fs'),
                (None, front, B, 'Christ Air', 'gr_dsmnt_christ_bs'),
                ('up', back, B, 'Tail Grab Airwalk', '2ft_air_grab_n_tail'),
                ('down', front, (A, X), 'Nose Grab Airwalk', '2ft_air_grab_n_nose')):
            jump(pre, (hand,))
            sim.played(clear=True)
            for b in (button if isinstance(button, tuple) else (button,)):
                sim.hold(b)
            hang(60)
            st0 = r.state()
            for b in (button if isinstance(button, tuple) else (button,)):
                sim.hold(b, False)
            hang(45)
            st, played = done()
            want = [clip + x + m for x in ('_0_into', '_0_cyc', '_0_out')]
            r.check(f"{who}: {label} ({[c for c in played if c in want]}; riding in the air {st0.riding}; '{last(st, 2)}')",
                    st0.riding and st0.mode == 'air' and played[:3] == want and label in last(st, 2) and st.riding)
        jump(None, (back, front))
        sim.played(clear=True)
        sim.hold(B)
        hang(60)
        sim.hold(B, False)
        hang(45)
        st, played = done()
        r.check(f"{who}: both hands + the brake button: Superman ({played[:3]}; '{last(st, 2)}')",
                played[:3] == ['gr_dsmnt_super_dbl' + x + m for x in ('_0_into', '_0_cyc', '_0_out')] and 'Superman' in last(st, 2)
                and st.riding)
        jump(None, (back,))
        sim.hold(B)
        hang(60)
        sim.played(clear=True)
        sim.hold(front)
        hang(50)
        st0 = r.state()
        sim.hold(B, False)
        hang(45)
        st, played = done()
        r.check(f"{who}: no-foot air, then the other hand as well: across into the superman ({played[:2]}; '{last(st, 4)}')",
                st0.grab == 'dbl' and st0.gvar == 'super'
                and played[:2] == ['gr_dsmnt_n_nofoot_to_super' + m, 'gr_dsmnt_super_dbl_0_cyc' + m]
                and 'No Foot Air' in last(st, 4) and 'Superman' in last(st, 4) and st.riding)
        jump('down', (front,))
        sim.played(clear=True)
        sim.hold(back)
        hang(60)
        st0 = r.state()
        sim.hold(back, False)
        hang(45)
        st, played = done()
        r.check(f"{who}: nose grab, then the other hand as well: Rocket Air ({played[:3]}; '{last(st, 2)}')",
                st0.grab == 'nose' and played[:3] == ['gr_nosegrab_rocketair_n' + x + m for x in ('_0_into', '_0_cyc', '_0_out')]
                and 'Rocket Air' in last(st, 2) and st.riding)

        # ---- finger flips: a flick of the right stick with a hand on the board
        fs_var, bs_var = ('FS_Varial', 'BS_Varial') if goofy else ('BS_Varial', 'FS_Varial')
        for pre, hand, gesture, label, clips, ends in (
                (None, back, 'Fingerflip', 'FS Grab Finger Flip', ('f_flip_fs_grab_into_0_n', 'f_flip_fs_grab_out_n_grab'), 'fs'),
                (None, front, 'Fingerflip', 'BS Grab Finger Flip', ('f_flip_bs_grab_into_0_n', 'f_flip_bs_grab_out_n_grab'), 'bs'),
                (None, back, bs_var, 'FS Grab Varial Finger Flip', ('f_flip_fs_grab_varial_into', 'f_flip_fs_grab_varial_out_grab'), 'fs'),
                (None, back, fs_var, 'FS Grab to Stalefish Finger Flip', ('f_flip_fs_grab_to_stale', 'gr_stalegrab_n_0_cyc'), 'stale'),
                (None, front, fs_var, 'BS Grab to Mute Finger Flip', ('f_flip_bs_grab_to_mute', 'gr_mutegrab_n_0_cyc'), 'mute'),
                ('right', front, fs_var, 'Mute to BS Grab Finger Flip', ('f_flip_mute_to_bs_grab', 'gr_grab_n_bs_0_cyc'), 'bs'),
                ('right', back, 'Fingerflip', 'Stalefish Finger Flip', ('f_flip_stale_grab_into_0_n', 'f_flip_stale_grab_out_n_grab'), 'stale'),
                ('up', back, 'Fingerflip', 'Tail Grab Finger Flip', ('f_flip_tail_grab_into_0_n', 'f_flip_tail_grab_out_n_grab'), None),
                (None, front, bs_var, 'BS Grab Varial Finger Flip', ('f_flip_bs_grab_varial_into', 'f_flip_bs_grab_varial_out_grab'), 'bs'),
                ('right', back, fs_var, 'Stalefish to FS Grab Finger Flip', ('f_flip_stale_to_fs_grab', 'gr_grab_n_fs_0_cyc'), 'fs'),
                ('right', front, 'Fingerflip', 'Mute Finger Flip', ('f_flip_mute_grab_into_0_n', 'f_flip_mute_grab_out_n_grab'), 'mute'),
                ('down', front, 'Fingerflip', 'Nose Grab Finger Flip', ('f_flip_nose_grab_into_0_n', 'f_flip_nose_grab_out_n_grab'), None),
                ('down', back, fs_var, 'Crail to Tail Grab Finger Flip', ('f_flip_crail_to_tail_grab',), None),
                ('up', front, fs_var, 'Seatbelt to Nose Grab Finger Flip', ('f_flip_seatbelt_to_nose_grab',), None)):
            jump(pre, (hand,))
            sim.played(clear=True)
            # the gesture that starts where the stick is being held (up or down), or any of them from the middle
            held = side[pre] if pre in ('up', 'down') else None
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
            path += [(coords[-1][0] * k, coords[-1][1] * k) for k in (0.7, 0.4, 0.1, 0.0)]
            for x, y in path:
                sim.stick(x, -y)
                hang(1)
            sim.stick(0.0, 0.0)
            hang(40)
            st0 = r.state()
            st, played = done()
            good = all(c + m in played for c in clips) and label in (st.line or '') and st.riding and upright_in_line(r, board)
            if ends:
                good = good and st0.grab == ends
            r.check(f"{who}: {label} ({[c for c in played if c.startswith('f_')]}; in hand afterwards: {st0.grab}; "
                    f"'{last(st, 3)}')", good)

        # ---- controls: the brake button with no hand on the board does nothing; Y gets off the board, hand or no hand
        jump(None, ())
        sim.hold(B)
        hang(20)
        st0 = r.state()
        sim.hold(B, False)
        r.check(f"{who}: control, the brake button in the air with no hand on the board: nothing ({st0.riding}, {st0.grab})",
                st0.riding and st0.mode == 'air' and st0.grab is None)
        sim.press(Y)
        r.frame(5)
        r.check(f"{who}: control, Y in the air with no hand on the board: off the board ({r.state().riding})", not r.state().riding)
        jump(None, (back,))
        sim.press(Y)
        r.frame(5)
        sim.hold(back, False)
        r.check(f"{who}: control, Y in the air with a hand on the board: off the board too ({r.state().riding})", not r.state().riding)
        ok &= r.finish('allgrabs ' + who)
    return ok


def allgrinds():
    """Every grind Skate 3 names (Grinds/Grinds.xml) and how one is come by: the truck on the rail and the way the nose
    points from it; the blunt slides (the board gone over the rail); the darkslide (a board caught upside down landed
    on a rail) and the trick out of it; a hand on the board while grinding. Controls: each name's opposite case."""
    ok = True

    # ---- 1. the naming rule itself, both stances, every name; each must be a name in Skate 3's scoring table
    for goofy in (True, False):
        who = 'goofy' if goofy else 'regular'
        r = rig.make(goofy=goofy)
        r.get_on()
        choose, score = r.T.chooseGrind, r.sim.run('skateboard', 'return Tune.baseScore')
        k = 1.0 if goofy else -1.0        # a mirrored rider: everything the other way round
        rows = [
            # nose off the rail's line (+ = left), stick, where the rail crosses the board, dark -> name, key
            (30, 'nose', None, False, 'Crooked', 'fs_crook'), (-30, 'nose', None, False, 'Overcrook', 'fs_overcrook'),
            (30, 'tail', None, False, 'Salad', 'fs_salad'), (-30, 'tail', None, False, '5-0', 'fs_5_o'),
            (30, None, 0.0, False, 'Feeble', 'fs_feeble'), (30, None, 0.3, False, 'Willy', 'fs_willy'),
            (-30, None, 0.0, False, 'Smith', 'fs_smith'), (-30, None, 0.3, False, 'Overwilly', 'fs_overwilly'),
            (-30, None, -0.3, False, 'Smith', 'fs_smith'), (30, None, -0.3, False, 'Feeble', 'fs_feeble'),
            (90, 'nose', None, False, 'Noseslide', None), (-90, 'nose', None, False, 'Noseblunt', None),
            (-90, 'tail', None, False, 'Tailslide', None), (90, 'tail', None, False, 'Blunt', None),
            (90, None, None, False, 'Boardslide', None), (-90, None, None, False, 'Lipslide', None),
            (90, None, None, True, 'Darkslide', None), (20, None, None, True, 'Darkslide', None),
            (0, None, None, False, '50-50', 'fs_50_50'), (0, 'nose', None, False, 'Nosegrind', 'fs_nosegrind'),
        ]
        bad = []
        for rel, adj, cross, dark, name, key in rows:
            g = choose(0.0, k * rel, adj, k * 1.0, cross, dark)   # the rail was on the toe side: a frontside grind
            if g.name != name or (key and g.key != key) or not g.key or score(g.key) <= 0:
                bad.append(f"{rel} {adj} {cross} {'dark' if dark else ''}: {g.name} / {g.key} ({score(g.key or 'none')} points) for {name}")
        ok &= r.check(f"{who}: {len(rows)} ways onto a rail on the toe side, each its own grind with its own name in "
                      f"Skate 3's table" + (f"; NOT: {bad}" if bad else ''), not bad)
        g1, g2 = choose(0.0, k * 30.0, 'nose', k * 1.0, None, False), choose(0.0, k * -30.0, 'nose', k * -1.0, None, False)
        ok &= r.check(f"{who}: the same angle with the rail on the heel side is the backside one ({g1.key}, {g2.key})",
                      g1.key == 'fs_crook' and g2.key == 'bs_crook')
        ok &= r.finish('allgrinds: names ' + who)

    # ---- 2. ridden: onto a rail (or the edge of a ledge) along +y from y = 10
    def onto(r, turn=0.0, stick_y=0.0, side=1.0, x0=0.0, flick=None, press=None, speed=8.0):
        """Roll at the rail, pop, turn the body `turn` degrees (+ = left) in the air, hold the right stick."""
        sim = r.sim
        if r.state().riding:
            r.get_off()
        r.get_on()
        r.frame(20)
        r.set('pos', (x0, 0.0, 0.0))
        r.set('facing', 0.0)
        r.set('speed', speed)
        for _ in range(600):
            if r.state().y >= 7.3:
                break
            r.set('speed', speed)
            r.frame()
        sim.stick(0.0, 0.0, right=False)
        coords = flick or OLLIE
        # (the crouch long enough for a strong pop, then the flick)
        for _ in range(16):
            sim.stick(0.0, -1.0)
            r.frame()
        for a, b in zip(coords, coords[1:]):
            for i in range(1, 4):
                sim.stick(a[0] + (b[0] - a[0]) * i / 3, -(a[1] + (b[1] - a[1]) * i / 3))
                r.frame()
        sim.stick(0.0, 0.0)
        r.frame(2)
        if press:
            sim.press(press)
        left, result = 0, None
        for i in range(240):
            st = r.state()
            if st.mode == 'air':
                left += 1
                if left == 1:
                    r.set('lastSide', side)
                turning = abs(st.spin) < abs(turn) - 4.0
                sim.stick((-1.0 if turn > 0 else 1.0) if turning else 0.0, 0.0, right=False)
                sim.stick(0.0, stick_y if left > 6 else 0.0)
            if st.mode == 'grind':
                result = st
                break
            if (left and st.mode == 'ground') or not st.riding:
                break
            r.frame()
        sim.stick(0.0, 0.0)
        sim.stick(0.0, 0.0, right=False)
        return result

    for goofy in (True, False):
        who = 'goofy' if goofy else 'regular'
        m = '' if goofy else '_mir'
        k = 1.0 if goofy else -1.0
        other = {'fs': 'bs', 'bs': 'fs'}
        for what, world in (('rail', dict(rail=dict(x=0.0, y1=10.0, y2=30.0, top=0.3))), ('ledge', {})):
            r = rig.make(goofy=goofy, **world)
            sim = r.sim
            if what == 'ledge':
                # a block on the far side of x = 0: its edge runs along x = 0, the rider comes from the open side
                sim.box(-3.0 * k, 10.0, 0.0, 0.0, 30.0, 0.3) if k > 0 else sim.box(0.0, 10.0, 0.0, 3.0, 30.0, 0.3)
            r.get_on()
            cases = [
                ('nose 40 over the rail, stick down', dict(turn=40.0 * k, stick_y=-0.8), 'Salad', 'g_salad_fs_hi_0_cyc'),
                ('nose 40 back from it, stick up', dict(turn=-40.0 * k, stick_y=0.8), 'Overcrook', 'g_crooks_bs_hi_0_cyc'),
                ('nose 40 over the rail, stick up', dict(turn=40.0 * k, stick_y=0.8), 'Crooked', 'g_crooks_fs_hi_0_cyc'),
                ('board across, tail on it, the board gone over (stick down)', dict(turn=90.0 * k, stick_y=-0.8), 'Blunt',
                 'g_blunt_%s_hi_0_cyc' if what == 'ledge' else 'g_tslide_%s_hi_0_cyc'),
                ('board across, nose on it, the board gone over (stick up)', dict(turn=-90.0 * k, stick_y=0.8), 'Noseblunt',
                 'g_nblunt_%s_hi_0_cyc' if what == 'ledge' else 'g_nslide_%s_hi_0_cyc'),
            ]
            if what == 'rail':
                cases += [
                    ('the rail 0.4 m to the side, nose 40 towards it, board level', dict(turn=40.0 * k, x0=0.4 * k), 'Willy',
                     'g_willy_bs_hi_0_cyc'),
                    ('the same, nose 40 away from it', dict(turn=-40.0 * k, x0=0.4 * k), 'Smith', 'g_smith_fs_hi_0_cyc'),
                    ('dead on the rail, nose 40 over it, board level', dict(turn=40.0 * k), 'Feeble', 'g_feeble_fs_hi_0_cyc'),
                ]
            for label, kw, name, clip in cases:
                st = onto(r, side=k, **kw)
                if not r.check(f"{who}, {what}: {label}: lands in a grind", st is not None):
                    print("      state:", r.state().mode, r.state().message)
                    continue
                r.frame(25)
                st = r.state()
                want = clip
                if '%s' in clip:
                    # a blunt on a ledge is its own side's clip; on a rail the other side's tail / nose slide
                    side = st.grindSide
                    want = clip % (side if what == 'ledge' else other[side])
                r.check(f"{who}, {what}: {label}: {name} ({st.grindLabel}; {st.clip})",
                        st.mode == 'grind' and st.grind == name and st.clip == want + m)
            ok &= r.finish(f'allgrinds: {what} {who}')

    # ---- 3. the darkslide, and out of it
    for goofy in (True, False):
        who = 'goofy' if goofy else 'regular'
        m = '' if goofy else '_mir'
        k = 1.0 if goofy else -1.0
        r = rig.make(goofy=goofy, rail=dict(x=0.0, y1=10.0, y2=30.0, top=0.3))
        sim = r.sim
        board = r.get_on()
        kick = r.pattern('Kickflip') if goofy else r.pattern('Heelflip')
        st = onto(r, turn=90.0 * k, side=k, flick=kick, press=RB)
        landed = st is not None
        r.frame(25)
        st = r.state()
        up = r.board_up(st.board) if landed else 1.0
        r.check(f"{who}: kickflip caught upside down, the board across a rail: a darkslide ({st.grindLabel}; {st.clip}; "
                f"the board's top points {'down' if up < -0.9 else 'elsewhere'})",
                landed and st.mode == 'grind' and st.grind == 'Darkslide' and st.dark and up < -0.9
                and st.clip in ('g_ds_fs_hi_0_cyc' + m, 'g_ds_bs_hi_0_cyc' + m))
        side = st.grindSide
        before = st.line or ''
        sim.played(clear=True)
        # (across the rail the gestures are turned with the board: Skate 3's own turned pattern sets)
        r.flick(r.pattern('Ollie', 'groundN90' if k > 0 else 'ground90'), hold=0.2)
        airborne(r, 300)
        r.frame(25)
        st = r.state()
        played = sim.played()
        board = st.board
        r.check(f"{who}: a flick on the darkslide: out of it, the board the right way up again ({[c for c in played if c.startswith('t_')]}; "
                f"line '{st.line}')",
                st.riding and not st.dark and upright_in_line(r, board) and 'Darkslide Out' in (st.line or '')
                and any(c in played for c in (f't_dslide_{side}_hi_0_straight_out{m}', f't_dslide_{side}_low_0_straight_out{m}')))
        # control: no rail under it: down on the grip tape, off the board
        r.get_off()
        r.get_on()
        r.frame(20)
        r.set('pos', (5.0, 0.0, 0.0))
        r.set('speed', 6.0)
        r.frame(30)
        d = flip_run(r, r.state().board, kick, boost=4.0, press=(RB, 6))
        r.check(f"{who}: control, the same catch over plain ground: no slide, the rider steps off ('{d['state'].message}')",
                d['dark'] and not d['state'].riding)
        ok &= r.finish('allgrinds: darkslide ' + who)

    # ---- 4. a hand on the board while grinding
    for goofy in (True, False):
        who = 'goofy' if goofy else 'regular'
        m = '' if goofy else '_mir'
        k = 1.0 if goofy else -1.0
        back, front = (LT, RT) if goofy else (RT, LT)
        r = rig.make(goofy=goofy, rail=dict(x=0.0, y1=10.0, y2=60.0, top=0.3))
        sim = r.sim
        r.get_on()
        for label, kw, hands, clip, text, key in (
                ('50-50, back hand', dict(), (back,), 'g_5050_fs_grab', '50-50 FS Grab', 'fs_50_50_fsgrab'),
                ('50-50, front hand', dict(), (front,), 'g_5050_bs_grab', '50-50 BS Grab', 'fs_50_50_bsgrab'),
                ('boardslide, both hands', dict(turn=90.0 * k), (back, front), 'g_bslide_%s_grab_double', 'Boardslide Double Grab', None),
                ('nosegrind, back hand', dict(stick_y=0.8), (back,), 'g_ngrind_hi_grab_tail', 'Nosegrind Tail Grab', 'fs_nosegrind_tailgrab'),
                ('feeble (no grab for it in the game), back hand', dict(turn=40.0 * k), (back,), None, 'Feeble Grind', None)):
            st = onto(r, side=k, speed=9.0, **kw)
            if not r.check(f"{who}: {label}: lands in a grind", st is not None):
                continue
            r.frame(15)
            side = r.state().grindSide
            sim.played(clear=True)
            for b in hands:
                sim.hold(b)
            r.frame(50)
            held = r.state().clip
            for b in hands:
                sim.hold(b, False)
            r.frame(80)
            after = r.state()
            played = sim.played()
            for _ in range(900):
                if r.state().mode != 'grind':
                    break
                r.frame()
            airborne(r, 200)
            r.frame(20)
            line = r.state().line or ''
            last = line.split(' + ')[-1] or f"(nothing: {r.state().message})"
            if clip:
                c = (clip % side if '%s' in clip else clip) + '_'
                good = played[:3] == [c + x + m for x in ('into', 'cyc', 'out')] and after.clip.startswith('g_') \
                    and 'grab' not in after.clip and last.endswith(text)
            else:
                good = not any('grab' in c for c in played) and last.endswith(text)
            r.check(f"{who}: {label}: {played[:3]}, then {after.clip}; '{last}'", good)
        ok &= r.finish('allgrinds: grabs ' + who)
    return ok


def groundtricks():
    """Off the ground without an ollie (Skate 3's Tricks.xml "PushTrick", T_HippyJump.xml, revert.xml): a foot planted
    out of a ground grab (boneless = front foot, fastplant = back foot), a no comply (the front foot's push button, then
    a flick), the hippy jump (both push buttons: the rider jumps, the board rolls on) and reverts (the left stick swept
    through a half circle). Controls: the same buttons in the cases that must stay what they were."""
    ok = True
    for goofy in (True, False):
        who = 'goofy' if goofy else 'regular'
        m = '' if goofy else '_mir'
        back, front = (LT, RT) if goofy else (RT, LT)
        front_foot, back_foot = (A, X) if goofy else (X, A)
        r = rig.make(goofy=goofy)
        sim = r.sim
        board = r.get_on()
        keep = sim.run('skateboard', 'return Tune.plantKeep')
        jump = sim.run('skateboard', 'return Tune.plantJump')()

        def fresh(speed=5.0):
            nonlocal board
            for b in (LT, RT, A, X):
                sim.hold(b, False)
            sim.stick(0.0, 0.0)
            sim.stick(0.0, 0.0, right=False)
            if not r.state().riding:
                r.get_on()
                board = r.state().board
            r.frame(120)
            r.set('speed', speed)
            r.frame(20)
            r.set('speed', speed)

        def ride_out(hold=()):
            """Until back on the ground: frames in the air, the highest the board's path went, the speed in the air."""
            n, peak, z0, v = 0, 0.0, r.state().z, None
            for _ in range(400):
                r.frame()
                st = r.state()
                if st.mode == 'air':
                    n += 1
                    peak = max(peak, st.z - z0)
                    v = st.speed
                elif n or not st.riding:
                    break
            for b in hold:
                sim.hold(b, False)
            r.frame(40)
            return n, peak, v

        # ---- a foot planted out of a ground grab
        for hand, foot, name, clip in ((back, front_foot, 'FS Boneless', 'boneless_fs'), (back, back_foot, 'FS Fastplant', 'fastplant_fs'),
                                       (front, front_foot, 'BS Boneless', 'boneless_bs'), (front, back_foot, 'BS Fastplant', 'fastplant_bs')):
            fresh(5.0)
            sim.hold(hand)
            r.frame(45)
            v0 = r.state().speed
            sim.played(clear=True)
            sim.press(foot)
            n, peak, v = ride_out(hold=(hand,))
            st = r.state()
            played = sim.played()
            parts = [c for c in played if c.startswith(clip)]
            want_peak = jump * jump / (2 * 9.8)
            grab = 'gr_grab_n_fs_0' if hand == back else 'gr_grab_n_bs_0'
            r.check(f"{who}: a hand on the board, then the {'front' if foot == front_foot else 'back'} foot's button: {name} "
                    f"({parts}; up {peak:.2f} m ({want_peak:.2f} by Skate 3's number), rolling {v0:.2f} -> {v:.2f} "
                    f"({v0 * keep(v0):.2f}); '{st.line}')",
                    st.riding and parts == [f'{clip}_fast_{x}{m}' for x in 'gfla'] and abs(peak - want_peak) < 0.03
                    and abs(v - v0 * keep(v0)) < 0.05 and name in (st.line or '') and upright_in_line(r, board)
                    and grab + '_cyc' + m in played and grab + '_into' + m not in played)
        fresh(5.0)
        sim.hold(back)
        sim.hold(front)
        r.frame(45)
        sim.press(front_foot)
        r.frame(30)
        r.check(f"{who}: control, both hands on the board and one push button: no plant (mode {r.state().mode})",
                r.state().mode == 'ground' and r.state().ggrab == 'dbl')

        # ---- no comply: the front foot's push button, then a flick while that foot is going down
        for foot, want, clips in ((front_foot, 'No Comply', True), (back_foot, 'Ollie', False)):
            fresh(4.0)
            sim.played(clear=True)
            sim.hold(foot)
            r.frame(3)
            r.flick(OLLIE, hold=0.05, settle=0)
            sim.hold(foot, False)
            n, peak, v = ride_out()
            st = r.state()
            parts = [c for c in sim.played() if c.startswith('nocomply')]
            last = (st.line or '').split(' + ')[-1]
            r.check(f"{who}: the {'front' if foot == front_foot else 'back'} foot's push button, then a flick: {want} "
                    f"({parts}; '{last}')" + ('' if clips else ' (control)'),
                    st.riding and last == want and (parts == [f'nocomply_l_med_into_{x}{m}' for x in 'fla']) == clips)

        # ---- the hippy jump
        for frames, height, rise in ((45, 'high', 0.70), (6, 'mini', 0.40 + 0.30 * (6 / 60) / 0.49)):
            fresh(5.0)
            sim.played(clear=True)
            sim.hold(A)
            sim.hold(X)
            r.frame(frames)
            crouching = r.state().hippy
            sim.hold(A, False)
            sim.hold(X, False)
            top, board_z, z0, y0 = 0.0, [], sim.ent(board).pos.z, r.state().y
            for _ in range(300):
                r.frame()
                st = r.state()
                if st.hippy is None:
                    break
                top = max(top, st.hop or 0.0)
                board_z.append(sim.ent(board).pos.z)
            r.frame(30)
            st = r.state()
            played = sim.played()
            want = ['t_hippyjump_high_n_0_antic' + m] + (['t_hippyjump_antic_cyc' + m] if frames > 31 else []) + \
                   [f't_hippyjump_{height}_n_0_into{m}', f't_hippyjump_{height}_n_0_cyc{m}']
            moved = max(abs(z - z0) for z in board_z)
            r.check(f"{who}: both push buttons held {frames} frames, then let go: the rider jumps {top:.2f} m ({rise:.2f} by "
                    f"Skate 3's numbers), the board stays on the ground (moves {moved * 100:.0f} cm up or down) and rolls on "
                    f"{st.y - y0:.1f} m; '{st.line}'",
                    crouching == 'antic' and st.riding and st.mode == 'ground' and abs(top - rise) < 0.03 and moved < 0.02
                    and st.y - y0 > 2.0 and (st.line or '').endswith('Hippy Jump') and played[:len(want)] == want
                    and any(c.startswith('l_') for c in played))
        fresh(3.0)
        v0 = r.state().speed
        sim.hold(A)
        r.frame(45)
        sim.hold(A, False)
        r.frame(60)
        st = r.state()
        r.check(f"{who}: control, one push button alone is a push ({v0:.2f} -> {st.speed:.2f} m/s, hippy {st.hippy})",
                st.speed > v0 + 0.5 and st.hippy is None)

        # ---- a revert: the left stick swept through a half circle
        for gesture, clockwise in (('SlideFs180', True), ('SlideBs180', False)):
            fresh(5.0)
            st0 = r.state()
            sim.played(clear=True)
            coords = r.pattern(gesture, 'left')
            path = [coords[0]] * 4
            for a, b in zip(coords, coords[1:]):
                path += [(a[0] + (b[0] - a[0]) * i / 4, a[1] + (b[1] - a[1]) * i / 4) for i in range(1, 5)]
            path += [(coords[-1][0] * k, coords[-1][1] * k) for k in (0.7, 0.4, 0.1, 0.0)]
            started, frames = None, 0
            for i in range(200):
                x, y = path[i] if i < len(path) else (0.0, 0.0)
                sim.stick(x, -y, right=False)
                r.frame()
                st = r.state()
                if st.revert:
                    started = started if started is not None else i
                    frames += 1
                elif started is not None:
                    break
            r.frame(10)
            st = r.state()
            # (the first revert leaves the rider rolling backwards, and so riding switch for the second: a mirrored
            # rider's clockwise is the backside way)
            side = 'fs' if clockwise != st0.mirrored else 'bs'
            mm = '_mir' if st0.mirrored else ''
            turned = rig_ang(st.facing - st0.facing)
            head0 = sim.ent(1).heading
            played = sim.played()
            r.check(f"{who}: left stick {gesture}: the board slides round in {frames} frames, then rolls backwards the way it "
                    f"was going (facing turned {abs(turned):.0f}, speed {st.speed:+.1f}, still going +y: {st.y - st0.y:+.1f} m; "
                    f"{[c for c in played if c.startswith('r_turn')]}; '{st.line}')",
                    started is not None and 25 <= frames <= 45 and abs(abs(turned) - 180.0) < 15.0 and st.speed < -3.5
                    and st.y - st0.y > 1.5 and f'r_turn_180slide_{side}_n_0_n{mm}' in played
                    and (st.line or '').endswith(('FS' if side == 'fs' else 'BS') + ' Revert'))
        fresh(0.0)
        coords = r.pattern('SlideFs180', 'left')
        for x, y in [coords[0]] * 4 + [coords[1]] * 4 + [coords[2]] * 4 + [(0.0, 0.0)] * 6:
            sim.stick(x, -y, right=False)
            r.frame()
        r.check(f"{who}: control, the same sweep standing still: no revert ({r.state().revert})", not r.state().revert)
        ok &= r.finish('groundtricks ' + who)
    return ok


SCENARIOS = {
    'basics': basics,
    'goofy': lambda: basics(goofy=True, name='goofy'),
    'freemode': lambda: basics(offset=(0.04, -0.05, 0.03), name='freemode'),
    'keeptasks': keeptasks,
    'watchdog': watchdog,
    'push': push,
    'tricks': tricks,
    'alltricks': alltricks,
    'late': late,
    'grabs': grabs,
    'manual': manual,
    'switch': switch,
    'grinds': grinds,
    'bails': bails,
    'stock': stock,
    'inventory': inventory,
    'tuning': tuning,
    'lock': lock,
    'approach': approach,
    'camera': camera,
    'selftest': selftest,
    'sound': sound,
    'anyrail': anyrail,
    'padbutton': padbutton,
    'slopes': slopes,
    'airlegs': airlegs,
    'groundgrabs': groundgrabs,
    'flips': flips,
    'allgrabs': allgrabs,
    'allgrinds': allgrinds,
    'groundtricks': groundtricks,
    'skitch': skitchtest.skitch,
    'helmet': skitchtest.helmet,
    'coffinboard': skitchtest.coffinboard,
    'shop': skitchtest.shop,
    'board': boardtest.board,
    'shoppage': boardtest.shoppage,
    'offboard': offtest.offboard,
    'fix_riding': fixtest.riding,
    'fix_bailboard': fixtest.bailboard,
    'fix_carry': fixtest.carry,
    'fix_chains': fixtest.chains,
    'fix_grabs': fixtest.grabs,
    'fix_devtools': fixtest.devtools,
    'fix_safety': fixtest.safety,
    'fix_landing': fixtest.landing,
    'transitions': surftest.transitions,
    'banks': surftest.banks,
    'creases': surftest.creases,
}


def main():
    want = sys.argv[1:] or list(SCENARIOS)
    results = {}
    for name in want:
        print(f"\n===== {name}")
        results[name] = SCENARIOS[name]()
    print()
    for name, good in results.items():
        print(("PASS " if good else "FAIL ") + name)
    print("ALL OK" if all(results.values()) else "FAILURES")
    sys.exit(0 if all(results.values()) else 1)


if __name__ == "__main__":
    main()
