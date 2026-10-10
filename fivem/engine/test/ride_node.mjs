// Does the WebAssembly build of the engine ride? The same script as the native probe: three pushes, a turn, an ollie.
// usage: node ride_node.mjs <sk8m_runtime.wasm> <assets root>
import { readFile } from 'node:fs/promises';
import { WASI } from 'node:wasi';

const [wasmPath, assets] = process.argv.slice(2);
const wasi = new WASI({ version: 'preview1', preopens: { '/assets': assets }, args: [], env: {} });
const module = await WebAssembly.compile(await readFile(wasmPath));
const instance = await WebAssembly.instantiate(module, wasi.getImportObject());
wasi.initialize(instance);
const e = instance.exports;

const bytes = () => new Uint8Array(e.memory.buffer);
const floats = () => new Float32Array(e.memory.buffer);
function text(call) {
  const cap = 4096, ptr = e.sk8m_alloc(cap);
  const n = call(ptr, cap);
  const s = new TextDecoder().decode(bytes().slice(ptr, ptr + n));
  e.sk8m_free(ptr, cap);
  return s;
}
function check(code, what) {
  if (code !== 0) throw new Error(what + ': ' + text(e.sk8m_error));
}

// a flat floor, y up, normal up
const s = 300;
const floor = [-s, 0, -s, -s, 0, s, s, 0, -s, s, 0, -s, -s, 0, s, s, 0, s];
const trisPtr = e.sk8m_alloc(floor.length * 4);
floats().set(floor, trisPtr / 4);
const root = new TextEncoder().encode('/assets');
const rootPtr = e.sk8m_alloc(root.length);
bytes().set(root, rootPtr);

let started = performance.now();
check(e.sk8m_load(rootPtr, root.length, trisPtr, 2, 0, 0, 0, 0, 0, 0), 'load');
const period = e.sk8m_period();
console.log(`loaded in ${((performance.now() - started) / 1000).toFixed(1)} s; one tick = ${period.toFixed(5)} s`);

const cap = 16 + 3 + 13 + 64 * 16, posePtr = e.sk8m_alloc(cap * 4);
const A = 0x1000, hz = Math.round(1 / period);
let topSpeed = 0, topHeight = -1e9;
started = performance.now();
const ticks = hz * 16;
for (let tick = 0; tick < ticks; tick++) {
  const t = tick * period;
  let buttons = 0, lx = 0, ry = 0;
  for (const push of [1, 2, 3]) if (t >= push && t < push + 0.25) buttons = A;
  if (t >= 7 && t < 8.5) lx = 20000;
  if (t >= 11 && t < 11.4) ry = -32767; else if (t >= 11.4 && t < 11.5) ry = 32767;
  check(e.sk8m_tick(buttons, 0, 0, lx, 0, 0, ry), 'tick');
  const bones = e.sk8m_pose(posePtr, cap);
  const f = floats().subarray(posePtr / 4, posePtr / 4 + cap);
  const speed = Math.hypot(f[16], f[17], f[18]);
  topSpeed = Math.max(topSpeed, speed);
  topHeight = Math.max(topHeight, f[13]);
  if (tick % (hz / 2) === 0) {
    console.log(`t ${t.toFixed(2).padStart(5)}  pos ${f[12].toFixed(3).padStart(8)} ${f[13].toFixed(3).padStart(7)} ` +
      `${f[14].toFixed(3).padStart(8)}  speed ${speed.toFixed(3).padStart(6)}  ${bones} bones  ${text(e.sk8m_state)}`);
  }
}
const ms = (performance.now() - started) / ticks;
console.log(`top speed ${topSpeed.toFixed(3)} m/s, highest root ${topHeight.toFixed(3)} m`);
console.log(`${ms.toFixed(3)} ms a tick (${(ms / (period * 1000) * 100).toFixed(1)} % of real time)`);
console.log('bones: ' + text(e.sk8m_bone_names).split('\n').join(' '));
