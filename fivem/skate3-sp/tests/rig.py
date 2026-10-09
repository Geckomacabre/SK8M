"""Shared set-up for the ride tests: both resources loaded into the simulator (harness.py), with a test window into
the controller's locals.

make(...) -> Ride. Options:
  stock        skate3_assets is not running (the stock-pose fallback)
  goofy        Config.Goofy (the clips as authored; the default regular rider plays the mirrored copies)
  offset       the ped's real feet minus the baked anchors, ped space (another skeleton, like a freemode ped)
  patch        {filename: fn(source) -> source} applied while loading (negative controls)
  config       Lua run after config.lua (overrides)
  tuning       False = an asset build without Skate 3's tuning table (the numbers in config.lua are used)
"""
import glob
import math
import os

from harness import Sim, qrot

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
SKATE = os.path.join(ROOT, "skateboard")
import os as _os, sys as _sys  # noqa: E401
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "tools"))
import paths  # noqa: E402
ASSETS = os.environ.get("S3_ASSETS") or paths.work(r"fivem\skate3_assets")

# pad controls (GTA control indices): left stick 30/31, right stick 1/2
A, X, Y, RT, LT, B, RB = 21, 22, 23, 24, 25, 45, 44

ACCESS = r'''
TEST = {
  getOn = getOn, getOff = getOff, requestPop = requestPop, chooseGrind = chooseGrind, pickUp = pickUp,
  stepOff = function() return stepOff() end, putAway = function(a) return putAway(a) end,
  ramps = function() return #ramps end, lastSide = function() return lastSide end,
  -- the face under the board, the way its nose points along it, the way up it is drawn with (surface.lua)
  surf = function() return sk.u, sk.d, sk.up, sk.ah, sk.re ~= nil end,
  state = function()
    return {
      riding = riding, mode = mode, speed = speed, facing = facing, x = pos.x, y = pos.y, z = pos.z, vz = vz,
      switch = switch, switching = switching ~= nil, spin = spin, total = totalScore, lineScore = lineScore,
      line = table.concat(line, ' + '), message = lastBail or message, antic = antic, pending = pending ~= nil,
      manual = manual and manual.label or nil, grab = grab and grab.kind or nil, air = air and air.label or nil,
      grind = grind and grind.name or nil, grindLabel = grind and grind.label or nil,
      grindSide = grind and grind.side or nil, grindFacing = grind and grind.facing or nil,
      grindFakie = grind and grind.fakie or false, grindSpeed = grind and grind.speed or nil,
      board = board, mirrored = mirrored(), clip = S3.clip, upper = S3.upper, lift = S3.lift, s3 = S3.active(),
      targetAdded = targetAdded, tuned = Tune.skate3, momentum = momentum, inputT = inputT, popHigh = popHigh,
      lockOff = lock and lock.off or nil, grindDist = grind and grind.dist or nil,
      grindH = grind and grind.h or nil, rail = grind and grind.rail or nil, surface = surface, ground = ground,
      groundVz = groundVz, ggrab = ggrab and ggrab.kind or nil, coffin = coffin ~= nil,
      onefoot = onefoot and onefoot.kind or nil, dark = S3.active() and S3.dark() or false, ttl = ttl,
      gvar = grab and grab.var or nil, tweak = grab and grab.tweak or nil,
      hippy = hippy and hippy.phase or nil, hop = hippy and hippy.hop or nil, revert = revert ~= nil,
      flips = (air and air.info) and air.info.n or nil, airTricks = air and #air.tricks or 0,
      skitch = skitch ~= nil, skitchOff = skitch and skitch.off or nil, skitchHand = skitch and skitch.hand or nil,
      skitchHigh = skitch and skitch.high or false, skitchCar = skitch and skitch.veh or nil, helmet = helmet.on,
      deck = Deck.describe(), parts = Deck.parts(),
      off = off and off.state or nil, offGait = off and off.gait or nil, offHolding = off and off.holding or false,
      offSpeed = off and off.v or nil, offHeading = off and off.heading or nil,
    }
  end,
  set = function(k, v)
    if k == 'speed' then speed = v elseif k == 'facing' then facing = v elseif k == 'lastSide' then lastSide = v
    elseif k == 'pos' then pos = vector3(v[1], v[2], v[3]) elseif k == 'vz' then vz = v end
  end,
}
'''


class Ride:
    def __init__(self, sim, stock):
        self.sim, self.stock = sim, stock
        self.T = sim.run('skateboard', 'return TEST')
        self.ok = True
        self.patterns = None if stock else sim.run('skate3_assets', 'return Skate3FlickPatterns')

    # ------------------------------------------------------------ checks
    def check(self, label, cond):
        self.ok &= bool(cond)
        print(("OK  " if cond else "BAD ") + label)
        return bool(cond)

    def state(self):
        return self.T.state()

    # ------------------------------------------------------------ driving
    def frame(self, n=1, each=None):
        self.sim.frame(n, each)

    def get_on(self):
        self.sim.S.spawn('skateboard', self.T.getOn)
        self.frame(3)
        return self.state().board

    def get_off(self):
        self.sim.S.spawn('skateboard', self.T.getOff)
        self.frame(2)

    def set(self, key, value):
        if isinstance(value, (tuple, list)):
            value = self.sim.lua.table_from(list(value))
        self.T.set(key, value)

    def flick(self, coords, hold=0.3, seg=0.05, fps=60, settle=8, each=None):
        """Play a Flick-It gesture on the right stick. coords: pattern space (x right +, y DOWN +)."""
        path = [coords[0]] * int(hold * fps)
        for a, b in zip(coords, coords[1:]):
            steps = max(1, int(seg * fps))
            path += [(a[0] + (b[0] - a[0]) * i / steps, a[1] + (b[1] - a[1]) * i / steps) for i in range(1, steps + 1)]
        path += [(coords[-1][0] * k, coords[-1][1] * k) for k in (0.7, 0.4, 0.1, 0.0)]
        path += [(0.0, 0.0)] * settle
        for x, y in path:
            self.sim.stick(x, -y)
            self.frame(1, each)
        self.sim.stick(0.0, 0.0)

    def pattern(self, name, set_name='ground', which=0):
        """The stick path of one of Skate 3's gesture patterns."""
        pats = [p for p in self.patterns[set_name].values() if hasattr(p, 'name') and p.name == name]
        return [(c[1], c[2]) for c in pats[which].coords.values()]

    # ------------------------------------------------------------ geometry
    def board_up(self, board):
        return qrot(self.sim.ent(board).q, (0, 0, 1))[2]

    def board_axis(self, board):
        """The board's long axis in the world (unit vector). The stub prop is long on x, like v_res_skateboard."""
        return qrot(self.sim.ent(board).q, (1, 0, 0))

    def feet_vs_deck(self, board):
        """Distance (m) from the soles of the simulated feet to the top of the deck, as the frame was left."""
        sole = self.sim.S.feetLocal()
        if sole is None or board is None or not self.sim.S.ent[board]:
            return None
        p, b = self.sim.ent(1), self.sim.ent(board)
        f = qrot(p.q, (sole.x, sole.y, sole.z))
        feet = (p.pos.x + f[0], p.pos.y + f[1], p.pos.z + f[2])
        # deck top of the stub prop: its bounding box top minus the kick rise the player assumes (0.03)
        t = qrot(b.q, (0.0, 0.0, 0.144 - 0.03))
        deck = (b.pos.x + t[0], b.pos.y + t[1], b.pos.z + t[2])
        return math.dist(feet, deck)

    def finish(self, name):
        v = self.sim.violations()
        self.check(f"no native misuse ({len(v)})", not v)
        for line in v[:12]:
            print("      " + line)
        p = self.sim.prints()
        self.check(f"no script errors or warnings printed ({len(p)})", not p)
        for line in p[:8]:
            print("      " + line[:300])
        print(("PASS " if self.ok else "FAIL ") + name)
        return self.ok


OX_TARGET = r'''
exports('addLocalEntity', function(entity, options) SIM.targets = SIM.targets or {}; SIM.targets[entity] = options end)
exports('removeLocalEntity', function(entity, names) if SIM.targets then SIM.targets[entity] = nil end end)
'''
OX_INVENTORY = r'''
exports('RemoveItem', function(src, item, count)
  if item ~= 'money' or (SIM.money or 0) < count then return false end
  SIM.money = SIM.money - count
  SIM.paid = (SIM.paid or 0) + 1
  return true
end)
exports('RegisterShop', function(kind, details) SIM.shops = SIM.shops or {}; SIM.shops[kind] = details end)
exports('openInventory', function(kind, data) SIM.opened = { kind = kind, data = data } end)
exports('GetItemCount', function(src, item)
  if item == 'skateboard' then SIM.itemQueries = (SIM.itemQueries or 0) + 1 end -- (how often the board item was asked about)
  if item == 'skate_helmet' then return SIM.helmets or 0 end
  if item == 'money' then return SIM.money or 0 end
  return item == 'skateboard' and (SIM.items or 0) or 0
end)
'''


def make(stock=False, goofy=False, offset=(0.0, 0.0, 0.0), patch=None, config='', rail=None, inventory=None,
         target=False, tuning=True, sounds=True, decks=True, server=False):
    """inventory: number of skateboard items the player has (starts a stand-in ox_inventory and the server script);
    target: start a stand-in ox_target."""
    sim = Sim()

    # a control that patches the old behaviour back in must really change the source: one whose target line has
    # since been edited would otherwise compare the new code with itself, and "pass"
    def checked(name, fn):
        def run(src):
            out = fn(src)
            if out == src:
                raise AssertionError(f"the patch for {name} changed nothing: the source it patches has moved on")
            return out
        return run

    patch = {name: checked(name, fn) for name, fn in (patch or {}).items()}
    if target:
        sim.stand_in('ox_target', OX_TARGET)
    if inventory is not None:
        sim.S.items = inventory
        sim.server('ox_inventory', code=OX_INVENTORY)
    if inventory is not None or server:
        sim.server('skateboard_server', [os.path.join(SKATE, n) for n in ("config.lua", "server.lua", "deck_server.lua")])
    def assets():
        files = sorted(glob.glob(os.path.join(ASSETS, "tracks", "*.lua")))
        files += [os.path.join(ASSETS, n) for n in ("clip_index.lua", "flick_patterns.lua")]
        if tuning:
            files.append(os.path.join(ASSETS, "tuning.lua"))
        if sounds and os.path.exists(os.path.join(ASSETS, "sounds.lua")):
            files.append(os.path.join(ASSETS, "sounds.lua"))
        if decks and os.path.exists(os.path.join(ASSETS, "decks.lua")):
            files.append(os.path.join(ASSETS, "decks.lua"))
        files.append(os.path.join(ASSETS, "s3_player.lua"))
        sim.resource('skate3_assets', files, patch=patch)
        sim.S.tracks = sim.run('skate3_assets', 'return SkateBoardTracks')
        sim.S.clipLength = sim.run('skate3_assets', 'return ClipLength')
        sim.S.skelOffset = sim.lua.eval("vector3(%r, %r, %r)" % tuple(offset))

    # S3_ORDER=late: the controller's threads run before the clip player's each frame (the order the game runs
    # resources in is not ours to choose, so the ride has to work both ways)
    late = os.environ.get("S3_ORDER") == "late"
    if not stock and not late:
        assets()
    # (the ride's own one-line reports of bails and landings are off here: a test that wants them asks for them)
    extra = ("\nConfig.Goofy = true" if goofy else "") + "\nConfig.Log = false\nConfig.TestCommands = true\n" + config + "\n"
    user = patch.get('config.lua')
    patch['config.lua'] = lambda s: (user(s) if user else s) + extra + "\n-- test\n"
    user_client = patch.get('client.lua')
    patch['client.lua'] = lambda s: (user_client(s) if user_client else s) + ACCESS
    sim.resource('skateboard', [os.path.join(SKATE, n) for n in ("config.lua", "flick.lua", "tuning.lua", "surface.lua", "s3.lua", "dev.lua",
                                                                 "deck.lua", "client.lua", "selftest.lua", "shop.lua")],
                 patch=patch)
    if not stock and late:
        assets()
    if rail:
        sim.rail(**rail)
    # a stand-in for html/sound.js: it answers the 'config' message the way the page does, having "loaded" every
    # recording of the pack whose file exists in the built resource
    sim.S.soundFile = lambda name: os.path.exists(os.path.join(ASSETS, 'sounds', name))
    sim.lua.execute('''
      SIM.nuiPage = function(res, msg)
        if msg.t ~= 'config' or not res.nuiCallbacks.sound_ready then return end
        local loaded, total = 0, 0
        for _, s in pairs(msg.sounds or {}) do
          for _, f in ipairs(s.files or {}) do
            total = total + 1
            if SIM.soundFile(f) then loaded = loaded + 1 end
          end
        end
        res.nuiCallbacks.sound_ready({ loaded = loaded, total = total, rate = 48000, state = 'running' }, function() end)
      end
    ''')
    sim.frame(2)  # let the resources' start-up threads run
    return Ride(sim, stock)
