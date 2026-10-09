"""Extract files from Skate 3 "EB" v3 .big archives (PS3, big-endian).

Format as documented by GHFear's RW4ArchiveTool (big_eb_parser.h). Runs on your own copy of the game;
the extracted files stay on your machine.

usage: python eb_extract.py <archive.big> <out_dir> [name filter substring ...]
       python eb_extract.py <archive.big> --list
"""
import os
import struct
import sys
import zlib


def refpack_decompress(src):
    p = 0
    flags = (src[0] << 8) | src[1]
    p = 2
    size_len = 4 if flags & 0x8000 else 3
    if flags & 0x0100:  # compressed size present
        p += size_len
    out_len = int.from_bytes(src[p:p + size_len], 'big')
    p += size_len
    out = bytearray()
    while p < len(src):
        b0 = src[p]
        if b0 < 0x80:
            b1 = src[p + 1]
            p += 2
            lit = b0 & 3
            ln = ((b0 >> 2) & 7) + 3
            off = ((b0 & 0x60) << 3) + b1 + 1
        elif b0 < 0xC0:
            b1, b2 = src[p + 1], src[p + 2]
            p += 3
            lit = (b1 >> 6) & 3
            ln = (b0 & 0x3F) + 4
            off = ((b1 & 0x3F) << 8) + b2 + 1
        elif b0 < 0xE0:
            b1, b2, b3 = src[p + 1], src[p + 2], src[p + 3]
            p += 4
            lit = b0 & 3
            ln = ((b0 & 0x0C) << 6) + b3 + 5
            off = ((b0 & 0x10) << 12) + (b1 << 8) + b2 + 1
        elif b0 < 0xFC:
            p += 1
            lit = ((b0 & 0x1F) << 2) + 4
            out += src[p:p + lit]
            p += lit
            continue
        else:
            p += 1
            lit = b0 & 3
            out += src[p:p + lit]
            break
        out += src[p:p + lit]
        p += lit
        start = len(out) - off
        for i in range(ln):  # may overlap
            out.append(out[start + i])
    return bytes(out[:out_len]) if out_len else bytes(out)


def chunk_decompress(f, base):
    f.seek(base)
    hdr = f.read(28)
    ident = hdr[:8].rstrip(b'\0').decode('ascii', 'replace')
    version, total, block, nseg, align = struct.unpack('>5I', hdr[8:28])
    out = bytearray()
    pos = base + 28
    for i in range(nseg):
        data_start = -(-(pos + 8) // align) * align
        f.seek(data_start - 8)
        csize, ctype = struct.unpack('>2I', f.read(8))
        data = f.read(csize)
        if ctype == 1:
            out += zlib.decompressobj(-15).decompress(data)
        elif ctype == 2:
            out += refpack_decompress(data)
        elif ctype == 4:
            out += data
        else:
            raise ValueError('%s: unsupported chunk compression %d (LZX is Xbox-only)' % (ident, ctype))
        pos = data_start + csize
    return bytes(out[:total])


def read_archive(path):
    f = open(path, 'rb')
    h = f.read(36)
    (sig, ver, count, flags, align, _res, names_off, names_size, fn_len, folder_len, folder_count,
     arch_size, fat_size) = struct.unpack('>HHIHBBIIBBHQI', h)
    if sig != 0x4542:
        raise ValueError('not an EB archive: %s' % path)
    entry_size = 20 if flags & 1 else 16
    f.seek(0x30)
    toc = []
    for i in range(count):
        off, csize, size = struct.unpack('>3I', f.read(entry_size)[:12])
        toc.append((off << align, csize, size))
    folders_off = -(-(names_off + count * fn_len) // 0x10) * 0x10
    f.seek(folders_off)
    folders = [f.read(folder_len).split(b'\0')[0].decode('latin-1') for _ in range(folder_count)]
    f.seek(names_off)
    entries = []
    for i in range(count):
        rec = f.read(fn_len)
        folder = struct.unpack('>H', rec[:2])[0]
        name = rec[2:].split(b'\0')[0].decode('latin-1')
        fold = folders[folder] if folder < len(folders) else ''
        entries.append((fold + '/' + name if fold else name, *toc[i]))
    return f, entries


def extract(f, off, csize, size):
    f.seek(off)
    magic = f.read(8)
    if magic.startswith(b'chunk'):
        return chunk_decompress(f, off)
    f.seek(off)
    data = f.read(csize if csize else size)
    if data[:2] == b'\x10\xfb' or (len(data) > 2 and data[1] == 0xFB):
        return refpack_decompress(data)
    return data[:size]


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    f, entries = read_archive(sys.argv[1])
    if sys.argv[2] == '--list':
        for name, off, csize, size in entries:
            print('%10d %10d  %s' % (size, csize, name))
        return 0
    out_dir, filters = sys.argv[2], [s.lower() for s in sys.argv[3:]]
    n = 0
    for name, off, csize, size in entries:
        if filters and not any(s in name.lower() for s in filters):
            continue
        data = extract(f, off, csize, size)
        dest = os.path.join(out_dir, name.replace('/', os.sep).lstrip(os.sep))
        os.makedirs(os.path.dirname(dest) or out_dir, exist_ok=True)
        open(dest, 'wb').write(data)
        n += 1
        if len(data) != size:
            print('WARN size mismatch %s: got %d want %d' % (name, len(data), size))
    print('extracted %d files to %s' % (n, out_dir))
    return 0


if __name__ == '__main__':
    sys.exit(main())
