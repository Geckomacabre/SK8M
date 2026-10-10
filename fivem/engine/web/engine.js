// Skate 3's engine in the browser: loads the WebAssembly build and the game's data files, then is driven a tick at
// a time. The page (a test view here, FiveM's NUI page later) owns the loop.
//
//   const engine = await loadEngine({ wasm: 'sk8m_runtime.wasm', data: 'data/', progress })
//   engine.load(triangles, rails, [x, y, z], heading)     // Float32Array of 9 floats a triangle; Skate space, y up
//   engine.tick(pad)                                      // { buttons, lt, rt, lx, ly, rx, ry } as XInput reports
//   const pose = engine.pose()                            // { root, velocity, camera, bones, state }
import { makeWasi, mapVfs } from './wasi_mem.js';

export const BUTTON = { up: 0x0001, down: 0x0002, left: 0x0004, right: 0x0008, start: 0x0010, back: 0x0020,
  ls: 0x0040, rs: 0x0080, lb: 0x0100, rb: 0x0200, a: 0x1000, b: 0x2000, x: 0x4000, y: 0x8000 };
const MAX_BONES = 64, POSE_FLOATS = 16 + 3 + 13 + MAX_BONES * 16;

export async function loadEngine({ wasm, data, progress = () => {}, log = () => {} }) {
  const list = await (await fetch(data + 'files.json')).json();
  const total = list.reduce((n, f) => n + f.bytes, 0);
  const files = new Map();
  let got = 0;
  await Promise.all(list.map(async (f) => {
    if (f.bytes === 0) {              // (a file the engine only checks is there)
      files.set(f.path, new Uint8Array(0));
      return;
    }
    const response = await fetch(data + f.path);
    if (!response.ok) throw new Error(f.path + ': ' + response.status);
    files.set(f.path, new Uint8Array(await response.arrayBuffer()));
    got += f.bytes;
    progress(got / total);
  }));
  const wasi = makeWasi(mapVfs(files), { log });
  // (not instantiateStreaming: FiveM's page server does not send the WebAssembly content type it insists on)
  const { instance } = await WebAssembly.instantiate(await (await fetch(wasm)).arrayBuffer(), wasi.imports);
  wasi.bind(instance);
  const e = instance.exports;
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
    const ptr = e.sk8m_alloc(Math.max(values.length, 1) * 4);
    floats().set(values, ptr / 4);
    try { return call(ptr); } finally { e.sk8m_free(ptr, Math.max(values.length, 1) * 4); }
  }
  // rails: [[x, y, z, x, y, z, ...], ...] -> count, points, count, points ...
  function packRails(rails) {
    const out = [];
    for (const rail of rails || []) out.push(rail.length / 3, ...rail);
    return new Float32Array(out);
  }

  let posePtr = 0, names = [];
  return {
    load(triangles, rails, place, heading) {
      const root = new TextEncoder().encode('/assets'), rootPtr = e.sk8m_alloc(root.length);
      bytes().set(root, rootPtr);
      const packed = packRails(rails);
      withFloats(triangles, (tris) => withFloats(packed, (railPtr) => check(e.sk8m_load(0, rootPtr, root.length, tris,
        triangles.length / 9, railPtr, packed.length, place[0], place[1], place[2], heading), 'load')));
      e.sk8m_free(rootPtr, root.length);
      posePtr = e.sk8m_alloc(POSE_FLOATS * 4);
      this.period = e.sk8m_period(0);
      names = text((p, c) => e.sk8m_bone_names(0, p, c)).split('\n');
      this.names = names;
    },
    world(triangles, rails) {
      const packed = packRails(rails);
      withFloats(triangles, (tris) => withFloats(packed, (railPtr) =>
        check(e.sk8m_world(0, tris, triangles.length / 9, railPtr, packed.length), 'world')));
    },
    place(position, heading) {
      check(e.sk8m_place(0, position[0], position[1], position[2], heading), 'place');
    },
    tick(pad) {
      check(e.sk8m_tick(0, pad.buttons | 0, pad.lt | 0, pad.rt | 0, pad.lx | 0, pad.ly | 0, pad.rx | 0, pad.ry | 0), 'tick');
    },
    pose() {
      const count = e.sk8m_pose(0, posePtr, POSE_FLOATS);
      const f = floats().subarray(posePtr / 4, posePtr / 4 + POSE_FLOATS);
      return { root: f.subarray(0, 16), velocity: f.subarray(16, 19), cameraAt: f.subarray(19, 22),
        cameraBasis: f.subarray(22, 31), fov: f[31], bones: f.subarray(32, 32 + count * 16), count,
        state: text((p, c) => e.sk8m_state(0, p, c)) };
    },
    period: 0,
    names,
  };
}
