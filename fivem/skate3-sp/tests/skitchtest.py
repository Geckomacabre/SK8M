"""Holding on to the back of a car (skitching), helmets, and where the board is in the coffin.

usage: python skitchtest.py [skitch helmet coffinboard]     (also run as scenarios of ridetest.py)

The cars are the simulator's (harness.py Sim.vehicle): a box that drives on by itself, seen by rays that ask for
vehicles. Each check that something happens has a control beside it showing it does not happen without its cause.
"""
import math
import os
import sys

import rig
from rig import RB

HANDS_AHEAD = 0.67  # Config.SkitchHandsAhead


def behind_car(sim, car, r):
    """(metres the board is behind the car's back end, metres to the car's right of its middle)"""
    s = r.state()
    h = math.radians(car.heading)
    fx, fy = -math.sin(h), math.cos(h)
    dx, dy = s.x - car.pos.x, s.y - car.pos.y
    along, across = dx * fx + dy * fy, dx * fy - dy * fx
    return -2.3 - along, across


def start(goofy=True, car_speed=6.0, gap=1.7, speed=7.0, config='', stock=False, heading=0.0, x=0.0, **car):
    r = rig.make(goofy=goofy, config=config, stock=stock)
    sim = r.sim
    r.get_on()
    e, c = sim.vehicle(x=0.0, y=20.0, heading=heading, speed=car_speed, **car)
    r.set('pos', (x, c.pos.y - 2.3 - gap, 0.0))
    r.set('speed', speed)
    sim.played(clear=True)
    return r, sim, c


def catch(r, sim, frames=150):
    sim.hold(RB, True)
    for i in range(frames):
        r.frame()
        if r.state().skitch:
            return i + 1
    return None


def skitch():
    ok = True
    for goofy in (True, False):
        who = 'goofy' if goofy else 'regular'
        m = '' if goofy else '_mir'
        r, sim, car = start(goofy=goofy)
        n = catch(r, sim)
        r.check(f"{who}: the hold button behind a car takes hold of it ({n} frames)", n is not None)
        r.frame(150)
        s = r.state()
        back, across = behind_car(sim, car, r)
        played = sim.played(clear=True)
        r.check(f"{who}: the car takes the board along: its speed ({s.speed:.2f} of 6.00), a hand's reach behind it "
                f"({back:.2f} m of {HANDS_AHEAD}), in line ({across:.2f} m), still riding",
                s.skitch and s.riding and s.mode == 'ground' and abs(s.speed - 6.0) < 0.05
                and abs(back - HANDS_AHEAD) < 0.05 and abs(across) < 0.05)
        r.check(f"{who}: Skate 3's clips: the reach, then the two-handed hold ({played})",
                played == [f'skch_2h_into_slow_reach{m}', f'skch_2h_idle{m}'])

        # along the back of the car: stick right = to the car's right, hand over hand, one hand at the end
        sim.stick(1.0, 0.0, right=False)
        r.frame(20)
        mid_clip = r.state().clip
        r.frame(100)
        s = r.state()
        _, across = behind_car(sim, car, r)
        # as authored (goofy) the right hand is the front one; at the car's right end the LEFT hand still has it
        one = ('skch_1h_idle_backhand' if goofy else 'skch_1h_idle_fronthand') + m
        shim = f'skch_2h_shimmy_{"r" if goofy else "l"}_lo_fast{m}'
        r.check(f"{who}: the left stick moves the rider along the car ({mid_clip}), to its end ({across:.2f} m of 0.85), "
                f"where one hand holds ({s.skitchHand}, {s.clip})",
                mid_clip == shim and abs(across - 0.85) < 0.05 and s.skitchHand == 'left' and s.clip == one and s.skitch)
        sim.stick(-1.0, 0.0, right=False)
        r.frame(60)
        s = r.state()
        r.check(f"{who}: ... and back the other way with both hands ({s.clip})",
                s.skitchHand is None and s.clip == f'skch_2h_shimmy_{"l" if goofy else "r"}_lo_fast{m}')
        sim.stick(0.0, 0.0, right=False)
        r.frame(30)
        r.check(f"{who}: stick let go: the two-handed hold again ({r.state().clip})", r.state().clip == f'skch_2h_idle{m}')

        # the car turns and speeds up: the rider stays with it
        car.turn, car.speed = 25.0, 9.0
        worst = 0.0
        for _ in range(180):
            r.frame()
            back, _ = behind_car(sim, car, r)
            worst = max(worst, abs(back - HANDS_AHEAD))
        s = r.state()
        off = abs((s.facing - car.heading + 180.0) % 360.0 - 180.0)
        r.check(f"{who}: round a bend and faster: still holding, never more than {worst:.2f} m out of place, facing the "
                f"car's way to {off:.0f} degrees, at its speed ({s.speed:.2f} of 9)",
                s.skitch and worst < 0.3 and off < 12.0 and abs(s.speed - 9.0) < 0.1)
        car.turn = 0.0

        # letting go with the stick forward: the sling
        sim.stick(0.0, 1.0, right=False)
        sim.hold(RB, False)
        r.frame(2)
        s = r.state()
        r.check(f"{who}: button let go with the stick forward: off the car and 2.5 m/s faster than it ({s.speed:.2f})",
                not s.skitch and s.riding and abs(s.speed - 11.5) < 0.2)
        sim.stick(0.0, 0.0, right=False)
        sim.hold(RB, True)
        r.frame(20)
        r.check(f"{who}: the button again at once: no new hold for half a second", not r.state().skitch)
        ok &= r.finish('skitch ' + who)

    # letting go: plain, pulled back, popped
    r, sim, car = start()
    catch(r, sim)
    r.frame(60)
    sim.hold(RB, False)
    r.frame(2)
    s = r.state()
    r.check(f"button let go: rolling on at the car's speed ({s.speed:.2f} of 6)", not s.skitch and abs(s.speed - 6.0) < 0.2)
    r.frame(40)
    car.speed = 6.0
    r.set('pos', (car.pos.x, car.pos.y - 2.3 - 1.0, 0.0))
    r.set('speed', 6.0)
    catch(r, sim)
    r.frame(60)
    sim.stick(0.0, -1.0, right=False)
    sim.hold(RB, False)
    r.frame(2)
    s = r.state()
    r.check(f"let go with the stick back: 2 m/s slower than the car ({s.speed:.2f})", not s.skitch and abs(s.speed - 4.0) < 0.2)
    sim.stick(0.0, 0.0, right=False)
    r.frame(40)
    r.set('pos', (car.pos.x, car.pos.y - 2.3 - 1.0, 0.0))
    r.set('speed', 6.0)
    catch(r, sim)
    r.frame(90)
    held = r.state().skitch
    r.flick(r.pattern('Ollie'))
    left = False
    for _ in range(40):
        r.frame()
        s = r.state()
        left = left or (s.mode == 'air' and not s.skitch)
    r.check(f"an ollie while holding on: lets go and pops (held {held}, in the air off the car {left})", held and left)
    sim.hold(RB, False)
    ok &= r.finish('skitch: letting go')

    # a tap is a hold of at least half a second; a car that pulls away too fast is lost
    r, sim, car = start()
    n = catch(r, sim)
    sim.hold(RB, False)
    r.frame(10)
    early = r.state().skitch
    r.frame(40)
    r.check(f"a tap on the button: held for the half second Skate 3 gives a hold, then let go ({early}, "
            f"{r.state().skitch})", n and early and not r.state().skitch)
    ok &= r.finish('skitch: tap')

    r, sim, car = start(stock=True, gap=1.0)
    n = catch(r, sim)
    r.frame(60)
    s = r.state()
    back, _ = behind_car(sim, car, r)
    r.check(f"stock poses (no Skate 3 clips): the hold itself works the same ({s.speed:.2f} m/s, {back:.2f} m behind)",
            n and s.skitch and abs(s.speed - 6.0) < 0.05 and abs(back - HANDS_AHEAD) < 0.05)
    ok &= r.finish('skitch: stock')

    # the high hold: a car with nothing at bumper height (a flatbed: the body starts 0.7 m up)
    r, sim, car = start()
    car.bodyLo = 0.2
    n = catch(r, sim)
    r.frame(120)
    s = r.state()
    r.check(f"nothing of the car at bumper height: the high hold ({s.clip})", n and s.skitchHigh and s.clip == 'skch_2h_idle_hi')
    ok &= r.finish('skitch: high hold')

    # a car met much faster than it goes: the quick reach and the pull on the arms
    r, sim, car = start(car_speed=2.0, speed=7.0, gap=1.2)
    n = catch(r, sim)
    r.frame(90)
    played = sim.played(clear=True)
    r.check(f"closing at 5 m/s: the quick reach and the pull on the arms first ({played})",
            n and played == ['skch_2h_into_fast_reach', 'skch_2h_into_slow_absorb', 'skch_2h_idle'])
    ok &= r.finish('skitch: fast')

    # controls: none of these may take hold
    def never(label, hold=True, **kw):
        r, sim, car = start(**kw)
        if hold:
            sim.hold(RB, True)
        got = False
        for _ in range(150):
            r.frame()
            got = got or r.state().skitch
        r.check(f"control, {label}: no hold", not got)
        return r

    never("the button not held", hold=False)
    never("a motorcycle", cls=8)
    never("switched off in the config", config="Config.Skitch.enabled = false")
    never("the car coming the other way", heading=180.0)
    never("a car going away faster than the board", car_speed=9.0, speed=7.0)
    never("beside the car, not behind it", gap=-2.0, x=1.6)
    r = never("15 m/s between the car and the board", car_speed=0.0, speed=16.0, gap=1.25)
    ok &= r.finish('skitch: controls')
    return ok


def helmet():
    ok = True
    r = rig.make(goofy=True)
    sim = r.sim
    S = sim.S
    put = sim.lua.eval('function(S, d, t) S.props[0] = { d, t } end')
    prop = sim.lua.eval('function(S) local p = S.props[0]; if not p then return nil end return tostring(p[1]) .. ":" .. tostring(p[2]) end')
    put(S, 5, 1)  # a hat is on

    def use():
        sim.run('skateboard', "exports.skateboard:useHelmet()")
        r.frame(2)

    use()
    r.check(f"using the helmet puts the game's own helmet on ({prop(S)}), and a bail will not knock it off",
            prop(S) == 'game helmet:-1' and S.propsStay and r.state().helmet)
    use()
    r.check(f"using it again takes it off and the hat that was on comes back ({prop(S)})",
            prop(S) == '5:1' and not r.state().helmet and not S.propsStay)

    sim.command('skatehelmet', '12', '2')
    r.frame(3)
    r.check(f"/skatehelmet 12 2: that head prop is the helmet now, and on ({prop(S)})", prop(S) == '12:2' and r.state().helmet)
    use()
    use()
    r.check(f"off and on again: the hat, then the chosen helmet ({prop(S)})", prop(S) == '12:2')
    sim.command('skatehelmet', 'next')
    r.frame(3)
    r.check(f"/skatehelmet next: the next head prop ({prop(S)})", prop(S) == '13:0')
    sim.command('skatehelmet', '99')
    r.frame(3)
    r.check(f"/skatehelmet 99 (the character has 40): refused, nothing changes ({prop(S)})", prop(S) == '13:0')
    sim.command('skatehelmet', 'default')
    r.frame(3)
    r.check(f"/skatehelmet default: the game's own again ({prop(S)})", prop(S) == 'game helmet:-1')
    sim.command('skatehelmet')
    r.frame(3)
    r.check(f"/skatehelmet alone: off, the hat is back ({prop(S)})", prop(S) == '5:1')

    # the helmet stays on through a ride and a bail
    use()
    r.get_on()
    r.frame(10)
    sim.run('skateboard', "CreateThread(function() TEST.getOff('test bail') end)")
    r.frame(5)
    r.check(f"a bail with the helmet on: still on ({prop(S)})", prop(S) == 'game helmet:-1' and 'ragdoll' in sim.log())
    ok &= r.finish('helmet')

    # with ox_inventory: the command needs the item
    r = rig.make(goofy=True, inventory=1)
    sim, S = r.sim, r.sim.S
    prop = sim.lua.eval('function(S) local p = S.props[0]; if not p then return nil end return tostring(p[1]) .. ":" .. tostring(p[2]) end')
    sim.command('skatehelmet')
    r.frame(60)
    r.check(f"ox_inventory running, no helmet item: /skatehelmet does nothing ({prop(S)})", prop(S) is None)
    S.helmets = 1
    sim.command('skatehelmet')
    r.frame(60)
    r.check(f"... with the item: on ({prop(S)})", prop(S) == 'game helmet:-1')
    ok &= r.finish('helmet: item')

    r = rig.make(goofy=True, config="Config.Helmet.enabled = false")
    sim, S = r.sim, r.sim.S
    sim.run('skateboard', "exports.skateboard:useHelmet()")
    sim.command('skatehelmet')
    r.frame(5)
    r.check("control, helmets switched off in the config: nothing goes on", S.props[0] is None)
    ok &= r.finish('helmet: off')
    return ok


def coffinboard():
    """In the coffin the rider lies on the board. The deck used to be kept under the feet, which in the coffin are a
    metre out past the end of the board: seen in the game as the board under the boots and the body on the road."""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools'))
    import s3_to_ycd as Y
    r = rig.make(goofy=True)
    sim = r.sim
    tracks = sim.S.tracks

    def anchor(clip, frame):
        t = tracks['skate3@gr/' + clip]
        f = t.frames[len(t.frames) if frame < 0 else frame + 1]
        return f[5], f[6], f[7]

    grab = anchor('gr_ground_n_dbl_0_cyc', 0)
    start = anchor('gr_ground_n_coffin_0_into', 0)
    cyc = anchor('gr_ground_n_coffin_0_cyc', 0)
    r.check(f"lying down, the deck stays where it was along the board when the rider crouched on it "
            f"(crouched {grab[1]:.2f}, start of lying back {start[1]:.2f}, lying {cyc[1]:.2f})",
            abs(cyc[1] - start[1]) < 0.02 and abs(start[1] - grab[1]) < 0.12)
    # the control: where the feet are in that clip, which is where the deck used to be put
    rt = Y.Retargeter(Y.Rig(), Y.S.load_clip(os.path.join(Y.CSV_DIR, "RIG_TPOSE.csv"))[0])
    fr = rt.frame(Y.S.load_clip(os.path.join(Y.CSV_DIR, "GR_GROUND_N_COFFIN_0_CYC.csv"))[0])
    feet = Y.anchors('R_IDLE', [fr[3]], Y.riding_stance(rt))[0]
    r.check(f"control: the feet in that clip are {feet[1]:.2f} m further along (a deck under them has nobody on it)",
            feet[1] - cyc[1] > 0.8)
    for clip in ('gr_ground_n_coffin_left_cyc', 'gr_ground_n_coffin_right_cyc', 'gr_ground_n_coffin_0_cyc_mir'):
        d = 'skate3@mirror/' if clip.endswith('_mir') else 'skate3@gr/'
        y = tracks[d + clip].frames[1][6]
        r.check(f"{clip}: the same ({y:.2f})", abs(y - cyc[1]) < 0.02)

    # in the ride: the rider's middle is over the board
    from rig import A, LT, RT, X
    board = r.get_on()
    r.set('speed', 5.0)
    for c in (LT, RT):
        sim.hold(c, True)
    r.frame(40)
    for c in (A, X):
        sim.hold(c, True)
    r.frame(90)
    s = r.state()
    ped, b = sim.ent(1), sim.ent(board)
    h = math.radians(s.facing)
    along = (ped.pos.x - b.pos.x) * -math.sin(h) + (ped.pos.y - b.pos.y) * math.cos(h)
    r.check(f"riding in the coffin ({s.coffin}): the rider's middle is {abs(along):.2f} m from the middle of the board "
            f"along it (it was about a metre)", s.coffin and abs(along) < 0.2)
    return r.finish('coffinboard')


def shop():
    """The skate shop: placed by an admin's command on the server, shown by the client, selling through ox_inventory."""
    ok = True
    r = rig.make(goofy=True, inventory=1, target=True)
    sim, S = r.sim, r.sim.S
    cmd = sim.lua.eval('function(S, ...) S.serverCommands.skateshop(1, { ... }) end')
    count = sim.lua.eval('function(t) local n = 0; for _ in pairs(t or {}) do n = n + 1 end; return n end')
    npcs = sim.lua.eval('function(S) local out = {}; for e, v in pairs(S.ent) do if v.npc then out[#out + 1] = e end end; return out end')
    option = sim.lua.eval("""function(S, ped, name)
        for _, o in ipairs(S.targets and S.targets[ped] or {}) do
          if o.name == name then return o end
        end
      end""")
    r.frame(40)
    r.check(f"before any shop is placed: no shopkeeper, no blip, ox_inventory knows the shop with no place "
            f"({count(S.shops.skateshop.locations)})",
            len(list(npcs(S).values())) == 0 and count(S.blips) == 0 and count(S.shops.skateshop.locations) == 0)
    # the command is an admin's, by the server's own say (not by the ace command.skateshop, which a server that
    # gives its admins their commands one by one does not hand out: on the user's server nobody could place a shop)
    cmd(S, 'place')
    r.frame(60)
    r.check("an ordinary player's /skateshop place: nothing (no shopkeeper, nothing stored)",
            len(list(npcs(S).values())) == 0 and S.serverKvp.skateshops is None)
    S.aces = sim.lua.table_from({'group.admin': True})
    r.check("... and the command is not one the server has to hand out by name", S.serverRestricted.skateshop is False)

    cmd(S, 'place')
    r.frame(60)
    keepers = list(npcs(S).values())
    reg = S.shops.skateshop
    r.check(f"/skateshop place: a shopkeeper stands there ({len(keepers)}), a blip is on the map ({count(S.blips)}), "
            f"ox_inventory has the place and the goods ({count(reg.locations)} place, {count(reg.inventory)} items), "
            f"and the server has stored it", len(keepers) == 1 and count(S.blips) == 1 and count(reg.locations) == 1
            and count(reg.targets) == 1 and reg.inventory[1].name == 'skateboard' and reg.inventory[2].name == 'skate_helmet'
            and S.serverKvp.skateshops is not None)
    ped = keepers[0]
    e = sim.ent(ped)
    r.check(f"the shopkeeper stands on the ground where the admin stood, frozen and unharmable ({e.pos.z:.1f}, {e.scenario})",
            abs(e.pos.z - 0.0) < 0.01 and e.frozen and e.invincible and e.scenario == 'WORLD_HUMAN_STAND_IMPATIENT')
    buy = option(S, ped, 'skateshop_buy')
    buy.onSelect()
    r.check(f"its ox_target option opens ox_inventory's shop window on this shop ({S.opened and S.opened.data.type}, "
            f"{S.opened and S.opened.data.id})", S.opened is not None and S.opened.kind == 'shop'
            and S.opened.data.type == 'skateshop' and S.opened.data.id == 1)
    S.helmets = 1
    option(S, ped, 'skateshop_next').onSelect()
    r.frame(60)
    r.check(f"'Try the next helmet' puts the next head prop on ({S.props[0] and S.props[0][1]})",
            S.props[0] is not None and S.props[0][1] == 0)

    cmd(S, 'remove')
    r.frame(60)
    r.check(f"/skateshop remove: shopkeeper and blip are gone, ox_inventory has no place left "
            f"({len(list(npcs(S).values()))}, {count(S.blips)}, {count(S.shops.skateshop.locations)})",
            len(list(npcs(S).values())) == 0 and count(S.blips) == 0 and count(S.shops.skateshop.locations) == 0)
    ok &= r.finish('shop')

    # without ox_target: stand by the shopkeeper and press E
    r = rig.make(goofy=True, inventory=1)
    sim, S = r.sim, r.sim.S
    S.aces = sim.lua.table_from({'group.admin': True})
    r.frame(40)
    sim.lua.eval('function(S) S.serverCommands.skateshop(1, { "place" }) end')(S)
    r.frame(60)
    sim.press(51)
    r.frame(2)
    opened = S.opened is not None
    r.check(f"no ox_target: E beside the shopkeeper opens the shop ({opened})", opened)
    ok &= r.finish('shop: no ox_target')

    r = rig.make(goofy=True, inventory=1, target=True, config="Config.Shop.enabled = false")
    sim, S = r.sim, r.sim.S
    S.aces = sim.lua.table_from({'group.admin': True})
    r.frame(40)
    sim.lua.eval('function(S) S.serverCommands.skateshop(1, { "place" }) end')(S)
    r.frame(60)
    r.check("control, shops switched off for this player: nothing is shown", sim.lua.eval(
        'function(S) for _, v in pairs(S.ent) do if v.npc then return false end end return next(S.blips) == nil end')(S))
    ok &= r.finish('shop: off')
    return ok


SCENARIOS = {'skitch': skitch, 'helmet': helmet, 'coffinboard': coffinboard, 'shop': shop}

if __name__ == "__main__":
    results = {}
    for name in sys.argv[1:] or list(SCENARIOS):
        print(f"\n===== {name}")
        results[name] = SCENARIOS[name]()
    print()
    for name, good in results.items():
        print(("PASS " if good else "FAIL ") + name)
    sys.exit(0 if all(results.values()) else 1)
