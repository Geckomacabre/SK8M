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

const FLAT = 2000;                     // metres each way: the flat floor a rider is on until their ground comes
const POSE_FLOATS = 16 + 3 + 13;       // what is sent back: the board's matrix, its velocity, the camera

const now = () => (typeof performance !== 'undefined' ? performance.now() : Date.now());
const say = (text) => console.log('[skateboard] engine: ' + text);

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
  say('loaded in ' + ((now() - began) / 1000).toFixed(1) + ' s: ' + count + (count === 1 ? ' rider' : ' riders') + ', ' +
    Math.round(e.memory.buffer.byteLength / 1048576) + ' MB, one tick = ' + period.toFixed(4) + ' s');
}

function drop(player, why) {
  const rider = riders.get(player);
  if (!rider) return;
  riders.delete(player);
  spare.push(rider.id);                    // (kept for the next player: see the top of the file)
  if (why) emitNet('skateboard:engError', player, why);
  if (riders.size === 0 && timer) { clearInterval(timer); timer = null; }
}

function setGround(rider, g) {
  const h = new Float32Array(g.h.length);
  for (let i = 0; i < h.length; i++) h[i] = g.h[i] <= g.none + 1 ? NaN : g.h[i];
  const tris = gridTriangles(g.n, g.cell, g.x0, g.z0, h);
  withFloats(tris, (ptr) => check(e.sk8m_world(rider.id, ptr, tris.length / 9, 0, 0), 'ground'));
}

function step() {
  const t = now();
  for (const [player, rider] of riders) {
    rider.owed = Math.min(rider.owed + (t - rider.last) / 1000, 0.1);   // (a stall is not made up for: six ticks at most)
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
      e.sk8m_pose(rider.id, posePtr, POSE_FLOATS);
      const f = floats().subarray(posePtr / 4, posePtr / 4 + POSE_FLOATS);
      emitNet('skateboard:engPose', player, ++rider.seq, text((ptr, cap) => e.sk8m_state(rider.id, ptr, cap)),
        Array.from(f.subarray(0, 16)), Array.from(f.subarray(16, 19)), Array.from(f.subarray(19, 32)));
    } catch (error) {
      drop(player, String(error && error.message || error));
    }
  }
}

const number = (v, low, high) => (typeof v === 'number' && v === v ? Math.min(high, Math.max(low, v)) : 0);

onNet('skateboard:engAsk', () => {
  emitNet('skateboard:engHave', global.source, e !== null);
});

onNet('skateboard:engStart', (heading) => {
  const player = global.source;
  if (!e) return emitNet('skateboard:engError', player, 'this server has no engine (skate3_assets was built without it)');
  drop(player);
  if (!spare.length) return emitNet('skateboard:engError', player, 'busy');
  const rider = { id: spare.pop(), pads: [], pad: [0, 0, 0, 0, 0, 0, 0], owed: 0, last: now(), seq: 0 };
  try {
    const began = now();
    // (the rider as the last player left it: back onto the flat floor at the engine's own start, facing as asked)
    withFloats(flatFloor(), (tris) => check(e.sk8m_world(rider.id, tris, 2, 0, 0), 'floor'));
    check(e.sk8m_place(rider.id, 0, 0, 0, number(heading, -100, 100)), 'place');
    riders.set(player, rider);
    rider.last = now();
    emitNet('skateboard:engReady', player, period, Math.round(now() - began));
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

onNet('skateboard:engGround', (n, cell, x0, z0, none, h) => {
  const player = global.source, rider = riders.get(player);
  if (!rider) return;
  if (!(n >= 2 && n <= 64) || !Array.isArray(h) || h.length !== n * n || !(cell > 0.05 && cell < 5)) return;
  try {
    setGround(rider, { n, cell, x0: number(x0, -1e6, 1e6), z0: number(z0, -1e6, 1e6), none: number(none, -1e9, 0), h });
  } catch (error) {
    drop(player, String(error && error.message || error));
  }
});

onNet('skateboard:engStop', () => drop(global.source));
on('playerDropped', () => drop(global.source));

on('onResourceStart', (name) => {
  if (name !== GetCurrentResourceName()) return;
  if (!available()) return say('skate3_assets has no engine in it: the resource\'s own ride is used');
  try {
    loadEngine();
  } catch (error) {
    e = null;
    say('FAILED to load: ' + (error && error.message || error));
  }
});

if (typeof module !== 'undefined') module.exports = { gridTriangles, riders };
