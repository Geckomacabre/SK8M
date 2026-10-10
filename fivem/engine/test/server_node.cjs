// The server's side of the engine (fivem/skateboard/engine_server.js) with FiveM stood in for: the events a
// player's game sends are fired by hand, and what the server sends back is collected.
// usage: node server_node.cjs <engine_server.js> <skate3_assets folder>
const fs = require('fs');
const os = require('os');
const path = require('path');
const [serverFile, assets] = process.argv.slice(2);
const own = fs.mkdtempSync(path.join(os.tmpdir(), 'sk8m-server-'));     // the resource's own folder, for its status file

const handlers = {}, sent = [];
global.on = (name, fn) => { (handlers[name] = handlers[name] || []).push(fn); };
global.onNet = global.on;
global.emitNet = (name, player, ...args) => sent.push({ name, player, args, at: performance.now() });
global.GetResourcePath = (name) => (name === 'skate3_assets' ? assets : own);
global.GetCurrentResourceName = () => 'skateboard';
global.GetConvarInt = (name, fallback) => (name === 'skateboard_engine_riders' ? 2 : fallback);
global.GetConvar = (name, fallback) => fallback;
function fire(name, player, ...args) {
  global.source = player;
  for (const fn of handlers[name] || []) fn(...args);
}
const quiet = console.log;
const lines = [];
console.log = (...a) => lines.push(a.join(' '));
require(path.resolve(serverFile));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const of = (name, player) => sent.filter((m) => m.name === name && m.player === player);
let ok = true;
const report = (label, good) => { ok = ok && good; quiet((good ? 'OK  ' : 'BAD ') + label); };

(async () => {
  let t = performance.now();
  fire('onResourceStart', 0, 'skateboard');
  const load = (performance.now() - t) / 1000;
  report(`the resource's start loads the engine (${load.toFixed(1)} s of the server's time): "${lines[lines.length - 1]}"`,
    lines.some((l) => l.includes('loaded in')));
  fire('skateboard:engAsk', 1);
  report('a player who asks is told the server has the engine', of('skateboard:engHave', 1).some((m) => m.args[0] === true && m.args[1] === ''));
  const status = fs.readFileSync(path.join(own, 'engine_status.txt'), 'utf8');
  report('what happened is in engine_status.txt in the resource\'s folder (' + status.trim().split('\n').length + ' lines, Node ' + process.version + ')',
    status.includes('starting on Node') && status.includes('loaded in'));

  // a rider: standing, then three pushes sent as the game sends them (two samples of the pad an event)
  t = performance.now();
  fire('skateboard:engStart', 1, Math.PI);
  const first = (performance.now() - t) / 1000;
  report(`a rider is ready ${(first * 1000).toFixed(0)} ms after asking (riders are made at the start)`,
    of('skateboard:engReady', 1).length === 1 && first < 0.5);
  const begun = performance.now();
  const sender = setInterval(() => {
    const s = (performance.now() - begun) / 1000, a = [1, 2, 3].some((p) => s >= p && s < p + 0.25) ? 0x1000 : 0;
    fire('skateboard:engPads', 1, [a, 0, 0, 0, 0, 0, 0, a, 0, 0, 0, 0, 0, 0]);
  }, 33);
  await sleep(4500);
  let poses = of('skateboard:engPose', 1);
  const span = (poses[poses.length - 1].at - poses[0].at) / 1000;
  const last = poses[poses.length - 1].args;       // seq, state, root, velocity, camera
  const speed = Math.hypot(...last[3]);
  report(`it answers ${(poses.length / span).toFixed(1)} times a second and the pushes take it to ${speed.toFixed(2)} m/s ` +
    `(${last[1]}, board at ${last[2].slice(12, 15).map((v) => v.toFixed(1)).join(' ')})`,
    poses.length / span > 50 && speed > 7.5 && last[1] === 'PhysicsGround' && last[2].length === 16 && last[4].length === 13);
  // heading pi: Skate +z turned half round, so it rolls towards -z
  report('started facing the other way it rolls the other way (Skate -z)', last[2][14] < -5);
  // the clip the rider is shown with: named with every answer, one of the converted ones, and not a new one every tick
  const index = fs.readFileSync(path.join(assets, 'clip_index.lua'), 'utf8');
  const names = [...new Set(poses.map((m) => m.args[5]))];
  let changes = 0;
  for (let i = 1; i < poses.length; i++) if (poses[i].args[5] !== poses[i - 1].args[5]) changes++;
  report(`each answer names the clip the rider plays and the time in it: ${names.join(', ')} (${changes} changes in ${poses.length} answers)`,
    names.every((n) => typeof n === 'string' && n !== '' && index.includes(`["${n}"]`)) &&
    names.some((n) => n.startsWith('r_push')) && names.includes('r_idle_hcom_000') && changes < 20 &&
    poses.every((m) => typeof m.args[6] === 'number' && m.args[6] >= 0 && m.args[7] === false));

  // a second rider at the same time, and the ground handed to the first: a slope falling to -z, where it is going
  t = performance.now();
  fire('skateboard:engStart', 2, 0);
  const second = (performance.now() - t) / 1000;
  report(`a second rider is ready in ${(second * 1000).toFixed(0)} ms`, of('skateboard:engReady', 2).length === 1 && second < 0.5);
  fire('skateboard:engStart', 3, 0);
  report('a third player, with two riders made, is told the engine is busy',
    of('skateboard:engError', 3).some((m) => m.args[0] === 'busy') && of('skateboard:engReady', 3).length === 0);
  clearInterval(sender);
  fire('skateboard:engPads', 1, [0, 0, 0, 0, 0, 0, 0]);
  const before = speed;
  const ground = setInterval(() => {
    const p = of('skateboard:engPose', 1).pop().args[2], cx = Math.round(p[12] / 2) * 2, cz = Math.round(p[14] / 2) * 2;
    const n = 41, cell = 0.5, h = [];
    for (let j = 0; j < n; j++) for (let i = 0; i < n; i++) h.push(0.1 * (cz - 10 + j * cell));
    fire('skateboard:engGround', 1, n, cell, cx - 10, cz - 10, -1000, h);
  }, 200);
  await sleep(4000);
  clearInterval(ground);
  const a = of('skateboard:engPose', 1).pop().args, b = of('skateboard:engPose', 2).pop().args;
  report(`on the slope handed over as a grid the first speeds up by itself (${before.toFixed(1)} -> ${Math.hypot(...a[3]).toFixed(1)} m/s, ` +
    `${(a[2][13] - 0.1 * a[2][14]).toFixed(2)} m over it); the second stands where it started (${Math.hypot(...b[2].slice(12, 15)).toFixed(2)} m off)`,
    Math.hypot(...a[3]) > before + 1 && Math.abs(a[2][13] - 0.1 * a[2][14] - 0.087) < 0.08 && Math.hypot(...b[2].slice(12, 15)) < 0.2);
  report('no errors were sent to either', of('skateboard:engError', 1).length + of('skateboard:engError', 2).length === 0);

  // stopping: no more answers; a player who drops is forgotten
  fire('skateboard:engStop', 1);
  const n1 = of('skateboard:engPose', 1).length;
  fire('playerDropped', 2, 'left');
  const n2 = of('skateboard:engPose', 2).length;
  await sleep(300);
  report('after stop / drop nothing more is sent', of('skateboard:engPose', 1).length === n1 && of('skateboard:engPose', 2).length === n2);
  fire('skateboard:engGround', 1, 41, 0.5, 0, 0, -1000, new Array(1681).fill(0));
  fire('skateboard:engPads', 9, 'nonsense');
  fire('skateboard:engGround', 9, 3, 0.5, 0, 0, -1000, [1, 2]);
  report('messages from players without a rider, or malformed ones, are ignored', true);
  // the riders are used again: the first player gets on once more, somewhere else, and stands on a floor
  t = performance.now();
  fire('skateboard:engStart', 1, 0);
  const again = performance.now() - t;
  await sleep(1000);
  const back = of('skateboard:engPose', 1).pop().args;
  report(`getting on again takes ${again.toFixed(0)} ms and starts afresh: standing at the start (${Math.hypot(back[2][12], back[2][14]).toFixed(2)} m off, ` +
    `${back[2][13].toFixed(3)} m up, ${Math.hypot(...back[3]).toFixed(2)} m/s, ${back[1]})`,
    again < 500 && Math.hypot(back[2][12], back[2][14]) < 0.2 && Math.abs(back[2][13] - 0.087) < 0.03 && Math.hypot(...back[3]) < 0.3);
  quiet('RESULT: ' + (ok ? 'ok' : 'FAILED'));
  process.exit(ok ? 0 : 1);
})().catch((error) => { quiet('FAILED: ' + error.stack); process.exit(1); });
