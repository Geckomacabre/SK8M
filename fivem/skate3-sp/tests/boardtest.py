"""Skate 3's own board in the ride: the deck object with its trucks and wheels, choosing parts, the server's say.

usage: python boardtest.py        (also the scenario "board" of ridetest.py)
"""
import sys

import rig
from harness import joaat


def signed(h):
    return h - (1 << 32) if h >= (1 << 31) else h


def model_of(sim, e):
    return sim.ent(e).model if sim.S.ent[e] else None


def board():
    ok = True
    r = rig.make(goofy=True, server=True)
    sim, S = r.sim, r.sim.S
    lua = sim.lua
    D = sim.run('skate3_assets', 'return Skate3Decks')
    r.check("the built assets carry Skate 3's board (%d decks, %d trucks, %d wheels)" % (
        len(list(D.stock.values())), len(list(D.trucks.values())), len(list(D.wheels.values()))), D is not None)
    r.frame(5)
    b = r.get_on()
    s = r.state()
    parts = list(s.parts.values())
    want = lambda kind, pid: signed(joaat('s3_%s_%s' % (kind, pid)))
    r.check("getting on makes the default Skate 3 board: the deck is the board (%s), with two objects on it" % s.deck.deck,
            s.deck.deck == D.default.deck and model_of(sim, b) == want('deck', D.default.deck) and len(parts) == 2)
    tm = sorted(model_of(sim, e) for e in parts)
    r.check("... the default trucks and wheels, attached to the deck with no offset and no collision of their own",
            tm == sorted([want('truck', D.default.truck), want('wheel', D.default.wheel)])
            and all(sim.ent(e).attached and sim.ent(e).attached.to == b and sim.ent(e).attached.pos.x == 0.0
                    and sim.ent(e).collision is False for e in parts))
    r.set('speed', 5.0)
    r.frame(60)
    r.check("riding: the parts are still the board's (%d)" % len(list(r.state().parts.values())),
            all(S.ent[e] is not None and sim.ent(e).attached.to == b for e in parts))

    # choosing another deck while riding: the server stores it, the board under the feet stays until the next mount
    other = D.stock[5].id
    sim.command('skatedeck', other)
    r.frame(5)
    s = r.state()
    r.check("/skatedeck %s while riding: it is my deck now (%s), the board under me is still the old one" % (other, s.deck.deck),
            s.deck.deck == other and model_of(sim, b) == want('deck', D.default.deck) and s.board == b)
    r.get_off()
    r.frame(5)
    r.check("stepped off: board, trucks and wheels are all still there",
            S.ent[b] is not None and all(S.ent[e] is not None for e in parts))
    # ... and on the ground a change rebuilds it at once
    truck = D.trucks[3].id
    sim.command('skatetruck', truck)
    r.frame(8)
    s = r.state()
    nb, nparts = s.board, list(s.parts.values())
    r.check("/skatetruck %s with the board on the ground: the board is built again there, with my deck and those trucks" % truck,
            nb is not None and nb != b and S.ent[b] is None and all(S.ent[e] is None for e in parts)
            and model_of(sim, nb) == want('deck', other) and want('truck', truck) in [model_of(sim, e) for e in nparts])
    sim.command('skatewheel', 'next')
    r.frame(8)
    s = r.state()
    r.check("/skatewheel next: the next wheels in Skate 3's list (%s)" % s.deck.wheel,
            s.deck.wheel != D.default.wheel and s.deck.wheel in [w.id for w in D.wheels.values()])
    before = dict(deck=s.deck.deck, truck=s.deck.truck, wheel=s.deck.wheel)
    sim.command('skatedeck', 'no_such_deck')
    r.frame(8)
    s = r.state()
    r.check("control, a deck that does not exist: nothing changes", s.deck.deck == before['deck'])
    # what the server has stored is what a fresh client is told
    stored = S.serverKvp['deck:license:test1']
    r.check("the server has stored the board under the player's licence", stored is not None)
    # picking the board up takes everything away
    sim.S.spawn('skateboard', r.T.pickUp)
    r.frame(60)
    s = r.state()
    r.check("picked up: no board and no stray trucks or wheels left in the world",
            s.board is None and len(list(s.parts.values())) == 0 and not any(
                getattr(v, 'model', None) in (want('truck', truck),) for v in S.ent.values()))
    ok &= r.finish('board')

    # a client cannot talk the server into anything
    r = rig.make(goofy=True, server=True)
    sim, S = r.sim, r.sim.S
    r.frame(5)
    send = sim.lua.eval('function(S, ...) S.toServer("skateboard:deckPick", ...) end')
    env = S.serverHandlers['skateboard:deckPick'].env
    send(S, 'deck', 123)
    send(S, 'hat', 'x')
    send(S, 'deck', 'x' * 200)
    send(S, None, None)
    r.frame(3)
    r.check("nonsense from a client (a number for an id, a kind that does not exist, a 200-letter id, nothing): ignored, "
            "no error, the board is the default (%s)" % r.state().deck.deck, r.state().deck.deck == D.default.deck)
    ok &= r.finish('board: nonsense')

    # parts that cost money (Config.Decks.free = false with ox_inventory): owned or paid for, once
    r = rig.make(goofy=True, inventory=1)
    sim, S = r.sim, r.sim.S
    env = S.serverHandlers['skateboard:deckPick'].env
    env.Config.Decks.free = False
    r.frame(5)
    send = sim.lua.eval('function(S, ...) S.toServer("skateboard:deckPick", ...) end')
    pick = D.stock[7]
    S.money = 500
    sim.command('skatedeck', pick.id)
    r.frame(5)
    r.check("parts cost money: the command does not buy (%s stays, money %d)" % (r.state().deck.deck, S.money),
            r.state().deck.deck == D.default.deck and S.money == 500)
    send(S, 'deck', pick.id, True)
    r.frame(5)
    r.check("bought at the shop: Skate 3's own price is taken (%d left of 500, price %d) and the deck is mine" % (S.money, pick.price),
            r.state().deck.deck == pick.id and S.money == 500 - pick.price and pick.price > 0)
    send(S, 'deck', D.default.deck, True)
    send(S, 'deck', pick.id, True)
    r.frame(5)
    r.check("back to the default and to the bought one again: not charged twice (%d)" % S.money,
            r.state().deck.deck == pick.id and S.money == 500 - pick.price)
    S.money = 3
    poor = D.stock[9]
    send(S, 'deck', poor.id, True)
    r.frame(5)
    r.check("too little money: refused, nothing taken, the deck stays (%s, %d)" % (r.state().deck.deck, S.money),
            r.state().deck.deck == pick.id and S.money == 3)
    ok &= r.finish('board: money')

    # control: assets without Skate 3's board, and no assets at all: GTA's prop, no parts
    for label, kw in (("assets built without the board", dict(decks=False, server=True)), ("no skate3_assets", dict(stock=True, server=True))):
        r = rig.make(goofy=True, **kw)
        sim = r.sim
        r.frame(5)
        b = r.get_on()
        s = r.state()
        r.check("control, %s: GTA's board, nothing attached, and the commands say so without an error" % label,
                model_of(sim, b) == signed(joaat('v_res_skateboard')) and len(list(s.parts.values())) == 0)
        sim.command('skatedeck', 'next')
        r.frame(3)
        ok &= r.finish('board: ' + label)
    return ok


def shoppage():
    """The Lua side of the skate shop's board page: opening it at the shopkeeper, buying through it, closing it."""
    ok = True
    r = rig.make(goofy=True, inventory=1, target=True)
    sim, S = r.sim, r.sim.S
    env = S.serverHandlers['skateboard:deckPick'].env
    D = sim.run('skate3_assets', 'return Skate3Decks')
    call = sim.lua.eval("""function(S, name, data)
        local out = {}
        S.resources.skateboard.nuiCallbacks[name](data, function(r) out.r = r end)
        return out
      end""")
    last = sim.lua.eval("function(S, t) for i = #S.nui, 1, -1 do if S.nui[i].t == t then return S.nui[i] end end end")
    option = sim.lua.eval("""function(S, name)
        for ped, list in pairs(S.targets or {}) do
          for _, o in ipairs(list) do if o.name == name then return o end end
        end
      end""")
    r.frame(40)
    sim.command('skatedeck')
    r.frame(5)
    r.check("control, /skatedeck away from any shop: the page stays shut", last(S, 'designer') is None and not S.nuiFocus)
    S.aces = sim.lua.table_from({'group.admin': True})
    sim.lua.eval('function(S) S.serverCommands.skateshop(1, { "place" }) end')(S)
    r.frame(60)
    S.money = 500
    o = option(S, 'skateshop_board')
    r.check("the shopkeeper offers the board page", o is not None and o.canInteract())
    o.onSelect()
    r.frame(5)
    m = last(S, 'designer')
    st = last(S, 'designer_state')
    r.check("choosing it opens the page with the mouse, tells it where Skate 3's pictures are, and sends what I own "
            "and my money (%s)" % (st and st.state.money),
            m is not None and m.open and S.nuiFocus is True and m.assets == 'https://cfx-nui-skate3_assets/'
            and m.resource == 'skateboard' and st is not None and st.state.money == 500
            and st.state.design.deck == D.default.deck)
    pick = D.stock[4]
    out = call(S, 'designer_pick', sim.lua.table_from({'kind': 'deck', 'id': pick.id}))
    r.frame(5)
    a = out.r
    r.check("a deck picked in the page: bought for Skate 3's price and on my board; the page is answered with the new "
            "state (ok %s, money %s, deck %s)" % (a and a.ok, a and a.state.money, a and a.state.design.deck),
            a is not None and a.ok and a.state.money == 500 - pick.price and a.state.design.deck == pick.id
            and S.money == 500 - pick.price and r.state().deck.deck == pick.id)
    truck = D.trucks[5]
    out = call(S, 'designer_pick', sim.lua.table_from({'kind': 'truck', 'id': truck.id}))
    r.frame(5)
    r.check("trucks the same way (%s)" % (out.r and out.r.state.design.truck), out.r is not None and out.r.ok
            and out.r.state.design.truck == truck.id and r.state().deck.truck == truck.id)
    S.money = 3
    other = D.stock[11]
    out = call(S, 'designer_pick', sim.lua.table_from({'kind': 'deck', 'id': other.id}))
    r.frame(5)
    a = out.r
    r.check("not enough money: the page is told so (code %s), nothing is taken, the deck stays" % (a and a.code),
            a is not None and not a.ok and a.code == 'funds' and S.money == 3 and a.state.design.deck == pick.id)
    out = call(S, 'designer_pick', sim.lua.table_from({'kind': 5}))
    r.frame(2)
    r.check("nonsense from the page is answered, not obeyed (%s)" % (out.r and out.r.code),
            out.r is not None and not out.r.ok and out.r.code == 'unknown')
    # the server never answers: the page still gets an answer
    handler = S.serverHandlers['skateboard:deckPick']
    S.serverHandlers['skateboard:deckPick'] = None
    out = call(S, 'designer_pick', sim.lua.table_from({'kind': 'deck', 'id': other.id}))
    r.frame(60)
    early = out.r
    r.frame(280)
    r.check("a server that never answers: the page is answered after 5 s (%s)" % (out.r and out.r.code),
            early is None and out.r is not None and not out.r.ok and out.r.code == 'timeout')
    S.serverHandlers['skateboard:deckPick'] = handler
    out = call(S, 'designer_close', sim.lua.table_from({}))
    r.frame(3)
    m = last(S, 'designer')
    r.check("closing gives the mouse back to the game and takes the page down", S.nuiFocus is False and m.open is False)
    sim.command('skatedeck')
    r.frame(5)
    r.check("/skatedeck at the shop opens it too", last(S, 'designer').open is True and S.nuiFocus is True)
    ok &= r.finish('shoppage')
    return ok


SCENARIOS = {'board': board, 'shoppage': shoppage}

if __name__ == "__main__":
    good = board()
    good &= shoppage()
    print("PASS" if good else "FAIL")
    sys.exit(0 if good else 1)
