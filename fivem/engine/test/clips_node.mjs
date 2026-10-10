// Which clips does the engine play? The scripted ride (stand, three pushes, roll, a turn, an ollie) with the clips
// each stretch is blended from: for seeing what a host that plays clips itself has to play.
// usage: node clips_node.mjs <sk8m_runtime.wasm> <web/data folder>
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { makeWasi, mapVfs } from '../web/wasi_mem.js';

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
  const cap = 16384, ptr = e.sk8m_alloc(cap), n = call(ptr, cap);
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
check(e.sk8m_load(0, rootPtr, root.length, trisPtr, 2, 0, 0, 0, 0, 0, 0), 'load');
const period = e.sk8m_period(0), hz = Math.round(1 / period);
const cap = 16 + 3 + 13 + 64 * 16, posePtr = e.sk8m_alloc(cap * 4);

let before = '', since = 0;
const seen = new Map();
for (let tick = 0; tick < hz * 14; tick++) {
  const t = tick * period;
  let buttons = 0, lx = 0, ry = 0;
  for (const push of [1, 2, 3]) if (t >= push && t < push + 0.25) buttons = 0x1000;
  if (t >= 7 && t < 8.5) lx = 20000;
  if (t >= 11 && t < 11.4) ry = -32767; else if (t >= 11.4 && t < 11.5) ry = 32767;
  check(e.sk8m_tick(0, buttons, 0, 0, lx, 0, 0, ry), 'tick');
  e.sk8m_pose(0, posePtr, cap);
  const clips = text((p, c) => e.sk8m_clips(0, p, c)).trim().split('\n').filter(Boolean).map((l) => l.split('\t'));
  for (const c of clips) seen.set(c[0], Math.max(seen.get(c[0]) || 0, +c[2]));
  // a line whenever the set of clips with a real share changes
  const now = clips.filter((c) => +c[2] >= 0.15).map((c) => c[0] + (c[3] === '1' ? '~' : '')).join(' + ');
  if (now !== before) {
    const top = clips[0] || ['-', '0', '0', '0'];
    console.log(`t ${t.toFixed(2).padStart(5)}  ${text((p, c) => e.sk8m_state(0, p, c)).padEnd(14)} ${clips.length} clips; ` +
      `top ${top[0]}${top[3] === '1' ? ' (mirrored)' : ''} at ${(+top[1]).toFixed(2)} s, share ${top[2]}  |  ${now}`);
    before = now;
  }
}
console.log(`${seen.size} different clips had a share; ~ = played mirrored`);
