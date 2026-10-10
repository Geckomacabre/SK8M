// Skate 3's own engine, run by the server.
//
// The engine is the Rust rewrite of Skate 3's skating that SK8V runs, built as WebAssembly (fivem/engine in the
// repository) and put into skate3_assets/engine with the data of the server owner's own disc. FiveM's in-game
// browser has WebAssembly switched off, so the engine cannot run on the player's side: it runs here, one rider a
// player, 60 ticks a second. A player's game sends its pad (engine.lua) and the ground round its board; this sends
// back where the board is. The game's data never leaves the server.
//
// One instance carries every rider. Making a rider takes about ten seconds of the server's time (the engine builds
// its whole animation and physics state for each), so riders are made when the resource starts and used again and
// again: `set skateboard_engine_riders 2` in server.cfg makes two (the default is one; each adds ten seconds to
// the start and is one player who can ride on the engine at a time; the others get the resource's own ride).
const fs = require('fs');
const path = require('path');
const zlib = require('zlib');
const { TextDecoder, TextEncoder } = require('util');

const FLAT = 2000;                     // metres each way: the flat floor a rider is on until their ground comes
const POSE_FLOATS = 16 + 3 + 13;       // what is sent back: the board's matrix, its velocity, the camera

const now = () => (typeof performance !== 'undefined' ? performance.now() : Date.now());
// What happens is said on the server's console and kept in engine_status.txt in this resource's folder, for
// looking into a report without the console at hand.
let problem = 'the resource has not started yet';      // why there is no engine ('' when there is one)
function say(text) {
  console.log('[skateboard] engine: ' + text);
  try {
    fs.appendFileSync(path.join(GetResourcePath(GetCurrentResourceName()), 'engine_status.txt'),
      new Date().toISOString() + '  ' + text + '\n');
  } catch (error) { /* a folder that cannot be written to: the console has it */ }
}

// ------------------------------------------------------------------ the engine's data folder, as the system calls
// it makes (WASI): it reads files and prints, nothing is ever written. Paths are matched without regard to case.
function makeWasi(folder, log) {
  const OK = 0, EBADF = 8, EINVAL = 28, ENOENT = 44, ENOTDIR = 54, DIR = 3, FILE = 4, CHARACTER = 2;
  const files = new Map(), dirs = new Set();
  (function walk(dir, rel) {
    for (const name of fs.readdirSync(dir)) {
      const full = path.join(dir, name), at = (rel ? rel + '/' : '') + name.toLowerCase();
      if (fs.statSync(full).isDirectory()) { dirs.add(at); walk(full, at); } else files.set(at, full);
    }
  })(folder, '');
  // (a file the engine only asks about: the skater model, which a host that draws the rider itself never opens)
  if (!files.has('private/skater.glb')) files.set('private/skater.glb', null);
  const size = (at) => (files.get(at) ? fs.statSync(files.get(at)).size : 0);
  const stat = (at) => (at === '' || dirs.has(at) ? { dir: true } : files.has(at) ? { size: size(at) } : null);

  let memory = null;
  const view = () => new DataView(memory.buffer), bytes = () => new Uint8Array(memory.buffer);
  const decoder = new TextDecoder(), root = new TextEncoder().encode('/assets');
  const fds = new Map([[3, { dir: true, path: '' }]]);
  let next = 4;
  const lines = { 1: '', 2: '' }, started = now();
  function resolve(fd, ptr, len) {
    const dir = fds.get(fd);
    if (!dir || !dir.dir) return null;
    const parts = [];
    for (const part of (dir.path + '/' + decoder.decode(bytes().subarray(ptr, ptr + len))).split('/')) {
      if (part === '' || part === '.') continue;
      if (part === '..') parts.pop(); else parts.push(part);
    }
    return parts.join('/').toLowerCase();
  }
  function writeStat(out, s) {
    const v = view();
    for (let i = 0; i < 64; i += 8) v.setBigUint64(out + i, 0n, true);
    v.setUint8(out + 16, s.dir ? DIR : FILE);
    v.setBigUint64(out + 24, 1n, true);
    v.setBigUint64(out + 32, BigInt(s.dir ? 0 : s.size), true);
  }
  const wasi = {
    random_get(ptr, len) {
      const target = bytes().subarray(ptr, ptr + len);
      for (let i = 0; i < len; i++) target[i] = (Math.random() * 256) | 0;
      return OK;
    },
    environ_sizes_get(count, total) { view().setUint32(count, 0, true); view().setUint32(total, 0, true); return OK; },
    environ_get() { return OK; },
    clock_time_get(id, precision, out) {
      view().setBigUint64(out, BigInt(Math.round((now() - started) * 1e6)), true);
      return OK;
    },
    fd_close(fd) { return fd >= 4 && fds.delete(fd) ? OK : EBADF; },
    fd_fdstat_get(fd, out) {
      const entry = fd < 3 ? { console: true } : fds.get(fd);
      if (!entry) return EBADF;
      const v = view();
      v.setUint8(out, entry.console ? CHARACTER : entry.dir ? DIR : FILE);
      v.setUint16(out + 2, 0, true);
      v.setBigUint64(out + 8, 0xffffffffffffffffn, true);
      v.setBigUint64(out + 16, 0xffffffffffffffffn, true);
      return OK;
    },
    fd_filestat_get(fd, out) {
      const entry = fds.get(fd);
      if (!entry) return EBADF;
      writeStat(out, entry.dir ? { dir: true } : { size: entry.data.length });
      return OK;
    },
    fd_prestat_get(fd, out) {
      if (fd !== 3) return EBADF;
      view().setUint8(out, 0);
      view().setUint32(out + 4, root.length, true);
      return OK;
    },
    fd_prestat_dir_name(fd, ptr, len) {
      if (fd !== 3) return EBADF;
      bytes().set(root.subarray(0, len), ptr);
      return OK;
    },
    fd_read(fd, iovs, count, readOut) {
      const entry = fds.get(fd);
      if (!entry || entry.dir) return EBADF;
      let total = 0;
      for (let i = 0; i < count; i++) {
        const ptr = view().getUint32(iovs + i * 8, true), len = view().getUint32(iovs + i * 8 + 4, true);
        const n = Math.min(len, entry.data.length - entry.at);
        bytes().set(entry.data.subarray(entry.at, entry.at + n), ptr);
        entry.at += n;
        total += n;
        if (n < len) break;
      }
      view().setUint32(readOut, total, true);
      return OK;
    },
    fd_write(fd, iovs, count, writtenOut) {
      let total = 0, text = '';
      for (let i = 0; i < count; i++) {
        const ptr = view().getUint32(iovs + i * 8, true), len = view().getUint32(iovs + i * 8 + 4, true);
        text += decoder.decode(bytes().slice(ptr, ptr + len));
        total += len;
      }
      if (fd === 1 || fd === 2) {
        const parts = (lines[fd] + text).split('\n');
        lines[fd] = parts.pop();
        for (const line of parts) log(line);
      }
      view().setUint32(writtenOut, total, true);
      return OK;
    },
    path_filestat_get(fd, flags, ptr, len, out) {
      const at = resolve(fd, ptr, len);
      if (at === null) return ENOTDIR;
      const s = stat(at);
      if (!s) return ENOENT;
      writeStat(out, s);
      return OK;
    },
    path_open(fd, dirflags, ptr, len, oflags, rightsBase, rightsInheriting, fdflags, fdOut) {
      const at = resolve(fd, ptr, len);
      if (at === null) return ENOTDIR;
      if (oflags & (1 | 4 | 8)) return EINVAL;          // create, exclusive, truncate: nothing is written here
      const s = stat(at);
      if (!s) return ENOENT;
      if ((oflags & 2) && !s.dir) return ENOTDIR;
      if (s.dir) fds.set(next, { dir: true, path: at });
      else fds.set(next, { data: files.get(at) ? new Uint8Array(fs.readFileSync(files.get(at))) : new Uint8Array(0), at: 0 });
      view().setUint32(fdOut, next++, true);
      return OK;
    },
    proc_exit(code) { throw new Error('the engine stopped with code ' + code); },
  };
  return { imports: { wasi_snapshot_preview1: wasi }, bind(instance) { memory = instance.exports.memory; } };
}

// ------------------------------------------------------------------ the ground a player's game found: heights on
// a square grid (n x n samples `cell` metres apart, the first at x0, z0, y up) -> triangles, two a cell, facing up.
// A cell with a corner that has no ground under it is left out.
function gridTriangles(n, cell, x0, z0, h) {
  const out = new Float32Array((n - 1) * (n - 1) * 18);
  let at = 0;
  for (let j = 0; j < n - 1; j++) {
    for (let i = 0; i < n - 1; i++) {
      const a = h[j * n + i], b = h[j * n + i + 1], c = h[(j + 1) * n + i], d = h[(j + 1) * n + i + 1];
      if (a !== a || b !== b || c !== c || d !== d) continue;
      const x = x0 + i * cell, z = z0 + j * cell, X = x + cell, Z = z + cell;
      out.set([x, a, z, x, c, Z, X, b, z, X, b, z, x, c, Z, X, d, Z], at);
      at += 18;
    }
  }
  return at === out.length ? out : out.slice(0, at);
}

// ------------------------------------------------------------------ the baked map (world.sk8w, made once from
// the server owner's GTA V by fivem/engine/tools/bake_collision.py): GTA's own collision triangles with the grind
// rails already found in them, in 64 m tiles. The file's layout is at the top of fivem/engine/bake/src/main.rs.
// With it a rider is on the map itself: kerbs are kerbs, and ledges and handrails can be ground. Without it, or
// where a player's game says the ground is not where the file has it (a map the server adds, a place only Online
// changes), the ground is what the player's game finds with rays.
// A new piece costs the engine 10 to 20 ms for every thousand triangles (it welds corners and finds every edge's
// neighbour), and this thread does nothing else meanwhile, so the piece is kept small: 50 to 100 ms in a town.
const AREA = 28;          // metres each way round its middle: the piece of the map a rider has
const AREA_EDGE = 14;     // a rider this near the piece's edge gets a new piece
const AREA_LEAD = 1.25;   // seconds of the board's speed the new piece's middle is ahead of it (10 m at most)
const AREA_BELOW = 25, AREA_ABOVE = 35;   // of the rider's height: what is under and over that is left out
const TILES_KEPT = 16;    // unpacked tiles kept in memory (a tile of a dense block is a few megabytes)
let world = null;         // { fd, size, tiles: 'tx,ty' -> { at, packed, count }, kept: 'tx,ty' -> tile }

function worldFile() {
  return GetConvar('skateboard_engine_world', '') || path.join(assetsFolder(), 'world.sk8w');
}

function openWorld() {
  const file = worldFile();
  if (!fs.existsSync(file)) return say('no baked map (' + file + '): the ground is what each player\'s game finds with rays');
  const fd = fs.openSync(file, 'r'), head = Buffer.alloc(16);
  fs.readSync(fd, head, 0, 16, 0);
  if (head.toString('latin1', 0, 4) !== 'SK8W' || head.readUInt32LE(4) !== 1) {
    fs.closeSync(fd);
    return say('the baked map ' + file + ' is not a version 1 world.sk8w: not used');
  }
  const count = head.readUInt32LE(12), table = Buffer.alloc(count * 28), tiles = new Map();
  fs.readSync(fd, table, 0, table.length, 16);
  for (let i = 0; i < count; i++) {
    const o = i * 28;
    tiles.set(table.readInt32LE(o) + ',' + table.readInt32LE(o + 4),
      { at: Number(table.readBigUInt64LE(o + 8)), packed: table.readUInt32LE(o + 16), count: table.readUInt32LE(o + 24) });
  }
  world = { fd, size: head.readFloatLE(8), tiles, kept: new Map() };
  say('baked map: ' + count + ' tiles of ' + world.size + ' m (' + file + ')');
}

// One tile unpacked: its triangles as floats (ten to a triangle: nine and the tag's place), the tags, the rails.
function tileOf(key) {
  const kept = world.kept.get(key);
  if (kept) {
    world.kept.delete(key);
    world.kept.set(key, kept);              // (the one used last is dropped last)
    return kept;
  }
  const entry = world.tiles.get(key);
  if (!entry) return null;
  const packed = Buffer.alloc(entry.packed);
  fs.readSync(world.fd, packed, 0, entry.packed, entry.at);
  const raw = zlib.inflateSync(packed);
  const data = raw.buffer.slice(raw.byteOffset, raw.byteOffset + raw.length);
  const bytes = entry.count * 40, view = new DataView(data), rails = [];
  for (let at = bytes; at + 8 <= raw.length;) {
    const id = view.getUint32(at, true), n = view.getUint32(at + 4, true);
    rails.push({ id, points: new Float32Array(data.slice(at + 8, at + 8 + n * 12)) });
    at += 8 + n * 12;
  }
  const tile = { count: entry.count, f: new Float32Array(data, 0, entry.count * 10), tags: new Uint32Array(data, 0, entry.count * 10), rails };
  world.kept.set(key, tile);
  if (world.kept.size > TILES_KEPT) world.kept.delete(world.kept.keys().next().value);
  return tile;
}

// The piece of the baked map round x, y, z (GTA's world): triangles and rails measured from `origin`, in GTA's
// axes. A triangle is in every tile its box overlaps: it is taken from the first of the tiles looked at.
function pieceAround(x, y, z, origin) {
  const s = world.size, x0 = x - AREA, x1 = x + AREA, y0 = y - AREA, y1 = y + AREA, z0 = z - AREA_BELOW, z1 = z + AREA_ABOVE;
  const tx0 = Math.floor(x0 / s), tx1 = Math.floor(x1 / s), ty0 = Math.floor(y0 / s), ty1 = Math.floor(y1 / s);
  const [ox, oy, oz] = origin, tris = [], tags = [], rails = [], seen = new Set();
  for (let tx = tx0; tx <= tx1; tx++) {
    for (let ty = ty0; ty <= ty1; ty++) {
      const tile = tileOf(tx + ',' + ty);
      if (!tile) continue;
      const f = tile.f;
      for (let i = 0, o = 0; i < tile.count; i++, o += 10) {
        const ax = f[o], ay = f[o + 1], az = f[o + 2], bx = f[o + 3], by = f[o + 4], bz = f[o + 5], cx = f[o + 6], cy = f[o + 7], cz = f[o + 8];
        const minx = Math.min(ax, bx, cx), miny = Math.min(ay, by, cy);
        if (minx > x1 || miny > y1 || Math.max(ax, bx, cx) < x0 || Math.max(ay, by, cy) < y0 ||
            Math.min(az, bz, cz) > z1 || Math.max(az, bz, cz) < z0) continue;
        if (Math.max(Math.floor(minx / s), tx0) !== tx || Math.max(Math.floor(miny / s), ty0) !== ty) continue;
        tris.push(ax - ox, ay - oy, az - oz, bx - ox, by - oy, bz - oz, cx - ox, cy - oy, cz - oz);
        tags.push(tile.tags[o + 9]);
      }
      for (const rail of tile.rails) {
        if (seen.has(rail.id)) continue;
        seen.add(rail.id);
        const p = rail.points;
        let near = false;
        for (let i = 0; i < p.length && !near; i += 3) near = p[i] >= x0 && p[i] <= x1 && p[i + 1] >= y0 && p[i + 1] <= y1 && p[i + 2] >= z0 && p[i + 2] <= z1;
        if (!near) continue;
        rails.push(p.length / 3);
        for (let i = 0; i < p.length; i += 3) rails.push(p[i] - ox, p[i + 1] - oy, p[i + 2] - oz);
      }
    }
  }
  return { tris: new Float32Array(tris), tags: new Uint32Array(tags), rails: new Float32Array(rails) };
}

// ------------------------------------------------------------------ the engine
let e = null;            // the instance's exports, once it is loaded
let posePtr = 0;
let period = 1 / 60;
const riders = new Map();   // player -> { id, pads, pad, owed, last, seq }
const spare = [];           // riders made and not in use
let timer = null;

function assetsFolder() {
  return path.join(GetResourcePath('skate3_assets') || '', 'engine');
}

function available() {
  const folder = assetsFolder();
  return fs.existsSync(path.join(folder, 'sk8m_runtime.wasm')) && fs.existsSync(path.join(folder, 'data', 'private', 'game.json'));
}

const bytes = () => new Uint8Array(e.memory.buffer), floats = () => new Float32Array(e.memory.buffer);
function text(call) {
  const cap = 8192, ptr = e.sk8m_alloc(cap), n = call(ptr, cap);
  const s = new TextDecoder().decode(bytes().slice(ptr, ptr + n));
  e.sk8m_free(ptr, cap);
  return s;
}
function check(code, what) {
  if (code !== 0) throw new Error(what + ': ' + text(e.sk8m_error));
}
function withFloats(values, call) {
  const size = Math.max(values.length, 1) * 4, ptr = e.sk8m_alloc(size);
  floats().set(values, ptr / 4);
  try { return call(ptr); } finally { e.sk8m_free(ptr, size); }
}
// Gives the rider the piece of the baked map round a place (GTA's axes, from the rider's start). False when the
// map has nothing there.
function setPiece(rider, x, y, z) {
  const began = now(), o = rider.origin;
  const piece = pieceAround(o[0] + x, o[1] + y, o[2] + z, o);
  const count = piece.tags.length;
  if (!count) return false;
  const tagBytes = count * 4, tagPtr = e.sk8m_alloc(tagBytes);
  try {
    new Uint32Array(e.memory.buffer).set(piece.tags, tagPtr / 4);
    withFloats(piece.tris, (tris) => withFloats(piece.rails, (rails) =>
      check(e.sk8m_area(rider.id, tris, tagPtr, count, rails, piece.rails.length), 'the baked map')));
  } finally {
    e.sk8m_free(tagPtr, tagBytes);
  }
  rider.piece = [x, y];
  rider.pieces++;
  pieceMs += now() - began;
  pieceCount++;
  pieceMsEver += now() - began;
  piecesEver++;
  return true;
}

const flatFloor = () => new Float32Array([-FLAT, 0, -FLAT, -FLAT, 0, FLAT, FLAT, 0, -FLAT, FLAT, 0, -FLAT, -FLAT, 0, FLAT, FLAT, 0, FLAT]);

// A rider standing at the engine's (0, 0, 0) on the flat floor, facing `heading`.
function makeRider(id, heading) {
  const root = new TextEncoder().encode('/assets'), rootPtr = e.sk8m_alloc(root.length);
  bytes().set(root, rootPtr);
  try {
    withFloats(flatFloor(), (tris) => check(e.sk8m_load(id, rootPtr, root.length, tris, 2, 0, 0, 0, 0, 0, heading), 'load'));
  } finally {
    e.sk8m_free(rootPtr, root.length);
  }
}

function loadEngine() {
  if (e) return;
  const folder = assetsFolder(), began = now();
  const wasi = makeWasi(path.join(folder, 'data'), () => {});
  const instance = new WebAssembly.Instance(new WebAssembly.Module(fs.readFileSync(path.join(folder, 'sk8m_runtime.wasm'))), wasi.imports);
  wasi.bind(instance);
  e = instance.exports;
  posePtr = e.sk8m_alloc(POSE_FLOATS * 4);
  const count = Math.min(Math.max(GetConvarInt('skateboard_engine_riders', 1), 1), 16);
  for (let id = 1; id <= count; id++) {
    makeRider(id, 0);
    spare.push(id);
  }
  period = e.sk8m_period(1) || 1 / 60;
  problem = '';
  try {
    openWorld();
  } catch (error) {
    world = null;
    say('the baked map could not be opened: ' + (error && error.message || error));
  }
  say('loaded in ' + ((now() - began) / 1000).toFixed(1) + ' s: ' + count + (count === 1 ? ' rider' : ' riders') + ', ' +
    Math.round(e.memory.buffer.byteLength / 1048576) + ' MB, one tick = ' + period.toFixed(4) + ' s');
}

function drop(player, why) {
  const rider = riders.get(player);
  if (!rider) return;
  riders.delete(player);
  spare.push(rider.id);                    // (kept for the next player: see the top of the file)
  if (why) emitNet('skateboard:engError', player, why);
  say('player ' + player + ' is off' + (why ? ': ' + why : ''));
  if (riders.size === 0 && timer) { clearInterval(timer); timer = null; }
}

function setGround(rider, g) {
  const h = new Float32Array(g.h.length);
  for (let i = 0; i < h.length; i++) h[i] = g.h[i] <= g.none + 1 ? NaN : g.h[i];
  const tris = gridTriangles(g.n, g.cell, g.x0, g.z0, h);
  withFloats(tris, (ptr) => check(e.sk8m_world(rider.id, ptr, tris.length / 9, 0, 0), 'ground'));
}

let steps = 0, ticks = 0, spent = 0, told = 0, pieceMs = 0, pieceCount = 0, piecesEver = 0, pieceMsEver = 0;

// The clip the rider is shown with: the one with the largest share of the engine's pose. The engine blends
// several, and a player's game plays one at a time (it cannot set bones): the one playing is kept until another
// has clearly more of the pose, so that two clips with near equal shares do not take turns every tick.
function playing(rider) {
  const lines = text((ptr, cap) => e.sk8m_clips(rider.id, ptr, cap)).split('\n');
  let top = null, kept = null;
  for (const line of lines) {
    const [name, time, share, mirrored] = line.split('\t');
    if (!name) continue;
    const clip = { name: name.toLowerCase(), time: +time, share: +share, mirrored: mirrored === '1' };
    if (!top) top = clip;                                   // (they come with the largest share first)
    if (rider.clip && clip.name === rider.clip && clip.mirrored === rider.mirrored) kept = clip;
  }
  const chosen = kept && top && kept.share >= top.share - 0.2 ? kept : top;
  if (!chosen) return { name: '', time: 0, mirrored: false };
  rider.clip = chosen.name;
  rider.mirrored = chosen.mirrored;
  return chosen;
}

function step() {
  const t = now();
  steps++;
  if (t - told > 15000) {                  // (now and then: how often the server lets this run, and what a tick costs)
    if (told) say(riders.size + ' riding; ' + (steps / ((t - told) / 1000)).toFixed(0) + ' steps a second, ' +
      (ticks ? (spent / ticks).toFixed(2) : '0') + ' ms a tick' +
      (pieceCount ? ', ' + pieceCount + ' pieces of the baked map at ' + (pieceMs / pieceCount).toFixed(0) + ' ms each' : ''));
    told = t; steps = 0; ticks = 0; spent = 0; pieceMs = 0; pieceCount = 0;
  }
  for (const [player, rider] of riders) {
    rider.owed = Math.min(rider.owed + (t - rider.last) / 1000, 0.2);   // (a long stall is not made up for: twelve ticks at most)
    rider.last = t;
    let ticked = 0;
    try {
      while (rider.owed >= period) {
        if (rider.pads.length) rider.pad = rider.pads.shift();          // (one sample of the pad a tick, in the order sent)
        const p = rider.pad;
        check(e.sk8m_tick(rider.id, p[0], p[1], p[2], p[3], p[4], p[5], p[6]), 'tick');
        rider.owed -= period;
        ticked++;
      }
      if (!ticked) continue;
      ticks += ticked;
      spent += now() - t;
      e.sk8m_pose(rider.id, posePtr, POSE_FLOATS);
      const f = floats().subarray(posePtr / 4, posePtr / 4 + POSE_FLOATS);
      const clip = playing(rider);
      if (rider.baked) {
        // (the board in GTA's axes from the start: Skate's x, y, z is GTA's x, -z, y; a new piece of the map when
        // it nears the edge of the one it has, with its middle a little ahead of the board)
        const x = f[12], y = -f[14], z = f[13], vx = f[16], vy = -f[18];
        if (Math.max(Math.abs(x - rider.piece[0]), Math.abs(y - rider.piece[1])) > AREA - AREA_EDGE) {
          const ahead = Math.min(AREA_LEAD, 10 / Math.max(Math.hypot(vx, vy), 0.001));
          if (!setPiece(rider, x + vx * ahead, y + vy * ahead, z)) rider.piece = [x, y];   // (nothing there: the old piece stays)
        }
      }
      emitNet('skateboard:engPose', player, ++rider.seq, text((ptr, cap) => e.sk8m_state(rider.id, ptr, cap)),
        Array.from(f.subarray(0, 16)), Array.from(f.subarray(16, 19)), Array.from(f.subarray(19, 32)),
        clip.name, clip.time, clip.mirrored);
    } catch (error) {
      drop(player, String(error && error.message || error));
    }
  }
}

const number = (v, low, high) => (typeof v === 'number' && v === v ? Math.min(high, Math.max(low, v)) : 0);

onNet('skateboard:engAsk', () => {
  emitNet('skateboard:engHave', global.source, e !== null, problem);
});

// heading: the engine's (radians about Skate's y); x, y, z: where in GTA's world the rider's Skate space starts.
onNet('skateboard:engStart', (heading, x, y, z) => {
  const player = global.source;
  if (!e) return emitNet('skateboard:engError', player, 'this server has no engine: ' + problem);
  drop(player);
  if (!spare.length) return emitNet('skateboard:engError', player, 'busy');
  const rider = { id: spare.pop(), pads: [], pad: [0, 0, 0, 0, 0, 0, 0], owed: 0, last: now(), seq: 0,
    origin: [number(x, -1e5, 1e5), number(y, -1e5, 1e5), number(z, -1e5, 1e5)], baked: false, piece: [0, 0], pieces: 0 };
  try {
    const began = now();
    // (the rider as the last player left it: onto the baked map where they stand, or with none back onto the
    // flat floor until their game's ground comes; at the engine's own start, facing as asked)
    rider.baked = world !== null && typeof x === 'number' && setPiece(rider, 0, 0, 0);
    if (!rider.baked) withFloats(flatFloor(), (tris) => check(e.sk8m_world(rider.id, tris, 2, 0, 0), 'floor'));
    check(e.sk8m_place(rider.id, 0, 0, 0, number(heading, -100, 100)), 'place');
    riders.set(player, rider);
    rider.last = now();
    say('player ' + player + ' is riding (rider ' + rider.id + ') on ' + (rider.baked ? 'the baked map' : 'the ground their game finds'));
    emitNet('skateboard:engReady', player, period, Math.round(now() - began), rider.baked);
    if (!timer) timer = setInterval(step, 4);
  } catch (error) {
    spare.push(rider.id);
    emitNet('skateboard:engError', player, String(error && error.message || error));
  }
});

// The pad, a few samples at a time (the game reads it every frame and sends them together): each sample is
// buttons, left trigger, right trigger, left stick x, y, right stick x, y, as XInput has them.
onNet('skateboard:engPads', (samples) => {
  const rider = riders.get(global.source);
  if (!rider || !Array.isArray(samples)) return;
  for (let i = 0; i + 6 < samples.length && i < 7 * 8; i += 7) {
    rider.pads.push([number(samples[i], 0, 65535) | 0, number(samples[i + 1], 0, 255) | 0, number(samples[i + 2], 0, 255) | 0,
      number(samples[i + 3], -32768, 32767) | 0, number(samples[i + 4], -32768, 32767) | 0,
      number(samples[i + 5], -32768, 32767) | 0, number(samples[i + 6], -32768, 32767) | 0]);
  }
  while (rider.pads.length > 6) rider.pads.shift();        // (never more than a tenth of a second behind the pad)
});

// A player's game found the ground somewhere else than the baked map has it (a map this server adds, a place only
// Online changes): from here on this rider's ground is what their game finds with rays. x, y, z (Skate space):
// the ground under the board as their game has it, where the rider is stood again when that ground has come.
onNet('skateboard:engRays', (x, y, z, heading, by) => {
  const player = global.source, rider = riders.get(player);
  if (!rider || !rider.baked) return;
  rider.baked = false;
  rider.again = [number(x, -1e5, 1e5), number(y, -1e5, 1e5), number(z, -1e5, 1e5), number(heading, -100, 100)];
  say('player ' + player + ': the baked map is ' + number(by, -1e5, 1e5).toFixed(2) + ' m off their game\'s ground at ' +
    (rider.origin[0] + rider.again[0]).toFixed(1) + ' ' + (rider.origin[1] - rider.again[2]).toFixed(1) + ' ' +
    (rider.origin[2] + rider.again[1]).toFixed(1) + ': rays from here on');
});

onNet('skateboard:engGround', (n, cell, x0, z0, none, h) => {
  const player = global.source, rider = riders.get(player);
  if (!rider || rider.baked) return;
  if (!(n >= 2 && n <= 64) || !Array.isArray(h) || h.length !== n * n || !(cell > 0.05 && cell < 5)) return;
  try {
    setGround(rider, { n, cell, x0: number(x0, -1e6, 1e6), z0: number(z0, -1e6, 1e6), none: number(none, -1e9, 0), h });
    if (rider.again) {
      check(e.sk8m_place(rider.id, rider.again[0], rider.again[1], rider.again[2], rider.again[3]), 'place');
      rider.again = null;
    }
  } catch (error) {
    drop(player, String(error && error.message || error));
  }
});

onNet('skateboard:engStop', () => drop(global.source));
on('playerDropped', () => drop(global.source));

on('onResourceStart', (name) => {
  if (name !== GetCurrentResourceName()) return;
  try { fs.unlinkSync(path.join(GetResourcePath(GetCurrentResourceName()), 'engine_status.txt')); } catch (error) { /* none yet */ }
  say('starting on Node ' + process.version + '; skate3_assets at ' + GetResourcePath('skate3_assets'));
  if (!available()) {
    problem = 'skate3_assets has no engine folder (it was built without the engine staged)';
    return say(problem + ': the resource\'s own ride is used');
  }
  try {
    loadEngine();
  } catch (error) {
    e = null;
    problem = 'it failed to load: ' + (error && error.message || error);
    say('FAILED to load: ' + (error && error.stack || error));
  }
});

if (typeof module !== 'undefined') module.exports = { gridTriangles, riders, pieceAround, world: () => world, pieces: () => [piecesEver, pieceMsEver] };
