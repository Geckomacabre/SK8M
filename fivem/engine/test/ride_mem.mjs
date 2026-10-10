// The WebAssembly engine on the in-memory file layer the browser will use (web/wasi_mem.js), fed from the real data
// folder. Checks that it rides as it does on Node's own WASI, and writes the list of files the engine really reads.
// usage: node ride_mem.mjs <sk8m_runtime.wasm> <assets root> <files-out.json>
import { readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { makeWasi } from '../web/wasi_mem.js';

const [wasmPath, assets, listOut] = process.argv.slice(2);

// every file under the folder, by lower-case relative path (read when the engine asks for it)
const index = new Map(), dirs = new Set();
(function walk(dir, rel) {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name), path = (rel ? rel + '/' : '') + name.toLowerCase();
    if (statSync(full).isDirectory()) { dirs.add(path); walk(full, path); } else index.set(path, full);
  }
})(assets, '');
const vfs = {
  stat(path) {
    if (index.has(path)) return { size: statSync(index.get(path)).size };
    return dirs.has(path) ? { dir: true } : null;
  },
  read(path) { return new Uint8Array(readFileSync(index.get(path))); },
};

const opened = new Set(), missing = new Set();
const stat = vfs.stat;
vfs.stat = (path) => { const s = stat(path); if (!s) missing.add(path); else if (!s.dir) opened.add(path); return s; };   // (a file only asked about must be there too)
const wasi = makeWasi(vfs, { opened, log: () => {} });
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

const s = 300, floor = [-s, 0, -s, -s, 0, s, s, 0, -s, s, 0, -s, -s, 0, s, s, 0, s];
const trisPtr = e.sk8m_alloc(floor.length * 4);
floats().set(floor, trisPtr / 4);
const root = new TextEncoder().encode('/assets'), rootPtr = e.sk8m_alloc(root.length);
bytes().set(root, rootPtr);
check(e.sk8m_load(rootPtr, root.length, trisPtr, 2, 0, 0, 0, 0, 0, 0), 'load');
const period = e.sk8m_period(), hz = Math.round(1 / period);
const cap = 16 + 3 + 13 + 64 * 16, posePtr = e.sk8m_alloc(cap * 4);
let topSpeed = 0, topHeight = -1e9, last = null;
for (let tick = 0; tick < hz * 16; tick++) {
  const t = tick * period;
  let buttons = 0, lx = 0, ry = 0;
  for (const push of [1, 2, 3]) if (t >= push && t < push + 0.25) buttons = 0x1000;
  if (t >= 7 && t < 8.5) lx = 20000;
  if (t >= 11 && t < 11.4) ry = -32767; else if (t >= 11.4 && t < 11.5) ry = 32767;
  check(e.sk8m_tick(buttons, 0, 0, lx, 0, 0, ry), 'tick');
  e.sk8m_pose(posePtr, cap);
  const f = floats().subarray(posePtr / 4, posePtr / 4 + cap);
  topSpeed = Math.max(topSpeed, Math.hypot(f[16], f[17], f[18]));
  topHeight = Math.max(topHeight, f[13]);
  last = [f[12], f[13], f[14]];
}
console.log(`top speed ${topSpeed.toFixed(3)} m/s, highest root ${topHeight.toFixed(3)} m, ends at ` +
  last.map((v) => v.toFixed(3)).join(' '));
const files = [...opened].sort().map((path) => ({ path, bytes: statSync(index.get(path)).size }));
const total = files.reduce((n, f) => n + f.bytes, 0);
console.log(`${files.length} files read, ${(total / 1e6).toFixed(1)} MB:`);
for (const f of files) console.log(`  ${String(f.bytes).padStart(9)}  ${f.path}`);
console.log('asked for and not there: ' + ([...missing].join(', ') || 'nothing'));
writeFileSync(listOut, JSON.stringify(files, null, 1));
