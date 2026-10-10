// The baked map on the server (fivem/skateboard/engine_server.js reading a world.sk8w) with FiveM stood in for.
// The map here is written by the test itself: a flat floor of 200 m at GTA 1000, 2000, 10 m up, in 64 m tiles,
// and one rail over it. With a real world.sk8w and a place given, a rider is also put there and pushed along, and
// what the server did is printed (nothing is judged: the place is yours).
// usage: node world_node.cjs <engine_server.js> <skate3_assets folder> [<world.sk8w> <x> <y> <z> [<GTA heading>]]
const fs = require('fs');
const os = require('os');
const path = require('path');
const zlib = require('zlib');
const [serverFile, assets, realFile, rx, ry, rz, rh] = process.argv.slice(2);
const own = fs.mkdtempSync(path.join(os.tmpdir(), 'sk8m-world-'));

// ---- a world.sk8w (the layout is at the top of fivem/engine/bake/src/main.rs)
function writeWorld(file, triangles, rails, size = 64) {
  const tiles = new Map();
  const tile = (tx, ty) => {
    const key = tx + ',' + ty;
    if (!tiles.has(key)) tiles.set(key, { tx, ty, tris: [], rails: [] });
    return tiles.get(key);
  };
  for (const t of triangles) {
    const xs = [t[0], t[3], t[6]], ys = [t[1], t[4], t[7]];
    for (let tx = Math.floor(Math.min(...xs) / size); tx <= Math.floor(Math.max(...xs) / size); tx++) {
      for (let ty = Math.floor(Math.min(...ys) / size); ty <= Math.floor(Math.max(...ys) / size); ty++) tile(tx, ty).tris.push(t);
    }
  }
  rails.forEach((points, id) => {
    const through = new Set();
    for (const p of points) through.add(Math.floor(p[0] / size) + ',' + Math.floor(p[1] / size));
    for (const key of through) tile(...key.split(',').map(Number)).rails.push({ id, points });
  });
  const sorted = [...tiles.values()].sort((a, b) => a.tx - b.tx || a.ty - b.ty);
  const blocks = sorted.map((t) => {
    const raw = Buffer.alloc(t.tris.length * 40 + t.rails.reduce((n, r) => n + 8 + r.points.length * 12, 0));
    let at = 0;
    for (const tri of t.tris) {
      for (let i = 0; i < 9; i++) raw.writeFloatLE(tri[i], at + i * 4);
      raw.writeUInt32LE(tri[9] || 0, at + 36);
      at += 40;
    }
    for (const r of t.rails) {
      raw.writeUInt32LE(r.id, at);
      raw.writeUInt32LE(r.points.length, at + 4);
      at += 8;
      for (const p of r.points) for (const v of p) { raw.writeFloatLE(v, at); at += 4; }
    }
    return { raw, packed: zlib.deflateSync(raw) };
  });
  const head = Buffer.alloc(16 + sorted.length * 28);
  head.write('SK8W', 0, 'latin1');
  head.writeUInt32LE(1, 4);
  head.writeFloatLE(size, 8);
  head.writeUInt32LE(sorted.length, 12);
  let where = head.length;
  sorted.forEach((t, i) => {
    const o = 16 + i * 28;
    head.writeInt32LE(t.tx, o);
    head.writeInt32LE(t.ty, o + 4);
    head.writeBigUInt64LE(BigInt(where), o + 8);
    head.writeUInt32LE(blocks[i].packed.length, o + 16);
    head.writeUInt32LE(blocks[i].raw.length, o + 20);
    head.writeUInt32LE(t.tris.length, o + 24);
    where += blocks[i].packed.length;
  });
  fs.writeFileSync(file, Buffer.concat([head, ...blocks.map((b) => b.packed)]));
  return sorted.length;
}

const FLOOR = 10, madeFile = path.join(own, 'made.sk8w'), triangles = [];
for (let x = 900; x < 1100; x += 4) {
  for (let y = 1900; y < 2100; y += 4) {
    triangles.push([x, y, FLOOR, x + 4, y, FLOOR, x, y + 4, FLOOR, 0], [x + 4, y, FLOOR, x + 4, y + 4, FLOOR, x, y + 4, FLOOR, 0]);
  }
}
const madeTiles = writeWorld(madeFile, triangles, [[[1010, 1990, FLOOR + 0.5], [1010, 2010, FLOOR + 0.5]]]);

// ---- FiveM, stood in for
const handlers = {}, sent = [];
let worldFile = madeFile;
global.on = (name, fn) => { (handlers[name] = handlers[name] || []).push(fn); };
global.onNet = global.on;
global.emitNet = (name, player, ...args) => sent.push({ name, player, args, at: performance.now() });
global.GetResourcePath = (name) => (name === 'skate3_assets' ? assets : own);
global.GetCurrentResourceName = () => 'skateboard';
global.GetConvarInt = (name, fallback) => (name === 'skateboard_engine_riders' ? 2 : fallback);
global.GetConvar = (name, fallback) => (name === 'skateboard_engine_world' ? worldFile : fallback);
function fire(name, player, ...args) {
  global.source = player;
  for (const fn of handlers[name] || []) fn(...args);
}
const quiet = console.log, lines = [];
console.log = (...a) => lines.push(a.join(' '));
const server = require(path.resolve(serverFile));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const of = (name, player) => sent.filter((m) => m.name === name && m.player === player);
const last = (player) => of('skateboard:engPose', player).pop().args;
let ok = true;
const report = (label, good) => { ok = ok && good; quiet((good ? 'OK  ' : 'BAD ') + label); };
// pushes: the A button a quarter of every second, as the game sends the pad
function pushing(player) {
  const begun = performance.now();
  return setInterval(() => {
    const a = ((performance.now() - begun) / 1000) % 1 < 0.25 ? 0x1000 : 0;
    fire('skateboard:engPads', player, [a, 0, 0, 0, 0, 0, 0, a, 0, 0, 0, 0, 0, 0]);
  }, 33);
}

(async () => {
  fire('onResourceStart', 0, 'skateboard');
  report(`the server opens the baked map at its start: "${lines.find((l) => l.includes('baked map')) || ''}"`,
    lines.some((l) => l.includes('baked map: ' + madeTiles + ' tiles')));

  // a rider in the middle of the made floor, facing GTA south (the engine's heading 0)
  fire('skateboard:engStart', 1, 0, 1000, 2000, FLOOR);
  const ready = of('skateboard:engReady', 1).pop();
  report('a rider started on the map is told so', !!ready && ready.args[2] === true);
  await sleep(1000);
  let p = last(1);
  report(`it stands on the baked floor (${p[1]}, ${p[2][13].toFixed(3)} m over it)`, p[1] === 'PhysicsGround' && Math.abs(p[2][13] - 0.087) < 0.03);
  const first = server.riders.get(1).pieces;
  let sender = pushing(1);
  await sleep(9000);
  clearInterval(sender);
  p = last(1);
  const rider = server.riders.get(1);
  report(`pushed ${Math.hypot(p[2][12], p[2][14]).toFixed(0)} m across it the board is still on the floor (${p[2][13].toFixed(3)} m, ${p[1]}) ` +
    `and has been given ${rider.pieces - first} more pieces of the map`,
    Math.hypot(p[2][12], p[2][14]) > 45 && Math.abs(p[2][13] - 0.087) < 0.05 && p[1] === 'PhysicsGround' && rider.pieces - first >= 2);
  // control: the same ride with the pieces never moved on runs off the first piece and falls
  fire('skateboard:engStop', 1);
  fire('skateboard:engStart', 1, 0, 1000, 2000, FLOOR);
  server.riders.get(1).baked = false;                     // (as a rider on the rays' ground: no new pieces)
  sender = pushing(1);
  await sleep(9000);
  clearInterval(sender);
  p = last(1);
  report(`control, the map never moved on: the board runs off the piece it started with and falls (${p[2][13].toFixed(1)} m)`, p[2][13] < -1);
  fire('skateboard:engStop', 1);

  // a place the map has nothing of: the flat floor, and the player's game is told to send its ground
  fire('skateboard:engStart', 2, 0, 5000, 5000, 3);
  const none = of('skateboard:engReady', 2).pop();
  await sleep(600);
  p = last(2);
  report(`a rider started where the map has nothing is told so and stands on the flat floor (${p[2][13].toFixed(3)} m)`,
    !!none && none.args[2] === false && Math.abs(p[2][13] - 0.087) < 0.03);
  fire('skateboard:engStop', 2);

  // the player's game finds the ground 2 m higher than the map has it: rays from there on, stood on that ground
  fire('skateboard:engStart', 1, 0, 1000, 2000, FLOOR);
  await sleep(300);
  fire('skateboard:engGround', 1, 41, 0.5, -10, -10, -1000, new Array(1681).fill(2));
  await sleep(300);
  report('ground sent by a game whose rider is on the map is not taken', Math.abs(last(1)[2][13] - 0.087) < 0.03);
  fire('skateboard:engRays', 1, 3, 2, 4, 0, -2);
  fire('skateboard:engGround', 1, 41, 0.5, -7, -6, -1000, new Array(1681).fill(2));
  await sleep(600);
  p = last(1);
  report(`told the map is off, the server takes the game's ground and stands the rider on it (${p[2][12].toFixed(1)} ${p[2][13].toFixed(3)} ${p[2][14].toFixed(1)}; ` +
    `"${(lines.find((l) => l.includes('off their game')) || '').replace(/^.*player/, 'player')}")`,
    server.riders.get(1).baked === false && Math.abs(p[2][13] - 2.087) < 0.05 && Math.abs(p[2][12] - 3) < 0.5 && Math.abs(p[2][14] - 4) < 0.5);
  fire('skateboard:engStop', 1);
  report('no errors were sent', of('skateboard:engError', 1).length + of('skateboard:engError', 2).length === 0);

  if (realFile) {
    // a real baked map: the server script loaded afresh on it, a rider put at the place given and pushed along
    const [x, y, z] = [rx, ry, rz].map(Number), gtaHeading = Number(rh || 0);
    worldFile = realFile;
    for (const name of Object.keys(handlers)) delete handlers[name];
    delete require.cache[require.resolve(path.resolve(serverFile))];
    const real = require(path.resolve(serverFile));
    lines.length = 0;
    sent.length = 0;
    fire('onResourceStart', 0, 'skateboard');
    quiet('---- ' + (lines.find((l) => l.includes('baked map')) || 'no baked map line'));
    let t = performance.now();
    fire('skateboard:engStart', 1, (gtaHeading + 180) * Math.PI / 180, x, y, z);
    const [, firstMs] = real.pieces();
    quiet(`start at ${x} ${y} ${z}: ${(performance.now() - t).toFixed(0)} ms, on the map: ${of('skateboard:engReady', 1).pop().args[2]}`);
    await sleep(1000);
    p = last(1);
    quiet(`after 1 s: ${p[1]}, ${p[2][13].toFixed(3)} m over the start's height`);
    sender = pushing(1);
    for (let i = 0; i < 4; i++) {
      await sleep(3000);
      p = last(1);
      const r = real.riders.get(1);
      quiet(`after ${4 + i * 3} s: ${p[1]}, ${Math.hypot(p[2][12], p[2][14]).toFixed(1)} m from the start, ${p[2][13].toFixed(2)} m up, ` +
        `${Math.hypot(...p[3]).toFixed(1)} m/s, clip ${p[5]}, ${r ? r.pieces : '?'} pieces so far`);
    }
    clearInterval(sender);
    const [count, ms] = real.pieces();
    quiet(`${count - 1} pieces of the map were handed over after the first, ${((ms - firstMs) / Math.max(count - 1, 1)).toFixed(0)} ms each`);
    const errors = of('skateboard:engError', 1).map((m) => m.args[0]);
    quiet(errors.length ? 'errors: ' + errors.join('; ') : 'no errors');
  }
  quiet('RESULT: ' + (ok ? 'ok' : 'FAILED'));
  process.exit(ok ? 0 : 1);
})().catch((error) => { quiet('FAILED: ' + error.stack); process.exit(1); });
