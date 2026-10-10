// The slice of WASI the engine needs, over files held in memory: it reads its data folder and prints to the log.
// Nothing is ever written. `vfs` answers two questions about a path under the folder (case does not matter):
//   vfs.stat(path) -> { dir: true } | { size: number } | null        vfs.read(path) -> Uint8Array
// makeWasi(vfs, { root, log, opened }) -> { imports, bind(instance) }; `opened` (a Set) collects the files read.
const OK = 0, EBADF = 8, EINVAL = 28, ENOENT = 44, ENOTDIR = 54;
const DIR = 3, FILE = 4, CHARACTER = 2;

export function makeWasi(vfs, options = {}) {
  const root = options.root || '/assets';
  const log = options.log || (() => {});
  const opened = options.opened || null;
  let memory = null;
  const view = () => new DataView(memory.buffer);
  const bytes = () => new Uint8Array(memory.buffer);
  const decoder = new TextDecoder(), encoder = new TextEncoder();
  const rootBytes = encoder.encode(root);
  // fd 0..2 = the console, 3 = the data folder; files and folders opened after that
  const fds = new Map([[3, { dir: true, path: '' }]]);
  let next = 4;
  const lines = { 1: '', 2: '' };
  const started = (typeof performance !== 'undefined' ? performance.now() : Date.now());

  function clean(base, path) {
    const parts = [];
    for (const part of (base + '/' + path).split('/')) {
      if (part === '' || part === '.') continue;
      if (part === '..') parts.pop(); else parts.push(part);
    }
    return parts.join('/').toLowerCase();
  }
  function pathAt(fd, ptr, len) {
    const dir = fds.get(fd);
    if (!dir || !dir.dir) return null;
    return clean(dir.path, decoder.decode(bytes().subarray(ptr, ptr + len)));
  }
  function writeStat(out, stat) {
    const v = view();
    for (let i = 0; i < 64; i += 8) v.setBigUint64(out + i, 0n, true);
    v.setUint8(out + 16, stat.dir ? DIR : FILE);
    v.setBigUint64(out + 24, 1n, true);
    v.setBigUint64(out + 32, BigInt(stat.dir ? 0 : stat.size), true);
  }

  const wasi = {
    random_get(ptr, len) {
      const target = bytes().subarray(ptr, ptr + len);
      for (let i = 0; i < len; i += 65536) crypto.getRandomValues(target.subarray(i, Math.min(len, i + 65536)));
      return OK;
    },
    environ_sizes_get(count, size) {
      view().setUint32(count, 0, true);
      view().setUint32(size, 0, true);
      return OK;
    },
    environ_get() { return OK; },
    clock_time_get(id, precision, out) {
      const now = (typeof performance !== 'undefined' ? performance.now() : Date.now()) - started;
      view().setBigUint64(out, BigInt(Math.round(now * 1e6)), true);
      return OK;
    },
    fd_close(fd) {
      if (fd < 4 || !fds.delete(fd)) return EBADF;
      return OK;
    },
    fd_fdstat_get(fd, out) {
      const entry = fd < 3 ? { console: true } : fds.get(fd);
      if (!entry) return EBADF;
      const v = view();
      v.setUint8(out, entry.console ? CHARACTER : entry.dir ? DIR : FILE);
      v.setUint16(out + 2, 0, true);
      v.setBigUint64(out + 8, 0xffffffffffffffffn, true);
      v.setBigUint64(out + 16, 0xffffffffffffffffn, true);
      return OK;
    },
    fd_filestat_get(fd, out) {
      const entry = fds.get(fd);
      if (!entry) return EBADF;
      writeStat(out, entry.dir ? { dir: true } : { size: entry.data.length });
      return OK;
    },
    fd_prestat_get(fd, out) {
      if (fd !== 3) return EBADF;
      view().setUint8(out, 0);
      view().setUint32(out + 4, rootBytes.length, true);
      return OK;
    },
    fd_prestat_dir_name(fd, ptr, len) {
      if (fd !== 3) return EBADF;
      bytes().set(rootBytes.subarray(0, len), ptr);
      return OK;
    },
    fd_read(fd, iovs, count, readOut) {
      const entry = fds.get(fd);
      if (!entry || entry.dir) return EBADF;
      let total = 0;
      for (let i = 0; i < count; i++) {
        const ptr = view().getUint32(iovs + i * 8, true), len = view().getUint32(iovs + i * 8 + 4, true);
        const n = Math.min(len, entry.data.length - entry.at);
        bytes().set(entry.data.subarray(entry.at, entry.at + n), ptr);
        entry.at += n;
        total += n;
        if (n < len) break;
      }
      view().setUint32(readOut, total, true);
      return OK;
    },
    fd_write(fd, iovs, count, writtenOut) {
      let total = 0, text = '';
      for (let i = 0; i < count; i++) {
        const ptr = view().getUint32(iovs + i * 8, true), len = view().getUint32(iovs + i * 8 + 4, true);
        text += decoder.decode(bytes().slice(ptr, ptr + len));
        total += len;
      }
      if (fd === 1 || fd === 2) {
        const parts = (lines[fd] + text).split('\n');
        lines[fd] = parts.pop();
        for (const line of parts) log(line);
      }
      view().setUint32(writtenOut, total, true);
      return OK;
    },
    path_filestat_get(fd, flags, ptr, len, out) {
      const path = pathAt(fd, ptr, len);
      if (path === null) return ENOTDIR;
      const stat = path === '' ? { dir: true } : vfs.stat(path);
      if (!stat) return ENOENT;
      writeStat(out, stat);
      return OK;
    },
    path_open(fd, dirflags, ptr, len, oflags, rightsBase, rightsInheriting, fdflags, fdOut) {
      const path = pathAt(fd, ptr, len);
      if (path === null) return ENOTDIR;
      if (oflags & (1 | 4 | 8)) return EINVAL;          // create, exclusive, truncate: nothing is written here
      const stat = path === '' ? { dir: true } : vfs.stat(path);
      if (!stat) return ENOENT;
      if ((oflags & 2) && !stat.dir) return ENOTDIR;
      if (stat.dir) {
        fds.set(next, { dir: true, path });
      } else {
        fds.set(next, { data: vfs.read(path), at: 0 });
        if (opened) opened.add(path);
      }
      view().setUint32(fdOut, next++, true);
      return OK;
    },
    proc_exit(code) {
      throw new Error('the engine stopped with code ' + code);
    },
  };
  return { imports: { wasi_snapshot_preview1: wasi }, bind(instance) { memory = instance.exports.memory; } };
}

// Files held in a Map of lower-case path -> Uint8Array.
export function mapVfs(files) {
  const dirs = new Set();
  for (const path of files.keys()) {
    const parts = path.split('/');
    for (let i = 1; i < parts.length; i++) dirs.add(parts.slice(0, i).join('/'));
  }
  return {
    stat(path) {
      const file = files.get(path);
      if (file) return { size: file.length };
      return dirs.has(path) ? { dir: true } : null;
    },
    read(path) { return files.get(path); },
  };
}
