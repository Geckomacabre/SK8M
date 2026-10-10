// The page's side of the engine: messages from the game script ({ t: 'eng', ... }) go to the engine's worker, and
// what the worker says goes back to the script (the NUI callback 'eng'). The worker is made on the first message.
(function () {
  let worker = null, busy = false, waiting = null;
  const resource = typeof GetParentResourceName === 'function' ? GetParentResourceName() : 'skateboard';

  function send(data) {
    return fetch('https://' + resource + '/eng', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data) }).catch(() => {});
  }
  // poses: only the newest matters, so one is on its way at a time and the next replaces any that waits
  function sendPose(data) {
    if (busy) { waiting = data; return; }
    busy = true;
    send(data).then(() => {
      busy = false;
      if (waiting) { const next = waiting; waiting = null; sendPose(next); }
    });
  }

  window.addEventListener('message', (event) => {
    const m = event.data;
    if (!m || m.t !== 'eng') return;
    if (!worker) {
      try {
        worker = new Worker('engine/worker.js', { type: 'module' });
        worker.onmessage = (e) => (e.data.k === 'pose' ? sendPose(e.data) : send(e.data));
        worker.onerror = (e) => send({ k: 'error', m: 'worker: ' + (e.message || 'could not start') });
      } catch (error) {
        send({ k: 'error', m: 'worker: ' + error });
        return;
      }
    }
    worker.postMessage(m);
  });
})();
