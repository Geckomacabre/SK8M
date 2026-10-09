// Skateboard sounds. The ride (client.lua) says what the board is doing; this plays the recordings for it.
//
// There are no sounds in this resource and none are made up here. They come from a sound pack: a folder of .ogg
// files plus a list of what is in it, which the ride passes on in its 'config' message. The pack the ride looks
// for is Skate 3's own sounds, converted from your copy of the game into skate3_assets (skate3-sp/tools).
// Without a pack nothing plays.
//
//   config   { volume: 0 .. 1, base: 'https://cfx-nui-<resource>/sounds/', sounds: { <name>: <sound> }, world }
//   state    { roll, grind, slide, air: speeds in m/s (0 = off), manual, quiet, surface, rail, at }   20 a second
//   hit      { name, v: 0 .. 1 }                                                       one-off sounds
//   pick     { name, sound }                                                           swap one sound of the pack
//   preview  { name, v, seconds }                                                      let one be heard
//   stop
//
// The sounds come from the board, not from the screen. `at` is where the board is as the game's camera hears it:
// [metres to its right, metres above it, metres BEHIND it] (in front is negative, the way Web Audio counts).
// Everything is played from that point: to one side when the camera is beside the rider, fainter when it is far
// off. `world` = { near, rolloff, model }: full loudness within `near` metres, how fast it falls away beyond,
// and 'HRTF' (direction as two ears hear it; the default) or 'equalpower' (plain left / right). world = false
// puts the sounds back on the screen.
//
// A <sound> is one of
//   { files: [...], gain }                                  one-off: one of the files, not the same twice running
//   { ramp: true, files: [f], seconds, speed, gain }        one long recording that goes from slow to fast: it
//                                                           is played from the place that fits the speed, as one
//                                                           running stream (speed = m/s at the end of the recording)
//   { layers: true, files: [slow, medium, fast], seconds: [...], pad, speeds: [...], gain }
//                                                           loops for three speeds, mixed by the speed. Each file
//                                                           has `pad` seconds of the loop's other end either side
//   { once: true, files: [f], gain }                        played from its start while it is on (wheels spinning
//                                                           down in the air)
'use strict';

const RATE = 48000;          // the pack is written at this rate
const FRONT = [0, -1.0, -2.5];   // where the board is from the usual camera, until the ride says where
let ctx, master, bus, panner;
let volume = 0.5;
// The volume is a slider position: half way is a quarter of the power, the way volume controls are. At 1 the
// recordings play at four fifths of full scale.
const loud = (v) => 0.8 * clamp(v, 0, 1) ** 2;
let base = '';
let pack = {};               // name -> { def, buffers: [AudioBuffer], last }
const cache = {};            // file -> Promise<AudioBuffer | null>
const voices = {};           // slot -> what is playing there
let timer = null;

function start() {
  if (ctx) return;
  const AC = window.AudioContext || window.webkitAudioContext;
  try { ctx = new AC({ sampleRate: RATE }); } catch (e) { ctx = new AC(); }
  master = ctx.createGain();
  master.gain.value = loud(volume);
  master.connect(ctx.destination);
  bus = ctx.createGain();           // every sound goes in here ...
  world({});                        // ... and out through one point in the world: the board
}

// Where the sounds are heard from. The listener stays at the origin looking down -z (the camera); the board moves.
function world(w) {
  try { bus.disconnect(); } catch (e) { /* not connected yet */ }
  if (panner) { try { panner.disconnect(); } catch (e) { /* gone */ } panner = null; }
  if (w === false) { bus.connect(master); return; }
  panner = ctx.createPanner();
  panner.panningModel = (w && w.model) || 'HRTF';
  panner.distanceModel = 'inverse';
  panner.refDistance = (w && w.near) || 3.5;
  panner.rolloffFactor = (w && w.rolloff) || 1.0;
  panner.maxDistance = 10000;
  panner.coneInnerAngle = 360;
  place(FRONT, true);
  bus.connect(panner);
  panner.connect(master);
}

function place(at, now) {
  if (!panner || !at || at.length < 3) return;
  const params = [panner.positionX, panner.positionY, panner.positionZ];
  for (let i = 0; i < 3; i++) {
    const v = Number(at[i]);
    if (!Number.isFinite(v)) return;
    if (now) params[i].setValueAtTime(v, ctx.currentTime);
    else params[i].setTargetAtTime(v, ctx.currentTime, 0.03);     // glide: the ride says where 20 times a second
  }
}

const ramp = (param, v, t) => param.setTargetAtTime(v, ctx.currentTime, t || 0.05);
const clamp = (x, lo, hi) => Math.max(lo, Math.min(hi, x));

function fetchBuffer(file) {
  if (!cache[file]) {
    cache[file] = fetch(base + file)
      .then((r) => { if (!r.ok) throw new Error(r.status); return r.arrayBuffer(); })
      .then((data) => ctx.decodeAudioData(data))
      .catch(() => null);   // that recording is missing: the others still play
  }
  return cache[file];
}

async function prepare(def) {
  const entry = { def, buffers: [], last: -1 };
  entry.buffers = await Promise.all((def.files || []).map(fetchBuffer));
  if (!def.ramp && !def.layers && !def.once) entry.buffers = entry.buffers.filter(Boolean);
  return entry;
}

async function load(sounds) {
  const names = Object.keys(sounds || {});
  const entries = await Promise.all(names.map((n) => prepare(sounds[n])));
  const next = {};
  names.forEach((n, i) => { next[n] = entries[i]; });
  stopAll();
  pack = next;
  report();
}

// Tell the ride what could be loaded, so that it can say so (/skatetest): nobody can hear a page.
function report() {
  if (typeof GetParentResourceName !== 'function') return;
  let loaded = 0, total = 0;
  for (const entry of Object.values(pack)) {
    total += (entry.def.files || []).length;
    loaded += entry.buffers.filter(Boolean).length;
  }
  fetch('https://' + GetParentResourceName() + '/sound_ready', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json; charset=UTF-8' },
    body: JSON.stringify({ loaded, total, rate: ctx.sampleRate, state: ctx.state, world: panner ? panner.panningModel : 'screen' }),
  }).catch(() => {});
}

const gainOf = (entry) => (entry.def.gain === undefined ? 1 : entry.def.gain);

// ---------------------------------------------------------------- one-off sounds

function pick(entry) {
  const n = entry.buffers.length;
  if (n === 0) return null;
  let i = Math.floor(Math.random() * n);
  if (n > 1 && i === entry.last) i = (i + 1) % n;
  entry.last = i;
  return entry.buffers[i];
}

function hit(name, v) {
  if (name === 'land' && v > 0.62 && pack.land_big) name = 'land_big';   // a drop, not a hop
  const entry = pack[name];
  const buffer = entry && pick(entry);
  if (!buffer) return;
  v = clamp(v === undefined ? 0.6 : v, 0, 1);
  const src = ctx.createBufferSource(), g = ctx.createGain();
  src.buffer = buffer;
  g.gain.value = gainOf(entry) * (0.35 + 0.65 * v);
  src.connect(g);
  g.connect(bus);
  src.start();
}

// ---------------------------------------------------------------- sounds that last

function release(slot, fade) {
  const v = voices[slot];
  if (!v) return;
  delete voices[slot];
  const t = fade || 0.06;
  ramp(v.out.gain, 0, t);
  v.dead = true;
  for (const src of v.sources || []) { try { src.stop(ctx.currentTime + t * 6); } catch (e) { /* not started */ } }
  setTimeout(() => { try { v.out.disconnect(); } catch (e) { /* gone */ } }, t * 8000 + 400);
}

function stopAll() {
  for (const slot of Object.keys(voices)) release(slot);
}

function voice(slot, name) {
  let v = voices[slot];
  // another surface: the old recording fades out under the new one coming in (about a third of a second)
  if (v && v.name !== name) { release(slot, v.kind === 'ramp' ? 0.12 : 0.05); v = null; }
  if (!v) {
    const out = ctx.createGain();
    out.gain.value = 0;
    out.connect(bus);
    v = voices[slot] = { name, out, sources: [] };
  }
  return v;
}

// A recording that runs from slow to fast. One stream of it plays at a time, from the place that fits the speed, so
// what is heard is the recording itself, unbroken. Left alone a stream runs on up the recording (towards "faster"),
// so while it plays it is held to the speed the board is doing: slowed or sped up a little for the pitch, and
// trimmed for the loudness, by how far its playhead is from the right place. Every second or two the next stream
// is faded in over it from just short of the right place; sooner when the speed has run away from it.
// (Cutting the recording into short pieces from here and there, as this did at first, follows the speed too, but
// it scrambles the rhythm of the wheels: it did not sound like one board rolling.)
const STREAM = [1.2, 1.8];   // seconds a stream plays before the next takes over
const FADE = 0.3;            // seconds of cross-fade between two streams
const AWAY = 1.6;            // seconds of recording a stream's playhead may be from the right place before then
const EASE = 0.18;           // seconds the speed the sound follows takes to catch up: a kick is not a step
const RATE_LO = 0.8, RATE_HI = 1.3;
const CURVE_IN = new Float32Array(48).map((_, i) => Math.sin(0.5 * Math.PI * i / 47));      // equal power
const CURVE_OUT = new Float32Array(48).map((_, i) => Math.cos(0.5 * Math.PI * i / 47));

// How loud a recording is along its length (every quarter second, evened out over three seconds).
function profile(buffer) {
  const x = buffer.getChannelData(0), step = Math.floor(buffer.sampleRate * 0.25);
  const n = Math.max(1, Math.floor(x.length / step)), raw = new Float32Array(n), level = new Float32Array(n);
  for (let k = 0; k < n; k++) {
    let sum = 0;
    for (let i = k * step; i < (k + 1) * step && i < x.length; i++) sum += x[i] * x[i];
    raw[k] = Math.sqrt(sum / step);
  }
  for (let k = 0; k < n; k++) {
    let sum = 0, count = 0;
    for (let j = Math.max(0, k - 6); j <= Math.min(n - 1, k + 6); j++) { sum += raw[j]; count++; }
    level[k] = Math.max(sum / count, 1e-5);
  }
  return level;
}

function levelAt(level, seconds) {
  const i = clamp(seconds / 0.25 - 0.5, 0, level.length - 1), a = Math.floor(i), b = Math.min(level.length - 1, a + 1);
  return level[a] + (level[b] - level[a]) * (i - a);
}

function rampVoice(slot, name, entry, speed, level) {
  const buffer = entry.buffers[0];
  if (!buffer) return release(slot);
  const v = voice(slot, name);
  if (v.kind !== 'ramp') {
    v.kind = 'ramp';
    v.buffer = buffer;
    v.level = entry.profile || (entry.profile = profile(buffer));
    v.top = entry.def.speed || 12;
    v.follow = speed;                 // the speed the sound is at
    v.stream = null;
    v.free = 0;                       // no hand-over before this time: one cross-fade at a time
    v.last = ctx.currentTime;
  }
  v.want = speed;
  ramp(v.out.gain, gainOf(entry) * level, 0.1);
  schedule();
}

function runRamp(v, now) {
  const dt = clamp(now - v.last, 0, 0.25);
  v.last = now;
  v.follow += (v.want - v.follow) * (1 - Math.exp(-dt / EASE));
  const span = Math.max(0.01, v.buffer.duration - STREAM[1] * RATE_HI - 0.4);    // the furthest a stream may start
  const place = (speed) => clamp(speed / v.top, 0, 1) * span;                     // seconds into the recording
  const speedAt = (seconds) => clamp(seconds / span, 0, 1) * v.top;
  // a part recorded at one speed, played for another: how much faster, and how much louder
  const pitch = (seconds) => clamp((v.follow + 1.5) / (speedAt(seconds) + 1.5), RATE_LO, RATE_HI);
  const want = place(v.follow);
  const trim = (seconds) => clamp(levelAt(v.level, want) / levelAt(v.level, seconds), 0.6, 1.6);
  const s = v.stream;
  if (s) {
    s.head += dt * s.rate;
    s.rate = pitch(s.head);
    s.src.playbackRate.setTargetAtTime(s.rate, now, 0.05);
    s.trim.gain.setTargetAtTime(trim(s.head), now, 0.08);
  }
  const away = s ? Math.abs(s.head - want) > AWAY : false;
  if (now < v.free || (s && now < s.until && !away)) return;
  const life = STREAM[0] + Math.random() * (STREAM[1] - STREAM[0]);
  const fade = !s ? 0.05 : (away ? FADE * 0.7 : FADE);
  // start it short of the place by half its run, so that it plays through it (not when chasing the speed)
  const at = clamp(want - (s && !away ? life * 0.5 : 0), 0, span);
  // The fade starts a moment ahead, never in the past, and the new gain starts at 0 by how it is made, not by
  // setting its value: setting a value is itself an event at "the time now", the audio clock runs on while this
  // code does, and a fade curve may not lie across another event (FiveM's browser refuses it: seen in the game).
  const t0 = Math.max(now, ctx.currentTime) + 0.004;
  const src = ctx.createBufferSource();
  const rate = pitch(at);
  const t = new GainNode(ctx, { gain: trim(at) }), g = new GainNode(ctx, { gain: 0 });
  src.buffer = v.buffer;
  src.playbackRate.value = rate;
  try {
    g.gain.setValueCurveAtTime(CURVE_IN, t0, fade);
  } catch (e) {
    g.gain.setTargetAtTime(1, t0, fade / 3);              // a plainer fade rather than no sound
  }
  src.connect(t);
  t.connect(g);
  g.connect(v.out);
  src.start(t0, at);
  if (s) {
    try {
      s.g.gain.setValueCurveAtTime(CURVE_OUT, t0, fade);
    } catch (e) {
      s.g.gain.cancelScheduledValues(t0);
      s.g.gain.setTargetAtTime(0, t0, fade / 3);
    }
    s.src.stop(t0 + fade + 0.05);
  }
  v.sources = s ? [s.src, src] : [src];
  v.stream = { src, g, trim: t, head: at, rate, until: t0 + life };
  v.free = t0 + fade + 0.03;
  v.handovers = (v.handovers || 0) + 1;
}

function schedule() {
  const now = ctx.currentTime;
  let busy = false;
  for (const v of Object.values(voices)) {
    if (v.kind !== 'ramp') continue;
    busy = true;
    try { runRamp(v, now); } catch (e) { console.error('skateboard sound: ' + e); }
  }
  if (busy && !timer) timer = setInterval(schedule, 40);
  if (!busy && timer) { clearInterval(timer); timer = null; }
}

// Loops for three speeds, mixed by the speed.
function layerVoice(slot, name, entry, speed, level) {
  const def = entry.def;
  if (!entry.buffers.some(Boolean)) return release(slot);
  const v = voice(slot, name);
  if (v.kind !== 'layers') {
    v.kind = 'layers';
    v.gains = [];
    const pad = def.pad || 0;
    entry.buffers.forEach((buffer, i) => {
      const g = ctx.createGain();
      g.gain.value = 0;
      g.connect(v.out);
      v.gains.push(g);
      if (!buffer) return;
      const src = ctx.createBufferSource();
      const seconds = (def.seconds && def.seconds[i]) || (buffer.duration - 2 * pad);
      src.buffer = buffer;
      src.loop = true;
      src.loopStart = pad;
      src.loopEnd = pad + seconds;
      src.connect(g);
      src.start(0, pad + Math.random() * seconds);
      v.sources.push(src);
    });
  }
  const s = def.speeds || [2, 5, 8];
  const n = v.gains.length;
  for (let i = 0; i < n; i++) {
    let w;
    if (n === 1) w = 1;
    else if (speed <= s[0]) w = i === 0 ? 1 : 0;
    else if (speed >= s[n - 1]) w = i === n - 1 ? 1 : 0;
    else {
      w = 0;
      for (let k = 0; k < n - 1; k++) {
        if (speed >= s[k] && speed <= s[k + 1]) {
          const f = (speed - s[k]) / (s[k + 1] - s[k]);
          if (i === k) w = 1 - f; else if (i === k + 1) w = f;
        }
      }
    }
    ramp(v.gains[i].gain, Math.sqrt(w), 0.1);
  }
  ramp(v.out.gain, gainOf(entry) * level, 0.06);
}

// Played from its start for as long as it is on.
function onceVoice(slot, name, entry, level) {
  const buffer = entry.buffers[0];
  if (!buffer) return release(slot);
  const v = voice(slot, name);
  if (v.kind !== 'once') {
    v.kind = 'once';
    const src = ctx.createBufferSource();
    src.buffer = buffer;
    src.connect(v.out);
    src.start();
    v.sources.push(src);
    v.out.gain.setValueAtTime(gainOf(entry) * level, ctx.currentTime);
  }
}

// One slot of the mix: `names` in order of preference (the first the pack has is played), a speed, a level.
function lasting(slot, names, speed, level) {
  let name, entry;
  for (const n of names) { if (pack[n]) { name = n; entry = pack[n]; break; } }
  if (!(speed > 0) || !entry) return release(slot);
  if (entry.def.ramp) rampVoice(slot, name, entry, speed, level);
  else if (entry.def.layers) layerVoice(slot, name, entry, speed, level);
  else if (entry.def.once) onceVoice(slot, name, entry, level);
  else release(slot);
}

function state(m) {
  place(m.at);
  const rollLevel = clamp(m.roll / 1.0, 0, 1) * (m.quiet ? 0.6 : 1);     // fades in over the first metre a second
  lasting('roll', ['roll_' + (m.surface || 'concrete_smooth'), 'roll_concrete_smooth'], m.roll, rollLevel);
  const rail = m.rail || 'concrete';
  lasting('grind', ['grind_' + rail, 'grind_concrete', 'grind'], m.grind, 0.6 + 0.4 * clamp(m.grind / 8, 0, 1));
  lasting('slide', ['slide_' + rail, 'slide_concrete', 'slide', 'grind_' + rail], m.slide, 0.6 + 0.4 * clamp(m.slide / 8, 0, 1));
  lasting('air', ['wheels'], m.air, 0.5 + 0.5 * clamp(m.air / 8, 0, 1));
  lasting('manual', ['wheels_manual'], m.manual, 0.5 + 0.5 * clamp(m.manual / 8, 0, 1));
}

async function preview(m) {
  const entry = pack[m.name];
  if (!entry) return;
  if (!entry.def.ramp && !entry.def.layers && !entry.def.once) return hit(m.name, m.v === undefined ? 0.8 : m.v);
  const slot = 'preview';
  release(slot);
  lasting(slot, [m.name], m.v || 5, 1);
  setTimeout(() => release(slot, 0.1), (m.seconds || 2.5) * 1000);
}

// The skate shop's board page (designer.html) lives in a frame of its own, made when the Lua side opens it and
// removed when it closes; this page stays the sound player. Messages whose t starts with 'designer' are the shop's.
let designerFrame = null;
function designerMessage(m) {
  if (m.t === 'designer' && !m.open) {
    if (designerFrame) designerFrame.remove();
    designerFrame = null;
  } else if (m.t === 'designer' && !designerFrame) {
    const f = document.createElement('iframe');
    f.src = 'designer.html';
    f.style.cssText = 'position:fixed;left:0;top:0;width:100vw;height:100vh;border:0;background:transparent;z-index:10';
    f.addEventListener('load', () => { f.contentWindow.postMessage(m, '*'); f.focus(); });
    document.body.appendChild(f);
    designerFrame = f;
  } else if (designerFrame && designerFrame.contentWindow) {
    designerFrame.contentWindow.postMessage(m, '*');
  }
}

window.addEventListener('message', (event) => {
  const m = event.data || {};
  if (m.t === undefined) return;
  if (typeof m.t === 'string' && m.t.indexOf('designer') === 0) return designerMessage(m);
  start();
  if (ctx.state === 'suspended') ctx.resume();
  switch (m.t) {
    case 'config':
      volume = m.volume === undefined ? volume : m.volume;
      ramp(master.gain, loud(volume), 0.05);
      if (m.world !== undefined) world(m.world);
      if (m.base) { base = m.base; load(m.sounds); }
      break;
    case 'state':
      state(m);
      break;
    case 'hit':
      hit(m.name, m.v);
      break;
    case 'pick':
      if (m.base) base = m.base;
      if (m.volume !== undefined) { volume = m.volume; ramp(master.gain, loud(volume), 0.05); }
      if (m.preview && Object.keys(voices).length === 0) place(FRONT, true);    // off the board: just in front
      prepare(m.sound).then((entry) => {
        for (const slot of Object.keys(voices)) if (voices[slot].name === m.name) release(slot);
        pack[m.name] = entry;
        if (m.preview) preview({ name: m.name, v: m.v, seconds: m.seconds });
      });
      break;
    case 'preview':
      preview(m);
      break;
    case 'stop':
      stopAll();
      break;
  }
});

// for looking in from outside (tests): what is loaded and what is playing
window.skateSound = () => ({
  volume, gain: master ? master.gain.value : 0,
  streams: Object.fromEntries(Object.entries(voices).filter(([, v]) => v.kind === 'ramp').map(([s, v]) =>
    [s, { follow: +v.follow.toFixed(2), head: v.stream ? +v.stream.head.toFixed(2) : null, rate: v.stream ? +v.stream.rate.toFixed(3) : null, handovers: v.handovers || 0 }])),
  at: panner ? [panner.positionX.value, panner.positionY.value, panner.positionZ.value] : null,
  model: panner ? panner.panningModel : 'screen',
  rate: ctx ? ctx.sampleRate : 0,
  state: ctx ? ctx.state : 'none',
  loaded: Object.fromEntries(Object.entries(pack).map(([n, e]) => [n, e.buffers.filter(Boolean).length])),
  playing: Object.fromEntries(Object.entries(voices).map(([s, v]) => [s, v.name])),
});
