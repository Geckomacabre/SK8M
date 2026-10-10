// Skate 3's engine in a worker of the resource's page: it keeps its own 60 ticks a second off the page's thread.
// The page hands over what the game script sends ({ op: 'start' | 'pad' | 'place' | 'stop' }) and gets back
// { k: 'ready' | 'pose' | 'log' | 'error' } to pass on to it.
import { loadEngine } from './engine.js';

const FLAT = 2000;                      // metres each way: the flat floor the rider is on until the map's ground comes
let engine = null, loading = null, running = false, timer = null;
let pad = { buttons: 0, lt: 0, rt: 0, lx: 0, ly: 0, rx: 0, ry: 0 };
let last = 0, owed = 0, seq = 0;

const say = (m) => postMessage({ k: 'log', m });

async function start(m) {
  if (!engine) {
    if (!loading) {
      loading = (async () => {
        let told = -1;
        const loaded = await loadEngine({
          wasm: m.base + 'sk8m_runtime.wasm', data: m.base + 'data/',
          progress: (p) => {
            const step = Math.floor(p * 4);
            if (step > told) { told = step; say('data ' + Math.round(p * 100) + ' %'); }
          },
        });
        const t = performance.now(), s = FLAT;
        loaded.load(new Float32Array([-s, 0, -s, -s, 0, s, s, 0, -s, s, 0, -s, -s, 0, s, s, 0, s]), [], [0, 0, 0], m.heading);
        postMessage({ k: 'ready', period: loaded.period, ms: Math.round(performance.now() - t), bones: loaded.names.length });
        return loaded;
      })();
    }
    engine = await loading;
  } else {
    engine.place([0, 0, 0], m.heading);
  }
  pad = { buttons: 0, lt: 0, rt: 0, lx: 0, ly: 0, rx: 0, ry: 0 };
  running = true;
  last = performance.now();
  owed = 0;
  if (!timer) timer = setInterval(step, 4);
}

function step() {
  if (!running || !engine) return;
  const now = performance.now();
  owed = Math.min(owed + (now - last) / 1000, 0.1);       // (a stall is not made up for: at most six ticks at once)
  last = now;
  let ticked = 0;
  try {
    while (owed >= engine.period) {
      engine.tick(pad);
      owed -= engine.period;
      ticked++;
    }
    if (!ticked) return;
    const p = engine.pose();
    postMessage({ k: 'pose', n: ++seq, s: p.state, r: Array.from(p.root), v: Array.from(p.velocity),
      c: [p.cameraAt[0], p.cameraAt[1], p.cameraAt[2], ...p.cameraBasis, p.fov] });
  } catch (error) {
    running = false;
    postMessage({ k: 'error', m: String(error && error.message || error) });
  }
}

onmessage = (event) => {
  const m = event.data;
  if (m.op === 'pad') {
    pad = m;
  } else if (m.op === 'start') {
    start(m).catch((error) => postMessage({ k: 'error', m: String(error && error.message || error) }));
  } else if (m.op === 'place') {
    if (engine) engine.place([m.x, m.y, m.z], m.heading);
  } else if (m.op === 'stop') {
    running = false;
    if (timer) { clearInterval(timer); timer = null; }
  }
};
