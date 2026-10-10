// Skate 3's engine in a worker of the resource's page: it keeps its own 60 ticks a second off the page's thread.
// The page hands over what the game script sends ({ op: 'start' | 'pad' | 'place' | 'stop' }) and gets back
// { k: 'ready' | 'pose' | 'log' | 'error' } to pass on to it.
import { loadEngine } from './engine.js';
import { gridTriangles } from './ground.js';

const FLAT = 2000;                      // metres each way: the flat floor the rider is on until the map's ground comes
let engine = null, loading = null, running = false, timer = null;
let pad = { buttons: 0, lt: 0, rt: 0, lx: 0, ly: 0, rx: 0, ry: 0 };
let last = 0, owed = 0, seq = 0;
let floor = null;                       // the ground the game sent last (kept for an engine still loading)

const say = (m) => postMessage({ k: 'log', m });
const flatFloor = () => new Float32Array([-FLAT, 0, -FLAT, -FLAT, 0, FLAT, FLAT, 0, -FLAT, FLAT, 0, -FLAT, -FLAT, 0, FLAT, FLAT, 0, FLAT]);

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
        const t = performance.now();
        loaded.load(flatFloor(), [], [0, 0, 0], m.heading);
        postMessage({ k: 'ready', period: loaded.period, ms: Math.round(performance.now() - t), bones: loaded.names.length });
        return loaded;
      })();
    }
    engine = await loading;
  } else {
    engine.world(flatFloor(), []);      // (the ground of the ride before was measured from where that one began)
    engine.place([0, 0, 0], m.heading);
  }
  if (floor) setGround(floor);
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

// The ground round the board as the game found it: heights on a grid (see ground.js), in place of the world so far.
function setGround(m) {
  const h = new Float32Array(m.h.length);
  for (let i = 0; i < h.length; i++) h[i] = m.h[i] <= m.none + 1 ? NaN : m.h[i];
  engine.world(gridTriangles({ n: m.n, cell: m.cell, x0: m.x0, z0: m.z0, h }), []);
}

onmessage = (event) => {
  const m = event.data;
  if (m.op === 'pad') {
    pad = m;
  } else if (m.op === 'ground') {
    floor = m;
    if (engine && running) {
      try { setGround(m); } catch (error) { postMessage({ k: 'error', m: 'ground: ' + (error && error.message || error) }); }
    }
  } else if (m.op === 'start') {
    start(m).catch((error) => postMessage({ k: 'error', m: String(error && error.message || error) }));
  } else if (m.op === 'place') {
    if (engine) engine.place([m.x, m.y, m.z], m.heading);
  } else if (m.op === 'stop') {
    running = false;
    floor = null;
    if (timer) { clearInterval(timer); timer = null; }
  }
};
