// The ground as the FiveM side will give it: a grid of heights around the board, turned into triangles and swapped
// in while riding. Measures what a swap costs and checks that the board rides a slope and climbs a kerb-sized ramp.
// usage: node ground_node.mjs <sk8m_runtime.wasm> <web/data folder>
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { makeWasi, mapVfs } from '../web/wasi_mem.js';
import { gridTriangles } from '../web/ground.js';

const [wasmPath, data] = process.argv.slice(2);
const files = new Map();
for (const f of JSON.parse(readFileSync(join(data, 'files.json'), 'utf8'))) {
  files.set(f.path, f.bytes ? new Uint8Array(readFileSync(join(data, f.path))) : new Uint8Array(0));
}
const wasi = makeWasi(mapVfs(files), {});
const instance = await WebAssembly.instantiate(await WebAssembly.compile(readFileSync(wasmPath)), wasi.imports);
wasi.bind(instance);
const e = instance.exports;
const bytes = () => new Uint8Array(e.memory.buffer), floats = () => new Float32Array(e.memory.buffer);
function text(call) {
  const cap = 4096, ptr = e.sk8m_alloc(cap), n = call(ptr, cap);
  const s = new TextDecoder().decode(bytes().slice(ptr, ptr + n));
  e.sk8m_free(ptr, cap);
  return s;
}
const check = (code, what) => { if (code !== 0) throw new Error(what + ': ' + text(e.sk8m_error)); };
function withFloats(values, call) {
  const ptr = e.sk8m_alloc(values.length * 4);
  floats().set(values, ptr / 4);
  const out = call(ptr);
  e.sk8m_free(ptr, values.length * 4);
  return out;
}

// heights on a grid: n x n samples, `cell` metres apart, centred on (cx, cz); height(x, z) in Skate space (y up)
function grid(n, cell, cx, cz, height) {
  const h = new Float32Array(n * n), x0 = cx - (n - 1) / 2 * cell, z0 = cz - (n - 1) / 2 * cell;
  for (let j = 0; j < n; j++) for (let i = 0; i < n; i++) h[j * n + i] = height(x0 + i * cell, z0 + j * cell);
  return { n, cell, x0, z0, h };
}

const root = new TextEncoder().encode('/assets'), rootPtr = e.sk8m_alloc(root.length);
bytes().set(root, rootPtr);
const flat = gridTriangles(grid(41, 0.5, 0, 0, () => 0));
withFloats(flat, (p) => check(e.sk8m_load(0, rootPtr, root.length, p, flat.length / 9, 0, 0, 0, 0, 0, 0), 'load'));
const period = e.sk8m_period(0), hz = Math.round(1 / period);
const cap = 16 + 3 + 13 + 64 * 16, posePtr = e.sk8m_alloc(cap * 4);
const pose = () => { e.sk8m_pose(0, posePtr, cap); return floats().subarray(posePtr / 4, posePtr / 4 + cap); };
const tick = (buttons = 0, lx = 0) => check(e.sk8m_tick(0, buttons, 0, 0, lx, 0, 0, 0), 'tick');
let ok = true;
const report = (label, good) => { ok = ok && good; console.log((good ? 'OK  ' : 'BAD ') + label); };

// 1. the cost of a swap, and that a swap under a standing board leaves it standing
for (let i = 0; i < hz; i++) tick();
const before = Array.from(pose().subarray(12, 15));
let worst = 0, total = 0;
for (let i = 0; i < 20; i++) {
  const tris = gridTriangles(grid(41, 0.5, 0, 0, () => 0));
  const t = performance.now();
  withFloats(tris, (p) => check(e.sk8m_world(0, p, tris.length / 9, 0, 0), 'world'));
  const ms = performance.now() - t;
  worst = Math.max(worst, ms);
  total += ms;
  tick();
}
for (let i = 0; i < hz; i++) tick();
const after = Array.from(pose().subarray(12, 15));
console.log(`      a 41 x 41 grid (${flat.length / 9} triangles): ${(total / 20).toFixed(2)} ms a swap, worst ${worst.toFixed(2)} ms`);
report(`the board stands still through 20 swaps of the same ground (moved ${(Math.hypot(...after.map((v, i) => v - before[i])) * 1000).toFixed(1)} mm)`,
  Math.hypot(...after.map((v, i) => v - before[i])) < 0.02);

// 2. a slope: the ground falls 1 in 10 towards +z; the window follows the board
const slope = (x, z) => -0.1 * z;
function follow(height) {
  const p = pose();
  const cx = Math.round(p[12] / 2) * 2, cz = Math.round(p[14] / 2) * 2;        // (windows 2 m apart)
  const tris = gridTriangles(grid(41, 0.5, cx, cz, height));
  withFloats(tris, (q) => check(e.sk8m_world(0, q, tris.length / 9, 0, 0), 'world'));
}
check(e.sk8m_place(0, 0, 0.05, 0, 0), 'place');
follow(slope);
for (let i = 0; i < hz * 6; i++) {
  if (i % 6 === 0) follow(slope);
  tick();
}
let p = pose();
report(`on a 1 in 10 slope it rolls off downhill by itself (${p[14].toFixed(1)} m in 6 s, ${Math.hypot(p[16], p[17], p[18]).toFixed(1)} m/s, ` +
  `${(p[13] - slope(p[12], p[14])).toFixed(2)} m above the slope, ${text((p, c) => e.sk8m_state(0, p, c))})`,
  p[14] > 5 && Math.abs(p[13] - slope(p[12], p[14]) - 0.087) < 0.06);

// 3. a kerb: 15 cm up across one cell, met at speed
const kerb = (x, z) => (z > 12 ? 0.15 : 0);
check(e.sk8m_place(0, 0, 0.05, 0, 0), 'place');
follow(kerb);
for (let i = 0; i < hz * 8; i++) {
  if (i % 6 === 0) follow(kerb);
  const t = i * period;
  tick((t > 0.5 && t < 0.75) || (t > 1.5 && t < 1.75) ? 0x1000 : 0);
}
p = pose();
report(`a 15 cm kerb sampled half a metre apart is ridden up (at z ${p[14].toFixed(1)}, ${(p[13] - 0.087).toFixed(2)} m up, ` +
  `${Math.hypot(p[16], p[17], p[18]).toFixed(1)} m/s, ${text((p, c) => e.sk8m_state(0, p, c))})`, p[14] > 14 && Math.abs(p[13] - 0.087 - 0.15) < 0.06);
console.log('RESULT: ' + (ok ? 'ok' : 'FAILED'));
process.exit(ok ? 0 : 1);
