// Which way along the board does the engine's root point? A host that lays a clip's board on the engine's has to
// know: prints where the engine has the trucks and the wheels against the root (the board), standing still.
// usage: node nose_node.mjs <sk8m_runtime.wasm> <web/data folder>
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
const cap = 16 + 3 + 13 + 64 * 16, posePtr = e.sk8m_alloc(cap * 4);
for (let tick = 0; tick < 120; tick++) check(e.sk8m_tick(0, 0, 0, 0, 0, 0, 0, 0), 'tick');
const count = e.sk8m_pose(0, posePtr, cap);
const names = text((p, c) => e.sk8m_bone_names(0, p, c)).split('\n');
const f = floats().slice(posePtr / 4, posePtr / 4 + cap);
const at = (name) => {
  const i = names.indexOf(name);
  return i < 0 || i >= count ? null : Array.from(f.subarray(32 + i * 16 + 12, 32 + i * 16 + 15));
};
console.log('root (the board in the world): right', Array.from(f.subarray(0, 3)).map((v) => v.toFixed(2)).join(' '),
  ' up', Array.from(f.subarray(4, 7)).map((v) => v.toFixed(2)).join(' '),
  ' z axis', Array.from(f.subarray(8, 11)).map((v) => v.toFixed(2)).join(' '));
console.log('against the root (x, y, z in metres):');
for (const name of names) {
  if (!/TRUCK|WHEEL|BOARD|FOOT|HEAD$|PELVIS|HIPS/i.test(name)) continue;
  const p = at(name);
  if (p) console.log('  ' + name.padEnd(22) + p.map((v) => v.toFixed(3).padStart(8)).join(''));
}
